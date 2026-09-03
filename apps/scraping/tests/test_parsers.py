import json
from unittest.mock import MagicMock

import pytest

from apps.companies.models import Company
from apps.scraping.fetching import FetchResult
from apps.scraping.parsers.ats_ashby import parse as ashby_parse
from apps.scraping.parsers.ats_greenhouse import parse as greenhouse_parse
from apps.scraping.parsers.ats_lever import parse as lever_parse
from apps.scraping.parsers.ats_smartrecruiters import parse as smartrecruiters_parse

# ==================== GREENHOUSE TESTS ====================


@pytest.fixture
def greenhouse_fixture():
    with open("apps/scraping/tests/fixtures/ats/greenhouse_jobs.json") as f:
        return json.load(f)


@pytest.fixture
def empty_greenhouse_fixture():
    return {"jobs": []}


@pytest.fixture
def greenhouse_company():
    return Company(
        name="Test Company",
        domain="test.com",
        career_source_type="greenhouse",
        ats_identifier="test-ats",
    )


def test_greenhouse_parses_jobs(greenhouse_fixture, greenhouse_company):
    mock_selector = MagicMock()
    mock_selector.json.return_value = greenhouse_fixture

    fetch_result = FetchResult(
        url="https://example.com",
        final_url="https://example.com",
        status_code=200,
        html="",
        selector=mock_selector,
        fetcher_used="http",
        elapsed_ms=100,
        from_cache=False,
        escalation_reason="",
    )

    payloads = greenhouse_parse(fetch_result, company=greenhouse_company)

    assert len(payloads) == 2
    assert payloads[0]["source_job_id"] == "4567890"
    assert payloads[0]["title"] == "Senior Software Engineer"
    assert payloads[0]["extraction_confidence"] == 90


def test_greenhouse_empty_jobs_key(empty_greenhouse_fixture, greenhouse_company):
    mock_selector = MagicMock()
    mock_selector.json.return_value = empty_greenhouse_fixture

    fetch_result = FetchResult(
        url="https://example.com",
        final_url="https://example.com",
        status_code=200,
        html="",
        selector=mock_selector,
        fetcher_used="http",
        elapsed_ms=100,
        from_cache=False,
        escalation_reason="",
    )

    payloads = greenhouse_parse(fetch_result, company=greenhouse_company)

    assert len(payloads) == 0


def test_greenhouse_malformed_json(greenhouse_company):
    mock_selector = MagicMock()
    mock_selector.json.side_effect = ValueError("Invalid JSON")

    fetch_result = FetchResult(
        url="https://example.com",
        final_url="https://example.com",
        status_code=200,
        html="",
        selector=mock_selector,
        fetcher_used="http",
        elapsed_ms=100,
        from_cache=False,
        escalation_reason="",
    )

    payloads = greenhouse_parse(fetch_result, company=greenhouse_company)

    assert len(payloads) == 0


# ==================== LEVER TESTS ====================


@pytest.fixture
def lever_fixture():
    with open("apps/scraping/tests/fixtures/ats/lever_jobs.json") as f:
        return json.load(f)


@pytest.fixture
def lever_company():
    return Company(
        name="Test Company",
        domain="test.com",
        career_source_type="lever",
        ats_identifier="test-ats",
    )


def test_lever_parses_jobs(lever_fixture, lever_company):
    mock_selector = MagicMock()
    mock_selector.json.return_value = lever_fixture

    fetch_result = FetchResult(
        url="https://example.com",
        final_url="https://example.com",
        status_code=200,
        html="",
        selector=mock_selector,
        fetcher_used="http",
        elapsed_ms=100,
        from_cache=False,
        escalation_reason="",
    )

    payloads = lever_parse(fetch_result, company=lever_company)

    assert len(payloads) == 2
    assert payloads[0]["source_job_id"] == "abc-def-123"
    assert payloads[0]["title"] == "Backend Engineer"
    assert payloads[0]["apply_url"] == "https://jobs.lever.co/acme/abc-def-123/apply"
    assert payloads[0]["posted_at"] is not None


def test_lever_missing_apply_url(lever_company):
    modified_fixture = [
        {
            "id": "abc-def-123",
            "text": "Backend Engineer",
            "categories": {
                "location": "Remote",
                "department": "Engineering",
                "commitment": "Full-time",
            },
            "descriptionPlain": "We are looking for a Backend Engineer to build scalable systems.",
            "description": "<div>We are looking for a Backend Engineer to build scalable systems.</div>",
            "hostedUrl": "https://jobs.lever.co/acme/abc-def-123",
            "createdAt": 1700000000000,
        }
    ]

    mock_selector = MagicMock()
    mock_selector.json.return_value = modified_fixture

    fetch_result = FetchResult(
        url="https://example.com",
        final_url="https://example.com",
        status_code=200,
        html="",
        selector=mock_selector,
        fetcher_used="http",
        elapsed_ms=100,
        from_cache=False,
        escalation_reason="",
    )

    payloads = lever_parse(fetch_result, company=lever_company)

    assert len(payloads) == 1
    assert payloads[0]["apply_url"] == "https://jobs.lever.co/acme/abc-def-123"


# ==================== ASHBY TESTS ====================


@pytest.fixture
def ashby_fixture():
    with open("apps/scraping/tests/fixtures/ats/ashby_jobs.json") as f:
        return json.load(f)


@pytest.fixture
def empty_ashby_fixture():
    return {"jobPostings": []}


@pytest.fixture
def ashby_company():
    return Company(
        name="Test Company",
        domain="test.com",
        career_source_type="ashby",
        ats_identifier="test-ats",
    )


def test_ashby_parses_jobs(ashby_fixture, ashby_company):
    mock_selector = MagicMock()
    mock_selector.json.return_value = ashby_fixture

    fetch_result = FetchResult(
        url="https://example.com",
        final_url="https://example.com",
        status_code=200,
        html="",
        selector=mock_selector,
        fetcher_used="http",
        elapsed_ms=100,
        from_cache=False,
        escalation_reason="",
    )

    payloads = ashby_parse(fetch_result, company=ashby_company)

    assert len(payloads) == 2
    assert payloads[0]["source_job_id"] == "xyz-789"
    assert payloads[0]["title"] == "Product Designer"
    assert payloads[0]["job_type"] == "full_time"


def test_ashby_empty_postings(empty_ashby_fixture, ashby_company):
    mock_selector = MagicMock()
    mock_selector.json.return_value = empty_ashby_fixture

    fetch_result = FetchResult(
        url="https://example.com",
        final_url="https://example.com",
        status_code=200,
        html="",
        selector=mock_selector,
        fetcher_used="http",
        elapsed_ms=100,
        from_cache=False,
        escalation_reason="",
    )

    payloads = ashby_parse(fetch_result, company=ashby_company)

    assert len(payloads) == 0


# ==================== SMARTRECRUITERS TESTS ====================


@pytest.fixture
def smartrecruiters_fixture():
    with open("apps/scraping/tests/fixtures/ats/smartrecruiters_jobs.json") as f:
        return json.load(f)


@pytest.fixture
def smartrecruiters_company():
    return Company(
        name="Test Company",
        domain="test.com",
        career_source_type="smartrecruiters",
        ats_identifier="test-ats",
    )


def test_smartrecruiters_parses_jobs(smartrecruiters_fixture, smartrecruiters_company):
    mock_selector = MagicMock()
    mock_selector.json.return_value = smartrecruiters_fixture

    fetch_result = FetchResult(
        url="https://example.com",
        final_url="https://example.com",
        status_code=200,
        html="",
        selector=mock_selector,
        fetcher_used="http",
        elapsed_ms=100,
        from_cache=False,
        escalation_reason="",
    )

    payloads = smartrecruiters_parse(fetch_result, company=smartrecruiters_company)

    assert len(payloads) == 2
    assert payloads[0]["source_job_id"] == "sr-job-001"
    assert payloads[0]["title"] == "Data Analyst"
    assert payloads[0]["work_mode"] == "remote"


def test_smartrecruiters_extraction_confidence_is_60(
    smartrecruiters_fixture, smartrecruiters_company
):
    mock_selector = MagicMock()
    mock_selector.json.return_value = smartrecruiters_fixture

    fetch_result = FetchResult(
        url="https://example.com",
        final_url="https://example.com",
        status_code=200,
        html="",
        selector=mock_selector,
        fetcher_used="http",
        elapsed_ms=100,
        from_cache=False,
        escalation_reason="",
    )

    payloads = smartrecruiters_parse(fetch_result, company=smartrecruiters_company)

    for payload in payloads:
        assert payload["extraction_confidence"] == 60


# ==================== NEW PARSER BRANCH TESTS ====================


def test_greenhouse_strips_html_from_description(greenhouse_company):
    """Test that Greenhouse parser strips HTML tags from description."""
    html_data = {
        "jobs": [
            {
                "id": "123",
                "title": "Test Job",
                "content": "<p>This is <strong>bold</strong> and <em>italic</em> text.</p>",
                "updated_at": "2025-01-01T00:00:00Z",
            }
        ]
    }
    mock_selector = MagicMock()
    mock_selector.json.return_value = html_data

    fetch_result = FetchResult(
        url="https://example.com",
        final_url="https://example.com",
        status_code=200,
        html="",
        selector=mock_selector,
        fetcher_used="http",
        elapsed_ms=100,
        from_cache=False,
        escalation_reason="",
    )

    payloads = greenhouse_parse(fetch_result, company=greenhouse_company)
    assert len(payloads) == 1
    # Description should be plain text without HTML tags
    assert "<p>" not in payloads[0]["description"]
    assert "<strong>" not in payloads[0]["description"]
    assert "<em>" not in payloads[0]["description"]
    assert "This is bold and italic text." in payloads[0]["description"]


def test_lever_missing_categories_key(greenhouse_company):
    """Test that Lever parser handles missing categories key."""
    # Use greenhouse_company since it has the right type, but we're testing Lever parser
    lever_data = [
        {
            "id": "456",
            "text": "Test Job",
            "hostedUrl": "https://example.com/jobs/456",
            # No categories key
        }
    ]
    mock_selector = MagicMock()
    mock_selector.json.return_value = lever_data

    fetch_result = FetchResult(
        url="https://example.com",
        final_url="https://example.com",
        status_code=200,
        html="",
        selector=mock_selector,
        fetcher_used="http",
        elapsed_ms=100,
        from_cache=False,
        escalation_reason="",
    )

    payloads = lever_parse(fetch_result, company=greenhouse_company)
    assert len(payloads) == 1
    # Should handle missing categories gracefully
    assert payloads[0]["location_raw"] == ""
    assert payloads[0]["department"] == ""


def test_ashby_employment_type_mapping():
    """Test Ashby employment type mapping."""
    from apps.scraping.parsers.ats_ashby import _map_job_type

    # Test the mapping function directly
    assert _map_job_type("PartTime") == "part_time"
    assert _map_job_type("Contract") == "contract"
    assert _map_job_type("FullTime") == "full_time"
    assert _map_job_type("Internship") == "internship"
    assert _map_job_type("") == ""
    assert _map_job_type("UnknownType") == ""  # Unknown types return empty string


def test_smartrecruiters_no_remote_flag():
    """Test SmartRecruiters parser when remote flag is absent."""
    from apps.scraping.parsers.ats_smartrecruiters import _extract_work_mode

    # Test with location dict missing remote key
    location_data = {"city": "San Francisco", "country": "USA"}
    assert _extract_work_mode(location_data) == ""

    # Test with remote=False
    location_data_false = {"city": "San Francisco", "remote": False}
    assert _extract_work_mode(location_data_false) == ""


def test_smartrecruiters_location_parts():
    """Test SmartRecruiters location building with city+region+country."""
    from apps.scraping.parsers.ats_smartrecruiters import _build_location

    # Test with all parts
    location_data = {"city": "San Francisco", "region": "CA", "country": "USA"}
    result = _build_location(location_data)
    assert result == "San Francisco, CA, USA"

    # Test with city and country only
    location_data_partial = {"city": "New York", "country": "USA"}
    result_partial = _build_location(location_data_partial)
    assert result_partial == "New York, USA"

    # Test with remote flag
    location_data_remote = {"city": "Boston", "remote": True}
    result_remote = _build_location(location_data_remote)
    assert result_remote == "Boston (Remote)"

    # Test with only remote
    location_data_only_remote = {"remote": True}
    result_only_remote = _build_location(location_data_only_remote)
    assert result_only_remote == "Remote"
