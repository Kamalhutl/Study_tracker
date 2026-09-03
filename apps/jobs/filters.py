from django.contrib.postgres.search import TrigramSimilarity
from django.db.models import (
    Case,
    IntegerField,
    Q,
    Value,
    When,
)
from django_filters import rest_framework as filters
from rest_framework.exceptions import ValidationError

from apps.jobs.models import Job


class CharInFilter(filters.BaseInFilter, filters.CharFilter):
    pass


class JobFilter(filters.FilterSet):
    q = filters.CharFilter(method="filter_q", label="Search")
    work_mode = CharInFilter(field_name="work_mode", lookup_expr="in")
    job_type = CharInFilter(field_name="job_type", lookup_expr="in")
    company = CharInFilter(field_name="company__slug", lookup_expr="in")
    department = filters.CharFilter(field_name="department", lookup_expr="icontains")
    location = filters.CharFilter(field_name="location_raw", lookup_expr="icontains")
    posted_after = filters.DateTimeFilter(field_name="posted_at", lookup_expr="gte")
    posted_within_days = filters.NumberFilter(method="filter_posted_within_days")
    has_apply_url = filters.BooleanFilter(method="filter_has_apply_url")
    ordering = filters.CharFilter(method="filter_ordering")

    class Meta:
        model = Job
        fields: list = []

    def filter_q(self, queryset, name, value):
        if not value:
            return queryset
        if len(value) < 3:
            return queryset.filter(
                Q(title__icontains=value)
                | Q(company__name__icontains=value)
                | Q(department__icontains=value)
            )
        return (
            queryset.annotate(
                similarity=TrigramSimilarity("title", value)
                + TrigramSimilarity("company__name", value)
                + TrigramSimilarity("department", value)
            )
            .filter(similarity__gt=0.1)
            .order_by("-similarity")
        )

    def filter_posted_within_days(self, queryset, name, value):
        from datetime import timedelta

        from django.utils import timezone

        if value is not None:
            cutoff = timezone.now() - timedelta(days=int(value))
            return queryset.filter(posted_at__gte=cutoff)
        return queryset

    def filter_has_apply_url(self, queryset, name, value):
        if value is True:
            return queryset.filter(apply_url__gt="")
        elif value is False:
            return queryset.filter(apply_url="")
        return queryset

    def filter_ordering(self, queryset, name, value):
        if not value:
            return queryset.order_by("-posted_at")
        values = [v.strip() for v in value.split(",") if v.strip()]
        if not values:
            return queryset.order_by("-posted_at")
        allowed = {"posted_at", "-posted_at", "created_at", "-created_at", "title"}
        for item in values:
            if item not in allowed:
                raise ValidationError(f"Invalid ordering: {item}")
        # Use Case to put nulls last for -posted_at
        if "-posted_at" in values:
            queryset = queryset.annotate(
                posted_at_null=Case(
                    When(posted_at__isnull=True, then=Value(1)),
                    default=Value(0),
                    output_field=IntegerField(),
                )
            )
            order_by = ["posted_at_null", "-posted_at"]
            values = [v for v in values if v != "-posted_at"]
            if values:
                order_by.extend(values)
            return queryset.order_by(*order_by)
        return queryset.order_by(*values) if values else queryset.order_by("-posted_at")
