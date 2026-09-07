"""Jobs domain: Job + SavedJob + JobReport + JobStatusEvent."""

from typing import ClassVar

from django.conf import settings
from django.contrib.postgres.indexes import GinIndex, OpClass
from django.db import models
from django.db.models import F, Q
from django.utils import timezone

from core.models import SoftDeleteModel, TimeStampedModel, UUIDModel

from .enums import (
    MAX_MISSING_COUNT,
    ExperienceLevel,
    JobStatus,
    JobType,
    ReportReason,
    ReportStatus,
    WorkMode,
)
from .querysets import AllJobsManager, JobManager


class Job(UUIDModel, TimeStampedModel, SoftDeleteModel):
    """A single job posting. Never hard-deleted; closed jobs stay visible forever."""

    # --- Dedupe identity ------------------------------------------------
    company = models.ForeignKey("companies.Company", on_delete=models.CASCADE, related_name="jobs")
    source_job_id = models.CharField(max_length=255, blank=True, db_index=True)
    source_url = models.URLField(max_length=1000)
    normalized_source_url = models.CharField(max_length=1000, db_index=True)
    apply_url = models.URLField(max_length=1000, blank=True)
    content_hash = models.CharField(max_length=64, db_index=True)
    parser_version = models.CharField(max_length=64, blank=True, db_index=True)

    # --- Content ---------------------------------------------------------
    title = models.CharField(max_length=500, db_index=True)
    title_normalized = models.CharField(max_length=500, db_index=True)
    slug = models.SlugField(max_length=320, unique=True, db_index=True, blank=True, null=True)
    description = models.TextField(blank=True)
    description_html = models.TextField(blank=True)
    description_html_sanitized = models.TextField(blank=True)
    location_raw = models.CharField(max_length=500, blank=True)
    city = models.CharField(max_length=120, blank=True, db_index=True)
    state = models.CharField(max_length=120, blank=True)
    country = models.CharField(max_length=120, blank=True)
    work_mode = models.CharField(
        max_length=16, choices=WorkMode.choices, default=WorkMode.UNKNOWN, db_index=True
    )
    job_type = models.CharField(
        max_length=20, choices=JobType.choices, default=JobType.UNKNOWN, db_index=True
    )
    experience_level = models.CharField(
        max_length=16,
        choices=ExperienceLevel.choices,
        default=ExperienceLevel.UNKNOWN,
        db_index=True,
    )
    min_experience_years = models.DecimalField(
        max_digits=4, decimal_places=1, null=True, blank=True
    )
    max_experience_years = models.DecimalField(
        max_digits=4, decimal_places=1, null=True, blank=True
    )
    salary_min = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    salary_max = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    salary_currency = models.CharField(max_length=8, blank=True)
    salary_period = models.CharField(max_length=16, blank=True)
    department = models.CharField(max_length=200, blank=True)
    skills = models.JSONField(default=list)
    education_required = models.CharField(max_length=255, blank=True)
    posted_at = models.DateTimeField(null=True, blank=True, db_index=True)
    deadline_at = models.DateTimeField(null=True, blank=True)

    # --- Lifecycle -------------------------------------------------------
    status = models.CharField(
        max_length=20, choices=JobStatus.choices, default=JobStatus.DRAFT, db_index=True
    )
    missing_count = models.PositiveSmallIntegerField(default=0)
    first_seen_at = models.DateTimeField(default=timezone.now, db_index=True)
    last_seen_at = models.DateTimeField(default=timezone.now, db_index=True)
    closed_at = models.DateTimeField(null=True, blank=True)
    reopened_count = models.PositiveSmallIntegerField(default=0)

    # --- Publishing / review ---------------------------------------------
    is_published = models.BooleanField(default=False, db_index=True)
    published_at = models.DateTimeField(null=True, blank=True)
    needs_review = models.BooleanField(default=False, db_index=True)
    review_reason = models.CharField(max_length=255, blank=True)
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="jobs_reviewed",
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)

    # --- Human-edit protection -------------------------------------------
    manually_edited_fields = models.JSONField(default=list)
    is_manual_status = models.BooleanField(default=False)

    # --- Quality ---------------------------------------------------------
    duplicate_of = models.ForeignKey(
        "self", null=True, blank=True, on_delete=models.SET_NULL, related_name="duplicates"
    )
    extraction_confidence = models.PositiveSmallIntegerField(default=0)
    trust_label = models.CharField(max_length=40, blank=True)
    report_count = models.PositiveIntegerField(default=0)
    view_count = models.PositiveIntegerField(default=0)
    save_count = models.PositiveIntegerField(default=0)

    # --- Search ----------------------------------------------------------

    raw_payload = models.JSONField(default=dict)

    objects: ClassVar[JobManager] = JobManager()
    all_objects: ClassVar[AllJobsManager] = AllJobsManager()

    class Meta:
        ordering = ["-posted_at", "-first_seen_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["company", "source_job_id"],
                condition=Q(is_deleted=False) & ~Q(source_job_id=""),
                name="uniq_company_source_job_id",
            ),
            models.UniqueConstraint(
                fields=["company", "title_normalized", "normalized_source_url"],
                condition=Q(is_deleted=False),
                name="uniq_company_title_sourceurl",
            ),
            models.CheckConstraint(
                condition=Q(missing_count__lte=MAX_MISSING_COUNT), name="job_missing_count_max"
            ),
            models.CheckConstraint(
                condition=~Q(status="closed") | Q(closed_at__isnull=False),
                name="closed_job_requires_closed_at",
            ),
            models.CheckConstraint(
                condition=Q(salary_min__isnull=True)
                | Q(salary_max__isnull=True)
                | Q(salary_max__gte=F("salary_min")),
                name="job_salary_range_sane",
            ),
            models.CheckConstraint(
                condition=Q(extraction_confidence__lte=100), name="job_confidence_range"
            ),
        ]
        indexes = [
            GinIndex(OpClass("title", name="gin_trgm_ops"), name="job_title_trgm"),
            models.Index(fields=["status", "is_published", "-posted_at"], name="idx_job_feed"),
            models.Index(fields=["company", "status"], name="idx_job_company_status"),
            models.Index(fields=["needs_review", "-first_seen_at"], name="idx_job_review_queue"),
            models.Index(fields=["content_hash"], name="idx_job_content_hash"),
        ]

    def __str__(self) -> str:
        return f"{self.title} @ {self.company.name}"

    @property
    def is_live(self) -> bool:
        return self.status == JobStatus.OPEN and self.is_published and not self.is_deleted

    @property
    def is_stale(self) -> bool:
        return self.status in {JobStatus.POSSIBLY_CLOSED, JobStatus.LIKELY_CLOSED}

    @property
    def age_days(self) -> int:
        anchor = self.posted_at or self.first_seen_at
        return (timezone.now() - anchor).days


class SavedJob(UUIDModel, TimeStampedModel):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="saved_jobs"
    )
    job = models.ForeignKey(Job, on_delete=models.CASCADE, related_name="saves")
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(fields=["user", "job"], name="uniq_saved_job_per_user")
        ]
        indexes = [
            models.Index(fields=["user", "-created_at"], name="idx_savedjob_user_created"),
        ]

    def __str__(self) -> str:
        return f"{self.user} saved {self.job}"


class JobReport(UUIDModel, TimeStampedModel):
    job = models.ForeignKey(Job, on_delete=models.CASCADE, related_name="reports")
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="job_reports",
    )
    reason = models.CharField(max_length=20, choices=ReportReason.choices)
    detail = models.TextField(blank=True)
    status = models.CharField(
        max_length=16, choices=ReportStatus.choices, default=ReportStatus.OPEN, db_index=True
    )
    resolved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="reports_resolved",
    )
    resolved_at = models.DateTimeField(null=True, blank=True)
    resolution_note = models.CharField(max_length=500, blank=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["job", "user"],
                condition=Q(status="open"),
                name="uniq_open_report_per_user_job",
            )
        ]
        indexes = [
            models.Index(fields=["status", "-created_at"], name="idx_jobreport_status_created"),
        ]

    def __str__(self) -> str:
        return f"report:{self.job} [{self.reason}]"


class JobStatusEvent(UUIDModel, TimeStampedModel):
    """Append-only status timeline — one row per transition."""

    job = models.ForeignKey(Job, on_delete=models.CASCADE, related_name="status_events")
    from_status = models.CharField(max_length=20, blank=True)
    to_status = models.CharField(max_length=20)
    missing_count = models.PositiveSmallIntegerField(default=0)
    trigger = models.CharField(max_length=40)
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL
    )
    scrape_run_id = models.UUIDField(null=True, blank=True)
    note = models.CharField(max_length=500, blank=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["job", "-created_at"], name="idx_job_status_timeline")]

    def __str__(self) -> str:
        return f"{self.job}: {self.from_status or '-'} -> {self.to_status} ({self.trigger})"
