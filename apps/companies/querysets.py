"""Company queryset helpers — the scheduler/detector/dashboard all read through these."""

from datetime import datetime
from typing import Any, cast

from django.db.models import Count, F, Q, QuerySet

from apps.jobs.enums import JobStatus
from core.models import AllObjectsManager, SoftDeleteManager, SoftDeleteQuerySet


class CompanyQuerySet(SoftDeleteQuerySet):
    def scrapable(self) -> "CompanyQuerySet":
        """Verified + active + alive + has a career URL + not paused."""
        from .enums import ScrapeHealth

        return (
            self.filter(
                is_verified=True,
                is_active=True,
                is_deleted=False,
            )
            .exclude(career_url="")
            .exclude(scrape_health=ScrapeHealth.PAUSED)
        )

    def due(self, now: datetime | None = None) -> "CompanyQuerySet":
        """Scrapable companies whose next_scrape_at has passed (or was never set)."""
        from django.utils import timezone

        target = now or timezone.now()
        return (
            self.scrapable()
            .filter(Q(next_scrape_at__isnull=True) | Q(next_scrape_at__lte=target))
            .order_by(F("next_scrape_at").asc(nulls_first=True))
        )

    def needs_attention(self) -> "CompanyQuerySet":
        from .enums import DetectionStatus, ScrapeHealth

        return self.filter(
            Q(scrape_health__in=[ScrapeHealth.FAILING, ScrapeHealth.PAUSED])
            | Q(
                detection_status__in=[
                    DetectionStatus.NEEDS_REVIEW,
                    DetectionStatus.FAILED,
                    DetectionStatus.NOT_FOUND,
                ]
            )
        )

    def pending_detection(self) -> "CompanyQuerySet":
        from .enums import DetectionStatus

        return self.filter(detection_status=DetectionStatus.PENDING)

    def with_job_counts(self) -> "CompanyQuerySet":
        from .models import Company

        annotated: QuerySet[Company] = self.annotate(
            open_jobs=Count("jobs", filter=Q(jobs__status="open")),
            total_jobs=Count("jobs"),
        )
        return cast("CompanyQuerySet", annotated)

    def public(self) -> "CompanyQuerySet":
        """Publicly visible companies: verified, active, not deleted."""
        return self.filter(is_verified=True, is_active=True, is_deleted=False).order_by("name")

    def with_public_job_counts(self) -> "CompanyQuerySet":
        """Annotate with open_jobs_count matching Job.objects.public() criteria."""
        annotated = self.annotate(
            open_jobs_count=Count(
                "jobs",
                filter=Q(
                    jobs__status=JobStatus.OPEN,
                    jobs__is_published=True,
                    jobs__is_deleted=False,
                ),
            )
        )
        return cast("CompanyQuerySet", annotated)

    def by_health(self) -> QuerySet[Any]:
        """Grouped health counts for the ops dashboard (single aggregate query)."""
        return cast(
            QuerySet[Any],
            self.values("scrape_health").annotate(total=Count("id")).order_by("scrape_health"),
        )


class CompanyManager(SoftDeleteManager.from_queryset(CompanyQuerySet)):  # type: ignore[misc]
    """Alive-only manager (matches SoftDeleteModel semantics).

    Respects ``Meta.ordering``; the parent manager's hardcoded ordering is dropped.
    """

    def get_queryset(self) -> CompanyQuerySet:
        return CompanyQuerySet(model=self.model, using=self._db).filter(is_deleted=False)


class AllCompaniesManager(AllObjectsManager.from_queryset(CompanyQuerySet)):  # type: ignore[misc]
    """Includes soft-deleted companies."""

    def get_queryset(self) -> CompanyQuerySet:
        return CompanyQuerySet(model=self.model, using=self._db)
