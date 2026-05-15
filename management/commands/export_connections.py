from __future__ import annotations

import json

from django.core.management import BaseCommand
from django.utils.timezone import now


class Command(BaseCommand):
    help = "Export envelope Connection models to a JSON file"

    def add_arguments(self, parser):
        parser.add_argument(
            "output",
            nargs="?",
            default=f"connections_{now().strftime('%Y%m%d_%H%M%S')}.json",
            help="Output file path (default: connections_<timestamp>.json)",
        )
        parser.add_argument(
            "--online-only",
            action="store_true",
            default=False,
            help="Only export connections where online=True",
        )

    def handle(self, *args, **options):
        from envelope.models import Connection

        qs = Connection.objects.select_related("user").order_by("id")
        if options["online_only"]:
            qs = qs.filter(online=True)

        records = []
        for conn in qs:
            records.append(
                {
                    "user_id": conn.user_id,
                    "channel_name": conn.channel_name,
                    "online_at": conn.online_at.isoformat() if conn.online_at else None,
                    "offline_at": conn.offline_at.isoformat()
                    if conn.offline_at
                    else None,
                    "last_action": conn.last_action.isoformat()
                    if conn.last_action
                    else None,
                }
            )

        output_path = options["output"]
        with open(output_path, "w") as f:
            json.dump(records, f, indent=2)

        self.stdout.write(
            self.style.SUCCESS(
                f"Exported {len(records)} connection(s) to {output_path}"
            )
        )
