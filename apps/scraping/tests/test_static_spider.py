import pytest
from scrapling.parser import Selector

from apps.companies.models import Company
from apps.scraping.fetching import FetchMode, FetchResult
from apps.scraping.spiders.static_jobs import extract


@pytest.fixture
def company():
    return Company(
        name="Test Company",
        domain="test.com",
        career_url="https://test.com/careers",
        career_source_type="own_career_page",
        ats_identifier="",
    )


def make_fetch_result(html: str, url: str = "https://test.com/careers") -> FetchResult:
    """Build a FetchResult with a real Scrapling Selector (no network)."""
    selector = Selector(content=html)
    return FetchResult(
        url=url,
        final_url=url,
        status_code=200,
        html=html,
        selector=selector,
        fetcher_used=FetchMode.HTTP,
        elapsed_ms=0,
        from_cache=False,
        escalation_reason="",
    )


def test_static_extracts_job_links(company):
    html = """
    <html><body>
        <a href="/jobs/senior-engineer">Senior Software Engineer</a>
        <a href="/jobs/product-manager">Product Manager</a>
        <a href="/jobs/data-scientist">Data Scientist</a>
        <a href="/jobs/frontend-dev">Frontend Developer</a>
        <a href="/jobs/backend-dev">Backend Developer</a>
    </body></html>
    """
    fetch_result = make_fetch_result(html, "https://test.com/careers")
    payloads = extract(fetch_result, company=company)
    assert len(payloads) == 5
    # Check that all have confidence 40
    for p in payloads:
        assert p["extraction_confidence"] == 40


def test_static_ignores_noise_links(company):
    html = """
    <html><body>
        <a href="https://linkedin.com/company/test">LinkedIn</a>
        <a href="mailto:contact@test.com">Email Us</a>
        <a href="https://twitter.com/test">Twitter</a>
        <a href="#section">Jump to section</a>
        <a href="javascript:void(0)">JS Link</a>
        <a href="/jobs/real-job">Real Job Title</a>
    </body></html>
    """
    fetch_result = make_fetch_result(html, "https://test.com/careers")
    payloads = extract(fetch_result, company=company)
    # Should only find the real job
    assert len(payloads) == 1
    assert payloads[0]["title"] == "Real Job Title"


def test_static_dedupes_urls(company):
    html = """
    <html><body>
        <a href="/jobs/engineer">Software Engineer</a>
        <a href="/jobs/engineer">Senior Software Engineer</a>
        <a href="/jobs/manager">Product Manager</a>
    </body></html>
    """
    fetch_result = make_fetch_result(html, "https://test.com/careers")
    payloads = extract(fetch_result, company=company)
    # Should deduplicate the /jobs/engineer URL, leaving 2
    assert len(payloads) == 2
    titles = [p["title"] for p in payloads]
    assert "Software Engineer" in titles or "Senior Software Engineer" in titles
    assert "Product Manager" in titles


def test_static_no_candidates_returns_empty(company):
    # Create HTML with only navigation links (no job signals)
    # Use links with text length <5 or >120 so they fail the job candidate check
    html = """
    <html><body>
        <a href="/">Hm</a>
        <a href="/about">Ab</a>
        <a href="/contact">Co</a>
    </body></html>
    """
    fetch_result = make_fetch_result(html, "https://test.com/careers")
    payloads = extract(fetch_result, company=company)
    assert len(payloads) == 0


def test_static_confidence_is_40(company):
    html = """
    <html><body>
        <a href="/jobs/test">Test Job Title</a>
    </body></html>
    """
    fetch_result = make_fetch_result(html, "https://test.com/careers")
    payloads = extract(fetch_result, company=company)
    assert len(payloads) == 1
    assert payloads[0]["extraction_confidence"] == 40
