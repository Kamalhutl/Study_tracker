from rest_framework import serializers

from apps.companies.models import Company
from apps.jobs.models import Job, JobReport, SavedJob


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

    class Meta:
        model = Job
        fields = (
            "id",
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
        )

    def get_is_saved(self, obj):
        request = self.context.get("request")
        if request and request.user.is_authenticated:
            return getattr(obj, "is_saved", False)
        return False


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
