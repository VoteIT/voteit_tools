from __future__ import annotations

from datetime import date
from functools import reduce

from django.core.management import BaseCommand
from django.db import models
from django.utils import timezone
from envelope.models import Connection

from voteit.organisation.models import Organisation
from voteit_tools.utils import render_org_stats


class Command(BaseCommand):
    help = "Generate organisation statistics for a specific year"

    def add_arguments(self, parser):
        parser.add_argument("organisation", help="first part of org domain name")
        parser.add_argument("-y", help="Year", default=int(timezone.now().date().year))
        parser.add_argument(
            "--pmin",
            help="Möten med färre deltagare än det här räknas inte",
            default=15,
            type=int,
        )
        parser.add_argument(
            "--plarge",
            help="Anse möten med fler deltagare än detta som stora",
            default=500,
            type=int,
        )

    def handle(self, *args, **options):
        year = int(options["y"])

        org = Organisation.objects.filter(
            host__startswith=f"{options['organisation']}."
        ).get()
        out = render_org_stats(org, year)

        # Print results
        self.stdout.write(out)
