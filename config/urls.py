"""Root URL configuration."""

from django.conf import settings
from django.contrib.sitemaps.views import index, sitemap
from django.http import HttpResponse
from django.urls import include, path
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView

from apps.companies.admin_site import ops_site
from apps.companies.sitemaps import CompanySitemap
from apps.exams.sitemaps import ExamSitemap
from apps.jobs.sitemaps import JobSitemap
from core.health import healthz, readyz
from core.sitemaps import StaticSitemap

sitemaps = {
    "jobs": JobSitemap,
    "companies": CompanySitemap,
    "exams": ExamSitemap,
    "static": StaticSitemap,
}

# Next.js site must rewrite /sitemap.xml, /sitemap-<section>.xml, and /robots.txt
# to this API in Sprint 2, so they are served from the website host.
urlpatterns = [
    path("admin/", ops_site.urls),
    path("healthz", healthz, name="healthz"),
    path("readyz", readyz, name="readyz"),
    path("api/v1/auth/", include("apps.accounts.urls")),
    path("api/v1/jobs/", include("apps.jobs.urls")),
    path("api/v1/companies/", include("apps.companies.urls")),
    path("api/v1/exams/", include("apps.exams.urls")),
    path("api/schema/", SpectacularAPIView.as_view(), name="schema"),
    path("api/docs/", SpectacularSwaggerView.as_view(url_name="schema"), name="docs"),
    path(
        "sitemap.xml",
        index,
        {"sitemaps": sitemaps, "sitemap_url_name": "sitemap-section"},
        name="sitemap-index",
    ),
    path(
        "sitemap-<str:section>.xml",
        sitemap,
        {"sitemaps": sitemaps},
        name="sitemap-section",
    ),
    path(
        "robots.txt",
        lambda request: HttpResponse(
            f"Allow: /\nDisallow: /admin/\nDisallow: /api/\nSitemap: {settings.SITE_BASE_URL}/sitemap.xml",
            content_type="text/plain",
        ),
    ),
]
