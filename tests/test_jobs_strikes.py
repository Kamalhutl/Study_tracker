"""apply_missing_strikes — the 3-strike ladder (100% coverage required)."""

import uuid

import pytest

from apps.jobs import services
from apps.jobs.enums import JobStatus
from apps.jobs.models import Job, JobStatusEvent
from tests.factories import CompanyFactory, JobFactory


@pytest.fixture
def company():
    return CompanyFactory(slug="strikes-co")


def _unseen() -> set[object]:
    """IDs that exist in no company's job set (satisfies the empty-result guard)."""
    return {uuid.uuid4()}


class TestLadderCycles:
    def test_four_cycles_never_delete_the_row(self, company):
        job = JobFactory(company=company)

        result = services.apply_missing_strikes(company=company, seen_job_ids=_unseen())
        job.refresh_from_db()
        assert job.status == JobStatus.POSSIBLY_CLOSED
        assert job.missing_count == 1
        assert result["possibly_closed"] == 1

        services.apply_missing_strikes(company=company, seen_job_ids=_unseen())
        job.refresh_from_db()
        assert job.status == JobStatus.LIKELY_CLOSED
        assert job.missing_count == 2

        services.apply_missing_strikes(company=company, seen_job_ids=_unseen())
        job.refresh_from_db()
        assert job.status == JobStatus.CLOSED
        assert job.missing_count == 3
        assert job.closed_at is not None

        services.apply_missing_strikes(company=company, seen_job_ids=_unseen())
        job.refresh_from_db()
        assert job.status == JobStatus.CLOSED
        assert job.missing_count == 3
        assert Job.objects.filter(pk=job.pk).exists() is True

    def test_job_seen_again_resets(self, company):
        job = JobFactory(company=company)
        services.apply_missing_strikes(company=company, seen_job_ids={job.id})
        job.refresh_from_db()
        assert job.status == JobStatus.OPEN
        assert job.missing_count == 0

    def test_manual_status_jobs_skipped(self, company):
        manual = JobFactory(company=company, manual_status=True)
        services.apply_missing_strikes(company=company, seen_job_ids=_unseen())
        manual.refresh_from_db()
        assert manual.status == JobStatus.OPEN
        assert manual.missing_count == 0

    def test_other_companies_untouched(self, company):
        other = CompanyFactory(slug="other-co")
        other_job = JobFactory(company=other)
        company_job = JobFactory(company=company)
        services.apply_missing_strikes(company=company, seen_job_ids=_unseen())
        other_job.refresh_from_db()
        company_job.refresh_from_db()
        assert other_job.status == JobStatus.OPEN
        assert company_job.status == JobStatus.POSSIBLY_CLOSED

    def test_cap_branch_when_missing_count_already_maxed(self, company):
        job = JobFactory(company=company, likely_closed=True, missing_count=3)
        result = services.apply_missing_strikes(company=company, seen_job_ids=_unseen())
        job.refresh_from_db()
        assert job.status == JobStatus.CLOSED
        assert job.missing_count == 3
        assert result["closed"] == 1

    def test_no_event_when_status_already_at_ladder_position(self, company):
        job = JobFactory(company=company, status=JobStatus.LIKELY_CLOSED, missing_count=1)
        result = services.apply_missing_strikes(company=company, seen_job_ids=_unseen())
        job.refresh_from_db()
        assert job.status == JobStatus.LIKELY_CLOSED
        assert job.missing_count == 2
        assert JobStatusEvent.objects.filter(job=job).count() == 0
        assert result["likely_closed"] == 1

    def test_closed_jobs_excluded_from_scope(self, company):
        closed = JobFactory(company=company, closed=True)
        services.apply_missing_strikes(company=company, seen_job_ids=_unseen())
        closed.refresh_from_db()
        assert closed.missing_count == 0


class TestEmptyResultGuard:
    def test_guard_fires_when_no_jobs_seen(self, company):
        JobFactory(company=company)
        result = services.apply_missing_strikes(company=company, seen_job_ids=[])
        assert result == {"skipped": True, "reason": "empty_result_guard"}
        job = company.jobs.first()
        assert job.status == JobStatus.OPEN

    def test_guard_noop_when_no_open_jobs(self, company):
        result = services.apply_missing_strikes(company=company, seen_job_ids=[])
        assert result["possibly_closed"] == 0


class TestCountsAndEvents:
    def test_counts_dict(self, company):
        JobFactory(company=company)
        JobFactory(company=company)
        JobFactory(company=company, stale=True)
        JobFactory(company=company, likely_closed=True)
        result = services.apply_missing_strikes(company=company, seen_job_ids=_unseen())
        assert result == {"possibly_closed": 2, "likely_closed": 1, "closed": 1, "untouched": 0}

    def test_event_per_transition(self, company):
        job = JobFactory(company=company)
        services.apply_missing_strikes(company=company, seen_job_ids=_unseen())
        services.apply_missing_strikes(company=company, seen_job_ids=_unseen())
        events = list(JobStatusEvent.objects.filter(job=job).order_by("created_at"))
        assert len(events) == 2
        assert events[0].from_status == JobStatus.OPEN
        assert events[0].to_status == JobStatus.POSSIBLY_CLOSED
        assert events[0].trigger == "ladder"
        assert events[0].missing_count == 1
        assert events[1].from_status == JobStatus.POSSIBLY_CLOSED
        assert events[1].to_status == JobStatus.LIKELY_CLOSED

    def test_no_events_for_seen_jobs(self, company):
        seen = JobFactory(company=company)
        services.apply_missing_strikes(company=company, seen_job_ids={seen.id})
        assert JobStatusEvent.objects.filter(job=seen).count() == 0


class TestBulkPath:
    def test_300_jobs_stay_under_query_budget(self, company, django_assert_max_num_queries):
        for i in range(300):
            JobFactory(
                company=company,
                title=f"Bulk Job {i}",
                source_url=f"https://jobs.example/b/{i}",
                normalized_source_url=f"https://jobs.example/b/{i}",
                content_hash=f"h{i:040d}",
            )
        with django_assert_max_num_queries(15):
            result = services.apply_missing_strikes(company=company, seen_job_ids=_unseen())
        assert result["possibly_closed"] == 300
        assert Job.objects.filter(company=company, status=JobStatus.POSSIBLY_CLOSED).count() == 300
