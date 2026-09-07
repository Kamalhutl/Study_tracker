from rest_framework import serializers

from apps.companies.models import Company


class CompanyListSerializer(serializers.ModelSerializer[Company]):
    open_jobs_count = serializers.IntegerField(read_only=True)

    class Meta:
        model = Company
        fields = (
            "name",
            "slug",
            "domain",
            "logo_url",
            "industry",
            "hq_location",
            "size_bucket",
            "open_jobs_count",
        )


class CompanyDetailSerializer(serializers.ModelSerializer[Company]):
    open_jobs_count = serializers.IntegerField(read_only=True)
    last_checked_at = serializers.DateTimeField(source="last_successful_scrape_at", read_only=True)

    class Meta:
        model = Company
        fields = (
            "name",
            "slug",
            "domain",
            "logo_url",
            "industry",
            "hq_location",
            "size_bucket",
            "open_jobs_count",
            "description",
            "linkedin_url",
            "career_url",
            "is_verified",
            "last_checked_at",
        )
