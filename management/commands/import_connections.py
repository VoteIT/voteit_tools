from __future__ import annotations

import json
from datetime import datetime

from django.core.management import BaseCommand


def _latest(*values: str | None) -> datetime | None:
    parsed = []
    for v in values:
        if v:
            parsed.append(datetime.fromisoformat(v))
    return max(parsed) if parsed else None


class Command(BaseCommand):
    help = "Import Connection records from an export_connections JSON file into voteit.websocket.models.Connection"

    def add_arguments(self, parser):
        parser.add_argument("input", help="Path to the JSON file produced by export_connections")

    def handle(self, *args, **options):
        from voteit.websocket.models import Connection

        with open(options["input"]) as f:
            records = json.load(f)

        created = skipped = 0
        for rec in records:
            last_action = _latest(rec.get("offline_at"), rec.get("last_action"))
            connected_at = rec.get("online_at")

            obj, was_created = Connection.objects.get_or_create(
                user_id=rec["user_id"],
                channel_name=rec["channel_name"],
                defaults={
                    "connected_at": datetime.fromisoformat(connected_at) if connected_at else None,
                    "last_action": last_action,
                },
            )
            if was_created:
                created += 1
            else:
                skipped += 1

        self.stdout.write(
            self.style.SUCCESS(f"Done: {created} created, {skipped} already existed")
        )