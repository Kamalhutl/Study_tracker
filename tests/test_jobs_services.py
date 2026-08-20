"""Jobs services — publish/close/reopen/duplicate/edit/report/save/search/trust."""

import pytest
from django.core.exceptions import ValidationError
from django.utils import timezone

from apps.audit_logs.models import AuditLog
from apps.jobs import services
from apps.jobs.enums import JobStatus, ReportReason, ReportStatus
from apps.jobs.models import Job, JobStatusEvent, SavedJob
from tests.factories import (
    CompanyFactory,
    JobFactory,
    JobReportFactory,
    UserFactory,
)


class TestPublishLifecycle:
    def test_publish_job(self):
        job = JobFactory(is_published=False)
        actor = UserFactory()
        out = services.publish_job(job=job, actor=actor)
        assert out.is_published is True
        assert out.published_at is not None

    def test_unpublish_job(self):
        job = JobFactory(is_published=True)
        actor = UserFactory()
        out = services.unpublish_job(job=job, actor=actor)
        assert out.is_published is False

    def test_mark_job_closed(self):
        job = JobFactory()
        actor = UserFactory()
        out = services.mark_job_closed(job=job, actor=actor, reason="no longer hiring")
        assert out.status == JobStatus.CLOSED
        assert out.closed_at is not None
        assert out.is_manual_status is True
        event = JobStatusEvent.objects.get(job=job, trigger="admin")
        assert event.to_status == JobStatus.CLOSED

    def test_reopen_job(self):
        job = JobFactory(closed=True, manual_status=True)
        actor = UserFactory()
        out = services.reopen_job(job=job, actor=actor)
        assert out.status == JobStatus.OPEN
        assert out.closed_at is None
        assert out.is_manual_status is False
        assert out.missing_count == 0
        assert out.reopened_count == 1
        assert JobStatusEvent.objects.filter(job=job, trigger="reopen").exists()

    def test_audit_rows(self):
        job = JobFactory(is_published=False)
        actor = UserFactory()
        services.publish_job(job=job, actor=actor)
        services.unpublish_job(job=job, actor=actor)
        services.mark_job_closed(job=job, actor=actor)
        services.reopen_job(job=job, actor=actor)
        assert AuditLog.objects.filter(action="job.published").count() == 1
        assert AuditLog.objects.filter(action="job.unpublished").count() == 1
        assert AuditLog.objects.filter(action="job.closed").count() == 1
        assert AuditLog.objects.filter(action="job.reopened").count() == 1


class TestMarkDuplicate:
    def test_self_reference_raises(self):
        job = JobFactory()
        with pytest.raises(ValueError):
            services.mark_duplicate(job=job, canonical=job, actor=UserFactory())

    def test_cycle_raises(self):
        actor = UserFactory()
        a = JobFactory()
        b = JobFactory()
        services.mark_duplicate(job=b, canonical=a, actor=actor)
        with pytest.raises(ValueError):
            services.mark_duplicate(job=a, canonical=b, actor=actor)

    def test_dupe_unpublished(self):
        actor = UserFactory()
        canonical = JobFactory()
        dupe = JobFactory(is_published=True)
        services.mark_duplicate(job=dupe, canonical=canonical, actor=actor)
        dupe.refresh_from_db()
        assert dupe.duplicate_of_id == canonical.pk
        assert dupe.is_published is False
        assert AuditLog.objects.filter(action="job.marked_duplicate").count() == 1


class TestEditJobFields:
    def test_appends_edited_fields_and_clears_review(self):
        actor = UserFactory()
        job = JobFactory(pending_review=True)
        out = services.edit_job_fields(
            job=job, changes={"city": "Pune", "description": "New text"}, actor=actor
        )
        assert out.city == "Pune"
        assert "city" in out.manually_edited_fields
        assert "description" in out.manually_edited_fields
        assert out.needs_review is False
        assert out.reviewed_by == actor
        assert out.reviewed_at is not None
        assert AuditLog.objects.filter(action="job.fields_edited").count() == 1

    def test_unknown_field_rejected(self):
        with pytest.raises(ValidationError):
            services.edit_job_fields(
                job=JobFactory(), changes={"hacked_field": 1}, actor=UserFactory()
            )

    def test_dedupes_edited_fields(self):
        actor = UserFactory()
        job = JobFactory()
        services.edit_job_fields(job=job, changes={"city": "X"}, actor=actor)
        services.edit_job_fields(job=job, changes={"city": "Y"}, actor=actor)
        job.refresh_from_db()
        assert job.manually_edited_fields.count("city") == 1


class TestReviewApproval:
    def test_approve_publishes(self):
        actor = UserFactory()
        job = JobFactory(pending_review=True)
        out = services.approve_job_review(job=job, actor=actor)
        assert out.needs_review is False
        assert out.is_published is True
        assert AuditLog.objects.filter(action="job.review.approved").count() == 1

    def test_reject_stays_unpublished(self):
        actor = UserFactory()
        job = JobFactory(pending_review=True)
        out = services.reject_job_review(job=job, actor=actor, reason="unclear posting")
        assert out.needs_review is False
        assert out.is_published is False
        assert out.review_reason == "unclear posting"
        assert AuditLog.objects.filter(action="job.review.rejected").count() == 1


class TestReports:
    def test_report_increments_count(self):
        job = JobFactory()
        user = UserFactory()
        report = services.submit_job_report(
            job=job, user=user, reason=ReportReason.SPAM, comment="bad"
        )
        assert report.status == ReportStatus.OPEN
        job.refresh_from_db()
        assert job.report_count == 1
        assert AuditLog.objects.filter(action="job.reported").count() == 1

    def test_third_open_report_flags_review(self):
        job = JobFactory(is_published=True)
        for _i in range(3):
            services.submit_job_report(job=job, user=UserFactory(), reason=ReportReason.EXPIRED)
        job.refresh_from_db()
        assert job.needs_review is True
        assert job.review_reason == "user reports"

    def test_duplicate_open_report_rejected(self):
        job = JobFactory()
        user = UserFactory()
        services.submit_job_report(job=job, user=user, reason=ReportReason.EXPIRED)
        with pytest.raises(ValidationError):
            services.submit_job_report(job=job, user=user, reason=ReportReason.SPAM)

    def test_unknown_reason_rejected(self):
        job = JobFactory()
        with pytest.raises(ValidationError):
            services.submit_job_report(job=job, user=UserFactory(), reason="bananas")

    def test_resolve_expired_accept_closes_job(self):
        job = JobFactory()
        report = JobReportFactory(job=job, reason=ReportReason.EXPIRED)
        out = services.resolve_report(
            report=report, actor=UserFactory(), accept=True, note="confirmed"
        )
        assert out.status == "accepted"
        job.refresh_from_db()
        assert job.status == JobStatus.CLOSED
        assert AuditLog.objects.filter(action="job.report.resolved").count() == 1

    def test_resolve_reject_keeps_job(self):
        job = JobFactory()
        report = JobReportFactory(job=job, reason=ReportReason.EXPIRED)
        out = services.resolve_report(report=report, actor=UserFactory(), accept=False)
        assert out.status == "rejected"
        job.refresh_from_db()
        assert job.status == JobStatus.OPEN


class TestSaveUnsave:
    def test_save_job_idempotent(self):
        job = JobFactory()
        user = UserFactory()
        services.save_job(user=user, job=job)
        services.save_job(user=user, job=job)
        assert SavedJob.objects.filter(user=user, job=job).count() == 1
        job.refresh_from_db()
        assert job.save_count == 1
        assert AuditLog.objects.filter(action="job.saved").count() == 2  # one audit row per call

    def test_unsave_job(self):
        job = JobFactory()
        user = UserFactory()
        services.save_job(user=user, job=job)
        services.unsave_job(user=user, job=job)
        assert SavedJob.objects.filter(user=user, job=job).count() == 0
        job.refresh_from_db()
        assert job.save_count == 0
        assert AuditLog.objects.filter(action="job.unsaved").count() == 1


class TestSearchAndTrust:
    def test_search_vector_finds_job(self):
        company = CompanyFactory(slug="search-co")
        job = JobFactory(
            company=company,
            title="Django Platform Engineer",
            description="Backend with Django and Postgres",
        )
        services.refresh_search_vector(job=job)
        results = Job.objects.search("django")
        assert job.pk in {j.pk for j in results}

    def test_company_bulk_refresh(self):
        company = CompanyFactory(slug="bulk-search")
        JobFactory(company=company, title="Go Engineer One")
        JobFactory(company=company, title="Go Engineer Two")
        services.refresh_search_vector(company=company)
        assert Job.objects.search("Go").count() == 2

    def test_compute_trust_label_verified_ats(self):
        company = CompanyFactory(slug="trust-ats", ats=True)
        job = JobFactory(company=company, last_seen_at=timezone.now() - timezone.timedelta(hours=1))
        label = services.compute_trust_label(job)
        assert "Verified source" in label
        assert "Checked recently" in label

    def test_compute_trust_label_custom(self):
        company = CompanyFactory(slug="trust-custom", career_source_type="own_career_page")
        job = JobFactory(company=company, last_seen_at=timezone.now() - timezone.timedelta(days=2))
        assert services.compute_trust_label(job) == "Official career page"
