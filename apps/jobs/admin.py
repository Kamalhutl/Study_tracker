"""Jobs admin — review queue, edit-through-services, status timeline."""

from typing import Any

from django.conf import settings
from django.contrib import admin, messages
from django.db.models import QuerySet
from django.forms import ModelForm
from django.http import HttpRequest, HttpResponse
from django.urls import reverse
from django.utils.html import format_html

from apps.companies.admin_site import ops_site

from . import services
from .enums import JobStatus, ReportStatus
from .models import Job, JobReport, JobStatusEvent, SavedJob

STATUS_COLORS: dict[str, str] = {
    JobStatus.OPEN: "#2e9b45",
    JobStatus.POSSIBLY_CLOSED: "#e8a33d",
    JobStatus.LIKELY_CLOSED: "#e0742f",
    JobStatus.CLOSED: "#999999",
    JobStatus.DRAFT: "#5a7bf5",
}

PUBLISHED_DOT = '<span style="display:inline-block;width:9px;height:9px;border-radius:50%;background:{color}"></span>'


class JobAdminForm(ModelForm):  # type: ignore[type-arg]
    class Meta:
        model = Job
        fields = (
            "title",
            "description",
            "description_html",
            "location_raw",
            "city",
            "state",
            "country",
            "work_mode",
            "job_type",
            "experience_level",
            "min_experience_years",
            "max_experience_years",
            "salary_min",
            "salary_max",
            "salary_currency",
            "salary_period",
            "department",
            "skills",
            "education_required",
            "posted_at",
            "deadline_at",
            "apply_url",
            "source_url",
        )

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.required = False


class JobStatusEventInline(admin.TabularInline):  # type: ignore[type-arg]
    model = JobStatusEvent
    extra = 0
    can_delete = False
    readonly_fields = (
        "from_status",
        "to_status",
        "missing_count",
        "trigger",
        "actor",
        "created_at",
    )

    def get_queryset(self, request: HttpRequest) -> QuerySet[Any]:
        return super().get_queryset(request).order_by("-created_at")

    def has_add_permission(self, request: HttpRequest, obj: Job | None = None) -> bool:
        return False

    def has_change_permission(self, request: HttpRequest, obj: Job | None = None) -> bool:
        return False

    def has_delete_permission(self, request: HttpRequest, obj: Job | None = None) -> bool:
        return False


class JobReportInline(admin.TabularInline):  # type: ignore[type-arg]
    model = JobReport
    extra = 0
    can_delete = False
    readonly_fields = ("user", "reason", "detail", "status", "created_at")

    def has_add_permission(self, request: HttpRequest, obj: Job | None = None) -> bool:
        return False

    def has_change_permission(self, request: HttpRequest, obj: Job | None = None) -> bool:
        return False

    def has_delete_permission(self, request: HttpRequest, obj: Job | None = None) -> bool:
        return False


class JobAdmin(admin.ModelAdmin):  # type: ignore[type-arg]
    change_list_template = "admin/jobs/job_change_list.html"
    form = JobAdminForm

    list_display = (
        "title",
        "company_link",
        "status_badge",
        "published_icon",
        "missing_count",
        "city",
        "job_type",
        "posted_at",
        "last_seen_at",
        "source_link",
        "apply_link",
    )
    list_filter = (
        "status",
        "is_published",
        "needs_review",
        "job_type",
        "work_mode",
        "experience_level",
        "company__career_source_type",
        "company",
    )
    search_fields = ("title", "description", "company__name", "city", "source_job_id")
    list_select_related = ("company",)
    date_hierarchy = "posted_at"
    ordering = ["-first_seen_at"]
    inlines = [JobStatusEventInline, JobReportInline]

    readonly_fields = (
        "id",
        "company",
        "content_hash",
        "title_normalized",
        "normalized_source_url",
        "first_seen_at",
        "last_seen_at",
        "reopened_count",
        "status",
        "missing_count",
        "closed_at",
        "is_published",
        "published_at",
        "needs_review",
        "review_reason",
        "reviewed_by",
        "reviewed_at",
        "manually_edited_fields",
        "raw_payload_pretty",
        "duplicate_of",
        "extraction_confidence",
        "trust_label",
        "report_count",
        "view_count",
        "save_count",
        "source_job_id",
        "created_at",
        "updated_at",
    )
    fieldsets = (
        (
            "Identity",
            {
                "fields": (
                    "company",
                    "source_job_id",
                    "source_url",
                    "normalized_source_url",
                    "apply_url",
                    "content_hash",
                )
            },
        ),
        (
            "Content",
            {
                "fields": (
                    "title",
                    "title_normalized",
                    "description",
                    "description_html",
                    "location_raw",
                    "city",
                    "state",
                    "country",
                )
            },
        ),
        (
            "Compensation",
            {"fields": ("salary_min", "salary_max", "salary_currency", "salary_period")},
        ),
        (
            "Classification",
            {
                "fields": (
                    "work_mode",
                    "job_type",
                    "experience_level",
                    "min_experience_years",
                    "max_experience_years",
                    "department",
                    "skills",
                    "education_required",
                )
            },
        ),
        (
            "Lifecycle",
            {
                "fields": (
                    "status",
                    "missing_count",
                    "first_seen_at",
                    "last_seen_at",
                    "closed_at",
                    "reopened_count",
                    "posted_at",
                    "deadline_at",
                )
            },
        ),
        (
            "Publishing",
            {
                "fields": (
                    "is_published",
                    "published_at",
                    "needs_review",
                    "review_reason",
                    "reviewed_by",
                    "reviewed_at",
                )
            },
        ),
        (
            "Quality",
            {
                "fields": (
                    "duplicate_of",
                    "extraction_confidence",
                    "trust_label",
                    "report_count",
                    "view_count",
                    "save_count",
                    "manually_edited_fields",
                )
            },
        ),
        (
            "Debug (collapsed)",
            {"classes": ("collapse",), "fields": ("raw_payload_pretty",)},
        ),
    )
    actions = (
        "publish_selected",
        "unpublish_selected",
        "close_selected",
        "reopen_selected",
        "approve_review_selected",
        "reject_review_selected",
    )

    def has_add_permission(self, request: HttpRequest) -> bool:
        return settings.DEBUG

    def save_model(self, request: HttpRequest, obj: Any, form: JobAdminForm, change: bool) -> None:
        if not change:
            super().save_model(request, obj, form, change)
            return
        changes = {
            name: form.cleaned_data[name] for name in form.changed_data if name in form.fields
        }
        services.edit_job_fields(job=obj, changes=changes, actor=request.user)

    def get_queryset(self, request: HttpRequest) -> QuerySet[Any]:
        return super().get_queryset(request).select_related("company")

    # -- display helpers --------------------------------------------------
    def company_link(self, obj: Job) -> str:
        url = reverse("admin:companies_company_change", args=[obj.company_id])
        return format_html('<a href="{0}">{1}</a>', url, obj.company.name)

    company_link.short_description = "company"  # type: ignore[attr-defined]

    def status_badge(self, obj: Job) -> str:
        color = STATUS_COLORS.get(obj.status, "#b0b0b0")
        extra = f" <small>(x{obj.missing_count})</small>" if obj.missing_count else ""
        return format_html(
            "<span style='color:{color}'>{status}</span>{extra}",
            color=color,
            status=obj.status,
            extra=extra,
        )

    status_badge.short_description = "status"  # type: ignore[attr-defined]

    def published_icon(self, obj: Job) -> str:
        color = "#2e9b45" if obj.is_published else "#d0d0d0"
        return format_html(PUBLISHED_DOT, color=color)

    published_icon.short_description = "pub"  # type: ignore[attr-defined]

    def source_link(self, obj: Job) -> str:
        if not obj.normalized_source_url:
            return "—"
        return format_html('<a href="{0}" target="_blank" rel="noopener">src</a>', obj.source_url)

    source_link.short_description = "source"  # type: ignore[attr-defined]

    def apply_link(self, obj: Job) -> str:
        if not obj.apply_url:
            return "—"
        return format_html('<a href="{0}" target="_blank" rel="noopener">apply</a>', obj.apply_url)

    apply_link.short_description = "apply"  # type: ignore[attr-defined]

    def raw_payload_pretty(self, obj: Job) -> str:
        import json

        return format_html(
            "<pre>{0}</pre>", json.dumps(obj.raw_payload, indent=2, default=str)[:4000]
        )

    raw_payload_pretty.short_description = "raw payload"  # type: ignore[attr-defined]

    def changelist_view(
        self, request: HttpRequest, extra_context: dict[str, Any] | None = None
    ) -> HttpResponse:
        context = {
            "review_count": Job.objects.filter(needs_review=True).count(),
        }
        if extra_context:
            context.update(extra_context)
        return super().changelist_view(request, extra_context=context)

    # -- actions ----------------------------------------------------------
    def publish_selected(self, request: HttpRequest, queryset: QuerySet[Any]) -> None:
        for job in queryset:
            services.publish_job(job=job, actor=request.user)
        self.message_user(request, f"Published {queryset.count()} job(s).", messages.SUCCESS)

    publish_selected.short_description = "Publish selected jobs"  # type: ignore[attr-defined]

    def unpublish_selected(self, request: HttpRequest, queryset: QuerySet[Any]) -> None:
        for job in queryset:
            services.unpublish_job(job=job, actor=request.user)
        self.message_user(request, f"Unpublished {queryset.count()} job(s).", messages.SUCCESS)

    unpublish_selected.short_description = "Unpublish selected jobs"  # type: ignore[attr-defined]

    def close_selected(self, request: HttpRequest, queryset: QuerySet[Any]) -> None:
        for job in queryset:
            services.mark_job_closed(job=job, actor=request.user, reason="bulk close")
        self.message_user(request, f"Closed {queryset.count()} job(s).", messages.SUCCESS)

    close_selected.short_description = "Mark selected jobs closed"  # type: ignore[attr-defined]

    def reopen_selected(self, request: HttpRequest, queryset: QuerySet[Any]) -> None:
        for job in queryset:
            services.reopen_job(job=job, actor=request.user, reason="bulk reopen")
        self.message_user(request, f"Reopened {queryset.count()} job(s).", messages.SUCCESS)

    reopen_selected.short_description = "Reopen selected jobs"  # type: ignore[attr-defined]

    def approve_review_selected(self, request: HttpRequest, queryset: QuerySet[Any]) -> None:
        for job in queryset:
            services.approve_job_review(job=job, actor=request.user)
        self.message_user(
            request, f"Approved review for {queryset.count()} job(s).", messages.SUCCESS
        )

    approve_review_selected.short_description = "Approve review (publish)"  # type: ignore[attr-defined]

    def reject_review_selected(self, request: HttpRequest, queryset: QuerySet[Any]) -> None:
        for job in queryset:
            services.reject_job_review(job=job, actor=request.user, reason="bulk rejection")
        self.message_user(
            request, f"Rejected review for {queryset.count()} job(s).", messages.SUCCESS
        )

    reject_review_selected.short_description = "Reject review (unpublished)"  # type: ignore[attr-defined]


class SavedJobAdmin(admin.ModelAdmin):  # type: ignore[type-arg]
    """Read-only view of user saves."""

    list_display = ("user", "job", "created_at")
    list_select_related = ("user", "job", "job__company")
    readonly_fields = [field.name for field in SavedJob._meta.fields]

    def has_add_permission(self, request: HttpRequest) -> bool:
        return False

    def has_change_permission(self, request: HttpRequest, obj: SavedJob | None = None) -> bool:
        return False

    def has_delete_permission(self, request: HttpRequest, obj: SavedJob | None = None) -> bool:
        return False


class JobReportAdmin(admin.ModelAdmin):  # type: ignore[type-arg]
    list_display = ("job", "user", "reason", "detail", "status", "created_at")
    list_filter = ("status", "reason")
    list_select_related = ("job", "user", "job__company")
    search_fields = ("job__title", "detail")
    readonly_fields = (
        "job",
        "user",
        "reason",
        "detail",
        "status",
        "resolved_by",
        "resolved_at",
        "resolution_note",
        "created_at",
    )
    actions = ("accept_selected", "reject_selected")

    def get_queryset(self, request: HttpRequest) -> QuerySet[Any]:
        qs = super().get_queryset(request)
        if not request.GET.get("status__exact"):
            qs = qs.filter(status=ReportStatus.OPEN)
        return qs

    def has_add_permission(self, request: HttpRequest) -> bool:
        return False

    def accept_selected(self, request: HttpRequest, queryset: QuerySet[Any]) -> None:
        for report in queryset:
            services.resolve_report(
                report=report, actor=request.user, accept=True, note="bulk accept"
            )
        self.message_user(request, f"Accepted {queryset.count()} report(s).", messages.SUCCESS)

    accept_selected.short_description = "Accept reports"  # type: ignore[attr-defined]

    def reject_selected(self, request: HttpRequest, queryset: QuerySet[Any]) -> None:
        for report in queryset:
            services.resolve_report(
                report=report, actor=request.user, accept=False, note="bulk reject"
            )
        self.message_user(request, f"Rejected {queryset.count()} report(s).", messages.SUCCESS)

    reject_selected.short_description = "Reject reports"  # type: ignore[attr-defined]


class JobStatusEventAdmin(admin.ModelAdmin):  # type: ignore[type-arg]
    """Fully read-only status timeline."""

    list_display = (
        "job",
        "from_status",
        "to_status",
        "trigger",
        "missing_count",
        "actor",
        "created_at",
    )
    list_filter = ("trigger", "to_status")
    list_select_related = ("job", "actor", "job__company")
    readonly_fields = [field.name for field in JobStatusEvent._meta.fields]

    def has_add_permission(self, request: HttpRequest) -> bool:
        return False

    def has_change_permission(
        self, request: HttpRequest, obj: JobStatusEvent | None = None
    ) -> bool:
        return False

    def has_delete_permission(
        self, request: HttpRequest, obj: JobStatusEvent | None = None
    ) -> bool:
        return False


# OpsAdminSite.register returns None — never usable as a decorator.
ops_site.register(Job, JobAdmin)
ops_site.register(SavedJob, SavedJobAdmin)
ops_site.register(JobReport, JobReportAdmin)
ops_site.register(JobStatusEvent, JobStatusEventAdmin)
