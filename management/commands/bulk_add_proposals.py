from auditlog.context import set_actor
from django.core.management import BaseCommand
from django.db import transaction

from voteit.meeting.models import Meeting
from voteit.proposal.models import Proposal


class Command(BaseCommand):
    help = "Bulk add proposals according to agenda patterns"

    def add_arguments(self, parser):
        parser.add_argument("-m", help="Meeting pk", required=True)
        parser.add_argument("-s", help="Agenda item starts with")
        # parser.add_argument(
        #     "-t",
        #     help="Tags, possible to use several",
        #     action="extend",
        #     nargs="+",
        #     type=str,
        # )
        parser.add_argument(
            "-u",
            help="User to add proposals, specify as PK or userid",
            required=True,
        )
        parser.add_argument(
            "-g",
            help="Group to add proposals, uses as_group. Specify as pk or groupid",
        )
        parser.add_argument("--txt", help="Proposal text, use HTML!", required=True)
        parser.add_argument(
            "--commit", help="Commit result to db", action="store_true", default=False
        )

    def handle(self, *args, **options):
        meeting: Meeting = Meeting.objects.get(pk=options.get("m"))
        ai_qs = meeting.agenda_items.all()
        txt = options["txt"]
        # Not needed right now
        # if tags := options.get("t", []):
        #     ai_qs = ai_qs.filter(tags__overlap=tags)
        if ai_title_start := options.get("s"):
            ai_qs = ai_qs.filter(title__startswith=ai_title_start)
        # Avoid duplicate proposals
        existing_prop_ai_pks = Proposal.objects.filter(
            agenda_item__in=ai_qs, body__contains=txt
        ).values_list("agenda_item_id", flat=True)
        if existing_prop_ai_pks.count():
            self.stdout.write(
                self.style.WARNING(
                    f"There are already proposals within {existing_prop_ai_pks.count()} of the agenda items that matches the same text, they will be ignored"
                )
            )
            ai_qs = ai_qs.exclude(pk__in=existing_prop_ai_pks)
        if ai_qs.count():
            self.stdout.write(
                f"Found {ai_qs.count()} agenda items in meeting {meeting.title}"
            )
        else:
            exit("No agenda items found, aborting")
        commit = options.get("commit")
        try:
            user = meeting.participants.get(**{"pk": int(options["u"])})
        except ValueError:
            user = meeting.participants.get(**{"userid": options["u"]})
        if group := options.get("g"):
            try:
                group = meeting.groups.get(**{"pk": int(group)})
            except ValueError:
                group = meeting.groups.get(**{"groupid": group})
        with transaction.atomic(durable=True):
            with set_actor(user):
                prop_kwargs = {"author": user}
                if group:
                    prop_kwargs.update({"meeting_group": group, "as_group": True})
                for ai in ai_qs:
                    ai.proposals.create(body=txt, **prop_kwargs)
            if commit:
                self.stdout.write(self.style.SUCCESS("All done, saving"))
            else:
                self.stdout.write(
                    self.style.WARNING("DRY-RUN: Specify --commit to save")
                )
                transaction.set_rollback(True)
