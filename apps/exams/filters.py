from django.contrib.postgres.search import TrigramSimilarity
from django.db.models import Q, QuerySet
from django.db.models.functions import Greatest
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
        fields: list[str] = []

    def filter_q(self, queryset: QuerySet[Exam], name: str, value: str) -> QuerySet[Exam]:
        if not value:
            return queryset
        if len(value) < 3:
            return queryset.filter(
                Q(name__icontains=value)
                | Q(short_name__icontains=value)
                | Q(conducting_body__name__icontains=value)
            )
        sim = Greatest(
            TrigramSimilarity("name", value),
            TrigramSimilarity("short_name", value),
            TrigramSimilarity("conducting_body__name", value),
        )
        return queryset.annotate(sim=sim).filter(sim__gte=0.3).order_by("-sim").distinct()

    def filter_body(self, queryset: QuerySet[Exam], name: str, value: str) -> QuerySet[Exam]:
        slugs = [s.strip() for s in value.split(",") if s.strip()]
        return queryset.filter(conducting_body__slug__in=slugs)

    def filter_category(self, queryset: QuerySet[Exam], name: str, value: str) -> QuerySet[Exam]:
        cats = [c.strip() for c in value.split(",") if c.strip()]
        return queryset.filter(category__in=cats)

    def filter_level(self, queryset: QuerySet[Exam], name: str, value: str) -> QuerySet[Exam]:
        levels = [v.strip() for v in value.split(",") if v.strip()]
        return queryset.filter(level__in=levels)

    def filter_status(self, queryset: QuerySet[Exam], name: str, value: str) -> QuerySet[Exam]:
        from django.db.models import OuterRef, Subquery

        from apps.exams.models import ExamCycle

        latest_status = Subquery(
            ExamCycle.objects.filter(exam=OuterRef("pk"), is_published=True)
            .order_by("-year", "-cycle_label")
            .values("status")[:1]
        )
        return queryset.annotate(latest_status=latest_status).filter(latest_status=value)

    def filter_applications_open(
        self, queryset: QuerySet[Exam], name: str, value: bool
    ) -> QuerySet[Exam]:
        if value:
            now = timezone.now().date()
            return queryset.filter(
                cycles__application_start__lte=now,
                cycles__application_end__gte=now,
                cycles__is_published=True,
            ).distinct()
        return queryset

    def filter_upcoming(
        self, queryset: QuerySet[Exam], name: str, value: int | None
    ) -> QuerySet[Exam]:
        if value is not None:
            from datetime import timedelta

            now = timezone.now().date()
            end = now + timedelta(days=int(value))
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

    def filter_allow_final_year(
        self, queryset: QuerySet[Exam], name: str, value: bool
    ) -> QuerySet[Exam]:
        if value:
            return queryset.filter(eligibility__allow_final_year_appearing=True).distinct()
        return queryset
