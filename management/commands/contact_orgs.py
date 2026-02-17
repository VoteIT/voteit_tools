from __future__ import annotations

from django.contrib.auth import get_user_model
from django.core.management import BaseCommand

from voteit.organisation.models import OrganisationRoles
from voteit.organisation.roles import ROLE_ORG_MANAGER
from voteit_org.models import ContactInfo
from voteit.organisation.models import Organisation

User = get_user_model()


class Command(BaseCommand):
    help = "Fetch emails for generic contacts, or admins"

    def handle(self, *args, **options):
        contacts_with_email = ContactInfo.objects.exclude(
            organisation__active=False
        ).exclude(generic_email="")
        missing_contact_orgs = Organisation.objects.exclude(
            pk__in=contacts_with_email.values_list("organisation_id", flat=True)
        ).exclude(active=False)
        self.stdout.write("-" * 80)
        self.stdout.write(
            f"{contacts_with_email.count()} organisationer med kontakt-epost"
        )
        self.stdout.write("=" * 80)
        for email, org_title in contacts_with_email.values_list(
            "generic_email", "organisation__title"
        ):
            self.stdout.write(f"{org_title}\t{email}")
        self.stdout.write("-" * 80)
        self.stdout.write(
            f"{missing_contact_orgs.count()} organisationer utan kontaktuppgifter"
        )
        self.stdout.write("=" * 80)
        for org_title, email in (
            OrganisationRoles.objects.filter(
                context__in=missing_contact_orgs, assigned__contains=ROLE_ORG_MANAGER
            )
            .exclude(user__email="")
            .exclude(user__email__contains="betahaus.net")
            .values_list("context__title", "user__email")
            .order_by("context__title")
        ):
            self.stdout.write(f"{org_title}\t{email}")
