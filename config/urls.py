"""Root URL configuration."""

from django.urls import include, path
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView

from apps.companies.admin_site import ops_site
from core.health import healthz, readyz

urlpatterns = [
    path("admin/", ops_site.urls),
    path("healthz", healthz, name="healthz"),
    path("readyz", readyz, name="readyz"),
    path("api/v1/auth/", include("apps.accounts.urls")),
    path("api/v1/jobs/", include("apps.jobs.urls")),
    path("api/v1/exams/", include("apps.exams.urls")),
    path("api/schema/", SpectacularAPIView.as_view(), name="schema"),
    path("api/docs/", SpectacularSwaggerView.as_view(url_name="schema"), name="docs"),
]
