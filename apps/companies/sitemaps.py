from typing import Any

from core.sitemaps import BaseSitemap

from .models import Company


class CompanySitemap(BaseSitemap):
    def items(self) -> Any:
        return Company.objects.public().only("slug", "updated_at").order_by("slug")

    def location(self, obj: Company) -> str:
        return f"/companies/{obj.slug}/"

    def lastmod(self, obj: Company) -> Any:
        return obj.updated_at

    def changefreq(self, obj: Company) -> str:
        return "daily"

    def priority(self, obj: Company) -> float:
        return 0.7
