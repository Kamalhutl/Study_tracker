"""Add a company via Case A (main website) or Case B (career URL)."""

from argparse import ArgumentParser
from typing import Any

from django.core.management.base import BaseCommand, CommandError

from apps.accounts.models import User
from apps.companies import services
from apps.companies.exceptions import CompanyError


class Command(BaseCommand):
    help = (
        "Add a company. Route to Case A (main website -> detection) or Case B "
        "(direct career URL -> verified + scheduled). --actor-email is required."
    )

    def add_arguments(self, parser: ArgumentParser) -> None:
        parser.add_argument("--name", required=True, help="Company name")
        parser.add_argument("--website", help="Homepage URL (Case A)")
        parser.add_argument("--career-url", help="Known career page URL (Case B)")
        parser.add_argument("--actor-email", required=True, help="User email for audit tracking")

    def handle(self, *args: Any, **options: Any) -> None:
        if bool(options["website"]) == bool(options["career_url"]):
            raise CommandError(
                "Provide exactly one of --website (Case A) or --career-url (Case B)."
            )

        try:
            actor = User.objects.get(email=options["actor_email"])
        except User.DoesNotExist:
            raise CommandError(
                f"Nobody with email {options['actor_email']!r} — create the user first."
            ) from None

        try:
            if options["website"]:
                company = services.add_company_from_main_website(
                    name=options["name"], website_url=options["website"], actor=actor
                )
                self.stdout.write(
                    f"Case A company created: {company.name} (id={company.id}). "
                    "Detection is queued — a human must approve a career URL before scraping starts."
                )
            else:
                company = services.add_company_from_direct_career_url(
                    name=options["name"], career_url=options["career_url"], actor=actor
                )
                self.stdout.write(
                    f"Case B company created: {company.name} (id={company.id}). "
                    "Verified + scheduled; first scrape window is set."
                )
        except CompanyError as exc:
            raise CommandError(str(exc)) from exc
