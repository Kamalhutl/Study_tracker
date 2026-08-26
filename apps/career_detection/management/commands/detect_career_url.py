"""Run career-URL detection for a company.

Usage:
    ./manage.py detect_career_url --company acme-corp
    ./manage.py detect_career_url --company 42 --dry-run --verbose
"""

from __future__ import annotations

import uuid
from argparse import ArgumentParser
from typing import Any

from django.core.management.base import BaseCommand, CommandError

from apps.companies.exceptions import DetectionNotApplicable
from apps.companies.models import Company

from ...services import run_detection


class Command(BaseCommand):
    help = "Detect the career page URL for a company."

    def add_arguments(self, parser: ArgumentParser) -> None:
        parser.add_argument("--company", required=True, help="Company slug or PK")
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Score candidates without persisting anything.",
        )
        parser.add_argument("--max-checks", type=int, default=None, help="Override the URL budget.")
        parser.add_argument("--verbose", action="store_true", help="Print per-candidate trails.")

    def handle(self, *args: Any, **options: Any) -> None:
        company = self._resolve_company(options["company"])
        try:
            result = run_detection(
                company,
                dry_run=options["dry_run"],
                max_checks=options["max_checks"],
            )
        except DetectionNotApplicable as exc:
            raise CommandError(str(exc)) from exc

        self.stdout.write(
            f"{company.name}: status={result['status']} "
            f"candidates={len(result['candidates'])} "
            f"best={result.get('best_score') or 0} checks={result['checks_used']}"
        )

        if result["notes"]:
            self.stdout.write("notes:")
            for note in result["notes"]:
                self.stdout.write(f"  - {note}")

        for candidate in result["candidates"]:
            score = candidate["score"]
            trail = "; ".join(f"{r['rule']}({r['points']:+d})" for r in candidate["trail"])
            self.stdout.write(
                f"  [{score:>3}] {candidate['origin']:<16} {candidate['url']}  {trail}"
            )

        if options["verbose"] and result["candidates"]:
            self.stdout.write("\nTop trail breakdown:")
            for candidate in result["candidates"][:5]:
                self.stdout.write(f"  {candidate['url']}")
                for rule in candidate["trail"]:
                    self.stdout.write(
                        f"    {rule['rule']:>24} {rule['points']:+d}  {rule['detail']}"
                    )

    def _resolve_company(self, company: str) -> Company:
        """Resolve ``--company`` given a slug, integer PK, or UUID PK (§6.8)."""
        queryset = Company.objects.all()
        try:
            found: Company | None
            if _is_pk(company):
                found = queryset.filter(pk=company).first()
            else:
                found = queryset.filter(slug=company).first()
            if found is None:
                raise Company.DoesNotExist(f"Unknown company: {company}")
            return found
        except (Company.DoesNotExist, ValueError) as exc:
            raise CommandError(f"Unknown company: {company}") from exc


def _is_pk(value: str) -> bool:
    """True for integer PKs and UUID strings — everything else is a slug."""
    if value.isdigit():
        return True
    try:
        uuid.UUID(value)
    except ValueError:
        return False
    return True
