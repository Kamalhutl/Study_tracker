from datetime import timedelta
from unittest.mock import MagicMock, patch

import pytest
from django.utils import timezone

from apps.accounts.models import User
from apps.companies.enums import CareerSourceType, ScrapeHealth
from apps.companies.models import Company
from apps.scraping.fetching import FetchResult
from apps.scraping.spiders.static_jobs import _build_absolute_url, _is_same_domain, extract
from apps.scraping.tasks import _build_fetch_url, _update_company_health, _use_fetch_with_escalation


@pytest.fixture
def user(db):
    return User.objects.create_user(email="testuser@example.com", password="testpass")


@pytest.mark.django_db
def test_update_company_health_success(user):
    company = Company.objects.create(
        name="Test",
        domain="test.com",
        slug="test",
        career_url="https://test.com",
        career_source_type=CareerSourceType.OWN_CAREER_PAGE,
        is_verified=True,
        is_active=True,
        scrape_interval_minutes=300,
        added_by=user,
    )
    _update_company_health(company, success=True)
    assert company.consecutive_failures == 0
    assert company.scrape_health == ScrapeHealth.HEALTHY


@pytest.mark.django_db
def test_update_company_health_failure(user):
    company = Company.objects.create(
        name="Test",
        domain="test.com",
        slug="test",
        career_url="https://test.com",
        career_source_type=CareerSourceType.OWN_CAREER_PAGE,
        is_verified=True,
        is_active=True,
        scrape_interval_minutes=300,
        consecutive_failures=1,
        added_by=user,
    )
    _update_company_health(company, success=False)
    assert company.consecutive_failures == 2
    assert company.scrape_health == ScrapeHealth.DEGRADED


@pytest.mark.django_db
def test_update_company_health_failure_to_failing(user):
    company = Company.objects.create(
        name="Test",
        domain="test.com",
        slug="test",
        career_url="https://test.com",
        career_source_type=CareerSourceType.OWN_CAREER_PAGE,
        is_verified=True,
        is_active=True,
        scrape_interval_minutes=300,
        consecutive_failures=4,
        added_by=user,
    )
    _update_company_health(company, success=False)
    assert company.consecutive_failures == 5
    assert company.scrape_health == ScrapeHealth.FAILING


def test_build_fetch_url():
    company = Company(
        name="Test",
        domain="test.com",
        slug="test",
        career_source_type=CareerSourceType.GREENHOUSE,
        ats_identifier="acme",
    )
    url = _build_fetch_url(company)
    assert url == "https://boards-api.greenhouse.io/v1/boards/acme/jobs?content=true"


def test_build_fetch_url_own_page():
    company = Company(
        name="Test",
        domain="test.com",
        slug="test",
        career_source_type=CareerSourceType.OWN_CAREER_PAGE,
        career_url="https://test.com/careers",
    )
    url = _build_fetch_url(company)
    assert url == "https://test.com/careers"


def test_use_fetch_with_escalation():
    assert _use_fetch_with_escalation(CareerSourceType.OWN_CAREER_PAGE) is True
    assert _use_fetch_with_escalation(CareerSourceType.UNKNOWN) is True
    assert _use_fetch_with_escalation(CareerSourceType.GREENHOUSE) is False


def test_static_spider_absolute_url():
    base = "https://example.com/careers/"
    assert _build_absolute_url("/jobs/123", base) == "https://example.com/jobs/123"
    assert _build_absolute_url("jobs/123", base) == "https://example.com/careers/jobs/123"
    assert _build_absolute_url("https://other.com/jobs", base) == "https://other.com/jobs"
    assert _build_absolute_url("#section", base) is None
    assert _build_absolute_url("mailto:test@example.com", base) is None
    assert _build_absolute_url("javascript:alert(1)", base) is None


def test_static_spider_same_domain():
    assert _is_same_domain("https://example.com/careers", "example.com") is True
    assert _is_same_domain("https://sub.example.com/careers", "example.com") is False
    assert _is_same_domain("https://other.com/careers", "example.com") is False
    assert _is_same_domain("", "example.com") is False
    assert _is_same_domain("https://example.com", "") is True


def test_static_spider_extract_with_absolute_links():
    company = Company(
        name="Test",
        domain="test.com",
        slug="test",
        career_url="https://test.com/careers",
        career_source_type=CareerSourceType.OWN_CAREER_PAGE,
    )
    html = """
    <html>
        <body>
            <a href="https://test.com/jobs/1">Job 1</a>
            <a href="https://test.com/careers/2">Job 2</a>
            <a href="https://other.com/jobs">Other</a>
        </body>
    </html>
    """
    mock_selector = MagicMock()
    anchors = []
    for href, text in [
        ("https://test.com/jobs/1", "Job 1"),
        ("https://test.com/careers/2", "Job 2"),
        ("https://other.com/jobs", "Other"),
    ]:
        mock_a = MagicMock()
        mock_a.attrib = {"href": href}
        mock_a.get_all_text.return_value = text
        anchors.append(mock_a)
    mock_selector.css.return_value = anchors

    fetch_result = FetchResult(
        url="https://test.com/careers",
        final_url="https://test.com/careers",
        status_code=200,
        html=html,
        selector=mock_selector,
        fetcher_used="http",
        elapsed_ms=100,
        from_cache=False,
        escalation_reason="",
    )
    payloads = extract(fetch_result, company=company)
    assert len(payloads) == 2


@pytest.mark.django_db
def test_refresh_all_companies_dispatches_due_also_when_locked(user):
    from apps.scraping.tasks import _execute_refresh_all

    now = timezone.now()
    _company1 = Company.objects.create(
        name="Company A",
        domain="companya.com",
        slug="companya",
        career_url="https://companya.com/careers",
        career_source_type=CareerSourceType.GREENHOUSE,
        ats_identifier="a",
        is_verified=True,
        is_active=True,
        scrape_interval_minutes=300,
        scrape_health=ScrapeHealth.HEALTHY,
        consecutive_failures=0,
        next_scrape_at=now - timedelta(hours=1),
        added_by=user,
    )
    _company2 = Company.objects.create(
        name="Company B",
        domain="companyb.com",
        slug="companyb",
        career_url="https://companyb.com/careers",
        career_source_type=CareerSourceType.LEVER,
        ats_identifier="b",
        is_verified=True,
        is_active=True,
        scrape_interval_minutes=300,
        scrape_health=ScrapeHealth.HEALTHY,
        consecutive_failures=0,
        next_scrape_at=now - timedelta(hours=2),
        added_by=user,
    )
    _company3 = Company.objects.create(
        name="Company C",
        domain="companyc.com",
        slug="companyc",
        career_url="https://companyc.com/careers",
        career_source_type=CareerSourceType.ASHBY,
        ats_identifier="c",
        is_verified=True,
        is_active=True,
        scrape_interval_minutes=300,
        scrape_health=ScrapeHealth.HEALTHY,
        consecutive_failures=0,
        next_scrape_at=now + timedelta(hours=1),
        added_by=user,
    )
    with patch("apps.scraping.tasks.scrape_company.apply_async") as mock_apply:
        result = _execute_refresh_all()
        assert result["dispatched"] == 2
        assert mock_apply.call_count == 2
