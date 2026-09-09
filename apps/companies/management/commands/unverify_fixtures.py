"""Unverify fixture companies and deactivate fixture users (dry-run by default)."""

from argparse import ArgumentParser
from typing import Any

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from apps.accounts.models import User
from apps.companies import services as company_services
from apps.companies.models import Company

_DOMAIN_SUFFIXES = (".example", ".invalid", ".demo.example")
_DOMAIN_EXACT = ("example.com",)
_NAME_PREFIXES = (
    "Smoke",
    "Bulk Co",
    "Company ",
    "Probe",
    "Due Now",
    "Paused Inc",
    "Failing Co",
    "Click Lever",
    "Burly Wood",
    "Acme Robotics",
    "Lever Demo",
)

_USER_EMAIL_SUFFIXES = ("@example.com", "@test.invalid", ".invalid")
_PROTECTED_EMAILS = {"officialkamal25@gmail.com"}


def _is_fixture_company(company: Company) -> bool:
    domain = (company.domain or "").lower()
    for suffix in _DOMAIN_SUFFIXES:
        if domain.endswith(suffix):
            return True
    if domain in _DOMAIN_EXACT:
        return True
    name = company.name or ""
    return any(name.startswith(prefix) for prefix in _NAME_PREFIXES)


def _is_fixture_user(user: User) -> bool:
    email = (user.email or "").lower()
    if email in _PROTECTED_EMAILS:
        return False
    return any(email.endswith(suffix) for suffix in _USER_EMAIL_SUFFIXES)


class Command(BaseCommand):
    help = "Unverify fixture/demo companies and deactivate fixture users (dry-run by default)."

    def add_arguments(self, parser: ArgumentParser) -> None:
        parser.add_argument(
            "--apply",
            action="store_true",
            default=False,
            help="Actually perform the mutations (default is dry-run).",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        if not settings.DEBUG and not getattr(settings, "ALLOW_DEMO_SEED", False):
            raise CommandError("unverify_fixtures refuses to run when DEBUG is False.")

        apply = options["apply"]
        mode = "APPLY" if apply else "DRY RUN"

        all_companies = Company.all_objects.all()
        fixture_companies = [c for c in all_companies if _is_fixture_company(c)]

        all_users = User.objects.all()
        fixture_users = [u for u in all_users if _is_fixture_user(u)]

        header = f"{'name':<30} {'domain':<30} {'was_verified':<14} {'action'}"
        self.stdout.write(header)
        self.stdout.write("-" * len(header))

        companies_unverified = 0
        for company in fixture_companies:
            was_verified = company.is_verified
            if was_verified:
                if apply:
                    company_services.unverify_company(company=company)
                action = "unverified"
                companies_unverified += 1
            else:
                action = "skip (already unverified)"
            self.stdout.write(
                f"{company.name:<30} {(company.domain or ''):<30} {was_verified!s:<14} {action}"
            )

        users_deactivated = 0
        for user in fixture_users:
            if user.is_active:
                if apply:
                    user.is_active = False
                    user.save(update_fields=["is_active"])
                action = "deactivated"
                users_deactivated += 1
            else:
                action = "skip (already inactive)"
            self.stdout.write(f"  user: {user.email} -> {action}")

        self.stdout.write(
            self.style.SUCCESS(
                f"\n{mode} complete: {companies_unverified} companies unverified, "
                f"{users_deactivated} users deactivated."
            )
        )
