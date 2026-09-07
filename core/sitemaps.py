from typing import Any

from django.conf import settings
from django.contrib.sitemaps import Sitemap


class BaseSitemap(Sitemap):  # type: ignore[type-arg]
    limit = 50000

    def get_urls(
        self, page: Any = 1, site: Any = None, protocol: Any = None
    ) -> list[dict[str, Any]]:
        items = self.items()
        start = (page - 1) * self.limit
        end = page * self.limit
        if hasattr(items, "__getitem__") and hasattr(items, "__len__"):
            sliced_items = items[start:end]
        else:
            sliced_items = list(items)[start:end]
        base = settings.SITE_BASE_URL.rstrip("/")  # type: ignore[attr-defined]
        urls = []
        for item in sliced_items:
            loc = self.location(item)
            if not loc.startswith("/"):
                loc = "/" + loc
            url = {
                "location": f"{base}{loc}",
                "lastmod": self.lastmod(item),
                "changefreq": self.changefreq(item),
                "priority": self.priority(item),
            }
            urls.append(url)
        return urls

    def lastmod(self, item: Any) -> Any:
        return None

    def changefreq(self, item: Any) -> str:
        return ""

    def priority(self, item: Any) -> float:
        return 0.5


class StaticSitemap(BaseSitemap):
    def items(self) -> list[str]:
        return ["/", "/jobs/", "/companies/", "/exams/", "/exams/calendar/"]

    def location(self, item: str) -> str:
        return item

    def lastmod(self, item: str) -> None:
        return None

    def changefreq(self, item: str) -> str:
        return "daily"

    def priority(self, item: str) -> float:
        return 0.8 if item == "/" else 0.7
