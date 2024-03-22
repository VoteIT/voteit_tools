from __future__ import annotations

from logging import getLogger
from typing import TYPE_CHECKING

from asgiref.sync import async_to_sync
from django.core.management import BaseCommand
from django_rq import get_queue

from envelope.channels.messages import Subscribe
from envelope.channels.models import ContextChannel
from envelope.utils import get_context_channel_registry
from voteit.meeting.models import Meeting

if TYPE_CHECKING:
    pass
logger = getLogger(__name__)


def _mk_message(pk, ch_name, user_pk) -> Subscribe:
    return Subscribe(
        channel_type=ch_name,
        pk=pk,
        mm={"user_pk": user_pk, "consumer_name": "abc"},
    )


class Command(BaseCommand):
    help = "RQ benchmarks"

    @property
    def channel_reg(self):
        return get_context_channel_registry()

    def add_arguments(self, parser):
        parser.add_argument(
            "name",
            help="channel name",
            choices=self.channel_reg.keys(),
        )
        parser.add_argument(
            "pk",
            help="channel object pk",
        )

    def handle(self, *args, **options):
        channel_type: type[ContextChannel] = self.channel_reg[options["name"]]
        instance = channel_type.model.objects.get(pk=options["pk"])
        meeting: Meeting = instance.meeting
        assert isinstance(meeting, Meeting)
        self.stdout.write(
            f"Running subscribe on channel {channel_type} with {meeting.participants.count()} subscribers"
        )
        queue = get_queue("default")
        user_pks = list(meeting.participants.all().values_list("pk", flat=True))
        for user_pk in user_pks:
            msg = Subscribe(
                mm={"user_pk": user_pk, "consumer_name": f"consumer_{user_pk}"},
                pk=options["pk"],
                channel_type=options["name"],
            )
            msg.rq_queue = queue
            msg.enqueue()
        self.stdout.write("Cleaning up. Check rq monitor for stats.")
        for user_pk in user_pks:
            ch = channel_type.from_instance(
                instance, consumer_channel=f"consumer_{user_pk}"
            )
            async_to_sync(ch.leave)()
