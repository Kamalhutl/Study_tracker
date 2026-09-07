"""Custom AdminSite with the ops dashboard (companies/jobs health at a glance)."""

from typing import Any

from django.contrib import admin
from django.db.models import Count, Min
from django.http import HttpRequest
from django.template.response import TemplateResponse
from django.urls import reverse


def dashboard_context(request: Any = None) -> dict[str, Any]:
    """One aggregate query per number — no loops over companies."""
    from apps.companies.enums import DetectionStatus, ScrapeHealth
    from apps.companies.models import Company, DetectionRun

    context: dict[str, Any] = {}
    companies = Company.objects
    context["company_total"] = companies.count()
    context["company_verified"] = companies.filter(is_verified=True).count()
    context["company_pending_detection"] = companies.filter(
        detection_status=DetectionStatus.PENDING
    ).count()
    context["company_needs_review"] = companies.filter(
        detection_status=DetectionStatus.NEEDS_REVIEW
    ).count()

    context["health_counts"] = dict(companies.by_health().values_list("scrape_health", "total"))
    changelist_href = reverse("admin:companies_company_changelist")
    context["health_rows"] = [
        (
            value,
            context["health_counts"].get(value, 0),
            f"{changelist_href}?scrape_health__exact={value}",
        )
        for value in ScrapeHealth.values
    ]

    from apps.jobs.enums import JobStatus
    from apps.jobs.models import Job

    context["job_counts"] = dict(
        Job.objects.values("status").annotate(total=Count("id")).values_list("status", "total")
    )
    job_changelist_href = reverse("admin:jobs_job_changelist")
    context["job_rows"] = [
        (value, context["job_counts"].get(value, 0), f"{job_changelist_href}?status__exact={value}")
        for value in JobStatus.values
    ]

    due = companies.due()
    context["due_now_count"] = due.count()
    next_min = due.aggregate(next=Min("next_scrape_at"))["next"]
    context["next_scrape_at"] = next_min

    context["last_detection_runs"] = DetectionRun.objects.select_related("company")[:10]

    # Dashboard-only: CompanyAdmin has a 14-query budget enforced by tests/test_admin.py::TestQueryBudgets
    from django.db.models import Q
    from django.utils import timezone

    from apps.scraping.models import ScrapeRun

    cutoff = timezone.now() - timezone.timedelta(days=7)
    unchanged_agg = ScrapeRun.objects.filter(created_at__gte=cutoff).aggregate(
        total=Count("id"),
        unchanged=Count("id", filter=Q(notes="not_modified")),
    )
    total_runs = unchanged_agg["total"] or 0
    unchanged_runs = unchanged_agg["unchanged"] or 0
    context["unchanged_rate_7d"] = (
        f"{(unchanged_runs / total_runs) * 100:.1f}%" if total_runs else "—"
    )
    context["unchanged_rate_7d_detail"] = f"{unchanged_runs}/{total_runs}"
    return context


class OpsAdminSite(admin.AdminSite):
    site_header = "Study Tracker Ops"
    site_title = "Study Tracker Ops"
    index_title = "Operations dashboard"
    index_template = "companies/admin_dashboard.html"

    def index(
        self, request: HttpRequest, extra_context: dict[str, Any] | None = None
    ) -> TemplateResponse:
        context: dict[str, Any] = dashboard_context(request)
        if extra_context:
            context.update(extra_context)
        return super().index(request, extra_context=context)


ops_site = OpsAdminSite(name="ops")
