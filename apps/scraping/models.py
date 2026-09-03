from django.db import models

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
