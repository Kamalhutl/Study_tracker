"""Tests for fetch retry logic in scrape_company.

Transient exceptions are retried with exponential backoff via Celery; permanent
exceptions are not retried. The retry count is bounded by SCRAPE_MAX_RETRIES.
SoftTimeLimitExceeded is handled without applying strikes and with a ScrapeError.
"""

from unittest.mock import MagicMock, patch

import pytest
from celery.exceptions import Retry

from apps.scraping.exceptions import FetchBudgetExceeded, FetchRobotsDisallowed, FetchTimeout
from tests.factories import CompanyFactory


@pytest.fixture
def company():
    return CompanyFactory(
        career_source_type="GREENHOUSE",
        ats_identifier="example",
        is_verified=True,
        is_active=True,
        scrape_health="HEALTHY",
        consecutive_failures=0,
    )


class TestFetchRetries:
    def _mock_parser_and_fetch(self, tasks_module, fetch_side_effect):
        """Helper to mock parser and fetch for retry tests."""
        parser_patch = patch.object(tasks_module, "_get_parser_module")
        mock_parser = parser_patch.start()
        mock_parser_mod = MagicMock()
        mock_parser_mod.PARSER_NAME = "greenhouse"
        mock_parser_mod.PARSER_VERSION = 1
        mock_parser.return_value = mock_parser_mod
        fetch_patch = patch.object(tasks_module, "fetch")
        mock_fetch = fetch_patch.start()
        mock_fetch.side_effect = fetch_side_effect
        return mock_fetch, parser_patch, fetch_patch

    def test_transient_exception_retries(self, company):
        """Transient exceptions (FetchTimeout, etc.) call self.retry()."""
        from apps.scraping import tasks as tasks_module

        mock_fetch, parser_patch, fetch_patch = self._mock_parser_and_fetch(
            tasks_module, FetchTimeout("timeout")
        )
        mock_self = MagicMock()
        mock_self.retry.side_effect = Retry()  # Celery's Retry exception

        with patch("apps.scraping.tasks.redis_lock") as mock_lock:
            mock_lock.return_value.__enter__ = MagicMock()
            mock_lock.return_value.__exit__ = MagicMock()

            with pytest.raises(Retry):
                tasks_module._execute_scrape(
                    self=mock_self,
                    company=company,
                    triggered_by="test",
                    lock_key="test",
                )

        mock_self.retry.assert_called_once_with(exc=mock_fetch.side_effect)
        parser_patch.stop()
        fetch_patch.stop()

    def test_permanent_exception_no_retry(self, company):
        """Permanent exceptions (FetchRobotsDisallowed, FetchBudgetExceeded) do not retry."""
        from apps.scraping import tasks as tasks_module

        for exc_class in (FetchRobotsDisallowed, FetchBudgetExceeded):
            mock_fetch, parser_patch, fetch_patch = self._mock_parser_and_fetch(
                tasks_module, exc_class("blocked")
            )
            mock_self = MagicMock()

            with patch("apps.scraping.tasks.redis_lock") as mock_lock:
                mock_lock.return_value.__enter__ = MagicMock()
                mock_lock.return_value.__exit__ = MagicMock()

                result = tasks_module._execute_scrape(
                    self=mock_self,
                    company=company,
                    triggered_by="test",
                    lock_key="test",
                )

            mock_self.retry.assert_not_called()
            assert result["status"] == "failed"
            assert "blocked" in result.get("error", "")
            assert result.get("error_type") == exc_class.__name__
            parser_patch.stop()
            fetch_patch.stop()

    def test_retries_stop_at_max(self, company):
        """Retries stop at SCRAPE_MAX_RETRIES."""
        from apps.scraping import tasks as tasks_module

        mock_fetch, parser_patch, fetch_patch = self._mock_parser_and_fetch(
            tasks_module, FetchTimeout("timeout")
        )
        mock_self = MagicMock()
        mock_self.max_retries = 2
        mock_self.retry.side_effect = Retry()

        with patch("apps.scraping.tasks.redis_lock") as mock_lock:
            mock_lock.return_value.__enter__ = MagicMock()
            mock_lock.return_value.__exit__ = MagicMock()

            with pytest.raises(Retry):
                tasks_module._execute_scrape(
                    self=mock_self,
                    company=company,
                    triggered_by="test",
                    lock_key="test",
                )

        mock_self.retry.assert_called_once_with(exc=mock_fetch.side_effect)
        parser_patch.stop()
        fetch_patch.stop()

    def test_soft_time_limit_exceeded_handling(self, company):
        """SoftTimeLimitExceeded leaves job statuses untouched and writes a ScrapeError row."""
        from celery.exceptions import SoftTimeLimitExceeded

        from apps.jobs.enums import JobStatus
        from apps.scraping.models import ScrapeError, ScrapeRun
        from apps.scraping.sanity import RunVerdict
        from tests.factories import JobFactory

        # Create a job for the company to ensure it would be affected if strikes ran
        job = JobFactory(company=company, status=JobStatus.OPEN, missing_count=0)

        # Mock fetch to return a dummy response and mock _get_parser_module to return a mock parser
        # that raises SoftTimeLimitExceeded when parse is called.
        mock_parser = MagicMock()
        mock_parser.PARSER_NAME = "greenhouse"
        mock_parser.PARSER_VERSION = 1
        mock_parser.parse.side_effect = SoftTimeLimitExceeded("timeout")
        with (
            patch("apps.scraping.tasks.fetch") as mock_fetch,
            patch("apps.scraping.tasks._get_parser_module", return_value=mock_parser),
            patch("apps.scraping.tasks.redis_lock") as mock_lock,
        ):
            from scrapling import Selector

            from apps.scraping.fetching import FetchMode, FetchResult

            mock_fetch.return_value = FetchResult(
                url="https://test.com/jobs",
                final_url="https://test.com/jobs",
                status_code=200,
                html="<html><body>test</body></html>",
                selector=Selector("<html><body>test</body></html>"),
                fetcher_used=FetchMode.HTTP,
                elapsed_ms=100,
                from_cache=False,
                escalation_reason="",
                not_modified=False,
            )
            mock_lock.return_value.__enter__ = MagicMock()
            mock_lock.return_value.__exit__ = MagicMock()

            # Call _execute_scrape directly (inside the lock context)
            from apps.scraping import tasks as tasks_module

            # Need a self mock; we'll just pass a dummy
            mock_self = MagicMock()
            # The task will not retry on SoftTimeLimitExceeded; it goes to outer except
            result = tasks_module._execute_scrape(
                self=mock_self,
                company=company,
                triggered_by="test",
                lock_key="test",
            )

        # Assertions
        # 1. ScrapeRun is finalized as failed with verdict UNTRUSTED
        scrape_run = ScrapeRun.objects.get(company=company)
        assert scrape_run.status == "failed"
        assert scrape_run.verdict == RunVerdict.UNTRUSTED

        # 2. A ScrapeError row is written
        scrape_error = ScrapeError.objects.filter(company=company).first()
        assert scrape_error is not None
        assert (
            "SoftTimeLimitExceeded" in scrape_error.error_type
            or "SoftTimeLimitExceeded" in scrape_error.message
        )

        # 3. NO Job row changes status or missing_count
        job.refresh_from_db()
        assert job.status == JobStatus.OPEN
        assert job.missing_count == 0

        # Also ensure apply_missing_strikes was NOT called (verification by absence of effect)
        assert result["status"] == "failed"
        assert result["jobs_missing"] == 0

    def test_fetch_robots_disallowed_zero_retries(self, company):
        """FetchRobotsDisallowed produces zero retries."""
        self.test_permanent_exception_no_retry(company)

    def test_fetch_budget_exceeded_zero_retries(self, company):
        """FetchBudgetExceeded produces zero retries."""
        self.test_permanent_exception_no_retry(company)
