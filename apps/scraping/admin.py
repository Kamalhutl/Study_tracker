from django.contrib import admin
from django.http import HttpRequest

from apps.scraping.models import ScrapeError, ScrapeRun


@admin.register(ScrapeRun)
class ScrapeRunAdmin(admin.ModelAdmin):  # type: ignore[type-arg]
    list_display = [
        "company",
        "status",
        "triggered_by",
        "jobs_found",
        "jobs_added",
        "jobs_missing",
        "duration_ms",
        "started_at",
    ]
    list_filter = ["status", "triggered_by"]
    search_fields = ["company__name"]
    readonly_fields = [
        "id",
        "company",
        "status",
        "triggered_by",
        "started_at",
        "finished_at",
        "duration_ms",
        "jobs_found",
        "jobs_added",
        "jobs_updated",
        "jobs_unchanged",
        "jobs_missing",
        "jobs_reopened",
        "error",
        "notes",
        "created_at",
    ]

    def has_add_permission(self, request: HttpRequest) -> bool:  # pragma: no cover
        return False

    def has_change_permission(
        self, request: HttpRequest, obj: ScrapeRun | None = None
    ) -> bool:  # pragma: no cover
        return False

    def has_delete_permission(
        self, request: HttpRequest, obj: ScrapeRun | None = None
    ) -> bool:  # pragma: no cover
        return False

    def duration_display(self, obj: ScrapeRun) -> str:  # pragma: no cover
        return str(obj.duration_ms)


@admin.register(ScrapeError)
class ScrapeErrorAdmin(admin.ModelAdmin):  # type: ignore[type-arg]
    list_display = [
        "company",
        "scrape_run",
        "error_type",
        "url",
        "created_at",
    ]
    list_filter = ["error_type"]
    search_fields = ["company__name", "message"]
    readonly_fields = [
        "id",
        "scrape_run",
        "company",
        "url",
        "error_type",
        "message",
        "traceback",
        "created_at",
    ]

    def has_add_permission(self, request: HttpRequest) -> bool:  # pragma: no cover
        return False

    def has_change_permission(
        self, request: HttpRequest, obj: ScrapeError | None = None
    ) -> bool:  # pragma: no cover
        return False

    def has_delete_permission(
        self, request: HttpRequest, obj: ScrapeError | None = None
    ) -> bool:  # pragma: no cover
        return False
