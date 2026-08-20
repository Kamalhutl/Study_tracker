"""Job queryset helpers."""

from datetime import timedelta
from typing import Any

from django.utils import timezone

from core.models import AllObjectsManager, SoftDeleteManager, SoftDeleteQuerySet

from .enums import JobStatus


class JobQuerySet(SoftDeleteQuerySet):
    def live(self) -> "JobQuerySet":
        return self.filter(status=JobStatus.OPEN, is_published=True, is_deleted=False)

    def published(self) -> "JobQuerySet":
        return self.filter(is_published=True)

    def open(self) -> "JobQuerySet":
        return self.filter(status=JobStatus.OPEN)

    def stale(self) -> "JobQuerySet":
        return self.filter(status__in=[JobStatus.POSSIBLY_CLOSED, JobStatus.LIKELY_CLOSED])

    def closed(self) -> "JobQuerySet":
        return self.filter(status=JobStatus.CLOSED)

    def needs_review(self) -> "JobQuerySet":
        return self.filter(needs_review=True)

    def for_company(self, company: Any) -> "JobQuerySet":
        return self.filter(company=company)

    def seen_in_run(self, scrape_run_id: Any) -> "JobQuerySet":
        """Jobs that produced a status event during a given scrape run."""
        return self.filter(status_events__scrape_run_id=scrape_run_id).distinct()

    def search(self, term: str) -> "JobQuerySet":
        return self.filter(search_vector=term)

    def with_company(self) -> "JobQuerySet":
        return self.select_related("company")

    def fresh(self, hours: int) -> "JobQuerySet":
        return self.filter(last_seen_at__gte=timezone.now() - timedelta(hours=hours))


class JobManager(SoftDeleteManager.from_queryset(JobQuerySet)):  # type: ignore[misc]
    """Alive-only manager (matches SoftDeleteModel semantics)."""

    def get_queryset(self) -> JobQuerySet:
        return JobQuerySet(model=self.model, using=self._db).filter(is_deleted=False)


class AllJobsManager(AllObjectsManager.from_queryset(JobQuerySet)):  # type: ignore[misc]
    """Includes soft-deleted jobs."""

    def get_queryset(self) -> JobQuerySet:
        return JobQuerySet(model=self.model, using=self._db)
