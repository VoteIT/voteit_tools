from auditlog.context import set_actor
from django.core.management import BaseCommand
from django.db import models
from django.db import transaction

from voteit.meeting.models import Meeting
from voteit.poll.app.polls.combined_simple import CombinedSimple
from voteit.poll.utils import get_poll_method_registry
from voteit_tools.management.utils import get_user


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
            "-u", help="User to add poll, specify as PK or userid", required=True
        )
        parser.add_argument("--txt", help="Poll text, use HTML!", required=False)
        parser.add_argument(
            "--commit", help="Commit result to db", action="store_true", default=False
        )
        reg = get_poll_method_registry()
        parser.add_argument("--method", choices=reg.keys(), default=CombinedSimple.name)

    def handle(self, *args, **options):
        meeting: Meeting = Meeting.objects.get(pk=options.get("m"))
        ai_qs = meeting.agenda_items.all()
        # Not needed right now
        # if tags := options.get("t", []):
        #     ai_qs = ai_qs.filter(tags__overlap=tags)
        if ai_title_start := options.get("s"):
            ai_qs = ai_qs.filter(title__startswith=ai_title_start)
        ai_qs = ai_qs.annotate(
            proposals_pub_count=models.Count(
                "proposals", filter=models.Q(proposals__state="published")
            )
        )
        no_prop_ai_qs = ai_qs.filter(proposals_pub_count=0)
        if no_prop_ai_qs.exists():
            self.stdout.write(
                self.style.WARNING(
                    "The following agenda items contain no proposals in published state, so they will be removed:"
                )
            )
            for ai in no_prop_ai_qs:
                self.stdout.write(ai.title)
            ai_qs = ai_qs.difference(no_prop_ai_qs)
        if ai_qs.count():
            self.stdout.write(
                f"Found {ai_qs.count()} agenda items in meeting {meeting.title}"
            )
        else:
            exit("No agenda items found, aborting")
        commit = options.get("commit")
        user = get_user(options["u"], meeting)
        body = options.get("txt", "")
        with transaction.atomic(durable=True):
            with set_actor(user):
                for ai in ai_qs:
                    poll = meeting.polls.create(
                        agenda_item=ai,
                        title=f"{ai.title[:67]} 1",
                        method_name=options["method"],
                        body=body,
                    )
                    poll.proposals.add(*ai.proposals.all())
                    poll.upcoming()
                    poll.save()
            if commit:
                self.stdout.write(self.style.SUCCESS("All done, saving"))
            else:
                self.stdout.write(
                    self.style.WARNING("DRY-RUN: Specify --commit to save")
                )
                transaction.set_rollback(True)
