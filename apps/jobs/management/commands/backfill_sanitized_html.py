import argparse
import logging
from typing import Any

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.jobs.models import Job
from apps.jobs.services import _sanitize_html

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Backfill description_html_sanitized from description_html"

    def add_arguments(self, parser: argparse.ArgumentParser) -> None:
        parser.add_argument(
            "--force",
            action="store_true",
            help="Re-sanitize every row with non-empty description_html",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Report counts without writing",
        )
        parser.add_argument(
            "--batch-size",
            type=int,
            default=500,
            help="Batch size for updates",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        force = options["force"]
        dry_run = options["dry_run"]
        batch_size = options["batch_size"]

        base_qs = Job.objects.filter(description_html__gt="")
        qs = base_qs.filter(description_html_sanitized="") if not force else base_qs

        total = qs.count()
        self.stdout.write(f"Scanned: {total} rows to process")
        if dry_run:
            self.stdout.write("Dry run: no changes made")
            return

        updated = 0
        failed = 0
        unchanged = 0
        last_pk = None
        max_iterations = -(-total // batch_size) + 2

        for _iteration in range(max_iterations):
            page_qs = qs.order_by("pk")
            if last_pk is not None:
                page_qs = page_qs.filter(pk__gt=last_pk)
            batch = list(page_qs[:batch_size])
            if not batch:
                break
            last_pk = batch[-1].pk

            to_update = []
            with transaction.atomic():
                for job in batch:
                    try:
                        sanitized = _sanitize_html(job.description_html, str(job.pk))
                    except Exception as e:
                        logger.error("Failed to sanitize job %s: %s", job.pk, e)
                        failed += 1
                        continue
                    if job.description_html_sanitized == sanitized:
                        unchanged += 1
                        continue
                    job.description_html_sanitized = sanitized
                    to_update.append(job)
                if to_update:
                    Job.objects.bulk_update(
                        to_update, ["description_html_sanitized"], batch_size=batch_size
                    )
                    updated += len(to_update)
        else:
            raise CommandError(
                f"Backfill did not terminate after {max_iterations} iterations "
                f"({total} rows, batch size {batch_size})"
            )

        self.stdout.write(f"Updated: {updated}")
        self.stdout.write("Skipped: 0")
        self.stdout.write(f"Unchanged: {unchanged}")
        self.stdout.write(f"Failed: {failed}")
