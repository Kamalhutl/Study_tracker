"""Enqueue or run detection for all PENDING companies.

Usage:
    ./manage.py detect_pending --limit 20 --enqueue
"""

from __future__ import annotations

from argparse import ArgumentParser
from typing import Any

from django.core.management.base import BaseCommand

from apps.companies.models import Company


class Command(BaseCommand):
    help = "Detect career URLs for every company still PENDING."

    def add_arguments(self, parser: ArgumentParser) -> None:
        parser.add_argument("--limit", type=int, default=50)
        parser.add_argument(
            "--enqueue",
            action="store_true",
            help="Enqueue one Celery task per company instead of running inline.",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        company_ids = list(
            Company.objects.pending_detection()
            .order_by("created_at")
            .values_list("pk", flat=True)[: options["limit"]]
        )
        if options["enqueue"]:
            from apps.career_detection.tasks import detect_career_url

            for company_id in company_ids:
                detect_career_url.delay(str(company_id))
            self.stdout.write(f"Enqueued detection for {len(company_ids)} companies")
            return

        from apps.career_detection.services import detect_pending_companies

        summaries = detect_pending_companies(limit=options["limit"])
        for summary in summaries:
            self.stdout.write(
                f"{summary['company_id']}: status={summary['status']} "
                f"best={summary.get('best_score') or 0}"
            )
        self.stdout.write(f"Processed {len(summaries)} companies")
