"""Root URL configuration."""

from django.urls import include, path

from apps.companies.admin_site import ops_site
from core.health import healthz, readyz

urlpatterns = [
    path("admin/", ops_site.urls),
    path("healthz", healthz, name="healthz"),
    path("readyz", readyz, name="readyz"),
    path("api/v1/auth/", include("apps.accounts.urls")),
]
