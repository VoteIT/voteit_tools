from django.core.management import BaseCommand
from django.template.loader import render_to_string

from voteit.meeting.models import Meeting


class Command(BaseCommand):
    help = "Generera HTML-fil med alla förslag i mötet, uppdelat per dagordningspunkt"

    def add_arguments(self, parser):
        parser.add_argument("meeting", help="Meeting id", type=int)

    def handle(self, *args, **options):
        meeting: Meeting = Meeting.objects.get(id=options["meeting"])
        ai_props = [
            {
                "title": ai.title,
                "prop_ids": ai.proposals.order_by("created").values_list(
                    "prop_id", flat=True
                ),
            }
            for ai in meeting.agenda_items.all()
        ]
        self.stdout.write(
            render_to_string(
                "all_props.html",
                {
                    "meeting": meeting,
                    "ai_props": ai_props,
                },
            )
        )
