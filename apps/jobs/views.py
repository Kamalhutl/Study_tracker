from django.core.cache import cache
from django.db.models import (
    BooleanField,
    Count,
    Exists,
    OuterRef,
    Value,
)
from django_filters.rest_framework import DjangoFilterBackend
from drf_spectacular.utils import (
    OpenApiParameter,
    OpenApiResponse,
    extend_schema,
    inline_serializer,
)
from rest_framework import generics, permissions, serializers, status, views
from rest_framework.exceptions import NotFound
from rest_framework.response import Response

from apps.jobs.filters import JobFilter
from apps.jobs.models import Job, SavedJob
from apps.jobs.serializers import (
    JobDetailSerializer,
    JobListSerializer,
    JobReportSerializer,
    SavedJobSerializer,
)
from apps.jobs.services import save_job, submit_job_report, unsave_job
from core.pagination import CursorAwarePageNumberPagination


class IsAuthenticatedOrReadOnly(permissions.BasePermission):
    def has_permission(self, request, view):
        if request.method in permissions.SAFE_METHODS:
            return True
        return request.user and request.user.is_authenticated


class JobListView(generics.ListAPIView):
    serializer_class = JobListSerializer
    pagination_class = CursorAwarePageNumberPagination
    filterset_class = JobFilter
    filter_backends = [DjangoFilterBackend]
    permission_classes = [permissions.AllowAny]

    def get_queryset(self):
        queryset = Job.objects.public().select_related("company")
        user = self.request.user
        if user.is_authenticated:
            saved_subquery = SavedJob.objects.filter(user=user, job=OuterRef("pk"))
            queryset = queryset.annotate(is_saved=Exists(saved_subquery))
        else:
            queryset = queryset.annotate(is_saved=Value(False, output_field=BooleanField()))
        return queryset

    @extend_schema(
        parameters=[
            OpenApiParameter(name="q", description="Search", type=str),
            OpenApiParameter(name="work_mode", description="Multi-value", type=str, many=True),
            OpenApiParameter(name="job_type", description="Multi-value", type=str, many=True),
            OpenApiParameter(name="company", description="Company slug", type=str, many=True),
            OpenApiParameter(name="department", description="icontains", type=str),
            OpenApiParameter(name="location", description="icontains", type=str),
            OpenApiParameter(name="posted_after", description="ISO date", type=str),
            OpenApiParameter(name="posted_within_days", description="Integer", type=int),
            OpenApiParameter(name="has_apply_url", description="Boolean", type=bool),
            OpenApiParameter(
                name="ordering",
                description="posted_at, -posted_at, created_at, -created_at, title",
                type=str,
            ),
        ],
        responses={200: JobListSerializer(many=True)},
    )
    def get(self, request, *args, **kwargs):
        return super().get(request, *args, **kwargs)


class JobDetailView(generics.RetrieveAPIView):
    queryset = Job.objects.public().select_related("company")
    serializer_class = JobDetailSerializer
    lookup_field = "pk"
    permission_classes = [permissions.AllowAny]

    def get_queryset(self):
        queryset = super().get_queryset()
        user = self.request.user
        if user.is_authenticated:
            saved_subquery = SavedJob.objects.filter(user=user, job=OuterRef("pk"))
            queryset = queryset.annotate(is_saved=Exists(saved_subquery))
        else:
            queryset = queryset.annotate(is_saved=Value(False, output_field=BooleanField()))
        return queryset

    @extend_schema(responses={200: JobDetailSerializer})
    def get(self, request, *args, **kwargs):
        return super().get(request, *args, **kwargs)


class SaveJobView(generics.GenericAPIView):
    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(
        request=None,
        responses={
            200: inline_serializer("SaveResponse", fields={"detail": serializers.CharField()})
        },
    )
    def post(self, request, pk):
        try:
            job = Job.objects.get(pk=pk, is_published=True, status="open", is_deleted=False)
        except Job.DoesNotExist:
            raise NotFound("Job not found") from None
        save_job(user=request.user, job=job)
        return Response({"detail": "Job saved"}, status=status.HTTP_200_OK)

    @extend_schema(responses={204: None})
    def delete(self, request, pk):
        try:
            job = Job.objects.get(pk=pk, is_published=True, status="open", is_deleted=False)
        except Job.DoesNotExist:
            raise NotFound("Job not found") from None
        unsave_job(user=request.user, job=job)
        return Response(status=status.HTTP_204_NO_CONTENT)


class SavedJobListView(generics.ListAPIView):
    serializer_class = SavedJobSerializer
    pagination_class = CursorAwarePageNumberPagination
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        return SavedJob.objects.filter(user=self.request.user).select_related("job", "job__company")

    @extend_schema(responses={200: SavedJobSerializer(many=True)})
    def get(self, request, *args, **kwargs):
        return super().get(request, *args, **kwargs)


class ReportJobView(generics.CreateAPIView):
    serializer_class = JobReportSerializer
    permission_classes = [permissions.IsAuthenticated]
    throttle_scope = "report"

    def get_throttles(self):
        if self.request.method == "POST":
            self.throttle_scope = "report"
        return super().get_throttles()

    @extend_schema(
        request=JobReportSerializer,
        responses={201: JobReportSerializer, 400: OpenApiResponse(description="Validation error")},
    )
    def post(self, request, pk):
        try:
            job = Job.objects.get(pk=pk, is_published=True, is_deleted=False)
        except Job.DoesNotExist:
            raise NotFound("Job not found") from None
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        report = submit_job_report(
            job=job,
            user=request.user,
            reason=serializer.validated_data["reason"],
            detail=serializer.validated_data.get("detail", ""),
        )
        return Response(JobReportSerializer(report).data, status=status.HTTP_201_CREATED)


class JobFacetsView(views.APIView):
    permission_classes = [permissions.AllowAny]

    @extend_schema(
        responses={
            200: inline_serializer(
                "FacetsResponse",
                fields={
                    "work_mode": inline_serializer(
                        "WorkModeFacet",
                        fields={
                            "onsite": serializers.IntegerField(),
                            "remote": serializers.IntegerField(),
                            "hybrid": serializers.IntegerField(),
                            "unknown": serializers.IntegerField(),
                        },
                    ),
                    "job_type": inline_serializer(
                        "JobTypeFacet",
                        fields={
                            "full_time": serializers.IntegerField(),
                            "part_time": serializers.IntegerField(),
                            "contract": serializers.IntegerField(),
                            "internship": serializers.IntegerField(),
                            "temporary": serializers.IntegerField(),
                            "freelance": serializers.IntegerField(),
                            "unknown": serializers.IntegerField(),
                        },
                    ),
                    "company": inline_serializer(
                        "CompanyFacet",
                        fields={
                            "slug": serializers.CharField(),
                            "name": serializers.CharField(),
                            "count": serializers.IntegerField(),
                        },
                    ),
                    "department": inline_serializer(
                        "DepartmentFacet",
                        fields={
                            "name": serializers.CharField(),
                            "count": serializers.IntegerField(),
                        },
                    ),
                },
            )
        }
    )
    def get(self, request):
        cache_key = "job_facets"
        cached = cache.get(cache_key)
        if cached:
            return Response(cached)

        base_qs = Job.objects.public()

        work_mode_counts = base_qs.values("work_mode").annotate(count=Count("id"))
        work_mode_dict = {item["work_mode"]: item["count"] for item in work_mode_counts}

        job_type_counts = base_qs.values("job_type").annotate(count=Count("id"))
        job_type_dict = {item["job_type"]: item["count"] for item in job_type_counts}

        company_counts = (
            base_qs.values("company__slug", "company__name")
            .annotate(count=Count("id"))
            .order_by("-count")[:20]
        )
        company_list = [
            {"slug": c["company__slug"], "name": c["company__name"], "count": c["count"]}
            for c in company_counts
        ]

        dept_counts = (
            base_qs.exclude(department="")
            .values("department")
            .annotate(count=Count("id"))
            .order_by("-count")[:20]
        )
        dept_list = [{"name": d["department"], "count": d["count"]} for d in dept_counts]

        data = {
            "work_mode": work_mode_dict,
            "job_type": job_type_dict,
            "company": company_list,
            "department": dept_list,
        }
        cache.set(cache_key, data, 300)
        return Response(data)
