from django.contrib.postgres.search import TrigramSimilarity
from django.db.models import QuerySet
from django_filters import rest_framework as filters
from rest_framework.exceptions import ValidationError

from apps.companies.models import Company


class CompanyFilter(filters.FilterSet):
    q = filters.CharFilter(method="filter_q", label="Search")
    industry = filters.CharFilter(field_name="industry", lookup_expr="icontains")
    has_open_jobs = filters.BooleanFilter(method="filter_has_open_jobs")
    ordering = filters.CharFilter(method="filter_ordering")

    class Meta:
        model = Company
        fields: list[str] = []

    def filter_q(self, queryset: QuerySet[Company], name: str, value: str) -> QuerySet[Company]:
        if not value:
            return queryset
        if len(value) < 3:
            return queryset.filter(name__icontains=value)
        return (
            queryset.annotate(similarity=TrigramSimilarity("name", value))
            .filter(similarity__gt=0.1)
            .order_by("-similarity")
        )

    def filter_has_open_jobs(
        self, queryset: QuerySet[Company], name: str, value: bool
    ) -> QuerySet[Company]:
        if value is True:
            return queryset.filter(open_jobs_count__gt=0)  # type: ignore
        elif value is False:
            return queryset.filter(open_jobs_count=0)  # type: ignore
        return queryset

    def filter_ordering(
        self, queryset: QuerySet[Company], name: str, value: str
    ) -> QuerySet[Company]:
        if not value:
            return queryset.order_by("name")
        allowed = {"name", "-name", "open_jobs_count", "-open_jobs_count"}
        values = [v.strip() for v in value.split(",") if v.strip()]
        for item in values:
            if item not in allowed:
                raise ValidationError(f"Invalid ordering: {item}")
        return queryset.order_by(*values)
