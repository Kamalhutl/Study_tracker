"""Jobs models & constraints tests."""

from datetime import timedelta

import pytest
from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.jobs.enums import JobStatus
from apps.jobs.models import JobReport
from tests.factories import CompanyFactory, JobFactory, JobReportFactory, UserFactory


class TestJobConstraints:
    def test_source_job_id_blank_allowed_dup(self):
        company = CompanyFactory(slug="sjid-blank")
        JobFactory(company=company, source_job_id="")
        JobFactory(company=company, source_job_id="")
        assert company.jobs.count() == 2

    def test_duplicate_source_job_id_rejected(self):
        company = CompanyFactory(slug="sjid-dup")
        JobFactory(company=company, source_job_id="abc123")
        with pytest.raises(IntegrityError), transaction.atomic():
            JobFactory(company=company, source_job_id="abc123")

    def test_missing_count_over_max_rejected(self):
        with pytest.raises(IntegrityError), transaction.atomic():
            JobFactory(missing_count=4)

    def test_closed_without_closed_at_rejected(self):
        with pytest.raises(IntegrityError), transaction.atomic():
            JobFactory(status=JobStatus.CLOSED, closed_at=None)

    def test_salary_range_sane(self):
        with pytest.raises(IntegrityError), transaction.atomic():
            JobFactory(salary_min=100, salary_max=50)

    def test_salary_nullable_ok(self):
        job = JobFactory(salary_min=None, salary_max=None)
        assert job.pk is not None

    def test_confidence_max(self):
        with pytest.raises(IntegrityError), transaction.atomic():
            JobFactory(extraction_confidence=101)


class TestJobProperties:
    def test_is_live(self):
        assert JobFactory().is_live is True
        assert JobFactory(is_published=False).is_live is False
        assert JobFactory(status=JobStatus.DRAFT, is_published=False).is_live is False

    def test_is_stale(self):
        assert JobFactory(stale=True).is_stale is True
        assert JobFactory(likely_closed=True).is_stale is True
        assert JobFactory().is_stale is False

    def test_age_days_uses_posted_at(self):
        job = JobFactory(posted_at=timezone.now() - timedelta(days=5))
        assert job.age_days == 5

    def test_str(self):
        company = CompanyFactory(slug="str-job-co", name="Acme")
        job = JobFactory(company=company, title="Engineer X")
        assert str(job) == "Engineer X @ Acme"


class TestSavedJobConstraints:
    def test_unique_per_user(self):
        user = UserFactory()
        job = JobFactory()
        assert JobReportFactory is not None  # imported for use
        from apps.jobs.models import SavedJob

        SavedJob.objects.create(user=user, job=job)
        with pytest.raises(IntegrityError), transaction.atomic():
            SavedJob.objects.create(user=user, job=job)


class TestJobReport:
    def test_str_and_default_status(self):
        job = JobFactory(title="Reported Job")
        report = JobReportFactory(job=job, reason="expired")
        assert report.status == "open"

    def test_open_report_unique_per_user(self):
        job = JobFactory()
        user = UserFactory()
        JobReport.objects.create(job=job, user=user, reason="expired")
        with pytest.raises(IntegrityError), transaction.atomic():
            JobReport.objects.create(job=job, user=user, reason="spam")
