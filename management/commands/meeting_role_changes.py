from django.contrib.contenttypes.models import ContentType
from django.core.management import BaseCommand
from django.utils.dateparse import parse_datetime

from auditlog.models import LogEntry

from voteit.meeting.models import Meeting
from voteit.meeting.models import MeetingRoles
from voteit.meeting.roles import ROLE_POTENTIAL_VOTER


def _role_in(value: str, role: str) -> bool:
    # Note that auditlog seems to change the format role is stored in, based on repr?
    return f"'{role}'" in value or f"({role})" in value


class Command(BaseCommand):
    help = "List LogEntry changes where a role was added or removed for a meeting"

    def add_arguments(self, parser):
        parser.add_argument("meeting_pk", type=int, help="Meeting primary key")
        parser.add_argument(
            "--role",
            default=ROLE_POTENTIAL_VOTER,
            help=f"Role abbreviation to filter on (default: {ROLE_POTENTIAL_VOTER})",
        )
        parser.add_argument(
            "--since",
            help="Only show changes at or after this datetime (ISO 8601, e.g. 2024-01-01T00:00:00)",
        )

    def handle(self, *args, **options):
        meeting_pk = options["meeting_pk"]
        role = options["role"]
        try:
            meeting = Meeting.objects.get(pk=meeting_pk)
        except Meeting.DoesNotExist:
            raise SystemExit(f"No meeting found with pk={meeting_pk}")
        self.stdout.write(f"Meeting: {meeting.title} (pk={meeting_pk})")

        ct = ContentType.objects.get_for_model(MeetingRoles)
        qs_filter = dict(
            content_type=ct,
            additional_data__m=meeting_pk,
            changes__has_key="assigned",
        )
        if since_raw := options.get("since"):
            since = parse_datetime(since_raw)
            if since is None:
                raise SystemExit(f"Could not parse date: {since_raw!r}")
            qs_filter["timestamp__gte"] = since
        entries = LogEntry.objects.filter(**qs_filter).order_by("timestamp")

        results = []
        for entry in entries:
            old, new = entry.changes["assigned"]
            role_before = _role_in(old, role)
            role_after = _role_in(new, role)
            if role_before == role_after:
                continue
            action = "added" if role_after else "removed"
            results.append((entry, action))

        if not results:
            self.stdout.write(f"No '{role}' role changes found.")
            return

        self.stdout.write(f"\nFound {len(results)} change(s):\n")
        self.stdout.write("\t".join(["timestamp", "action", "actor", "actor_pk"]))
        for entry, action in results:
            self.stdout.write(
                "\t".join(
                    [
                        f"{entry.timestamp:%Y-%m-%d %H:%M:%S}",
                        action,
                        entry.actor_id
                        and f"{entry.actor.get_full_name()}"
                        or "-system",
                        f"{entry.actor_id}",
                    ]
                )
            )
