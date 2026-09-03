from django.contrib.postgres.search import TrigramSimilarity
from django.db.models import Q
from django.utils import timezone
from django_filters import rest_framework as filters

from apps.exams.models import Exam


class ExamFilter(filters.FilterSet):
    q = filters.CharFilter(method="filter_q", label="Search (trigram)")
    body = filters.CharFilter(method="filter_body")
    category = filters.CharFilter(method="filter_category")
    level = filters.CharFilter(method="filter_level")
    status = filters.CharFilter(method="filter_status")
    applications_open = filters.BooleanFilter(method="filter_applications_open")
    upcoming_within_days = filters.NumberFilter(method="filter_upcoming")
    allow_final_year = filters.BooleanFilter(method="filter_allow_final_year")

    class Meta:
        model = Exam
        fields = []

    def filter_q(self, queryset, name, value):
        if not value:
            return queryset
        if len(value) < 3:
            return queryset.filter(
                Q(name__icontains=value)
                | Q(short_name__icontains=value)
                | Q(conducting_body__name__icontains=value)
            )
        # Trigram similarity
        return (
            queryset.annotate(
                sim=TrigramSimilarity("name", value)
                + TrigramSimilarity("conducting_body__name", value)
            )
            .filter(sim__gte=0.1)
            .distinct()
        )

    def filter_body(self, queryset, name, value):
        slugs = [s.strip() for s in value.split(",") if s.strip()]
        return queryset.filter(conducting_body__slug__in=slugs)

    def filter_category(self, queryset, name, value):
        cats = [c.strip() for c in value.split(",") if c.strip()]
        return queryset.filter(category__in=cats)

    def filter_level(self, queryset, name, value):
        levels = [v.strip() for v in value.split(",") if v.strip()]
        return queryset.filter(level__in=levels)

    def filter_status(self, queryset, name, value):
        # Filter by latest cycle status
        return queryset.filter(cycles__status=value, cycles__is_published=True).distinct()

    def filter_applications_open(self, queryset, name, value):
        if value:
            now = timezone.now().date()
            return queryset.filter(
                cycles__application_start__lte=now,
                cycles__application_end__gte=now,
                cycles__is_published=True,
            ).distinct()
        return queryset

    def filter_upcoming(self, queryset, name, value):
        if value is not None:
            from datetime import timedelta

            now = timezone.now().date()
            end = now + timedelta(days=value)
            return queryset.filter(
                Q(cycles__notification_date__range=(now, end))
                | Q(cycles__application_start__range=(now, end))
                | Q(cycles__application_end__range=(now, end))
                | Q(cycles__fee_last_date__range=(now, end))
                | Q(cycles__result_date__range=(now, end))
                | Q(cycles__stages__date_start__range=(now, end))
                | Q(cycles__stages__admit_card_date__range=(now, end))
                | Q(cycles__stages__result_date__range=(now, end)),
                cycles__is_published=True,
            ).distinct()
        return queryset

    def filter_allow_final_year(self, queryset, name, value):
        if value:
            return queryset.filter(eligibility__allow_final_year_appearing=True).distinct()
        return queryset
