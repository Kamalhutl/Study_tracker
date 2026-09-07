"""Targeted coverage tests using the same mock pattern as test_tasks.py."""

from __future__ import annotations

from datetime import timedelta
from unittest.mock import MagicMock, patch

import pytest

from apps.companies.enums import CareerSourceType, ScrapeHealth
from apps.scraping.models import ScrapeError, ScrapeRun
from apps.scraping.tasks import scrape_company
from tests.factories import UserFactory


@pytest.fixture
def user(db):
    return UserFactory()


@pytest.fixture
def company(db, user):
    from apps.companies.models import Company

    return Company.objects.create(
        name="Helper Test Co",
        domain="helpertest.com",
        slug="helper-test-co",
        career_url="https://helpertest.com/careers",
        career_source_type=CareerSourceType.GREENHOUSE,
        ats_identifier="helpertest",
        is_verified=True,
        is_active=True,
        scrape_health=ScrapeHealth.HEALTHY,
        consecutive_failures=0,
        added_by=user,
    )


def test_get_parser_module_valid():
    from apps.scraping.tasks import _get_parser_module

    module = _get_parser_module("greenhouse")
    assert module is not None
    assert hasattr(module, "parse")


def test_get_parser_module_unknown():
    import apps.scraping.tasks as tasks_module

    assert tasks_module._get_parser_module("totally_unknown_xyz") is None


@pytest.mark.django_db
def test_build_fetch_url_greenhouse(company):
    from apps.scraping.tasks import _build_fetch_url

    url = _build_fetch_url(company)
    assert url is not None
    assert "helpertest" in url


@pytest.mark.django_db
def test_update_health_success_resets(company):
    from apps.scraping.tasks import _update_company_health

    company.consecutive_failures = 3
    company.scrape_health = ScrapeHealth.DEGRADED
    company.save()

    _update_company_health(company, success=True)

    company.refresh_from_db()
    assert company.consecutive_failures == 0
    assert company.scrape_health == ScrapeHealth.HEALTHY


@pytest.mark.django_db
def test_update_health_degraded(company):
    from apps.scraping.tasks import _update_company_health

    company.consecutive_failures = 1
    company.save()

    _update_company_health(company, success=False)

    company.refresh_from_db()
    assert company.scrape_health == ScrapeHealth.DEGRADED


@pytest.mark.django_db
def test_update_health_failing(company):
    from apps.scraping.tasks import _update_company_health

    company.consecutive_failures = 4
    company.save()

    _update_company_health(company, success=False)

    company.refresh_from_db()
    assert company.scrape_health == ScrapeHealth.FAILING


@pytest.mark.django_db
def test_scrape_company_no_parser_returns_failed(company):
    with (
        patch("apps.scraping.tasks._get_parser_module") as mock_parser,
        patch("apps.scraping.tasks._build_fetch_url") as mock_url,
        patch("apps.scraping.tasks._use_fetch_with_escalation") as mock_esc,
    ):
        mock_parser.return_value = None
        mock_url.return_value = "https://example.com/jobs"
        mock_esc.return_value = False

        result = scrape_company(str(company.id), triggered_by="manual")

    assert result["status"] == "failed"
    assert ScrapeRun.objects.filter(company=company, status="failed").exists()


@pytest.mark.django_db
def test_scrape_company_no_fetch_url_returns_failed(company):
    mock_parser_mod = MagicMock()
    mock_parser_mod.PARSER_NAME = "greenhouse"
    mock_parser_mod.PARSER_VERSION = 1
    mock_parser_mod.parse.return_value = []

    with (
        patch("apps.scraping.tasks._get_parser_module") as mock_parser,
        patch("apps.scraping.tasks._build_fetch_url") as mock_url,
        patch("apps.scraping.tasks._use_fetch_with_escalation") as mock_esc,
    ):
        mock_parser.return_value = mock_parser_mod
        mock_url.return_value = ""
        mock_esc.return_value = False

        result = scrape_company(str(company.id), triggered_by="manual")

    assert result["status"] == "failed"


@pytest.mark.django_db
def test_scrape_company_full_success_job_loop(company):
    job_payload = {
        "source_job_id": "gh-1",
        "title": "Backend Engineer",
        "description_html": "<p>Build APIs</p>",
        "job_url": "https://example.com/jobs/1",
        "location": "Remote",
        "work_mode": "remote",
        "employment_type": "full_time",
        "posted_at": None,
        "raw_payload": {},
    }

    mock_parser_mod = MagicMock()
    mock_parser_mod.PARSER_NAME = "greenhouse"
    mock_parser_mod.PARSER_VERSION = 1
    mock_parser_mod.parse.return_value = [job_payload]

    with (
        patch("apps.scraping.tasks._get_parser_module") as mock_gpm,
        patch("apps.scraping.tasks._build_fetch_url") as mock_url,
        patch("apps.scraping.tasks._use_fetch_with_escalation") as mock_esc,
        patch("apps.scraping.tasks.fetch") as mock_fetch,
        patch("apps.scraping.tasks.upsert_job") as mock_upsert,
        patch("core.locks.redis_lock") as mock_lock,
    ):
        mock_lock.return_value.__enter__ = MagicMock()
        mock_lock.return_value.__exit__ = MagicMock()

        mock_gpm.return_value = mock_parser_mod
        mock_url.return_value = "https://boards-api.greenhouse.io/v1/boards/helpertest/jobs"
        mock_esc.return_value = False
        from scrapling import Selector

        from apps.scraping.fetching import FetchMode, FetchResult

        mock_fetch.return_value = FetchResult(
            url="https://boards-api.greenhouse.io/v1/boards/helpertest/jobs",
            final_url="https://boards-api.greenhouse.io/v1/boards/helpertest/jobs",
            status_code=200,
            html="<html><body>test</body></html>",
            selector=Selector("<html><body>test</body></html>"),
            fetcher_used=FetchMode.HTTP,
            elapsed_ms=100,
            from_cache=False,
            escalation_reason="",
            not_modified=False,
        )
        mock_upsert.return_value = MagicMock(created=True)

        result = scrape_company(str(company.id), triggered_by="manual")

    assert result["status"] in ("success", "partial")
    assert result["jobs_found"] == 1
    assert mock_upsert.call_count == 1


@pytest.mark.django_db
def test_scrape_company_parse_error_creates_scrape_error(company):
    mock_parser_mod = MagicMock()
    mock_parser_mod.PARSER_NAME = "greenhouse"
    mock_parser_mod.PARSER_VERSION = 1
    mock_parser_mod.parse.side_effect = Exception("parse boom")

    with (
        patch("apps.scraping.tasks._get_parser_module") as mock_gpm,
        patch("apps.scraping.tasks._build_fetch_url") as mock_url,
        patch("apps.scraping.tasks._use_fetch_with_escalation") as mock_esc,
        patch("apps.scraping.tasks.fetch") as mock_fetch,
    ):
        mock_gpm.return_value = mock_parser_mod
        mock_url.return_value = "https://boards-api.greenhouse.io/v1/boards/helpertest/jobs"
        mock_esc.return_value = False
        from scrapling import Selector

        from apps.scraping.fetching import FetchMode, FetchResult

        mock_fetch.return_value = FetchResult(
            url="https://boards-api.greenhouse.io/v1/boards/helpertest/jobs",
            final_url="https://boards-api.greenhouse.io/v1/boards/helpertest/jobs",
            status_code=200,
            html="<html><body>test</body></html>",
            selector=Selector("<html><body>test</body></html>"),
            fetcher_used=FetchMode.HTTP,
            elapsed_ms=100,
            from_cache=False,
            escalation_reason="",
            not_modified=False,
        )

        result = scrape_company(str(company.id), triggered_by="manual")

    assert result["status"] in ("partial", "failed")
    assert ScrapeError.objects.filter(company=company).count() >= 1


@pytest.mark.django_db
def test_execute_refresh_all_dispatches_due(company):
    from django.utils import timezone

    from apps.scraping.tasks import _execute_refresh_all

    company.next_scrape_at = timezone.now() - timedelta(minutes=10)
    company.is_verified = True
    company.is_active = True
    company.scrape_health = ScrapeHealth.HEALTHY
    company.save()

    with patch("apps.scraping.tasks.scrape_company.apply_async") as mock_async:
        result = _execute_refresh_all()

    assert mock_async.call_count >= 1
    assert isinstance(result, dict)


@pytest.mark.django_db
def test_execute_refresh_all_skips_failing(company):
    from django.utils import timezone

    from apps.scraping.tasks import _execute_refresh_all

    company.next_scrape_at = timezone.now() - timedelta(minutes=10)
    company.scrape_health = ScrapeHealth.FAILING
    company.save()

    with patch("apps.scraping.tasks.scrape_company.apply_async") as mock_async:
        _execute_refresh_all()

    assert mock_async.call_count == 0
