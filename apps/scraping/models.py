from django.db import models

from apps.scraping.sanity import RunVerdict
from core.models import TimeStampedModel, UUIDModel


class ScrapeRun(UUIDModel, TimeStampedModel):
    company = models.ForeignKey(
        "companies.Company",
        on_delete=models.CASCADE,
        related_name="scrape_runs",
    )
    status = models.CharField(
        max_length=16,
        choices=[
            ("running", "Running"),
            ("success", "Success"),
            ("partial", "Partial"),
            ("failed", "Failed"),
        ],
        default="running",
    )
    triggered_by = models.CharField(
        max_length=16,
        choices=[
            ("schedule", "Schedule"),
            ("manual", "Manual"),
        ],
        default="schedule",
    )
    started_at = models.DateTimeField(auto_now_add=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    duration_ms = models.PositiveIntegerField(null=True, blank=True)
    jobs_found = models.PositiveIntegerField(default=0)
    jobs_added = models.PositiveIntegerField(default=0)
    jobs_updated = models.PositiveIntegerField(default=0)
    jobs_unchanged = models.PositiveIntegerField(default=0)
    jobs_missing = models.PositiveIntegerField(default=0)
    jobs_reopened = models.PositiveIntegerField(default=0)
    error = models.JSONField(default=dict)
    notes = models.TextField(blank=True)
    verdict = models.CharField(
        max_length=16,
        choices=RunVerdict.choices,
        default=RunVerdict.TRUSTED,
        db_index=True,
    )
    verdict_reason = models.CharField(max_length=200, blank=True)
    parser_version = models.CharField(max_length=64, blank=True, db_index=True)

    @property
    def succeeded(self) -> bool:
        return self.status == "success"


class ScrapeError(UUIDModel, TimeStampedModel):
    scrape_run = models.ForeignKey(
        ScrapeRun,
        on_delete=models.CASCADE,
        related_name="errors",
    )
    company = models.ForeignKey(
        "companies.Company",
        on_delete=models.CASCADE,
        related_name="scrape_errors",
    )
    url = models.URLField(max_length=1000, blank=True)
    error_type = models.CharField(max_length=80)
    message = models.TextField()
    traceback = models.TextField(blank=True)

    class Meta:
        ordering = ["-created_at"]


class ScrapeArtifact(UUIDModel, TimeStampedModel):
    """Stored HTML response body for quarantined/failed runs."""

    scrape_run = models.ForeignKey(
        ScrapeRun,
        on_delete=models.CASCADE,
        related_name="artifacts",
    )
    company = models.ForeignKey(
        "companies.Company",
        on_delete=models.CASCADE,
        related_name="scrape_artifacts",
    )
    url = models.URLField(max_length=1000, blank=True)
    content_gzip = models.BinaryField()
    content_type = models.CharField(max_length=100, blank=True)
    byte_size = models.PositiveIntegerField(help_text="Original uncompressed byte size")
    truncated = models.BooleanField(default=False)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["scrape_run", "-created_at"]),
            models.Index(fields=["company", "-created_at"]),
        ]


class SourceFetchState(UUIDModel, TimeStampedModel):
    """Conditional GET state keyed by URL hash."""

    url_hash = models.CharField(max_length=64, unique=True)  # sha256 of url
    url = models.TextField()
    etag = models.CharField(max_length=256, blank=True)
    last_modified = models.CharField(max_length=128, blank=True)  # raw header string
    body_hash = models.CharField(max_length=64, blank=True)
    last_fetched_at = models.DateTimeField()
    hit_count = models.PositiveIntegerField(default=0)
    miss_count = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["-last_fetched_at"]
        indexes = [
            models.Index(fields=["url_hash"]),
            models.Index(fields=["last_fetched_at"]),
        ]
