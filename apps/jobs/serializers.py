from typing import Any, Dict, Optional

from django.conf import settings
from rest_framework import serializers

from apps.companies.models import Company
from apps.jobs.models import Job, JobReport, SavedJob
from apps.jobs.seo import build_job_posting


class CompanyNestedSerializer(serializers.ModelSerializer):
    class Meta:
        model = Company
        fields = ("id", "name", "slug", "domain", "logo_url")


class JobListSerializer(serializers.ModelSerializer):
    company = CompanyNestedSerializer(read_only=True)
    is_saved = serializers.SerializerMethodField()

    class Meta:
        model = Job
        fields = (
            "id",
            "slug",
            "title",
            "company",
            "location_raw",
            "work_mode",
            "job_type",
            "department",
            "posted_at",
            "apply_url",
            "is_saved",
        )

    def get_is_saved(self, obj):
        request = self.context.get("request")
        if request and request.user.is_authenticated:
            return getattr(obj, "is_saved", False)
        return False


class JobDetailSerializer(serializers.ModelSerializer):
    company = CompanyNestedSerializer(read_only=True)
    is_saved = serializers.SerializerMethodField()
    description_html_sanitized = serializers.CharField(read_only=True)
    scraped_at = serializers.DateTimeField(source="last_seen_at", read_only=True)
    canonical_url = serializers.SerializerMethodField()
    structured_data = serializers.SerializerMethodField()

    class Meta:
        model = Job
        fields = (
            "id",
            "slug",
            "title",
            "company",
            "location_raw",
            "work_mode",
            "job_type",
            "department",
            "posted_at",
            "apply_url",
            "is_saved",
            "description",
            "description_html_sanitized",
            "source_url",
            "experience_level",
            "extraction_confidence",
            "scraped_at",
            "canonical_url",
            "structured_data",
        )

    def get_is_saved(self, obj):
        request = self.context.get("request")
        if request and request.user.is_authenticated:
            return getattr(obj, "is_saved", False)
        return False

    def get_canonical_url(self, obj) -> str:
        return f"{settings.SITE_BASE_URL}/jobs/{obj.slug}"

    def get_structured_data(self, obj) -> Optional[Dict[str, Any]]:
        return build_job_posting(obj)


class SavedJobSerializer(serializers.ModelSerializer):
    job = JobListSerializer(read_only=True)

    class Meta:
        model = SavedJob
        fields = ("id", "job", "notes", "created_at")


class JobReportSerializer(serializers.ModelSerializer):
    class Meta:
        model = JobReport
        fields = ("id", "reason", "detail", "status", "created_at")
        read_only_fields = ("status",)
