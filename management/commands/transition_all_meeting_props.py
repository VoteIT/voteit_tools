from auditlog.context import set_actor
from django.contrib.contenttypes.models import ContentType
from django.core.management import BaseCommand
from django.db import transaction

from voteit.agenda.workflows import AgendaItemWf
from voteit.meeting.models import Meeting
from voteit.proposal.models import Proposal
from voteit.proposal.workflows import ProposalWf


class Command(BaseCommand):
    help = """Gör en transition alla förslag i ett möte med ett visst state och sätt en flaggknapp för dessa förslag.
    Gäller endast dagordningspunkter som är kommande eller pågående."""

    AI_STATES = (AgendaItemWf.ONGOING, AgendaItemWf.UPCOMING)

    def add_arguments(self, parser):
        parser.add_argument(dest="meeting", help="Meeting PK", type=int)
        parser.add_argument("-s", help="Från state", type=str)
        parser.add_argument("-t", help="Namn på transition", type=str)
        parser.add_argument("-f", help="PK för eventuell flagga att sätta")
        parser.add_argument(
            "-u",
            help="userid för användare som utför operationen - måste vara del av mötet",
            required=True,
            type=str,
        )
        parser.add_argument(
            "--commit", help="Commit result to db", action="store_true", default=False
        )

    def handle(self, *args, **options):
        meeting: Meeting = Meeting.objects.get(pk=options["meeting"])
        source_state = options["s"]
        transition = getattr(Proposal, options["t"])
        assert source_state in ProposalWf.states, "Invalid source state"
        assert hasattr(transition, "_django_fsm"), "Invalid transition"
        user = meeting.participants.get(userid=options["u"])
        flag_btn = None
        if flag_pk := options["f"]:
            flag_btn = meeting.reaction_buttons.get(pk=flag_pk)
            assert flag_btn.flag_mode, "Reaction button must be a flag button"
            self.stdout.write(f"Will flag proposals that change state with {flag_btn}")

        ai_qs = meeting.agenda_items.filter(state__in=self.AI_STATES)
        if ai_count := ai_qs.count():
            self.stdout.write(f"Processing {ai_count} agenda item(s)")
        else:
            self.stdout.write(self.style.WARNING("No published agenda items"))
            exit("Nothing to do")

        prop_qs = Proposal.objects.filter(agenda_item__in=ai_qs, state=source_state)
        if prop_count := prop_qs.count():
            self.stdout.write(f"Found {prop_count} proposal(s)")
        else:
            self.stdout.write(self.style.WARNING("No proposals found"))
            exit("Nothing to do")

        with transaction.atomic(durable=True):
            flagged_count = 0
            with set_actor(user):
                for proposal in prop_qs:
                    if flag_btn:
                        _, created = flag_btn.reactions.get_or_create(
                            agenda_item_id=proposal.agenda_item_id,
                            object_id=proposal.id,
                            content_type=ContentType.objects.get_for_model(Proposal),
                            defaults={"user": user},
                        )
                        if created:
                            flagged_count += 1
                    transition(proposal)
                    proposal.save()
                    if not options["commit"]:
                        self.stdout.write(f"{proposal.prop_id} would change")

            if flagged_count:
                self.stdout.write(
                    f"Flagged {flagged_count} proposals after they changed state"
                )

            if options["commit"]:
                self.stdout.write(self.style.SUCCESS("All done, saving"))
            else:
                self.stdout.write(
                    self.style.WARNING("DRY-RUN: Specify --commit to save")
                )
                transaction.set_rollback(True)
