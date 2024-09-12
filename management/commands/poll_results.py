import csv
from dataclasses import asdict
from dataclasses import dataclass
from dataclasses import fields

from django.core.management import BaseCommand

from voteit.meeting.models import Meeting
from voteit.poll.app.polls.combined_simple import CombinedSimple
from voteit.poll.workflows import PollWf
from voteit.poll.models import Poll


@dataclass
class SimplePollProposalExport:
    ai_title: str
    prop_text: str
    yes: int
    no: int
    abstain: int
    er_voters: int
    er_voter_weight: int


class Command(BaseCommand):
    help = "Read polls results"

    def add_arguments(self, parser):
        parser.add_argument("-m", help="Meeting pk", required=True)
        # reg = get_poll_method_registry()
        # Vi kan lägga på fler metoder sen
        # parser.add_argument("--method", choices=reg.keys(), default=CombinedSimple.name)
        parser.add_argument("-o", help="Output file", required=True)

    def handle(self, *args, **options):
        meeting: Meeting = Meeting.objects.get(pk=options.get("m"))
        poll_qs = (
            meeting.polls.filter(state=PollWf.FINISHED, method_name=CombinedSimple.name)
            .prefetch_related(
                "agenda_item",
                "electoral_register",
                "proposals",
            )
            .order_by("started")
        )
        if poll_qs.count():
            self.stdout.write(
                f"Found {poll_qs.count()} polls with method {CombinedSimple.title} in meeting {meeting.title}"
            )
        else:
            exit("No finished polls with combined simple found, aborting")
        items = []
        for poll in poll_qs:
            poll: Poll
            for prop in poll.proposals.all():
                items.append(
                    SimplePollProposalExport(
                        ai_title=poll.agenda_item.title,
                        prop_text=prop.body,
                        er_voters=poll.electoral_register.voterweight_set.count(),
                        er_voter_weight=poll.electoral_register.get_total_vote_weight(),
                        **poll.result_data["results"][str(prop.pk)],
                    )
                )
        fn = options["o"]
        with open(fn, "w") as stream:
            writer = csv.DictWriter(
                stream, fieldnames=[f.name for f in fields(SimplePollProposalExport)]
            )
            writer.writeheader()  # Custom?
            writer.writerows(iter(asdict(x) for x in items))
        self.stdout.write(self.style.SUCCESS(f"All done, wrote {fn}"))
