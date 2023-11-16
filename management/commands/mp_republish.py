from auditlog.context import set_actor
from django.contrib.contenttypes.models import ContentType
from django.core.management import BaseCommand
from django.db import models
from django.db import transaction

from voteit.agenda.workflows import AgendaItemWf
from voteit.meeting.models import Meeting
from voteit.proposal.models import Proposal

from voteit.proposal.workflows import ProposalWf
from voteit.reactions.models import ReactionButton


class Command(BaseCommand):
    help = "Återpublicera förslag som kommer över gräns"
    # PROPOSAL_WF_STATES = set(ProposalWf.states) - {ProposalWf.RETRACTED}
    AI_STATES = (AgendaItemWf.ONGOING,)
    PROP_STATES = (ProposalWf.UNHANDLED,)

    def add_arguments(self, parser):
        parser.add_argument("-m", help="Meeting pk", required=True)
        parser.add_argument(
            "-p", help="PK för återpublicera-knapp med target", required=True
        )
        parser.add_argument("-f", help="PK för eventuellt flagga att sätta")
        parser.add_argument(
            "-u",
            help="PK för användare som utför operationen - måste vara del av mötet",
            required=True,
        )
        parser.add_argument(
            "--commit", help="Commit result to db", action="store_true", default=False
        )

    def handle(self, *args, **options):
        meeting: Meeting = Meeting.objects.get(pk=options.get("m"))
        commit = options.get("commit")
        republish_target_btn: ReactionButton = meeting.reaction_buttons.get(
            pk=options.get("p")
        )
        assert republish_target_btn.target, "Återpublicera-knappen måste ha target satt"
        flag_btn = None
        if flag_pk := options.get("f"):
            flag_btn = meeting.reaction_buttons.get(pk=flag_pk)
            assert flag_btn.flag_mode, "Flagga-knappen måste ha flag_mode satt"
            self.stdout.write(f"Will flag proposals that change state with {flag_btn}")
        user = meeting.participants.get(pk=options.get("u"))

        ai_qs = meeting.agenda_items.filter(state__in=self.AI_STATES)
        if ai_count := ai_qs.count():
            self.stdout.write(f"Processing {ai_count} agenda items")
        else:
            self.stdout.write(self.style.WARNING("No published agenda items"))
            exit("Nothing to do")

        prop_qs = Proposal.objects.filter(
            agenda_item__in=ai_qs, state__in=self.PROP_STATES
        )
        # Find reactons over target
        reactions_qs = (
            republish_target_btn.reactions.filter(
                object_id__in=prop_qs.values("pk"),
                content_type=ContentType.objects.get_for_model(Proposal),
            )
            .values("object_id")
            .annotate(count=models.Count("pk"))
            .order_by()
        )
        self.stdout.write(
            f"Target for {republish_target_btn} is {republish_target_btn.target}"
        )
        reactions_qs = reactions_qs.filter(count__gte=republish_target_btn.target)
        over_limit_prop_qs = prop_qs.filter(
            pk__in=reactions_qs.values_list("object_id", flat=True)
        )

        with transaction.atomic(durable=True):
            already_flagged_prop_pks = set()
            if flag_btn:
                already_flagged_prop_pks.update(
                    flag_btn.reactions.filter(
                        object_id__in=over_limit_prop_qs.values("pk"),
                        content_type=ContentType.objects.get_for_model(Proposal),
                    ).values_list("object_id", flat=True)
                )
            if prop_count := over_limit_prop_qs.count():
                self.stdout.write(
                    self.style.SUCCESS(f"Found {prop_count} proposals to adjust.")
                )
            else:
                self.stdout.write(self.style.WARNING(f"No proposals to adjust"))
                exit()
            flagged = 0
            with set_actor(user):
                for prop in over_limit_prop_qs:
                    prop.publish()
                    prop.save()
                    if flag_btn and prop.pk not in already_flagged_prop_pks:
                        flag_btn.reactions.create(
                            object=prop, user=user, agenda_item_id=prop.agenda_item_id
                        )
                        flagged += 1
                if flagged:
                    self.stdout.write(
                        f"Flagged {flagged} proposals after they changed state"
                    )
            if commit:
                self.stdout.write(self.style.SUCCESS("All done, saving"))
            else:
                self.stdout.write(
                    self.style.WARNING("DRY-RUN: Specify --commit to save")
                )
                transaction.set_rollback(True)
