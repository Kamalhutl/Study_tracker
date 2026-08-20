"""Companies admin — the Phase-1 internal ops product.

Two sanctioned add paths (Case A / Case B), a candidate approval queue, source
history, and a health dashboard. Admins never write Company fields directly —
every mutation goes through ``companies.services``.
"""

from typing import Any, cast

from django.contrib import admin, messages
from django.core.exceptions import PermissionDenied
from django.db.models import QuerySet
from django.forms import CharField, Form, IntegerField, Textarea, URLField
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect, render
from django.urls import path, reverse
from django.utils.html import format_html

from . import services
from .admin_site import ops_site
from .enums import CandidateStatus, ScrapeHealth
from .models import CareerCandidateUrl, Company, CompanySource, DetectionRun
from .querysets import CompanyQuerySet

DOT = '<span style="display:inline-block;width:9px;height:9px;border-radius:50%;background:{color}"></span>'

HEALTH_COLORS: dict[str, str] = {
    ScrapeHealth.HEALTHY: "#2e9b45",
    ScrapeHealth.DEGRADED: "#e8a33d",
    ScrapeHealth.FAILING: "#d9534f",
    ScrapeHealth.PAUSED: "#999999",
    ScrapeHealth.UNKNOWN: "#b0b0b0",
}


def _badge(value: str, color: str, label: str | None = None) -> str:
    return format_html(
        "{dot} <span style='color:{color}'>{label}</span>",
        dot=DOT,
        color=color,
        label=label or value,
    )


class MainWebsiteForm(Form):
    """CASE A: admin pastes the home page; detection comes later (PROMPT 3)."""

    name = CharField(max_length=255)
    website_url = URLField(max_length=1000)
    logo_url = URLField(max_length=500, required=False)
    description = CharField(widget=Textarea, required=False)
    hq_location = CharField(max_length=255, required=False)
    industry = CharField(max_length=120, required=False)
    size_bucket = CharField(max_length=40, required=False)
    linkedin_url = URLField(max_length=500, required=False)

    def save(self, actor: Any) -> Company:
        data = self.cleaned_data
        return services.add_company_from_main_website(
            name=data["name"],
            website_url=data["website_url"],
            actor=actor,
            logo_url=data.get("logo_url", ""),
            description=data.get("description", ""),
            hq_location=data.get("hq_location", ""),
            industry=data.get("industry", ""),
            size_bucket=data.get("size_bucket", ""),
            linkedin_url=data.get("linkedin_url", ""),
        )


class DirectCareerForm(Form):
    """CASE B: admin already knows the career page — verified + scheduled now."""

    name = CharField(max_length=255)
    career_url = URLField(max_length=1000)
    website_url = URLField(max_length=1000, required=False)
    scrape_interval_minutes = IntegerField(required=False, min_value=30)
    logo_url = URLField(max_length=500, required=False)
    description = CharField(widget=Textarea, required=False)
    hq_location = CharField(max_length=255, required=False)
    industry = CharField(max_length=120, required=False)
    size_bucket = CharField(max_length=40, required=False)
    linkedin_url = URLField(max_length=500, required=False)

    def save(self, actor: Any) -> Company:
        data = self.cleaned_data
        return services.add_company_from_direct_career_url(
            name=data["name"],
            career_url=data["career_url"],
            actor=actor,
            website_url=data.get("website_url", ""),
            scrape_interval_minutes=data.get("scrape_interval_minutes"),
            logo_url=data.get("logo_url", ""),
            description=data.get("description", ""),
            hq_location=data.get("hq_location", ""),
            industry=data.get("industry", ""),
            size_bucket=data.get("size_bucket", ""),
            linkedin_url=data.get("linkedin_url", ""),
        )


class CandidateInline(admin.TabularInline):  # type: ignore[type-arg]
    model = CareerCandidateUrl
    extra = 0
    can_delete = False
    readonly_fields = (
        "url",
        "origin",
        "guessed_type",
        "score",
        "status",
        "decided_by",
        "decided_at",
    )

    def has_add_permission(self, request: HttpRequest, obj: Company | None = None) -> bool:
        return False

    def has_change_permission(self, request: HttpRequest, obj: Company | None = None) -> bool:
        return False

    def has_delete_permission(self, request: HttpRequest, obj: Company | None = None) -> bool:
        return False


class CompanySourceInline(admin.TabularInline):  # type: ignore[type-arg]
    model = CompanySource
    extra = 0
    can_delete = False
    readonly_fields = (
        "url",
        "source_type",
        "ats_identifier",
        "is_current",
        "set_by",
        "reason",
        "retired_at",
    )

    def has_add_permission(self, request: HttpRequest, obj: Company | None = None) -> bool:
        return False

    def has_change_permission(self, request: HttpRequest, obj: Company | None = None) -> bool:
        return False

    def has_delete_permission(self, request: HttpRequest, obj: Company | None = None) -> bool:
        return False


class CompanyAdmin(admin.ModelAdmin):  # type: ignore[type-arg]
    list_display = (
        "name",
        "domain_link",
        "source_badge",
        "verified_badge",
        "health_badge",
        "open_jobs",
        "last_scraped_at",
        "next_scrape_at",
    )
    list_filter = (
        "detection_status",
        "career_source_type",
        "scrape_health",
        "is_verified",
        "is_active",
        "industry",
    )
    search_fields = ("name", "domain", "career_url", "ats_identifier")
    ordering = ["-created_at"]
    list_select_related = ("added_by",)
    readonly_fields = (
        "id",
        "slug",
        "input_url",
        "input_type",
        "added_by",
        "domain",
        "career_url",
        "career_source_type",
        "ats_identifier",
        "career_url_set_by",
        "career_url_set_at",
        "detection_status",
        "is_verified",
        "verified_by",
        "verified_at",
        "detection_attempts",
        "last_detection_at",
        "is_active",
        "scrape_interval_minutes",
        "next_scrape_at",
        "last_scraped_at",
        "last_successful_scrape_at",
        "scrape_health",
        "consecutive_failures",
        "total_scrapes",
        "total_failures",
        "last_failure_reason",
        "last_jobs_seen",
        "created_at",
        "updated_at",
    )
    inlines = [CandidateInline, CompanySourceInline]
    fieldsets = (
        (
            "Identity",
            {
                "fields": (
                    "name",
                    "slug",
                    "domain",
                    "logo_url",
                    "description",
                    "hq_location",
                    "industry",
                    "size_bucket",
                    "linkedin_url",
                )
            },
        ),
        (
            "Input (how it was added)",
            {"fields": ("input_type", "input_url", "added_by", "created_at")},
        ),
        (
            "Career source",
            {
                "fields": (
                    "career_url",
                    "career_source_type",
                    "ats_identifier",
                    "career_url_set_by",
                    "career_url_set_at",
                )
            },
        ),
        (
            "Verification",
            {
                "fields": (
                    "detection_status",
                    "is_verified",
                    "verified_by",
                    "verified_at",
                    "detection_attempts",
                    "last_detection_at",
                )
            },
        ),
        (
            "Schedule",
            {
                "fields": (
                    "is_active",
                    "scrape_interval_minutes",
                    "next_scrape_at",
                    "last_scraped_at",
                    "last_successful_scrape_at",
                )
            },
        ),
        (
            "Health",
            {
                "fields": (
                    "scrape_health",
                    "consecutive_failures",
                    "total_scrapes",
                    "total_failures",
                    "last_failure_reason",
                    "last_jobs_seen",
                )
            },
        ),
        ("Internal notes", {"fields": ("notes", "updated_at")}),
    )
    actions = (
        "verify_selected",
        "pause_selected",
        "resume_selected",
        "archive_selected",
        "request_redetection_selected",
        "reset_failures_selected",
    )

    def get_queryset(self, request: HttpRequest) -> QuerySet[Any]:
        qs = cast(CompanyQuerySet, super().get_queryset(request))
        return qs.with_job_counts()

    def get_urls(self) -> list[Any]:
        urls = super().get_urls()
        custom = [
            path(
                "add-main-website/",
                self.admin_site.admin_view(self.add_main_website_view),
                name="companies_company_add_main_website",
            ),
            path(
                "add-career-url/",
                self.admin_site.admin_view(self.add_career_url_view),
                name="companies_company_add_career_url",
            ),
        ]
        return custom + urls

    def has_add_permission(self, request: HttpRequest) -> bool:
        return False

    # -- custom add views ------------------------------------------------
    def _render_add_view(
        self,
        request: HttpRequest,
        form_class: type[MainWebsiteForm] | type[DirectCareerForm],
        template: str,
        title: str,
        blurb: str,
    ) -> HttpResponse:
        if not (request.user.is_staff and request.user.has_perm("companies.add_company")):
            raise PermissionDenied
        form = form_class(request.POST) if request.method == "POST" else form_class()
        if request.method == "POST" and form.is_valid():
            company = form.save(actor=request.user)
            self.message_user(request, f"Company {company.name} created.", messages.SUCCESS)
            return redirect(reverse("admin:companies_company_change", args=[company.pk]))
        context = {
            **self.admin_site.each_context(request),
            "title": title,
            "blurb": blurb,
            "form": form,
            "add": True,
            "change": False,
            "opts": self.model._meta,
        }
        return render(request, template, context)

    def add_main_website_view(self, request: HttpRequest) -> HttpResponse:
        return self._render_add_view(
            request,
            MainWebsiteForm,
            "companies/company_add.html",
            "Add company — home page (detection later)",
            "We will run career-URL detection after you save; until a URL is verified the company is not scrapable.",
        )

    def add_career_url_view(self, request: HttpRequest) -> HttpResponse:
        return self._render_add_view(
            request,
            DirectCareerForm,
            "companies/company_add.html",
            "Add company — direct career URL",
            "The company is verified immediately and scheduled for scraping (source type is auto-sniffed).",
        )

    def save_model(self, request: HttpRequest, obj: Any, form: Any, change: bool) -> None:
        if change:
            changes = {
                name: form.cleaned_data.get(name)
                for name in form.changed_data
                if name in form.fields
            }
            services.update_company_details(company=obj, actor=request.user, **changes)
            return
        super().save_model(request, obj, form, change)

    # -- display helpers --------------------------------------------------
    def domain_link(self, obj: Company) -> str:
        return format_html(
            '<a href="https://{0}" target="_blank" rel="noopener">{0}</a>', obj.domain
        )

    domain_link.short_description = "domain"  # type: ignore[attr-defined]

    def source_badge(self, obj: Company) -> str:
        color = "#7a5af5" if obj.is_ats else "#5a7bf5"
        return _badge(obj.career_source_type, color)

    source_badge.short_description = "source"  # type: ignore[attr-defined]

    def verified_badge(self, obj: Company) -> str:
        return _badge("verified", "#2e9b45") if obj.is_verified else _badge("unverified", "#b0b0b0")

    verified_badge.short_description = "verified"  # type: ignore[attr-defined]

    def health_badge(self, obj: Company) -> str:
        return _badge(obj.scrape_health, HEALTH_COLORS.get(obj.scrape_health, "#b0b0b0"))

    health_badge.short_description = "health"  # type: ignore[attr-defined]

    def open_jobs(self, obj: Company) -> int:
        return int(cast(Any, obj).open_jobs)

    open_jobs.short_description = "open jobs"  # type: ignore[attr-defined]

    # -- actions ----------------------------------------------------------
    def _row_message(self, request: HttpRequest, ok: int, skipped: int, verb: str) -> None:
        if ok:
            self.message_user(request, f"{verb}: {ok} company(ies) updated.", messages.SUCCESS)
        if skipped:
            self.message_user(
                request, f"{verb}: {skipped} skipped (no career URL).", messages.WARNING
            )

    def verify_selected(self, request: HttpRequest, queryset: QuerySet[Any]) -> None:
        ok = skipped = 0
        for company in queryset:
            if not company.career_url:
                skipped += 1
                continue
            services.set_manual_career_url(
                company=company, career_url=company.career_url, actor=request.user
            )
            ok += 1
        self._row_message(request, ok, skipped, "Verify")

    verify_selected.short_description = "Verify selected companies (career URL present)"  # type: ignore[attr-defined]

    def pause_selected(self, request: HttpRequest, queryset: QuerySet[Any]) -> None:
        for company in queryset:
            services.pause_company(company=company, actor=request.user)
        self.message_user(request, f"Paused {queryset.count()} company(ies).", messages.SUCCESS)

    pause_selected.short_description = "Pause scraping"  # type: ignore[attr-defined]

    def resume_selected(self, request: HttpRequest, queryset: QuerySet[Any]) -> None:
        for company in queryset:
            services.resume_company(company=company, actor=request.user)
        self.message_user(request, f"Resumed {queryset.count()} company(ies).", messages.SUCCESS)

    resume_selected.short_description = "Resume scraping"  # type: ignore[attr-defined]

    def archive_selected(self, request: HttpRequest, queryset: QuerySet[Any]) -> None:
        for company in queryset:
            services.archive_company(company=company, actor=request.user)
        self.message_user(request, f"Archived {queryset.count()} company(ies).", messages.SUCCESS)

    archive_selected.short_description = "Archive (soft delete) companies"  # type: ignore[attr-defined]

    def request_redetection_selected(self, request: HttpRequest, queryset: QuerySet[Any]) -> None:
        for company in queryset:
            services.request_redetection(company=company, actor=request.user)
        self.message_user(
            request, f"Queued redetection for {queryset.count()} company(ies).", messages.SUCCESS
        )

    request_redetection_selected.short_description = "Request career-URL redetection"  # type: ignore[attr-defined]
    # PROMPT 3: "Run detection now" action goes here
    # PROMPT 5: "Scrape now" action goes here

    def reset_failures_selected(self, request: HttpRequest, queryset: QuerySet[Any]) -> None:
        for company in queryset:
            services.reset_scrape_failures(company=company, actor=request.user)
        self.message_user(
            request, f"Reset failures for {queryset.count()} company(ies).", messages.SUCCESS
        )

    reset_failures_selected.short_description = "Reset failure counters"  # type: ignore[attr-defined]


class CareerCandidateUrlAdmin(admin.ModelAdmin):  # type: ignore[type-arg]
    """THE approval queue: humans pick exactly one candidate per company."""

    list_display = (
        "company",
        "url_link",
        "origin",
        "guessed_type",
        "score",
        "sample_titles_preview",
        "status",
        "decided_by",
    )
    list_filter = ("status", "origin", "guessed_type")
    list_select_related = ("company", "decided_by", "detection_run")
    search_fields = ("url", "company__name")
    actions = ("approve_selected", "reject_selected")

    def get_queryset(self, request: HttpRequest) -> QuerySet[Any]:
        qs = super().get_queryset(request)
        if not request.GET.get("status__exact"):
            qs = qs.filter(status=CandidateStatus.PENDING)
        return qs.order_by("-score")

    def has_add_permission(self, request: HttpRequest) -> bool:
        return False

    readonly_fields = (
        "company",
        "detection_run",
        "url",
        "normalized_url",
        "origin",
        "guessed_type",
        "ats_identifier",
        "score",
        "score_reasons_pretty",
        "page_title",
        "http_status",
        "sample_job_titles",
        "status",
        "decided_by",
        "decided_at",
        "reject_reason",
        "created_at",
    )
    fieldsets = (
        (
            None,
            {
                "fields": (
                    "company",
                    "detection_run",
                    "url",
                    "normalized_url",
                    "origin",
                    "guessed_type",
                    "ats_identifier",
                )
            },
        ),
        (
            "Scoring",
            {
                "fields": (
                    "score",
                    "score_reasons_pretty",
                    "page_title",
                    "http_status",
                    "sample_job_titles",
                )
            },
        ),
        ("Decision", {"fields": ("status", "decided_by", "decided_at", "reject_reason")}),
    )

    def url_link(self, obj: CareerCandidateUrl) -> str:
        return format_html('<a href="{0}" target="_blank" rel="noopener">{0}</a>', obj.url)

    url_link.short_description = "url"  # type: ignore[attr-defined]

    def sample_titles_preview(self, obj: CareerCandidateUrl) -> str:
        titles = obj.sample_job_titles[:3]
        return ", ".join(str(t) for t in titles) if titles else "—"

    sample_titles_preview.short_description = "sample titles"  # type: ignore[attr-defined]

    def score_reasons_pretty(self, obj: CareerCandidateUrl) -> str:
        if not obj.score_reasons:
            return "—"
        items = "".join(
            f"<li><strong>{r.get('rule', '?')}</strong>: {r.get('points', 0)} pts</li>"
            for r in obj.score_reasons
        )
        return format_html("<ul>{0}</ul>", items)

    score_reasons_pretty.short_description = "score reasons"  # type: ignore[attr-defined]

    def approve_selected(self, request: HttpRequest, queryset: QuerySet[Any]) -> None:
        companies = set(queryset.values_list("company_id", flat=True))
        if len(companies) != len(queryset):
            self.message_user(
                request,
                "Refused: select at most one candidate per company per run.",
                messages.ERROR,
            )
            return
        ok = failed = 0
        for candidate in queryset:
            try:
                services.approve_career_candidate(candidate=candidate, actor=request.user)
                ok += 1
            except Exception as exc:
                failed += 1
                self.message_user(request, f"{candidate}: {exc}", messages.ERROR)
        if ok:
            self.message_user(request, f"Approved {ok} candidate(s).", messages.SUCCESS)

    approve_selected.short_description = "Approve selected candidates"  # type: ignore[attr-defined]

    def reject_selected(self, request: HttpRequest, queryset: QuerySet[Any]) -> None:
        ok = 0
        for candidate in queryset:
            try:
                services.reject_career_candidate(
                    candidate=candidate, actor=request.user, reason="rejected in bulk"
                )
                ok += 1
            except Exception as exc:
                self.message_user(request, f"{candidate}: {exc}", messages.ERROR)
        self.message_user(request, f"Rejected {ok} candidate(s).", messages.SUCCESS)

    reject_selected.short_description = "Reject selected candidates"  # type: ignore[attr-defined]


class CompanySourceAdmin(admin.ModelAdmin):  # type: ignore[type-arg]
    """Fully read-only source history."""

    list_display = (
        "company",
        "normalized_url",
        "source_type",
        "is_current",
        "set_by",
        "retired_at",
    )
    list_filter = ("source_type", "is_current")
    search_fields = ("company__name", "normalized_url")
    list_select_related = ("company", "set_by")
    readonly_fields = [field.name for field in CompanySource._meta.fields]

    def has_add_permission(self, request: HttpRequest) -> bool:
        return False

    def has_change_permission(self, request: HttpRequest, obj: CompanySource | None = None) -> bool:
        return False

    def has_delete_permission(self, request: HttpRequest, obj: CompanySource | None = None) -> bool:
        return False


class DetectionRunAdmin(admin.ModelAdmin):  # type: ignore[type-arg]
    """Fully read-only; written by detection (PROMPT 3)."""

    list_display = (
        "company",
        "status",
        "started_at",
        "duration_ms",
        "urls_checked",
        "candidates_found",
    )
    list_filter = ("status",)
    list_select_related = ("company", "triggered_by")
    readonly_fields = (
        "company",
        "triggered_by",
        "status",
        "started_at",
        "finished_at",
        "duration_ms",
        "urls_checked",
        "candidates_found",
        "strategies_pretty",
        "error_message",
        "log_pretty",
    )
    fieldsets = (
        (None, {"fields": ("company", "triggered_by", "status", "started_at", "finished_at")}),
        (
            "Results",
            {
                "fields": (
                    "duration_ms",
                    "urls_checked",
                    "candidates_found",
                    "strategies_pretty",
                    "error_message",
                )
            },
        ),
        ("Trace", {"fields": ("log_pretty",)}),
    )

    def strategies_pretty(self, obj: DetectionRun) -> str:
        return ", ".join(str(s) for s in obj.strategies_used) or "—"

    strategies_pretty.short_description = "strategies"  # type: ignore[attr-defined]

    def log_pretty(self, obj: DetectionRun) -> str:
        if not obj.log:
            return "—"
        rows = "".join(f"<li>{entry}</li>" for entry in obj.log)
        return format_html("<ol>{0}</ol>", rows)

    log_pretty.short_description = "detection log"  # type: ignore[attr-defined]

    def has_add_permission(self, request: HttpRequest) -> bool:
        return False

    def has_change_permission(self, request: HttpRequest, obj: DetectionRun | None = None) -> bool:
        return False

    def has_delete_permission(self, request: HttpRequest, obj: DetectionRun | None = None) -> bool:
        return False


ops_site.register(Company, CompanyAdmin)
ops_site.register(CareerCandidateUrl, CareerCandidateUrlAdmin)
ops_site.register(CompanySource, CompanySourceAdmin)
ops_site.register(DetectionRun, DetectionRunAdmin)

# PROMPT 2 DECISION (see PART 6): Step 1 models register on the default admin
# site, which is NOT mounted (only ops_site is). Re-register them here so the
# ops portal can see users + the audit trail. Step 1 files remain untouched.
from apps.accounts.admin import UserAdmin as AccountsUserAdmin  # noqa: E402
from apps.accounts.models import User  # noqa: E402
from apps.audit_logs.admin import AuditLogAdmin  # noqa: E402
from apps.audit_logs.models import AuditLog  # noqa: E402

ops_site.register(User, AccountsUserAdmin)
ops_site.register(AuditLog, AuditLogAdmin)
