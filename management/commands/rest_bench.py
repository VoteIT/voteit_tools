from contextlib import suppress

from django.contrib.auth import get_user_model
from django.core.management import BaseCommand
from django.db.transaction import get_connection
from django.test.utils import CaptureQueriesContext
from django.urls import NoReverseMatch
from django.urls import reverse
from rest_framework.test import APIClient

from voteit_tools.utils import exectime


class Command(BaseCommand):
    help = "Check rest retrieve or list."

    def add_arguments(self, parser):
        parser.add_argument(
            "url_or_reverse",
            help="URL or reverse lookup name. Type 'all' for all of list urls.",
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

    def get_all_list_urls(self):
        from voteit.core.rest_api.router import router

        for prefix, viewset, basename in router.registry:
            with suppress(NoReverseMatch):
                yield reverse(basename + "-list")

    def check_url(self, user, client, url, sql=False):
        conn = get_connection()
        with CaptureQueriesContext(connection=conn) as cqc:
            with exectime() as et:
                response = client.get(url)
            if not response.content:
                self.stdout.write(self.style.ERROR(f"URL: {url} wasn't proper json"))
                return
            msg = (
                f"URL: {url} execution time: {et():.4f} secs - Queries: {len(cqc)} - "
                f"Content items: {len(response.json())} - Length: {len(response.content)}"
            )
            if len(cqc) > 5:
                msg = self.style.ERROR(msg)
            elif len(cqc) > 2:
                msg = self.style.WARNING(msg)
            self.stdout.write(msg)
            if sql:
                self.stdout.write(str(cqc.captured_queries))

    def handle(self, *args, **options):
        User = get_user_model()
        user = User.objects.get(pk=options["u"])
        client = APIClient()
        client.force_login(user)
        url = options["url_or_reverse"]
        if url == "all":
            for url in self.get_all_list_urls():
                self.check_url(user, client, url, sql=options["sql"])
        else:
            if not url.startswith("/"):
                url = reverse(url)
            self.check_url(user, client, url, sql=options["sql"])
