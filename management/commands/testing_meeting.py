import random
from collections import defaultdict

from auditlog.context import disable_auditlog
from django.contrib.auth.hashers import make_password
from django.core.management import BaseCommand
from django.core.management import CommandError
from django.db import transaction
from django.db.models import ProtectedError
from django.db.models import RestrictedError

from voteit.agenda.models import AgendaItem
from voteit.agenda.statemachines import AgendaItemStateMachine
from voteit.core.models import User
from voteit.meeting.models import Meeting
from voteit.meeting.roles import ROLE_PARTICIPANT, ROLE_POTENTIAL_VOTER
from voteit.meeting.statemachines import MeetingStateMachine
from voteit.organisation.models import Organisation
from voteit.poll.app.er_policies.auto_before_poll import AutoBeforePoll
from voteit.proposal.models import Proposal

# Markers that identify data created by this command. Nothing else writes them,
# so they're what a later run uses to find leftovers from an aborted one.
AUTO_MARKER = "__auto__"
DEMO_MEETING_TITLE = "Scripted demo meeting"


class Command(BaseCommand):
    help = "Create a demo meeting and play actions."

    def add_arguments(self, parser):
        # Optional so --cleanup-only can run bare, see handle().
        parser.add_argument("org_id", help="Organisation ID", type=int, nargs="?")
        parser.add_argument(
            "password", help="Password for created users", type=str, nargs="?"
        )
        parser.add_argument("-u", help="Number of users", type=int, default=50)
        parser.add_argument(
            "--cleanup-only",
            help="Remove leftover demo data and exit without creating anything",
            action="store_true",
            default=False,
        )

    def find_leftovers(self):
        """Demo data currently in the db, from this run or an aborted earlier one.

        Deliberately not scoped to a single organisation: usernames are globally
        unique, so a stale user-0 in another org blocks creation just as hard.
        """
        return (
            Meeting.objects.filter(title=DEMO_MEETING_TITLE),
            User.objects.filter(last_name=AUTO_MARKER),
        )

    def report_leftovers(self, meetings, users) -> bool:
        """Print what was found, grouped by org. Returns True if there's anything."""
        counts = defaultdict(lambda: [0, 0])
        for org_pk, title in meetings.values_list(
            "organisation__pk", "organisation__title"
        ):
            counts[(org_pk, title)][0] += 1
        for org_pk, title in users.values_list(
            "organisation__pk", "organisation__title"
        ):
            counts[(org_pk, title)][1] += 1
        if not counts:
            return False
        self.stdout.write(self.style.WARNING("Found leftover demo data:"))
        for (org_pk, title), (meeting_count, user_count) in sorted(
            counts.items(), key=lambda item: item[0][0] or 0
        ):
            org_label = f"{title} (org {org_pk})" if org_pk else "no organisation"
            self.stdout.write(
                f"  {org_label}: {meeting_count} meeting(s), {user_count} user(s)"
            )
        return True

    def cleanup(self, meetings, users):
        """Delete demo data. Meetings first -- most user FKs are RESTRICT and only
        go away with the meeting cascade."""
        with disable_auditlog():
            meeting_count = meetings.count()
            meetings.delete()
            user_count, failed = self.delete_users(users)
        self.stdout.write(
            self.style.SUCCESS(
                f"Deleted {meeting_count} meeting(s) and {user_count} user(s)"
            )
        )
        if failed:
            self.stderr.write(
                self.style.ERROR(
                    f"Could not delete {len(failed)} user(s), still referenced "
                    f"elsewhere: {', '.join(failed)}"
                )
            )

    def delete_users(self, users) -> tuple[int, list[str]]:
        """Bulk delete, falling back to one-by-one so a single stuck user doesn't
        block the rest. Each attempt gets its own transaction -- a failed delete
        would otherwise poison the surrounding one."""
        try:
            with transaction.atomic():
                count = users.count()
                users.delete()
                return count, []
        except (RestrictedError, ProtectedError):
            pass
        deleted = 0
        failed = []
        for user in list(users):
            try:
                with transaction.atomic():
                    user.delete()
                deleted += 1
            except (RestrictedError, ProtectedError):
                failed.append(user.username)
        return deleted, failed

    def confirm(self, question: str) -> bool:
        try:
            answer = input(f"{question} [y/N] ")
        except (KeyboardInterrupt, EOFError):
            self.stdout.write("")
            return False
        return answer.strip().lower() in ("y", "yes")

    @transaction.atomic
    def create_meeting(self, org: Organisation, password: str, user_count: int):
        # Create meeting
        # Set voter registry to automatic - changing state of a poll will commit potential voters
        meeting = Meeting.objects.create(
            er_policy_name=AutoBeforePoll.name,
            organisation=org,
            state=MeetingStateMachine.ongoing.value,
            title=DEMO_MEETING_TITLE,
        )
        ai = AgendaItem.objects.create(
            title="Demo AI", meeting=meeting, state=AgendaItemStateMachine.ongoing.value
        )
        # Create users
        password_hash = make_password(password)  # Use same password hash for speed
        users = [
            User.objects.create(
                is_staff=True,
                last_name=AUTO_MARKER,
                organisation=org,
                password=password_hash,
                username=f"user-{i}",
            )
            for i in range(user_count)
        ]
        for user in users:
            meeting.add_roles(user, ROLE_PARTICIPANT, ROLE_POTENTIAL_VOTER)
        # Create 6 proposals
        for i in range(7):
            Proposal.objects.create(
                author=random.choice(users),
                agenda_item=ai,
                prop_id=f"prop_{i}",
                body=f"Proposal #{i}",
            )
        return meeting, ai, users

    def handle(self, *args, **options):
        if options["cleanup_only"]:
            meetings, users = self.find_leftovers()
            if not self.report_leftovers(meetings, users):
                self.stdout.write("No demo data found — nothing to do.")
                return
            if not self.confirm("Delete it?"):
                self.stdout.write(self.style.WARNING("Aborted, nothing deleted."))
                return
            self.cleanup(meetings, users)
            return

        if options["org_id"] is None or options["password"] is None:
            raise CommandError(
                "org_id and password are required unless --cleanup-only is given"
            )

        leftovers = self.find_leftovers()
        if self.report_leftovers(*leftovers):
            self.stdout.write(
                "An earlier run probably didn't clean up after itself. Creating new "
                "data will fail on the duplicate usernames until this is removed."
            )
            if not self.confirm("Delete it before creating new data?"):
                raise CommandError("Leftover demo data present — aborting.")
            self.cleanup(*leftovers)

        org = Organisation.objects.filter(pk=options["org_id"]).first()
        if org is None:
            raise CommandError(f"No organisation with id {options['org_id']}")

        self.stdout.write(f"Creating meeting, ai and {options['u']} users...")
        with disable_auditlog():
            meeting, ai, users = self.create_meeting(
                org=org,
                password=options["password"],
                user_count=options["u"],
            )
        try:
            self.stdout.write(
                self.style.SUCCESS(
                    f"Open '{meeting.title}' in browser. Participating objects:\n"
                    f"Meeting: {meeting.pk}\n"
                    f"AI: {ai.pk}\n"
                )
            )
            try:
                input("Press enter to delete users and meeting.\n")
            except (KeyboardInterrupt, EOFError):
                self.stdout.write("")
        finally:
            # Runs even if the wait is interrupted, so this run cleans up after
            # itself whenever the process gets the chance.
            self.stdout.write("Deleting demo meeting...")
            self.cleanup(
                Meeting.objects.filter(pk=meeting.pk),
                User.objects.filter(pk__in=[x.pk for x in users]),
            )
