from django.db.models import BooleanField, Exists, OuterRef, QuerySet, Value
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import generics, permissions
from rest_framework.exceptions import NotFound

from apps.companies.filters import CompanyFilter
from apps.companies.models import Company
from apps.companies.serializers import CompanyDetailSerializer, CompanyListSerializer
from apps.jobs.models import Job, SavedJob
from apps.jobs.serializers import JobListSerializer
from core.pagination import CursorAwarePageNumberPagination


class CompanyListView(generics.ListAPIView[Company]):
    serializer_class = CompanyListSerializer
    pagination_class = CursorAwarePageNumberPagination
    filterset_class = CompanyFilter
    filter_backends = [DjangoFilterBackend]
    permission_classes = [permissions.AllowAny]

    def get_queryset(self) -> QuerySet[Company]:
        return Company.objects.public().with_public_job_counts()  # type: ignore


class CompanyDetailView(generics.RetrieveAPIView[Company]):
    queryset = Company.objects.public().with_public_job_counts()
    serializer_class = CompanyDetailSerializer
    lookup_field = "slug"
    permission_classes = [permissions.AllowAny]


class CompanyJobsView(generics.ListAPIView[Job]):
    serializer_class = JobListSerializer
    pagination_class = CursorAwarePageNumberPagination
    permission_classes = [permissions.AllowAny]

    def get_queryset(self) -> QuerySet[Job]:
        company_slug = self.kwargs.get("slug")
        try:
            company = Company.objects.public().get(slug=company_slug)
        except Company.DoesNotExist:
            raise NotFound("Company not found") from None

        queryset = Job.objects.public().filter(company=company).select_related("company")

        user = self.request.user
        if user.is_authenticated:
            saved_subquery = SavedJob.objects.filter(user=user, job=OuterRef("pk"))
            queryset = queryset.annotate(is_saved=Exists(saved_subquery))
        else:
            queryset = queryset.annotate(is_saved=Value(False, output_field=BooleanField()))

        return queryset  # type: ignore
