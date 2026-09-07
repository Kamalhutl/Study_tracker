import json
from datetime import timedelta
from unittest.mock import MagicMock, patch

import pytest
from django.test import override_settings
from django.utils import timezone
from scrapling.parser import Selector

from apps.companies.enums import CareerSourceType, ScrapeHealth
from apps.companies.models import Company
from apps.jobs.models import Job
from apps.scraping.fetching import FetchError, FetchResult
from apps.scraping.models import ScrapeError, ScrapeRun
from apps.scraping.tasks import refresh_all_companies, scrape_company


@pytest.fixture
def company(db):
    from apps.accounts.models import User

    user = User.objects.create_user(email="testuser@example.com", password="testpass")
    return Company.objects.create(
        added_by=user,
        name="Test Company",
        domain="test.com",
        slug="test-company",
        career_url="https://test.com/careers",
        career_source_type=CareerSourceType.GREENHOUSE,
        ats_identifier="test-ats",
        is_verified=True,
        is_active=True,
        scrape_interval_minutes=300,
        scrape_health=ScrapeHealth.HEALTHY,
        consecutive_failures=0,
    )


@pytest.fixture
def greenhouse_fixture():
    with open("apps/scraping/tests/fixtures/ats/greenhouse_jobs.json") as f:
        return json.load(f)


@pytest.fixture
def mock_fetch_result(greenhouse_fixture):
    mock_selector = MagicMock()
    mock_selector.json.return_value = greenhouse_fixture

    return FetchResult(
        url="https://boards-api.greenhouse.io/v1/boards/test-ats/jobs?content=true",
        final_url="https://boards-api.greenhouse.io/v1/boards/test-ats/jobs?content=true",
        status_code=200,
        html="",
        selector=mock_selector,
        fetcher_used="http",
        elapsed_ms=100,
        from_cache=False,
        escalation_reason="",
    )


def test_scrape_company_greenhouse_creates_jobs(db, company, mock_fetch_result):
    with (
        patch("apps.scraping.tasks.fetch") as mock_fetch,
        patch("apps.scraping.tasks._get_parser_module") as mock_get_parser,
        patch("apps.scraping.tasks._build_fetch_url") as mock_build_url,
        patch("apps.scraping.tasks._use_fetch_with_escalation") as mock_use_escalation,
    ):
        mock_fetch.return_value = mock_fetch_result
        mock_parser_mod = MagicMock()
        mock_parser_mod.PARSER_NAME = "greenhouse"
        mock_parser_mod.PARSER_VERSION = 1
        mock_parser_mod.parse.return_value = [
            {
                "source_job_id": "4567890",
                "source_url": "https://boards.greenhouse.io/test-ats/jobs/4567890",
                "apply_url": "https://boards.greenhouse.io/test-ats/jobs/4567890",
                "title": "Senior Software Engineer",
                "location_raw": "Remote",
                "description": "We are looking for a Senior Software Engineer.",
                "description_html": "<div>We are looking for a Senior Software Engineer.</div>",
                "department": "Engineering",
                "job_type": "",
                "work_mode": "",
                "experience_level": "",
                "posted_at": timezone.now(),
                "extraction_confidence": 90,
            }
        ]
        mock_get_parser.return_value = mock_parser_mod
        mock_build_url.return_value = (
            "https://boards-api.greenhouse.io/v1/boards/test-ats/jobs?content=true"
        )
        mock_use_escalation.return_value = False

        result = scrape_company(str(company.id), triggered_by="manual")

        assert result["status"] == "success"
        assert result["jobs_found"] == 1
        assert result["jobs_added"] == 1

        # Check ScrapeRun was created
        scrape_runs = ScrapeRun.objects.filter(company=company)
        assert scrape_runs.exists()
        scrape_run = scrape_runs.first()
        assert scrape_run.status == "success"
        assert scrape_run.jobs_found == 1

        # Check Job was created
        jobs = Job.objects.filter(company=company)
        assert jobs.count() == 1


def test_scrape_company_fetch_error_marks_failed(db, company):
    with (
        patch("apps.scraping.tasks.fetch") as mock_fetch,
        patch("apps.scraping.tasks._get_parser_module") as mock_get_parser,
        patch("apps.scraping.tasks._build_fetch_url") as mock_build_url,
        patch("apps.scraping.tasks._use_fetch_with_escalation") as mock_use_escalation,
    ):
        # Provide a mock parser with the required attributes
        mock_parser_mod = MagicMock()
        mock_parser_mod.PARSER_NAME = "greenhouse"
        mock_parser_mod.PARSER_VERSION = 1
        mock_get_parser.return_value = mock_parser_mod

        mock_fetch.side_effect = FetchError("Connection timeout", url="https://test.com")
        mock_build_url.return_value = (
            "https://boards-api.greenhouse.io/v1/boards/test-ats/jobs?content=true"
        )
        mock_use_escalation.return_value = False

        result = scrape_company(str(company.id), triggered_by="manual")

        assert result["status"] == "failed"

        # Check ScrapeRun was created with failed status
        scrape_runs = ScrapeRun.objects.filter(company=company)
        assert scrape_runs.exists()
        scrape_run = scrape_runs.first()
        assert scrape_run.status == "failed"

        # Check ScrapeError was created
        errors = ScrapeError.objects.filter(company=company)
        assert errors.exists()

        # Check company consecutive_failures was incremented
        company.refresh_from_db()
        assert company.consecutive_failures == 1


def test_scrape_company_lock_skips_duplicate(db, company):
    from contextlib import contextmanager

    @contextmanager
    def mock_lock(key, timeout=3600, blocking=False):
        from core.locks import LockNotAcquired

        raise LockNotAcquired("Lock already held")

    with patch("apps.scraping.tasks.redis_lock", mock_lock):
        result = scrape_company(str(company.id), triggered_by="manual")

        assert result["skipped"] == "locked"


def test_scrape_company_applies_missing_strikes(db, company, mock_fetch_result):
    # First run: create 3 jobs
    with (
        patch("apps.scraping.tasks.fetch") as mock_fetch,
        patch("apps.scraping.tasks._get_parser_module") as mock_get_parser,
        patch("apps.scraping.tasks._build_fetch_url") as mock_build_url,
        patch("apps.scraping.tasks._use_fetch_with_escalation") as mock_use_escalation,
    ):
        mock_fetch.return_value = mock_fetch_result
        mock_parser_mod = MagicMock()
        mock_parser_mod.PARSER_NAME = "greenhouse"
        mock_parser_mod.PARSER_VERSION = 1
        mock_parser_mod.parse.return_value = [
            {
                "source_job_id": "job1",
                "source_url": "https://test.com/jobs/1",
                "apply_url": "https://test.com/jobs/1",
                "title": "Job 1",
                "location_raw": "Remote",
                "description": "Job 1 description",
                "description_html": "<div>Job 1 description</div>",
                "department": "",
                "job_type": "",
                "work_mode": "",
                "experience_level": "",
                "posted_at": timezone.now(),
                "extraction_confidence": 90,
            },
            {
                "source_job_id": "job2",
                "source_url": "https://test.com/jobs/2",
                "apply_url": "https://test.com/jobs/2",
                "title": "Job 2",
                "location_raw": "Remote",
                "description": "Job 2 description",
                "description_html": "<div>Job 2 description</div>",
                "department": "",
                "job_type": "",
                "work_mode": "",
                "experience_level": "",
                "posted_at": timezone.now(),
                "extraction_confidence": 90,
            },
            {
                "source_job_id": "job3",
                "source_url": "https://test.com/jobs/3",
                "apply_url": "https://test.com/jobs/3",
                "title": "Job 3",
                "location_raw": "Remote",
                "description": "Job 3 description",
                "description_html": "<div>Job 3 description</div>",
                "department": "",
                "job_type": "",
                "work_mode": "",
                "experience_level": "",
                "posted_at": timezone.now(),
                "extraction_confidence": 90,
            },
        ]
        mock_get_parser.return_value = mock_parser_mod
        mock_build_url.return_value = (
            "https://boards-api.greenhouse.io/v1/boards/test-ats/jobs?content=true"
        )
        mock_use_escalation.return_value = False

        result1 = scrape_company(str(company.id), triggered_by="manual")
        assert result1["jobs_found"] == 3

    # Second run: only 1 job remains
    with (
        patch("apps.scraping.tasks.fetch") as mock_fetch,
        patch("apps.scraping.tasks._get_parser_module") as mock_get_parser,
        patch("apps.scraping.tasks._build_fetch_url") as mock_build_url,
        patch("apps.scraping.tasks._use_fetch_with_escalation") as mock_use_escalation,
    ):
        mock_fetch.return_value = mock_fetch_result
        mock_parser_mod = MagicMock()
        mock_parser_mod.PARSER_NAME = "greenhouse"
        mock_parser_mod.PARSER_VERSION = 1
        mock_parser_mod.parse.return_value = [
            {
                "source_job_id": "4567890",
                "source_url": "https://boards.greenhouse.io/test-ats/jobs/4567890",
                "apply_url": "https://boards.greenhouse.io/test-ats/jobs/4567890",
                "title": "Senior Software Engineer",
                "location_raw": "Remote",
                "description": "We are looking for a Senior Software Engineer.",
                "description_html": "<div>We are looking for a Senior Software Engineer.</div>",
                "department": "Engineering",
                "job_type": "",
                "work_mode": "",
                "experience_level": "",
                "posted_at": timezone.now(),
                "extraction_confidence": 90,
            }
        ]
        mock_get_parser.return_value = mock_parser_mod
        mock_build_url.return_value = (
            "https://boards-api.greenhouse.io/v1/boards/test-ats/jobs?content=true"
        )
        mock_use_escalation.return_value = False

        result2 = scrape_company(str(company.id), triggered_by="manual")
        assert result2["jobs_found"] == 1

        # Check that the missing jobs have strikes applied
        jobs = Job.objects.filter(company=company)
        for job in jobs:
            if job.source_job_id in ["job2", "job3"]:
                assert job.missing_count == 1


def test_scrape_company_updates_next_scrape_at(db, company, mock_fetch_result):
    with (
        patch("apps.scraping.tasks.fetch") as mock_fetch,
        patch("apps.scraping.tasks._get_parser_module") as mock_get_parser,
        patch("apps.scraping.tasks._build_fetch_url") as mock_build_url,
        patch("apps.scraping.tasks._use_fetch_with_escalation") as mock_use_escalation,
    ):
        mock_fetch.return_value = mock_fetch_result
        mock_parser_mod = MagicMock()
        mock_parser_mod.PARSER_NAME = "greenhouse"
        mock_parser_mod.PARSER_VERSION = 1
        mock_parser_mod.parse.return_value = [
            {
                "source_job_id": "4567890",
                "source_url": "https://boards.greenhouse.io/test-ats/jobs/4567890",
                "apply_url": "https://boards.greenhouse.io/test-ats/jobs/4567890",
                "title": "Senior Software Engineer",
                "location_raw": "Remote",
                "description": "We are looking for a Senior Software Engineer.",
                "description_html": "<div>We are looking for a Senior Software Engineer.</div>",
                "department": "Engineering",
                "job_type": "",
                "work_mode": "",
                "experience_level": "",
                "posted_at": timezone.now(),
                "extraction_confidence": 90,
            }
        ]
        mock_get_parser.return_value = mock_parser_mod
        mock_build_url.return_value = (
            "https://boards-api.greenhouse.io/v1/boards/test-ats/jobs?content=true"
        )
        mock_use_escalation.return_value = False

        _result = scrape_company(str(company.id), triggered_by="manual")

        # Refresh company from DB
        company.refresh_from_db()

        assert company.last_scraped_at is not None
        assert company.next_scrape_at is not None
        assert company.next_scrape_at > company.last_scraped_at


def test_refresh_all_companies_dispatches_due(db):
    # Create companies - 2 due, 1 not due
    now = timezone.now()

    from apps.accounts.models import User

    user = User.objects.create_user(email="testuser2@example.com", password="testpass")
    _company1 = Company.objects.create(
        added_by=user,
        name="Company 1",
        domain="company1.com",
        slug="company-1",
        career_url="https://company1.com/careers",
        career_source_type=CareerSourceType.GREENHOUSE,
        ats_identifier="ats1",
        is_verified=True,
        is_active=True,
        scrape_interval_minutes=300,
        scrape_health=ScrapeHealth.HEALTHY,
        consecutive_failures=0,
        next_scrape_at=now - timedelta(hours=1),  # Due
    )

    _company2 = Company.objects.create(
        added_by=user,
        name="Company 2",
        domain="company2.com",
        slug="company-2",
        career_url="https://company2.com/careers",
        career_source_type=CareerSourceType.LEVER,
        ats_identifier="ats2",
        is_verified=True,
        is_active=True,
        scrape_interval_minutes=300,
        scrape_health=ScrapeHealth.HEALTHY,
        consecutive_failures=0,
        next_scrape_at=now - timedelta(hours=2),  # Due
    )

    _company3 = Company.objects.create(
        added_by=user,
        name="Company 3",
        domain="company3.com",
        slug="company-3",
        career_url="https://company3.com/careers",
        career_source_type=CareerSourceType.ASHBY,
        ats_identifier="ats3",
        is_verified=True,
        is_active=True,
        scrape_interval_minutes=300,
        scrape_health=ScrapeHealth.HEALTHY,
        consecutive_failures=0,
        next_scrape_at=now + timedelta(hours=1),  # Not due
    )

    with patch("apps.scraping.tasks.scrape_company.apply_async") as mock_apply_async:
        result = refresh_all_companies()

        assert result["dispatched"] == 2
        assert mock_apply_async.call_count == 2


def test_refresh_all_companies_locked_skips(db):
    from core.locks import LockNotAcquired

    with patch("apps.scraping.tasks.redis_lock") as mock_lock:
        mock_lock.side_effect = LockNotAcquired("Global lock held")

        result = refresh_all_companies()

        assert result["skipped"] == "cycle_locked"


# ==================== NEW TASK PATH TESTS ====================


def test_scrape_company_unknown_source_type(db, user):
    """Test that UNKNOWN source type with career_url uses fetch_with_escalation + static spider."""
    from apps.companies.enums import CareerSourceType

    company = Company.objects.create(
        added_by=user,
        name="Test Unknown",
        domain="test.com",
        career_url="https://test.com/careers",
        career_source_type=CareerSourceType.UNKNOWN,
        ats_identifier="",
        is_verified=True,
        is_active=True,
    )

    with patch("apps.scraping.tasks.fetch_with_escalation") as mock_fetch:
        mock_fetch.return_value = FetchResult(
            url="https://test.com/careers",
            final_url="https://test.com/careers",
            status_code=200,
            html="<html><body></body></html>",
            selector=Selector(content="<html><body></body></html>"),
            fetcher_used="http",
            elapsed_ms=100,
            from_cache=False,
            escalation_reason="",
        )

        result = scrape_company(company.id)

        # Should have called fetch_with_escalation for UNKNOWN source type
        mock_fetch.assert_called_once()
        assert "status" in result


def test_scrape_company_own_career_page(db, user):
    """Test that OWN_CAREER_PAGE source type uses static spider."""
    from apps.companies.enums import CareerSourceType

    company = Company.objects.create(
        added_by=user,
        name="Test Own Career",
        domain="test.com",
        career_url="https://test.com/careers",
        career_source_type=CareerSourceType.OWN_CAREER_PAGE,
        ats_identifier="",
        is_verified=True,
        is_active=True,
    )

    with patch("apps.scraping.tasks.fetch_with_escalation") as mock_fetch:
        mock_fetch.return_value = FetchResult(
            url="https://test.com/careers",
            final_url="https://test.com/careers",
            status_code=200,
            html="<html><body></body></html>",
            selector=Selector(content="<html><body></body></html>"),
            fetcher_used="http",
            elapsed_ms=100,
            from_cache=False,
            escalation_reason="",
        )

        result = scrape_company(company.id)

        # Should have called fetch_with_escalation for OWN_CAREER_PAGE
        mock_fetch.assert_called_once()
        assert "status" in result


def test_scrape_company_company_not_found(db):
    """Test that nonexistent company UUID returns not_found error."""
    from uuid import uuid4

    nonexistent_id = str(uuid4())
    result = scrape_company(nonexistent_id)

    assert result == {"error": "not_found"}


def test_refresh_dispatches_only_due_companies(db, user):
    """Test that refresh only dispatches companies that are due for scraping."""
    from django.utils import timezone as django_timezone

    from apps.companies.enums import CareerSourceType

    now = django_timezone.now()

    # Create 3 companies: 2 due, 1 not due
    company1 = Company.objects.create(
        added_by=user,
        name="Due Company 1",
        domain="due1.com",
        career_url="https://due1.com/careers",
        career_source_type=CareerSourceType.GREENHOUSE,
        ats_identifier="due1",
        slug="due1",
        is_verified=True,
        is_active=True,
        next_scrape_at=now - timedelta(hours=1),  # Due 1 hour ago
    )

    company2 = Company.objects.create(
        added_by=user,
        name="Due Company 2",
        domain="due2.com",
        career_url="https://due2.com/careers",
        career_source_type=CareerSourceType.GREENHOUSE,
        ats_identifier="due2",
        slug="due2",
        is_verified=True,
        is_active=True,
        next_scrape_at=now - timedelta(hours=2),  # Due 2 hours ago
    )

    company3 = Company.objects.create(
        added_by=user,
        name="Not Due Company",
        domain="notdue.com",
        career_url="https://notdue.com/careers",
        career_source_type=CareerSourceType.GREENHOUSE,
        ats_identifier="notdue",
        slug="notdue",
        is_verified=True,
        is_active=True,
        next_scrape_at=now + timedelta(hours=1),  # Due in 1 hour
    )

    with patch("apps.scraping.tasks.scrape_company.apply_async") as mock_apply_async:
        refresh_all_companies()

        # Should have been called twice (for the 2 due companies)
        assert mock_apply_async.call_count == 2

        # Check that the calls were for the due companies
        called_ids = [call[1]["args"][0] for call in mock_apply_async.call_args_list]
        assert str(company1.id) in called_ids
        assert str(company2.id) in called_ids
        assert str(company3.id) not in called_ids


def test_refresh_skips_failing_health(db, user):
    """Test that companies with FAILING health are excluded from dispatch."""
    from django.utils import timezone as django_timezone

    from apps.companies.enums import CareerSourceType, ScrapeHealth

    now = django_timezone.now()

    # Create a company with FAILING health
    failing_company = Company.objects.create(
        added_by=user,
        name="Failing Company",
        domain="failing.com",
        career_url="https://failing.com/careers",
        career_source_type=CareerSourceType.GREENHOUSE,
        ats_identifier="failing",
        slug="failing",
        is_verified=True,
        is_active=True,
        next_scrape_at=now - timedelta(hours=1),  # Due
        scrape_health=ScrapeHealth.FAILING,
    )

    # Create a healthy company
    healthy_company = Company.objects.create(
        added_by=user,
        name="Healthy Company",
        domain="healthy.com",
        career_url="https://healthy.com/careers",
        career_source_type=CareerSourceType.GREENHOUSE,
        ats_identifier="healthy",
        slug="healthy",
        is_verified=True,
        is_active=True,
        next_scrape_at=now - timedelta(hours=1),  # Due
        scrape_health=ScrapeHealth.HEALTHY,
    )

    with patch("apps.scraping.tasks.scrape_company.apply_async") as mock_apply_async:
        refresh_all_companies()

        # Should have been called once (only for the healthy company)
        assert mock_apply_async.call_count == 1

        # Check that the call was for the healthy company, not the failing one
        called_ids = [call[1]["args"][0] for call in mock_apply_async.call_args_list]
        assert str(healthy_company.id) in called_ids
        assert str(failing_company.id) not in called_ids


def test_scrape_company_partial_on_zero_jobs(db, user):
    """Test that zero jobs found results in partial status."""
    from scrapling.parser import Selector

    from apps.companies.enums import CareerSourceType
    from apps.scraping.fetching import FetchResult

    company = Company.objects.create(
        added_by=user,
        name="Zero Jobs Company",
        domain="zerojobs.com",
        career_url="https://zerojobs.com/careers",
        career_source_type=CareerSourceType.OWN_CAREER_PAGE,
        ats_identifier="",
        is_verified=True,
        is_active=True,
    )

    with patch("apps.scraping.tasks.fetch_with_escalation") as mock_fetch:
        # Return empty HTML (no jobs found)
        mock_fetch.return_value = FetchResult(
            url="https://zerojobs.com/careers",
            final_url="https://zerojobs.com/careers",
            status_code=200,
            html="<html><body></body></html>",
            selector=Selector(content="<html><body></body></html>"),
            fetcher_used="http",
            elapsed_ms=100,
            from_cache=False,
            escalation_reason="",
        )

        result = scrape_company(company.id)

        # Should return partial status when no jobs found
        assert result.get("status") == "partial"
        assert result.get("jobs_found") == 0


def test_scrape_company_consecutive_failures_incremented(db, user):
    """Test that consecutive failures are incremented on FetchError."""
    from apps.companies.enums import CareerSourceType
    from apps.scraping.fetching import FetchError

    company = Company.objects.create(
        added_by=user,
        name="Failure Company",
        domain="failure.com",
        career_url="https://failure.com/careers",
        career_source_type=CareerSourceType.GREENHOUSE,
        ats_identifier="failure",
        slug="failure",
        is_verified=True,
        is_active=True,
        consecutive_failures=1,
    )

    with patch("apps.scraping.tasks.fetch") as mock_fetch:
        mock_fetch.side_effect = FetchError("Test error")

        scrape_company(company.id)

        # Reload company to get updated values
        company.refresh_from_db()

        # Consecutive failures should be incremented from 1 to 2
        assert company.consecutive_failures == 2


def test_scrape_company_health_set_to_failing_at_5(db, user):
    """Test that health is set to FAILING when consecutive failures reach 5."""
    from apps.companies.enums import CareerSourceType, ScrapeHealth
    from apps.scraping.fetching import FetchError

    company = Company.objects.create(
        added_by=user,
        name="Health Test Company",
        domain="healthtest.com",
        career_url="https://healthtest.com/careers",
        career_source_type=CareerSourceType.GREENHOUSE,
        ats_identifier="healthtest",
        slug="healthtest",
        is_verified=True,
        is_active=True,
        consecutive_failures=4,  # One away from threshold
        scrape_health=ScrapeHealth.HEALTHY,
    )

    with patch("apps.scraping.tasks.fetch") as mock_fetch:
        mock_fetch.side_effect = FetchError("Test error")

        scrape_company(company.id)

        # Reload company to get updated values
        company.refresh_from_db()

        # Consecutive failures should reach 5 and health should be FAILING
        assert company.consecutive_failures == 5
        assert company.scrape_health == ScrapeHealth.FAILING


# ==================== CONDITIONAL GET CORRECTIONS TESTS ====================


def test_not_modified_calls_record_scrape_outcome(db, user):
    """Test that record_scrape_outcome is called on the not_modified path."""
    import hashlib

    from apps.companies.enums import CareerSourceType, ScrapeHealth
    from apps.scraping.fetching import FetchMode, FetchResult
    from apps.scraping.models import SourceFetchState

    company = Company.objects.create(
        added_by=user,
        name="Not Modified Co",
        domain="notmod.com",
        career_url="https://notmod.com/careers",
        career_source_type=CareerSourceType.GREENHOUSE,
        ats_identifier="notmod",
        slug="notmod",
        is_verified=True,
        is_active=True,
        last_jobs_seen=5,
        scrape_health=ScrapeHealth.DEGRADED,
        consecutive_failures=2,
        total_scrapes=0,
    )

    url = "https://notmod.com/careers"
    url_hash = hashlib.sha256(url.encode()).hexdigest()
    SourceFetchState.objects.create(
        url_hash=url_hash,
        url=url,
        etag="abc",
        last_modified="",
        body_hash="",
        last_fetched_at=timezone.now(),
        hit_count=3,
        miss_count=0,
    )

    # Create a fetch result with not_modified=True
    not_modified_result = FetchResult(
        url=url,
        final_url=url,
        status_code=304,
        html="",
        selector=None,
        fetcher_used=FetchMode.HTTP,
        elapsed_ms=100,
        from_cache=False,
        escalation_reason="",
        not_modified=True,
        xhr_payloads=[],
    )

    with (
        patch("apps.scraping.tasks.fetch") as mock_fetch,
        patch("apps.scraping.tasks.redis_lock") as mock_lock,
    ):
        mock_lock.return_value.__enter__ = MagicMock()
        mock_lock.return_value.__exit__ = MagicMock()
        mock_fetch.return_value = not_modified_result

        with patch("apps.scraping.tasks.record_scrape_outcome") as mock_record:

            def record_side_effect(company, success, jobs_seen, now):
                company.total_scrapes += 1
                company.last_scraped_at = now
                company.consecutive_failures = 0
                company.scrape_health = ScrapeHealth.HEALTHY
                company.next_scrape_at = now + timedelta(minutes=company.scrape_interval_minutes)
                company.save()

            mock_record.side_effect = record_side_effect

            scrape_company(company.id)

            mock_record.assert_called_once()

            call_args = mock_record.call_args[1]
            assert call_args["company"] == company
            assert call_args["success"] is True
            assert call_args["jobs_seen"] == 5
            assert call_args["now"] is not None

            company.refresh_from_db()
            assert company.scrape_health == ScrapeHealth.HEALTHY
            assert company.consecutive_failures == 0
            assert company.total_scrapes == 1
            assert company.next_scrape_at > company.last_scraped_at


def test_not_modified_advances_next_scrape_at(db, user):
    """Test that next_scrape_at moves forward after a 304."""

    from apps.companies.enums import CareerSourceType, ScrapeHealth
    from apps.scraping.fetching import FetchMode, FetchResult

    company = Company.objects.create(
        added_by=user,
        name="Next Scrape Co",
        domain="nextscrape.com",
        career_url="https://nextscrape.com/careers",
        career_source_type=CareerSourceType.GREENHOUSE,
        ats_identifier="nextscrape",
        slug="nextscrape",
        is_verified=True,
        is_active=True,
        last_jobs_seen=5,
        scrape_health=ScrapeHealth.HEALTHY,
        consecutive_failures=0,
        total_scrapes=0,
        last_scraped_at=timezone.now() - timedelta(hours=1),
        next_scrape_at=timezone.now() - timedelta(minutes=30),
    )

    not_modified_result = FetchResult(
        url="https://nextscrape.com/careers",
        final_url="https://nextscrape.com/careers",
        status_code=304,
        html="",
        selector=None,
        fetcher_used=FetchMode.HTTP,
        elapsed_ms=100,
        from_cache=False,
        escalation_reason="",
        not_modified=True,
        xhr_payloads=[],
    )

    with patch("apps.scraping.tasks.fetch") as mock_fetch:
        mock_fetch.return_value = not_modified_result

        with patch("apps.scraping.tasks.record_scrape_outcome") as mock_record:
            # Simulate record_scrape_outcome updating the company
            def record_side_effect(company, success, jobs_seen, now):
                company.total_scrapes += 1
                company.last_scraped_at = now
                company.consecutive_failures = 0
                company.scrape_health = ScrapeHealth.HEALTHY
                company.next_scrape_at = now + timedelta(minutes=company.scrape_interval_minutes)
                company.save()

            mock_record.side_effect = record_side_effect

            old_next = company.next_scrape_at
            scrape_company(company.id)

            company.refresh_from_db()
            assert company.next_scrape_at > old_next


def test_not_modified_recovers_health(db, user):
    """Test that company with consecutive_failures=2 and DEGRADED becomes HEALTHY after 304."""

    from apps.companies.enums import CareerSourceType, ScrapeHealth
    from apps.scraping.fetching import FetchMode, FetchResult

    company = Company.objects.create(
        added_by=user,
        name="Recover Co",
        domain="recover.com",
        career_url="https://recover.com/careers",
        career_source_type=CareerSourceType.GREENHOUSE,
        ats_identifier="recover",
        slug="recover",
        is_verified=True,
        is_active=True,
        last_jobs_seen=5,
        scrape_health=ScrapeHealth.DEGRADED,
        consecutive_failures=2,
        total_scrapes=0,
    )

    not_modified_result = FetchResult(
        url="https://recover.com/careers",
        final_url="https://recover.com/careers",
        status_code=304,
        html="",
        selector=None,
        fetcher_used=FetchMode.HTTP,
        elapsed_ms=100,
        from_cache=False,
        escalation_reason="",
        not_modified=True,
        xhr_payloads=[],
    )

    with (
        patch("apps.scraping.tasks.fetch") as mock_fetch,
        patch("apps.scraping.tasks.redis_lock") as mock_lock,
    ):
        mock_lock.return_value.__enter__ = MagicMock()
        mock_lock.return_value.__exit__ = MagicMock()
        mock_fetch.return_value = not_modified_result

        with patch("apps.scraping.tasks.record_scrape_outcome") as mock_record:

            def record_side_effect(company, success, jobs_seen, now):
                company.total_scrapes += 1
                company.last_scraped_at = now
                company.consecutive_failures = 0
                company.scrape_health = ScrapeHealth.HEALTHY
                company.next_scrape_at = now + timedelta(minutes=company.scrape_interval_minutes)
                company.save()

            mock_record.side_effect = record_side_effect

            scrape_company(company.id)

            company.refresh_from_db()
            assert company.consecutive_failures == 0
            assert company.scrape_health == ScrapeHealth.HEALTHY


def test_not_modified_increments_total_scrapes(db, user):
    """Test that total_scrapes is incremented after a 304."""

    from apps.companies.enums import CareerSourceType
    from apps.scraping.fetching import FetchMode, FetchResult

    company = Company.objects.create(
        added_by=user,
        name="Total Scrapes Co",
        domain="totalscrapes.com",
        career_url="https://totalscrapes.com/careers",
        career_source_type=CareerSourceType.GREENHOUSE,
        ats_identifier="totalscrapes",
        slug="totalscrapes",
        is_verified=True,
        is_active=True,
        last_jobs_seen=5,
        scrape_health=ScrapeHealth.HEALTHY,
        consecutive_failures=0,
        total_scrapes=0,
    )

    not_modified_result = FetchResult(
        url="https://totalscrapes.com/careers",
        final_url="https://totalscrapes.com/careers",
        status_code=304,
        html="",
        selector=None,
        fetcher_used=FetchMode.HTTP,
        elapsed_ms=100,
        from_cache=False,
        escalation_reason="",
        not_modified=True,
        xhr_payloads=[],
    )

    with patch("apps.scraping.tasks.fetch") as mock_fetch:
        mock_fetch.return_value = not_modified_result

        with patch("apps.scraping.tasks.record_scrape_outcome") as mock_record:
            # Simulate record_scrape_outcome incrementing total_scrapes
            def record_side_effect(company, success, jobs_seen, now):
                company.total_scrapes += 1
                company.last_scraped_at = now
                company.consecutive_failures = 0
                company.scrape_health = ScrapeHealth.HEALTHY
                company.next_scrape_at = now + timedelta(minutes=company.scrape_interval_minutes)
                company.save()

            mock_record.side_effect = record_side_effect

            scrape_company(company.id)

            company.refresh_from_db()
            assert company.total_scrapes == 1


def test_clear_fetch_state_keeps_row(db, user):
    """Test that clearing validators updates fields to blank but keeps the row and hit_count."""
    import hashlib

    from apps.scraping.models import SourceFetchState
    from apps.scraping.tasks import _clear_fetch_state

    url = "https://testclear.com/careers"
    url_hash = hashlib.sha256(url.encode()).hexdigest()

    # Create a state row with validators and hit_count
    state = SourceFetchState.objects.create(
        url_hash=url_hash,
        url=url,
        etag="abc123",
        last_modified="Mon, 01 Jan 2024 00:00:00 GMT",
        body_hash="def456",
        last_fetched_at=timezone.now(),
        hit_count=42,
        miss_count=7,
    )

    # Call _clear_fetch_state (which now updates blanks)
    _clear_fetch_state(url)

    # Reload state from DB
    state.refresh_from_db()

    # Row should still exist
    assert SourceFetchState.objects.filter(url_hash=url_hash).exists()

    # Validators should be blank
    assert state.etag == ""
    assert state.last_modified == ""
    assert state.body_hash == ""

    # hit_count and miss_count should be preserved
    assert state.hit_count == 42
    assert state.miss_count == 7


@override_settings(FETCH_ALLOW_DYNAMIC=True)
def test_browser_escalation_clears_validators(db, user):
    """Test that browser-escalated fetch clears stored validators and writes no etag/body_hash."""
    import hashlib

    from scrapling.parser import Selector

    from apps.companies.enums import CareerSourceType
    from apps.scraping.fetching import FetchMode, FetchResult, fetch_with_escalation
    from apps.scraping.models import SourceFetchState

    company = Company.objects.create(
        added_by=user,
        name="Escalation Co",
        domain="escalation.com",
        career_url="https://escalation.com/careers",
        career_source_type=CareerSourceType.OWN_CAREER_PAGE,
        ats_identifier="",
        slug="escalation",
        is_verified=True,
        is_active=True,
    )

    url = "https://escalation.com/careers"
    url_hash = hashlib.sha256(url.encode()).hexdigest()

    # Create a state row with validators
    SourceFetchState.objects.create(
        url_hash=url_hash,
        url=url,
        etag="existing_etag",
        last_modified="Mon, 01 Jan 2024 00:00:00 GMT",
        body_hash="existing_hash",
        last_fetched_at=timezone.now(),
        hit_count=10,
        miss_count=0,
    )

    # Mock fetch to return a sparse HTTP result that triggers escalation
    # and then a dynamic fetch result
    with patch("apps.scraping.fetching.fetch") as mock_fetch:
        # First call (HTTP) - sparse page to trigger escalation
        http_result = FetchResult(
            url=url,
            final_url=url,
            status_code=200,
            html="<html><body>test</body></html>",
            selector=Selector(content="<html><body>test</body></html>"),
            fetcher_used=FetchMode.HTTP,
            elapsed_ms=50,
            from_cache=False,
            escalation_reason="",
        )

        # Second call (DYNAMIC) - the escalated browser fetch
        dynamic_result = FetchResult(
            url=url,
            final_url=url,
            status_code=200,
            html="<html><body><h1>Rendered</h1></body></html>",
            selector=Selector(content="<html><body><h1>Rendered</h1></body></html>"),
            fetcher_used=FetchMode.DYNAMIC,
            elapsed_ms=200,
            from_cache=False,
            escalation_reason="",
        )

        mock_fetch.side_effect = [http_result, dynamic_result]

        result = fetch_with_escalation(url, company=company)

        assert result.fetcher_used == FetchMode.DYNAMIC

        state = SourceFetchState.objects.get(url_hash=url_hash)
        assert state.etag == ""
        assert state.last_modified == ""
        assert state.body_hash == ""
        assert state.hit_count == 10
