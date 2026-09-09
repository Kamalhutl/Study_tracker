"""Read-only audit: exit 1 if any verified company has bad provenance or fixture users remain active."""

import sys
from typing import Any

from django.core.management.base import BaseCommand

from apps.accounts.models import User
from apps.companies.models import Company
from apps.jobs.models import Job

_USER_EMAIL_SUFFIXES = ("@example.com", "@test.invalid", ".invalid")
_PROTECTED_EMAILS = {"officialkamal25@gmail.com"}


def _verified_by_is_bad(company: Company) -> bool:
    verified_by = company.verified_by
    if verified_by is None:
        return True
    if not verified_by.is_active:
        return True
    email = (verified_by.email or "").lower()
    return (
        email.endswith("@example.com")
        or email.endswith("@test.invalid")
        or email.endswith(".invalid")
    )


def _is_fixture_user(user: User) -> bool:
    email = (user.email or "").lower()
    if email in _PROTECTED_EMAILS:
        return False
    return any(email.endswith(suffix) for suffix in _USER_EMAIL_SUFFIXES)


class Command(BaseCommand):
    help = "Audit the public surface by provenance. Read-only, exits 1 on violations."

    def handle(self, *args: Any, **options: Any) -> None:
        verified = list(
            Company.all_objects.filter(is_verified=True, is_deleted=False).select_related(
                "verified_by"
            )
        )

        self.stdout.write("STAYS VERIFIED")
        self.stdout.write("slug | domain | verified_by | career_url")
        for c in verified:
            verified_by = getattr(c.verified_by, "email", None) or "-"
            self.stdout.write(
                f"{c.slug} | {c.domain or '-'} | {verified_by} | {c.career_url or '-'}"
            )

        violations: list[str] = []
        flagged_ids: set[int] = set()

        for c in verified:
            if _verified_by_is_bad(c):
                flagged_ids.add(c.id)
                violations.append(f"Verified company with bad provenance: {c.name} ({c.domain})")

        if flagged_ids:
            published_jobs = Job.objects.filter(
                company_id__in=flagged_ids,
                is_published=True,
                status="open",
            )
            for j in published_jobs:
                violations.append(
                    f"Published open job on bad-provenance company: {j.title} @ {j.company.name}"
                )

        active_fixture_users = [
            u for u in User.objects.filter(is_active=True) if _is_fixture_user(u)
        ]
        for u in active_fixture_users:
            violations.append(f"Active fixture user: {u.email}")

        verified_count = len(verified)
        violation_count = len(flagged_ids)
        clean_count = verified_count - violation_count

        self.stdout.write(
            f"SUMMARY verified={verified_count} violations={violation_count} clean={clean_count}"
        )

        if violations:
            for v in violations:
                self.stderr.write(self.style.ERROR(v))
            sys.exit(1)
        sys.exit(0)
