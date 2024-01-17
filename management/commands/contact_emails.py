from __future__ import annotations

from datetime import timedelta
from functools import reduce
from operator import or_

from django.contrib.auth import get_user_model
from django.core.management import BaseCommand
from django.db import models
from django.utils.timezone import now

from voteit.meeting.models import Meeting
from voteit.meeting.models import MeetingRoles
from voteit.meeting.roles import ROLE_MODERATOR
from voteit.meeting.workflows import MeetingWf
from voteit.organisation.models import Organisation
from voteit.organisation.models import OrganisationRoles
from voteit.organisation.roles import ROLE_MEETING_CREATOR
from voteit.organisation.roles import ROLE_ORG_MANAGER

User = get_user_model()


class Command(BaseCommand):
    help = "Fetch emails for contacts, only upcoming or ongoing meetings"

    def add_arguments(self, parser):
        parser.add_argument(
            "-m",
            help="Skip moderators",
            default=False,
            action="store_true",
        )
        parser.add_argument(
            "-a",
            help="Skip org admins",
            default=False,
            action="store_true",
        )
        parser.add_argument(
            "-c",
            help="Skip meeting creators",
            default=False,
            action="store_true",
        )
        parser.add_argument(
            "--started",
            help="Skip meetings started more than x days ago. Default=30",
            default=30,
            type=int,
        )
        parser.add_argument(
            "--created",
            help="Skip meetings in upcoming state created more than x days ago Default=90",
            default=90,
            type=int,
        )
        parser.add_argument(
            "-o", "--output", help="txt file to write contents to, one email per row"
        )

    def handle(self, *args, **options):
        filters = []
        if not options.get("m"):
            relevant_meetings_qs = Meeting.objects.filter(
                models.Q(
                    state=MeetingWf.UPCOMING,
                    created__gt=now() - timedelta(days=options["created"]),
                )
                | models.Q(
                    state=MeetingWf.ONGOING,
                    start_time__gt=now() - timedelta(days=options["started"]),
                )
            )
            filters.append(
                models.Q(
                    pk__in=MeetingRoles.objects.filter(
                        context__in=relevant_meetings_qs,
                        assigned__contains=ROLE_MODERATOR,
                    ).values_list("user_id", flat=True)
                )
            )
        if not options.get("a"):
            filters.append(
                models.Q(
                    pk__in=OrganisationRoles.objects.filter(
                        assigned__contains=ROLE_ORG_MANAGER
                    ).values_list("user_id", flat=True)
                )
            )
        if not options.get("c"):
            filters.append(
                models.Q(
                    pk__in=OrganisationRoles.objects.filter(
                        assigned__contains=ROLE_MEETING_CREATOR
                    ).values_list("user_id", flat=True)
                )
            )
        if not filters:
            exit("Everything filtered so nothing to show")
        qs = User.objects.filter(reduce(or_, filters))
        # Remove other things that we might not want, like organisations with no provider
        qs = qs.exclude(
            organisation__in=Organisation.objects.filter(
                models.Q(provider__isnull=True)
                | models.Q(host="demo.voteit.se")
                | models.Q(active=False)
            )
        )
        emails = (
            qs.exclude(email="")
            .values_list("email", flat=True)
            .distinct()
            .order_by("email")
        )
        self.stdout.write(
            self.style.SUCCESS(
                f"Found {qs.count()} users and {emails.count()} distinct emails"
            )
        )
        if output := options["output"]:
            if not emails.count():
                exit("Nothing to write")
            with open(output, "w") as f:
                f.writelines([f"{e}\n" for e in emails])
            self.stdout.write(f"Wrote {output}")
        else:
            self.stdout.writelines(emails)
