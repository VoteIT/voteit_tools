from __future__ import annotations

import zlib
from itertools import groupby
from json import loads
from logging import getLogger
from typing import TYPE_CHECKING
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.management import BaseCommand
from django.db.transaction import get_connection
from django.test.utils import CaptureQueriesContext
from envelope.core.channels import ContextChannel
from envelope.messages.channels import Subscribe
from envelope.signals import channel_subscribed
from envelope.utils import AppState
from envelope.utils import channel_layer
from envelope.utils import get_context_channel_registry

from voteit_tools.utils import exectime

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
    help = "Check subscribe info."

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
        parser.add_argument(
            "-u",
            help="User PK",
            required=True,
        )
        parser.add_argument(
            "--sql",
            help="Print SQL",
            action="store_true",
            default=False,
        )

    def handle(self, *args, **options):
        User = get_user_model()
        channel: type[ContextChannel] = self.channel_reg[options["name"]]
        user = User.objects.get(pk=options["u"])
        instance = channel.model.objects.get(pk=options["pk"])
        self.stdout.write(f"Checking subscribe for object {instance}")
        msg = _mk_message(instance.pk, channel.name, user.pk)
        conn = get_connection()

        with CaptureQueriesContext(connection=conn) as cqc:
            with patch.object(channel_layer, "send") as mocked_send:
                msg.run_job()
            self.stdout.write(f"Queries on subscribe: {len(cqc)}")
            for mc in mocked_send.mock_calls:
                txt = mc.args[1]["text_data"]
                self.stdout.write("Payload size: %s" % "{:,}".format(len(txt)))
                clvl = 3
                with exectime() as et:
                    txt_compressed = zlib.compress(bytes(txt, "utf-8"), level=clvl)
                self.stdout.write(
                    f"Payload compressed lvl {clvl} size: %s - exec time {et():.4f}"
                    % "{:,}".format(len(txt_compressed))
                )
                self.stdout.write(f"Compress exec time: {et():.4f} secs")
                data = loads(txt)
                app_state = data["p"]["app_state"]
                if not app_state:
                    self.stdout.write("No app_state")
                    continue
                for k, grp in groupby(app_state, key=lambda x: x["t"]):
                    if k == "s.batch":
                        for batch in grp:
                            size = "{:,}".format(len(str(batch["p"]["payloads"])))
                            self.stdout.write(
                                f"Batch {batch['p']['t']}".ljust(25)
                                + f"Items: {len(batch['p']['payloads'])}".ljust(20)
                                + f"Size: {size}"
                            )
                    else:
                        items = list(grp)
                        size = "{:,}".format(sum(len(str(x)) for x in items))
                        self.stdout.write(
                            f"{k}".ljust(25)
                            + f"Items: {len(items)}".ljust(20)
                            + f"Size: {size}"
                        )
        print("\n")
        app_state = AppState()
        kwargs = dict(
            sender=channel,
            context=instance,
            user=user,
            app_state=app_state,
        )
        for receiver in channel_subscribed._live_receivers(channel):
            with CaptureQueriesContext(connection=conn) as cqc:
                with exectime() as et:
                    receiver(signal=channel_subscribed, **kwargs)
                self.stdout.write(
                    f"Receiver: {receiver.__module__}.{receiver.__name__} execution time: {et():.4f} secs - queries: {len(cqc)}"
                )
                if options["sql"]:
                    self.stdout.write(str(cqc.captured_queries))
                print("-" * 80)
