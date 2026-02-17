import random
from contextlib import suppress

from auditlog.context import disable_auditlog
from django.contrib.auth.hashers import make_password
from django.core.management import BaseCommand
from django.db import transaction

from voteit.agenda.models import AgendaItem
from voteit.agenda.workflows import AgendaItemWf
from voteit.core.models import User
from voteit.meeting.models import Meeting
from voteit.meeting.roles import ROLE_PARTICIPANT, ROLE_POTENTIAL_VOTER
from voteit.meeting.workflows import MeetingWf
from voteit.organisation.models import Organisation
from voteit.poll.app.er_policies.auto_before_poll import AutoBeforePoll
from voteit.proposal.models import Proposal


class Command(BaseCommand):
    help = "Create a demo meeting and play actions."

    def add_arguments(self, parser):
        parser.add_argument("org_id", help="Organisation ID", type=int)
        parser.add_argument("password", help="Password for created users", type=str)
        parser.add_argument("-u", help="Number of users", type=int, default=50)

    @transaction.atomic
    def create_meeting(self, org: Organisation, password: str, user_count: int):
        # Create meeting
        # Set voter registry to automatic - changing state of a poll will commit potential voters
        meeting = Meeting.objects.create(
            er_policy_name=AutoBeforePoll.name,
            organisation=org,
            state=MeetingWf.ONGOING,
            title="Scripted demo meeting",
        )
        ai = AgendaItem.objects.create(
            title="Demo AI", meeting=meeting, state=AgendaItemWf.ONGOING
        )
        # Create users
        password_hash = make_password(password)  # Use same password hash for speed
        users = [
            User.objects.create(
                is_staff=True,
                last_name="__auto__",
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
        print(f"Creating meeting, ai and {options['u']} users...")
        org = Organisation.objects.get(pk=options["org_id"])
        with disable_auditlog():
            meeting, ai, users = self.create_meeting(
                org=org,
                password=options["password"],
                user_count=options["u"],
            )
            print(
                f"Open '{meeting.title}' in browser. Participating objects:\n"
                f"Meeting: {meeting.pk}\n"
                f"AI: {ai.pk}\n\n"
            )
            with suppress(KeyboardInterrupt):
                input("Press enter to delete users and meeting.\n")

            print("Deleting demo meeting...")
            meeting.delete()
            for x in users:
                x.delete()
