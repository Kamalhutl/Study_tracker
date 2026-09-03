"""Companies domain: Company + source history + detection candidates + runs."""

from datetime import timedelta
from typing import Any, ClassVar

from django.conf import settings
from django.contrib.postgres.indexes import GinIndex, OpClass
from django.db import models
from django.db.models import Q
from django.utils import timezone

from core.models import SoftDeleteModel, TimeStampedModel, UUIDModel

from .enums import (
    DEFAULT_SCRAPE_INTERVAL_MINUTES,
    MAX_BACKOFF_MINUTES,
    MIN_SCRAPE_INTERVAL_MINUTES,
    CandidateOrigin,
    CandidateStatus,
    CareerSourceType,
    DetectionStatus,
    ScrapeHealth,
    SourceInputType,
)
from .querysets import AllCompaniesManager, CompanyManager


class Company(UUIDModel, TimeStampedModel, SoftDeleteModel):
    """A company we track. Never hard-deleted; archiving is a soft delete."""

    # --- Identity -------------------------------------------------------
    name = models.CharField(max_length=255, db_index=True)
    slug = models.SlugField(max_length=280, unique=True)
    domain = models.CharField(max_length=255, db_index=True)
    logo_url = models.URLField(max_length=500, blank=True)
    description = models.TextField(blank=True)
    hq_location = models.CharField(max_length=255, blank=True)
    industry = models.CharField(max_length=120, blank=True)
    size_bucket = models.CharField(max_length=40, blank=True)
    linkedin_url = models.URLField(max_length=500, blank=True)

    # --- How it was added ----------------------------------------------
    input_type = models.CharField(max_length=32, choices=SourceInputType.choices)
    input_url = models.URLField(max_length=1000)
    added_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="companies_added",
    )

    # --- Resolved career source ----------------------------------------
    career_url = models.URLField(max_length=1000, blank=True, db_index=True)
    career_source_type = models.CharField(
        max_length=32, choices=CareerSourceType.choices, default=CareerSourceType.UNKNOWN
    )
    ats_identifier = models.CharField(max_length=255, blank=True)
    career_url_set_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="career_urls_set",
    )
    career_url_set_at = models.DateTimeField(null=True, blank=True)

    # --- Verification / detection ---------------------------------------
    detection_status = models.CharField(
        max_length=32,
        choices=DetectionStatus.choices,
        default=DetectionStatus.PENDING,
        db_index=True,
    )
    is_verified = models.BooleanField(default=False, db_index=True)
    verified_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="companies_verified",
    )
    verified_at = models.DateTimeField(null=True, blank=True)
    detection_attempts = models.PositiveSmallIntegerField(default=0)
    last_detection_at = models.DateTimeField(null=True, blank=True)

    # --- Scheduling -----------------------------------------------------
    is_active = models.BooleanField(default=True, db_index=True)
    scrape_interval_minutes = models.PositiveIntegerField(default=DEFAULT_SCRAPE_INTERVAL_MINUTES)
    next_scrape_at = models.DateTimeField(null=True, blank=True, db_index=True)
    last_scraped_at = models.DateTimeField(null=True, blank=True)
    last_successful_scrape_at = models.DateTimeField(null=True, blank=True)

    # --- Health bookkeeping ---------------------------------------------
    scrape_health = models.CharField(
        max_length=16, choices=ScrapeHealth.choices, default=ScrapeHealth.UNKNOWN, db_index=True
    )
    consecutive_failures = models.PositiveSmallIntegerField(default=0)
    total_scrapes = models.PositiveIntegerField(default=0)
    total_failures = models.PositiveIntegerField(default=0)
    last_failure_reason = models.TextField(blank=True)
    last_jobs_seen = models.PositiveIntegerField(default=0)
    notes = models.TextField(blank=True)

    # --- Managers -------------------------------------------------------
    objects: ClassVar[CompanyManager] = CompanyManager()
    all_objects: ClassVar[AllCompaniesManager] = AllCompaniesManager()

    class Meta:
        ordering = ["name"]
        verbose_name_plural = "companies"
        constraints = [
            models.UniqueConstraint(
                fields=["domain"],
                condition=Q(is_deleted=False),
                name="uniq_active_company_domain",
            ),
            models.UniqueConstraint(
                fields=["career_url"],
                condition=Q(is_deleted=False) & ~Q(career_url=""),
                name="uniq_active_career_url",
            ),
            models.CheckConstraint(
                condition=Q(scrape_interval_minutes__gte=MIN_SCRAPE_INTERVAL_MINUTES),
                name="company_min_scrape_interval",
            ),
            models.CheckConstraint(
                condition=Q(is_verified=False) | ~Q(career_url=""),
                name="verified_company_requires_career_url",
            ),
            models.CheckConstraint(
                condition=Q(consecutive_failures__lte=50),
                name="company_failure_counter_sane",
            ),
        ]
        indexes = [
            GinIndex(OpClass("name", name="gin_trgm_ops"), name="company_name_trgm"),
            models.Index(
                fields=["is_verified", "is_active", "next_scrape_at"],
                name="idx_company_scheduler",
            ),
            models.Index(
                fields=["detection_status", "-created_at"],
                name="idx_company_detection_queue",
            ),
            models.Index(
                fields=["scrape_health", "-consecutive_failures"],
                name="idx_company_health",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.name} ({self.domain})"

    # --- Read-only helpers ----------------------------------------------
    @property
    def is_scrapable(self) -> bool:
        return (
            self.is_verified
            and self.is_active
            and not self.is_deleted
            and bool(self.career_url)
            and self.scrape_health != ScrapeHealth.PAUSED
        )

    @property
    def is_ats(self) -> bool:
        return self.career_source_type in {
            CareerSourceType.GREENHOUSE,
            CareerSourceType.LEVER,
            CareerSourceType.ASHBY,
            CareerSourceType.SMARTRECRUITERS,
        }

    @property
    def needs_attention(self) -> bool:
        return self.scrape_health in {
            ScrapeHealth.FAILING,
            ScrapeHealth.PAUSED,
        } or self.detection_status in {
            DetectionStatus.NEEDS_REVIEW,
            DetectionStatus.FAILED,
            DetectionStatus.NOT_FOUND,
        }

    def is_due(self, now: Any = None) -> bool:
        target = now or timezone.now()
        return self.is_scrapable and (self.next_scrape_at is None or self.next_scrape_at <= target)

    def compute_next_scrape_at(self, now: Any = None, *, backoff_factor: int = 1) -> Any:
        """Deterministic per-company jitter: 1000 companies spread across the window."""
        base = int(self.scrape_interval_minutes) * int(backoff_factor)
        jitter = int(self.id.int) % max(1, min(base, 60))
        return (
            (now or timezone.now())
            + timedelta(minutes=min(base, MAX_BACKOFF_MINUTES))
            + timedelta(minutes=jitter)
        )


class CompanySource(UUIDModel, TimeStampedModel):
    """Append-only history of every career source a company has had."""

    company = models.ForeignKey(Company, on_delete=models.CASCADE, related_name="sources")
    url = models.URLField(max_length=1000)
    normalized_url = models.CharField(max_length=1000, db_index=True)
    source_type = models.CharField(max_length=32, choices=CareerSourceType.choices)
    ats_identifier = models.CharField(max_length=255, blank=True)
    is_current = models.BooleanField(default=True, db_index=True)
    set_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL
    )
    reason = models.CharField(max_length=255, blank=True)
    retired_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["company"],
                condition=Q(is_current=True),
                name="uniq_current_source_per_company",
            ),
            models.UniqueConstraint(
                fields=["company", "normalized_url"], name="uniq_company_source_url"
            ),
        ]

    def __str__(self) -> str:
        return f"{self.company.name} -> {self.normalized_url}"


class CareerCandidateUrl(UUIDModel, TimeStampedModel):
    """A possible career page found by detection; humans approve exactly one per company."""

    company = models.ForeignKey(Company, on_delete=models.CASCADE, related_name="candidates")
    detection_run = models.ForeignKey(
        "companies.DetectionRun",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="candidates",
    )
    url = models.URLField(max_length=1000)
    normalized_url = models.CharField(max_length=1000, db_index=True)
    origin = models.CharField(max_length=32, choices=CandidateOrigin.choices)
    discovered_via = models.CharField(max_length=255, blank=True)
    guessed_type = models.CharField(
        max_length=32, choices=CareerSourceType.choices, default=CareerSourceType.UNKNOWN
    )
    ats_identifier = models.CharField(max_length=255, blank=True)
    score = models.IntegerField(default=0, db_index=True)
    score_reasons = models.JSONField(default=list)
    page_title = models.CharField(max_length=500, blank=True)
    http_status = models.PositiveSmallIntegerField(null=True, blank=True)
    sample_job_titles = models.JSONField(default=list)
    status = models.CharField(
        max_length=16,
        choices=CandidateStatus.choices,
        default=CandidateStatus.PENDING,
        db_index=True,
    )
    decided_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL
    )
    decided_at = models.DateTimeField(null=True, blank=True)
    reject_reason = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ["-score", "-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["company", "normalized_url"], name="uniq_candidate_per_company"
            ),
            models.UniqueConstraint(
                fields=["company"],
                condition=Q(status="approved"),
                name="uniq_approved_candidate_per_company",
            ),
            models.CheckConstraint(
                condition=Q(score__gte=0) & Q(score__lte=100), name="candidate_score_range"
            ),
        ]

    def __str__(self) -> str:
        return f"{self.company.name}: {self.url} ({self.status})"


class DetectionRun(UUIDModel, TimeStampedModel):
    """One execution of career-URL detection for one company (written by PROMPT 3)."""

    company = models.ForeignKey(Company, on_delete=models.CASCADE, related_name="detection_runs")
    triggered_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL
    )
    status = models.CharField(
        max_length=32,
        choices=DetectionStatus.choices,
        default=DetectionStatus.RUNNING,
        db_index=True,
    )
    started_at = models.DateTimeField(default=timezone.now)
    finished_at = models.DateTimeField(null=True, blank=True)
    duration_ms = models.PositiveIntegerField(null=True, blank=True)
    urls_checked = models.PositiveIntegerField(default=0)
    checks_used = models.PositiveIntegerField(default=0)
    candidates_found = models.PositiveIntegerField(default=0)
    strategies_used = models.JSONField(default=list)
    ats_short_circuit = models.BooleanField(default=False)
    notes = models.TextField(blank=True)
    error_message = models.TextField(blank=True)
    log = models.JSONField(default=list)

    class Meta:
        ordering = ["-started_at"]
        indexes = [models.Index(fields=["company", "-started_at"], name="idx_detection_company")]

    def __str__(self) -> str:
        return f"detection:{self.company.name} [{self.status}]"
