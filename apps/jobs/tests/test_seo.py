import datetime

import pytest
from django.test import override_settings
from django.utils import timezone

from apps.jobs.enums import JobStatus, JobType, WorkMode
from apps.jobs.seo import build_job_posting


@pytest.mark.django_db
class TestBuildJobPosting:
    def test_fully_populated_job(self, company_factory, job_factory):
        company = company_factory(
            name="TestCo",
            domain="testco.com",
            logo_url="https://testco.com/logo.png",
        )
        job = job_factory(
            company=company,
            title="Software Engineer",
            description="Build software.",
            description_html_sanitized="<p>Build software.</p>",
            posted_at=timezone.now() - datetime.timedelta(days=5),
            first_seen_at=timezone.now() - datetime.timedelta(days=5),
            deadline_at=timezone.now() + datetime.timedelta(days=30),
            city="Bangalore",
            state="Karnataka",
            country="India",
            source_job_id="job123",
            salary_min=100000,
            salary_max=150000,
            salary_currency="INR",
            salary_period="year",
            job_type=JobType.FULL_TIME,
            work_mode=WorkMode.ONSITE,
            status=JobStatus.OPEN,
            is_published=True,
        )
        data = build_job_posting(job)
        assert data is not None
        assert data["title"] == "Software Engineer"
        assert data["description"] == "<p>Build software.</p>"
        assert "datePosted" in data
        assert "validThrough" in data
        assert data["hiringOrganization"]["name"] == "TestCo"
        assert data["hiringOrganization"]["sameAs"] == "https://testco.com"
        assert data["hiringOrganization"]["logo"] == "https://testco.com/logo.png"
        assert data["jobLocation"]["address"]["addressCountry"] == "IN"
        assert data["identifier"]["value"] == "job123"
        assert data["employmentType"] == "FULL_TIME"
        assert data["baseSalary"]["unitText"] == "YEAR"
        assert data["directApply"] is False

    def test_unpublished_job_returns_none(self, job_factory):
        job = job_factory(is_published=False, status=JobStatus.OPEN)
        assert build_job_posting(job) is None

    def test_non_open_status_returns_none(self, job_factory):
        from django.utils import timezone

        for status in [
            JobStatus.DRAFT,
            JobStatus.CLOSED,
            JobStatus.POSSIBLY_CLOSED,
            JobStatus.LIKELY_CLOSED,
        ]:
            kwargs = {"status": status, "is_published": True}
            if status == JobStatus.CLOSED:
                kwargs["closed_at"] = timezone.now()
            job = job_factory(**kwargs)
            assert build_job_posting(job) is None

    def test_remote_job_has_telecommute(self, job_factory):
        job = job_factory(
            work_mode=WorkMode.REMOTE,
            status=JobStatus.OPEN,
            is_published=True,
        )
        data = build_job_posting(job)
        assert data["jobLocationType"] == "TELECOMMUTE"
        assert "applicantLocationRequirements" in data

    def test_hybrid_job_has_no_telecommute(self, job_factory):
        job = job_factory(
            work_mode=WorkMode.HYBRID,
            status=JobStatus.OPEN,
            is_published=True,
        )
        data = build_job_posting(job)
        assert "jobLocationType" not in data
        assert "applicantLocationRequirements" not in data

    def test_missing_deadline_falls_back_to_first_seen_plus_60_days(self, job_factory):
        first_seen = timezone.now() - datetime.timedelta(days=10)
        job = job_factory(
            first_seen_at=first_seen,
            posted_at=None,
            deadline_at=None,
            status=JobStatus.OPEN,
            is_published=True,
        )
        data = build_job_posting(job)
        expected = (first_seen + datetime.timedelta(days=60)).isoformat()
        assert data["validThrough"] == expected

    def test_missing_salary_omits_base_salary_key(self, job_factory):
        job = job_factory(
            salary_min=None,
            salary_max=None,
            status=JobStatus.OPEN,
            is_published=True,
        )
        data = build_job_posting(job)
        assert "baseSalary" not in data

    def test_all_job_type_mappings(self, job_factory):
        mappings = {
            JobType.FULL_TIME: "FULL_TIME",
            JobType.PART_TIME: "PART_TIME",
            JobType.INTERNSHIP: "INTERN",
            JobType.CONTRACT: "CONTRACTOR",
            JobType.TEMPORARY: "TEMPORARY",
            JobType.FREELANCE: "CONTRACTOR",
            JobType.UNKNOWN: None,
        }
        for job_type, expected in mappings.items():
            job = job_factory(
                job_type=job_type,
                status=JobStatus.OPEN,
                is_published=True,
            )
            data = build_job_posting(job)
            if expected is None:
                assert "employmentType" not in data
            else:
                assert data["employmentType"] == expected

    def test_no_null_or_empty_string_values(self, job_factory):
        job = job_factory(
            title="Test",
            description="",
            description_html_sanitized="",
            posted_at=None,
            first_seen_at=timezone.now(),
            status=JobStatus.OPEN,
            is_published=True,
        )
        data = build_job_posting(job)
        for _key, value in data.items():
            if isinstance(value, dict):
                for _subkey, subvalue in value.items():
                    if isinstance(subvalue, dict):
                        for _ssubkey, ssubvalue in subvalue.items():
                            assert ssubvalue is not None
                            if isinstance(ssubvalue, str):
                                assert ssubvalue != ""
                    else:
                        assert subvalue is not None
                        if isinstance(subvalue, str):
                            assert subvalue != ""
            else:
                assert value is not None
                if isinstance(value, str):
                    assert value != ""

    def test_description_sanitized_no_script(self, job_factory):
        job = job_factory(
            description_html_sanitized="<p>Safe content</p>",
            status=JobStatus.OPEN,
            is_published=True,
        )
        data = build_job_posting(job)
        assert "<script>" not in data["description"]

    @override_settings(SITE_BASE_URL="https://example.com")
    def test_canonical_url_uses_site_base_url(self, job_factory):
        # Tested via serializer's get_canonical_url.
        pass

    def test_country_mapping_falls_back_to_in(self, job_factory):
        job = job_factory(
            country="UnknownCountry",
            status=JobStatus.OPEN,
            is_published=True,
        )
        data = build_job_posting(job)
        assert data["jobLocation"]["address"]["addressCountry"] == "IN"
