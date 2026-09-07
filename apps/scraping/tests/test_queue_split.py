from datetime import timedelta
from unittest.mock import MagicMock, patch

import pytest
from django.test import override_settings
from django.utils import timezone

from apps.companies.enums import CareerSourceType, ScrapeHealth
from apps.companies.models import Company
from apps.scraping.fetching import FetchMode, FetchResult
from apps.scraping.models import ScrapeRun
from apps.scraping.sanity import RunVerdict
from apps.scraping.tasks import (
    compute_adaptive_interval,
    refresh_all_companies,
    scrape_company,
)
from tests.factories import UserFactory


@pytest.fixture
def user(db):
    return UserFactory()


@pytest.fixture
def company(db, user):
    return Company.objects.create(
        name="Queue Split Co",
        domain="queuesplit.com",
        slug="queue-split-co",
        career_url="https://queuesplit.com/careers",
        career_source_type=CareerSourceType.OWN_CAREER_PAGE,
        ats_identifier="",
        is_verified=True,
        is_active=True,
        scrape_health=ScrapeHealth.HEALTHY,
        consecutive_failures=0,
        scrape_interval_minutes=60,
        added_by=user,
    )


class TestDeferredRun:
    @override_settings(SCRAPE_DEFER_DELAY_MINUTES=30)
    def test_deferred_run_no_side_effects(self, db, company):
        http_result = FetchResult(
            url="https://queuesplit.com/careers",
            final_url="https://queuesplit.com/careers",
            status_code=200,
            html="<html><body>test</body></html>",
            selector=MagicMock(),
            fetcher_used=FetchMode.HTTP,
            elapsed_ms=50,
            from_cache=False,
            escalation_reason="only 2 anchors",
            not_modified=False,
        )
        with (
            patch("apps.scraping.tasks.fetch_with_escalation", return_value=http_result),
            patch("apps.scraping.tasks.scrape_company.apply_async") as mock_apply,
            patch("apps.scraping.tasks.record_scrape_outcome") as mock_record,
            patch("apps.scraping.tasks.apply_missing_strikes") as mock_strikes,
            patch("apps.scraping.tasks.redis_lock") as mock_lock,
        ):
            mock_lock.return_value.__enter__ = MagicMock()
            mock_lock.return_value.__exit__ = MagicMock()
            result = scrape_company(str(company.id), triggered_by="schedule")

        assert result["status"] == "deferred"
        mock_record.assert_not_called()
        mock_strikes.assert_not_called()
        mock_apply.assert_called_once()
        call_kwargs = mock_apply.call_args
        assert call_kwargs[1]["queue"] == "scraping_browser"
        assert call_kwargs[1]["kwargs"]["force_browser"] is True

        company.refresh_from_db()
        run = ScrapeRun.objects.filter(company=company).order_by("-started_at").first()
        assert run.notes == "deferred_to_browser"
        assert run.verdict == RunVerdict.TRUSTED

    @override_settings(SCRAPE_DEFER_DELAY_MINUTES=30)
    def test_deferred_run_sets_next_scrape_at(self, db, company):
        http_result = FetchResult(
            url="https://queuesplit.com/careers",
            final_url="https://queuesplit.com/careers",
            status_code=200,
            html="<html><body>test</body></html>",
            selector=MagicMock(),
            fetcher_used=FetchMode.HTTP,
            elapsed_ms=50,
            from_cache=False,
            escalation_reason="only 2 anchors",
            not_modified=False,
        )
        before = timezone.now()
        with (
            patch("apps.scraping.tasks.fetch_with_escalation", return_value=http_result),
            patch("apps.scraping.tasks.scrape_company.apply_async"),
            patch("apps.scraping.tasks.redis_lock") as mock_lock,
        ):
            mock_lock.return_value.__enter__ = MagicMock()
            mock_lock.return_value.__exit__ = MagicMock()
            scrape_company(str(company.id), triggered_by="schedule")

        company.refresh_from_db()
        expected_min = before + timedelta(minutes=29)
        expected_max = before + timedelta(minutes=31)
        assert expected_min <= company.next_scrape_at <= expected_max


class TestForceBrowserNoRequeue:
    @override_settings(FETCH_ALLOW_DYNAMIC=True)
    def test_force_browser_never_requeues(self, db, company):
        dynamic_result = FetchResult(
            url="https://queuesplit.com/careers",
            final_url="https://queuesplit.com/careers",
            status_code=200,
            html="<html><body>rendered</body></html>",
            selector=MagicMock(),
            fetcher_used=FetchMode.DYNAMIC,
            elapsed_ms=200,
            from_cache=False,
            escalation_reason="only 2 anchors",
            not_modified=False,
        )
        with (
            patch("apps.scraping.tasks.fetch", return_value=dynamic_result),
            patch("apps.scraping.tasks._get_parser_module") as mock_parser,
            patch("apps.scraping.tasks.scrape_company.apply_async") as mock_apply,
            patch("apps.scraping.tasks.redis_lock") as mock_lock,
        ):
            mock_lock.return_value.__enter__ = MagicMock()
            mock_lock.return_value.__exit__ = MagicMock()
            mock_parser_mod = MagicMock()
            mock_parser_mod.PARSER_NAME = "static"
            mock_parser_mod.PARSER_VERSION = 1
            mock_parser_mod.parse.return_value = []
            mock_parser.return_value = mock_parser_mod

            scrape_company(str(company.id), triggered_by="schedule", force_browser=True)

        mock_apply.assert_not_called()


class TestQueueRouting:
    def test_escalation_dispatches_to_browser_queue(self, db, company):
        http_result = FetchResult(
            url="https://queuesplit.com/careers",
            final_url="https://queuesplit.com/careers",
            status_code=200,
            html="<html><body>test</body></html>",
            selector=MagicMock(),
            fetcher_used=FetchMode.HTTP,
            elapsed_ms=50,
            from_cache=False,
            escalation_reason="only 2 anchors",
            not_modified=False,
        )
        with (
            patch("apps.scraping.tasks.fetch_with_escalation", return_value=http_result),
            patch("apps.scraping.tasks.scrape_company.apply_async") as mock_apply,
            patch("apps.scraping.tasks.redis_lock") as mock_lock,
        ):
            mock_lock.return_value.__enter__ = MagicMock()
            mock_lock.return_value.__exit__ = MagicMock()
            scrape_company(str(company.id), triggered_by="schedule")

        mock_apply.assert_called_once()
        assert mock_apply.call_args[1]["queue"] == "scraping_browser"

    def test_scraping_queue_path_no_browser_fetcher(self, db, company):
        http_result = FetchResult(
            url="https://queuesplit.com/careers",
            final_url="https://queuesplit.com/careers",
            status_code=200,
            html="<html><body>enough text and links for no escalation</body></html>" * 100,
            selector=MagicMock(),
            fetcher_used=FetchMode.HTTP,
            elapsed_ms=50,
            from_cache=False,
            escalation_reason="",
            not_modified=False,
        )
        with (
            patch("apps.scraping.tasks.fetch_with_escalation", return_value=http_result),
            patch("apps.scraping.tasks._get_parser_module") as mock_parser,
            patch("apps.scraping.tasks.scrape_company.apply_async") as mock_apply,
            patch("apps.scraping.tasks.redis_lock") as mock_lock,
        ):
            mock_lock.return_value.__enter__ = MagicMock()
            mock_lock.return_value.__exit__ = MagicMock()
            mock_parser_mod = MagicMock()
            mock_parser_mod.PARSER_NAME = "static"
            mock_parser_mod.PARSER_VERSION = 1
            mock_parser_mod.parse.return_value = []
            mock_parser.return_value = mock_parser_mod

            scrape_company(str(company.id), triggered_by="schedule")

        mock_apply.assert_not_called()


class TestAdaptiveInterval:
    def test_doubles_after_three_quiet_trusted_runs(self):
        recent = [(0, 0), (0, 0), (0, 0)]
        result = compute_adaptive_interval(current_minutes=60, recent=recent)
        assert result == 120

    def test_caps_at_max(self):
        recent = [(0, 0), (0, 0), (0, 0)]
        result = compute_adaptive_interval(current_minutes=1000, recent=recent)
        assert result == 1440

    def test_halves_on_churn(self):
        recent = [(5, 0), (0, 0), (0, 0)]
        result = compute_adaptive_interval(current_minutes=120, recent=recent)
        assert result == 60

    def test_floors_at_min(self):
        recent = [(5, 0), (0, 0), (0, 0)]
        result = compute_adaptive_interval(current_minutes=30, recent=recent)
        assert result == 30

    def test_unchanged_with_mixed_history(self):
        recent = [(0, 0), (1, 0), (0, 0)]
        result = compute_adaptive_interval(current_minutes=60, recent=recent)
        assert result == 60

    def test_insufficient_recent_returns_current(self):
        result = compute_adaptive_interval(current_minutes=60, recent=[(0, 0)])
        assert result == 60

    def test_quarantined_excluded_from_window(self, db, company):
        now = timezone.now()
        for i in range(3):
            ScrapeRun.objects.create(
                company=company,
                status="success",
                verdict=RunVerdict.TRUSTED,
                jobs_added=0,
                jobs_missing=0,
                finished_at=now - timedelta(hours=i + 1),
            )
        ScrapeRun.objects.create(
            company=company,
            status="failed",
            verdict=RunVerdict.QUARANTINED,
            jobs_added=0,
            jobs_missing=0,
            finished_at=now,
        )
        with patch("apps.companies.services.update_scrape_interval") as mock_update:
            from apps.scraping.tasks import _maybe_apply_adaptive_interval

            run = ScrapeRun.objects.filter(company=company, verdict=RunVerdict.TRUSTED).first()
            _maybe_apply_adaptive_interval(company=company, scrape_run=run)

        mock_update.assert_called_once()
        assert mock_update.call_args[1]["minutes"] == 120

    def test_no_change_skips_update(self, db, company):
        company.scrape_interval_minutes = 30
        company.save(update_fields=["scrape_interval_minutes"])
        now = timezone.now()
        ScrapeRun.objects.create(
            company=company,
            status="success",
            verdict=RunVerdict.TRUSTED,
            jobs_added=1,
            jobs_missing=0,
            finished_at=now - timedelta(hours=1),
        )
        ScrapeRun.objects.create(
            company=company,
            status="success",
            verdict=RunVerdict.TRUSTED,
            jobs_added=0,
            jobs_missing=0,
            finished_at=now - timedelta(hours=2),
        )
        ScrapeRun.objects.create(
            company=company,
            status="success",
            verdict=RunVerdict.TRUSTED,
            jobs_added=0,
            jobs_missing=0,
            finished_at=now - timedelta(hours=3),
        )
        with patch("apps.companies.services.update_scrape_interval") as mock_update:
            from apps.scraping.tasks import _maybe_apply_adaptive_interval

            run = ScrapeRun.objects.filter(company=company, verdict=RunVerdict.TRUSTED).first()
            _maybe_apply_adaptive_interval(company=company, scrape_run=run)

        mock_update.assert_not_called()


class TestLockTTL:
    def test_global_cycle_lock_ttl_is_15_minutes(self):
        with patch("apps.scraping.tasks.redis_lock") as mock_lock:
            from core.locks import LockNotAcquired

            mock_lock.side_effect = LockNotAcquired("locked")
            refresh_all_companies()

        mock_lock.assert_called_once()
        call_kwargs = mock_lock.call_args
        assert call_kwargs[1]["timeout"] == 15 * 60
