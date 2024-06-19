from __future__ import annotations

from datetime import date
from functools import reduce

from django.core.management import BaseCommand
from django.db import models
from django.utils import timezone
from envelope.models import Connection

from voteit.organisation.models import Organisation


class Command(BaseCommand):
    help = "Printa aktiva domäner"

    def add_arguments(self, parser):
        parser.add_argument(
            "--inactive",
            help="Ta med organisationer som inte är aktiva nu",
            default=False,
            action="store_true",
        )
        parser.add_argument(
            "--go",
            help="Formatera som GO-domänsträng",
            default=False,
            action="store_true",
        )

    def handle(self, *args, **options):
        org_qs = Organisation.objects.all().order_by("host")
        if not options["inactive"]:
            org_qs = org_qs.filter(active=True)
        values = []
        for org in org_qs:
            values.append(org.host)
        # Print results
        self.stdout.write("\n\n")
        if options["go"]:
            self.stdout.write("`" + "`,`".join(values) + "`")
        else:
            for val in values:
                self.stdout.write(val)
