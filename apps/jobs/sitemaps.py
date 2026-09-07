from typing import Any

from core.sitemaps import BaseSitemap

from .models import Job


class JobSitemap(BaseSitemap):
    def items(self) -> Any:
        return (
            Job.objects.public()
            .filter(duplicate_of__isnull=True)
            .only("slug", "last_seen_at")
            .order_by("slug")
        )

    def location(self, obj: Job) -> str:
        return f"/jobs/{obj.slug}/"

    def lastmod(self, obj: Job) -> Any:
        return obj.last_seen_at

    def changefreq(self, obj: Job) -> str:
        return "hourly"

    def priority(self, obj: Job) -> float:
        return 0.8
