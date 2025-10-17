from auditlog.context import set_actor
from django.contrib.contenttypes.models import ContentType
from django.core.management import BaseCommand
from django.db import models
from django.db import transaction

from voteit.agenda.workflows import AgendaItemWf
from voteit.meeting.models import Meeting
from voteit.proposal.models import Proposal
from voteit.proposal.workflows import ProposalWf
from voteit.reactions.models import Reaction
from voteit.reactions.models import ReactionButton


class Command(BaseCommand):
    help = "Dra tillbaka förslag som inte uppnått speciell gräns"
    AI_STATES = (AgendaItemWf.ONGOING, AgendaItemWf.UPCOMING)
    PROP_STATES = (ProposalWf.UNHANDLED,)

    def add_arguments(self, parser):
        parser.add_argument("-m", help="Meeting pk", required=True)
        parser.add_argument(
            "-p", help="PK för återyrka-knapp med target", required=True
        )
        parser.add_argument(
            "-i",
            help="Ingorera förslag med följande knappar aktiva",
            action="extend",
            nargs="+",
            type=int,
        )
        parser.add_argument(
            "-b",
            help="Välj bara förslag med följande knappar aktiva",
            required=True,
            action="extend",
            nargs="+",
            type=int,
        )
        parser.add_argument(
            "-d",
            help="Sätt förslag med dessa knapp(ar) som avslagna istället",
            action="extend",
            nargs="+",
            type=int,
        )
        parser.add_argument(
            "-u",
            help="PK för användare som utför operationen - måste vara del av mötet",
            required=True,
        )
        parser.add_argument(
            "--ai",
            help="Välj bara från dessa dagordningspunkter (annars alla kommande/pågående)",
            action="extend",
            nargs="+",
            type=int,
        )
        parser.add_argument(
            "--commit",
            help="Commit result to db",
            action="store_true",
            default=False,
        )

    def handle(self, *args, **options):
        meeting: Meeting = Meeting.objects.get(pk=options.get("m"))
        commit = options.get("commit")
        republish_target_btn: ReactionButton = meeting.reaction_buttons.get(
            pk=options.get("p")
        )
        if not republish_target_btn.target:
            exit("(-p) Återpublicera-knappen måste ha target satt.")
        btns = meeting.reaction_buttons.filter(pk__in=options["b"], flag_mode=True)
        if btns.count() != len(options["b"]):
            exit("(-b) Knapp-IDn stämmer inte med mötesknappar i flagg-läge.")
        if options["i"]:
            ignore_btns = meeting.reaction_buttons.filter(
                pk__in=options["i"], flag_mode=True
            )
            if ignore_btns.count() != len(options["i"]):
                exit(
                    "(-i) Knapp-IDn för ignorera stämmer inte med mötesknappar i flagg-läge."
                )
        else:
            ignore_btns = []
        if options["d"]:
            denied_btns = meeting.reaction_buttons.filter(
                pk__in=options["d"], flag_mode=True
            )
            if denied_btns.count() != len(options["d"]):
                exit(
                    "(-d) Knapp-IDn för avslå (denied) stämmer inte med mötesknappar i flagg-läge."
                )
        else:
            denied_btns = []
        user = meeting.participants.get(pk=options.get("u"))
        if options["ai"]:
            ai_qs = meeting.agenda_items.filter(pk__in=options["ai"])
        else:
            ai_qs = meeting.agenda_items.filter(state__in=self.AI_STATES)
        if ai_count := ai_qs.count():
            self.stdout.write(f"Processing {ai_count} agenda items")
        else:
            self.stdout.write(self.style.WARNING("No matching agenda items"))
            exit("Nothing to do")
        prop_qs = Proposal.objects.filter(
            agenda_item__in=ai_qs, state=ProposalWf.PUBLISHED
        )
        # Find proposals that match specific flags
        if denied_btns:
            btns = btns.union(denied_btns)
            set_deny_object_ids = Reaction.objects.filter(
                button__in=denied_btns,
                object_id__in=prop_qs.values("pk"),
                content_type=ContentType.objects.get_for_model(Proposal),
            ).values_list("object_id", flat=True)
        else:
            set_deny_object_ids = []
        relevant_proposal_ids = Reaction.objects.filter(
            button__in=btns,
            object_id__in=prop_qs.values("pk"),
            content_type=ContentType.objects.get_for_model(Proposal),
        ).values_list("object_id", flat=True)
        # Find reactions over target
        self.stdout.write(
            f"Target for {republish_target_btn} is {republish_target_btn.target}"
        )
        over_target_proposal_ids = (
            republish_target_btn.reactions.filter(
                object_id__in=prop_qs.values("pk"),
                content_type=ContentType.objects.get_for_model(Proposal),
            )
            .values("object_id")
            .order_by()
            .annotate(count=models.Count("pk"))
            .filter(count__gte=republish_target_btn.target)
        )

        self.stdout.write(
            f"Found {over_target_proposal_ids.count()} proposals over target."
        )
        relevant_proposal_ids = relevant_proposal_ids.exclude(
            object_id__in=over_target_proposal_ids.values("object_id")
        )
        if ignore_btns:
            relevant_proposal_ids = relevant_proposal_ids.exclude(
                object_id__in=Reaction.objects.filter(
                    button__in=ignore_btns,
                    object_id__in=prop_qs.values("pk"),
                    content_type=ContentType.objects.get_for_model(Proposal),
                ).values_list("object_id", flat=True)
            )
        prop_qs = Proposal.objects.filter(
            pk__in=relevant_proposal_ids, agenda_item__meeting=meeting
        )
        if unhandled_count := prop_qs.count():
            self.stdout.write(
                self.style.SUCCESS(
                    f"Found {unhandled_count} proposals to set as unhandled."
                )
            )
        else:
            self.stdout.write(self.style.WARNING("Nothing set as unhandled."))

        with transaction.atomic(durable=True):
            with set_actor(user):
                for prop in prop_qs.filter(pk__in=set_deny_object_ids):
                    prop.denied()
                    prop.save()
                for prop in prop_qs.exclude(pk__in=set_deny_object_ids):
                    prop.unhandled()
                    prop.save()
            if commit:
                self.stdout.write(self.style.SUCCESS("All done, saving"))
            else:
                self.stdout.write(
                    self.style.WARNING("DRY-RUN: Specify --commit to save")
                )
                transaction.set_rollback(True)
