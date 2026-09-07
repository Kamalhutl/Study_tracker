from typing import Any

from core.sitemaps import BaseSitemap

from .models import Exam


class ExamSitemap(BaseSitemap):
    def items(self) -> Any:
        return Exam.objects.filter(is_deleted=False).only("slug", "updated_at").order_by("slug")

    def location(self, obj: Exam) -> str:
        return f"/exams/{obj.slug}/"

    def lastmod(self, obj: Exam) -> Any:
        return obj.updated_at

    def changefreq(self, obj: Exam) -> str:
        return "weekly"

    def priority(self, obj: Exam) -> float:
        return 0.6
