from django.contrib import admin
from django.http import HttpRequest

from apps.scraping.models import ScrapeArtifact, ScrapeError, ScrapeRun, SourceFetchState


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
    list_filter = ["status", "triggered_by", "parser_version"]
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
        "parser_version",
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


@admin.register(ScrapeArtifact)
class ScrapeArtifactAdmin(admin.ModelAdmin):  # type: ignore[type-arg]
    list_display = [
        "scrape_run",
        "company",
        "url",
        "byte_size",
        "truncated",
        "created_at",
    ]
    list_filter = ["truncated"]
    search_fields = ["company__name", "url"]
    readonly_fields = [
        "id",
        "scrape_run",
        "company",
        "url",
        "content_gzip",
        "content_type",
        "byte_size",
        "truncated",
        "created_at",
    ]
    ordering = ["-created_at"]

    def has_add_permission(self, request: HttpRequest) -> bool:  # pragma: no cover
        return False

    def has_change_permission(
        self, request: HttpRequest, obj: ScrapeArtifact | None = None
    ) -> bool:  # pragma: no cover
        return False

    def has_delete_permission(
        self, request: HttpRequest, obj: ScrapeArtifact | None = None
    ) -> bool:  # pragma: no cover
        return False

    # No need to override get_list_display; list_display already omits content_gzip.


@admin.register(SourceFetchState)
class SourceFetchStateAdmin(admin.ModelAdmin):  # type: ignore[type-arg]
    """Read-only admin for conditional GET state."""

    list_display = [
        "url_hash",
        "url",
        "etag",
        "last_modified",
        "body_hash",
        "last_fetched_at",
        "hit_count",
        "miss_count",
    ]
    search_fields = ["url"]
    readonly_fields = [
        "id",
        "url_hash",
        "url",
        "etag",
        "last_modified",
        "body_hash",
        "last_fetched_at",
        "hit_count",
        "miss_count",
        "created_at",
        "updated_at",
    ]

    def has_add_permission(self, request: HttpRequest) -> bool:
        return False

    def has_change_permission(
        self, request: HttpRequest, obj: SourceFetchState | None = None
    ) -> bool:
        return False

    def has_delete_permission(
        self, request: HttpRequest, obj: SourceFetchState | None = None
    ) -> bool:
        return False
