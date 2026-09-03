from unittest.mock import MagicMock

import pytest

from apps.companies.enums import CareerSourceType, ScrapeHealth
from apps.companies.models import Company
from apps.scraping.parsers import ats_ashby, ats_greenhouse, ats_lever, ats_smartrecruiters
from tests.factories import UserFactory

pytestmark = pytest.mark.django_db


def one(**kw):
    r = []
    r.append(dict(**kw))
    return r


def fr(d):
    m = MagicMock()
    m.selector.json.return_value = d
    return m


def frx():
    m = MagicMock()
    m.selector.json.side_effect = Exception("boom")
    return m


@pytest.fixture
def pco(db):
    return Company.objects.create(
        name="PCo",
        domain="pco.com",
        slug="pco",
        career_url="https://pco.com/j",
        career_source_type=CareerSourceType.GREENHOUSE,
        ats_identifier="pco",
        is_verified=True,
        is_active=True,
        scrape_health=ScrapeHealth.HEALTHY,
        consecutive_failures=0,
        added_by=UserFactory(),
    )


def test_lever_paths(pco):
    full = one(
        id="l1",
        text="BE",
        descriptionPlain="d",
        applyUrl="https://a.co/1",
        createdAt=1704067200000,
        categories={"location": "Remote", "team": "Eng", "commitment": "Full-time"},
        workplaceType="remote",
    )
    assert len(ats_lever.parse(fr(full), company=pco)) == 1
    assert len(ats_lever.parse(fr(one(id="l2", text="Min")), company=pco)) == 1
    assert ats_lever.parse(fr([]), company=pco) == []
    assert ats_lever.parse(fr({"bad": 1}), company=pco) == []
    assert ats_lever.parse(frx(), company=pco) == []
    assert "Hi" in ats_lever._strip_html("<p>Hi</p>")
    assert ats_lever._strip_html("") == ""


def test_ashby_paths(pco):
    full = one(
        id="a1",
        title="FE",
        descriptionHtml="<p>d</p>",
        applyUrl="https://a.co/2",
        publishedAt="2024-01-15T10:00:00.000Z",
        locationName="NY",
        employmentType="FullTime",
        isRemote=True,
    )
    assert len(ats_ashby.parse(fr({"jobPostings": full}), company=pco)) == 1
    assert len(ats_ashby.parse(fr({"jobPostings": one(id="a2", title="Min")}), company=pco)) == 1
    for t in ("PartTime", "Contract", "Internship", "Temporary", "Freelance", "Weird"):
        rows = one(id="x", title="T", employmentType=t)
        assert len(ats_ashby.parse(fr({"jobPostings": rows}), company=pco)) == 1
    assert ats_ashby.parse(fr({"jobPostings": []}), company=pco) == []
    assert ats_ashby.parse(fr({}), company=pco) == []
    assert ats_ashby.parse(frx(), company=pco) == []
    assert "Hi" in ats_ashby._strip_html("<div>Hi</div>")
    assert ats_ashby._strip_html("") == ""


def test_greenhouse_paths(pco):
    full = one(
        id=1001,
        title="DE",
        content="<p>d</p>",
        location={"name": "Remote"},
        updated_at="2024-01-15T10:00:00.000Z",
        absolute_url="https://a.co/3",
    )
    assert len(ats_greenhouse.parse(fr({"jobs": full}), company=pco)) == 1
    assert len(ats_greenhouse.parse(fr({"jobs": one(id=2, title="Min")}), company=pco)) == 1
    assert ats_greenhouse.parse(fr({"jobs": []}), company=pco) == []
    assert ats_greenhouse.parse(fr({}), company=pco) == []
    assert ats_greenhouse.parse(frx(), company=pco) == []


def test_smartrecruiters_paths(pco):
    full = one(
        id="s1",
        name="PM",
        industry={"label": "Tech"},
        location={"city": "Austin", "country": "USA"},
        typeOfEmployment={"label": "Full-time"},
        experienceLevel={"label": "Mid"},
        ref="https://a.co/4",
        releasedDate="2024-01-15",
    )
    assert len(ats_smartrecruiters.parse(fr({"content": full}), company=pco)) == 1
    assert (
        len(ats_smartrecruiters.parse(fr({"content": one(id="s2", name="Min")}), company=pco)) == 1
    )
    assert ats_smartrecruiters.parse(fr({"content": []}), company=pco) == []
    assert ats_smartrecruiters.parse(fr({}), company=pco) == []
    assert ats_smartrecruiters.parse(frx(), company=pco) == []


def test_url_templates_are_api_endpoints(pco):
    from apps.companies.enums import CareerSourceType
    from apps.scraping.tasks import _build_fetch_url

    pco.ats_identifier = "acme"
    pco.career_source_type = CareerSourceType.GREENHOUSE
    assert (
        _build_fetch_url(pco) == "https://boards-api.greenhouse.io/v1/boards/acme/jobs?content=true"
    )
    pco.career_source_type = CareerSourceType.LEVER
    assert _build_fetch_url(pco) == "https://api.lever.co/v0/postings/acme?mode=json"
    pco.career_source_type = CareerSourceType.ASHBY
    assert _build_fetch_url(pco) == "https://jobs.ashbyhq.com/acme/json"
    pco.career_source_type = CareerSourceType.SMARTRECRUITERS
    assert _build_fetch_url(pco) == "https://api.smartrecruiters.com/v1/companies/acme/postings"


def test_lever_work_mode_mapping():
    from apps.jobs.enums import WorkMode
    from apps.scraping.parsers.ats_lever import _extract_work_mode

    assert _extract_work_mode({"workplaceType": "remote"}) == str(WorkMode.REMOTE)
    assert _extract_work_mode({"workplaceType": "hybrid"}) == str(WorkMode.HYBRID)
    assert _extract_work_mode({"workplaceType": "onsite"}) == str(WorkMode.ONSITE)
    assert _extract_work_mode({"workplaceType": "on-site"}) == str(WorkMode.ONSITE)
    assert _extract_work_mode({"workplaceType": "REMOTE"}) == str(WorkMode.REMOTE)
    assert _extract_work_mode({"workplaceType": "unspecified"}) == ""
    assert _extract_work_mode({}) == ""


def test_lever_job_type_mapping():
    from apps.jobs.enums import JobType
    from apps.scraping.parsers.ats_lever import _extract_job_type

    assert _extract_job_type({"categories": {"commitment": "Full-time"}}) == str(JobType.FULL_TIME)
    assert _extract_job_type({"categories": {"commitment": "Part time"}}) == str(JobType.PART_TIME)
    assert _extract_job_type({"categories": {"commitment": "Contract"}}) == str(JobType.CONTRACT)
    assert _extract_job_type({"categories": {"commitment": "Internship"}}) == str(
        JobType.INTERNSHIP
    )
    assert _extract_job_type({"categories": {"commitment": "Temporary"}}) == str(JobType.TEMPORARY)
    assert _extract_job_type({"categories": {"commitment": "Freelance"}}) == str(JobType.FREELANCE)
    assert _extract_job_type({"categories": {"commitment": "Seasonal"}}) == ""
    assert _extract_job_type({"categories": {}}) == ""
    assert _extract_job_type({"categories": "nope"}) == ""
    assert _extract_job_type({}) == ""


def test_lever_department_team_fallback():
    from apps.scraping.parsers.ats_lever import _extract_department

    assert _extract_department({"categories": {"team": "Ops"}}) == "Ops"
    assert _extract_department({"categories": {"department": "Eng", "team": "Ops"}}) == "Eng"
    assert _extract_department({"categories": "nope"}) == ""


def test_work_mode_from_text():
    from apps.jobs.enums import WorkMode
    from apps.scraping.parsers._common import work_mode_from_text

    assert work_mode_from_text("Remote - US") == str(WorkMode.REMOTE)
    assert work_mode_from_text("Hybrid Remote, Berlin") == str(WorkMode.HYBRID)
    assert work_mode_from_text("Onsite, Pune") == str(WorkMode.ONSITE)
    assert work_mode_from_text("Work From Home") == str(WorkMode.REMOTE)
    assert work_mode_from_text("Bengaluru, India") == ""
    assert work_mode_from_text(None, "") == ""
    assert work_mode_from_text("Bengaluru", "Remote Engineer") == str(WorkMode.REMOTE)


def test_ashby_work_mode():
    from apps.jobs.enums import WorkMode
    from apps.scraping.parsers.ats_ashby import _extract_work_mode

    assert _extract_work_mode({"isRemote": True}) == str(WorkMode.REMOTE)
    assert _extract_work_mode({"isRemote": False, "locationName": "Hybrid, NY"}) == str(
        WorkMode.HYBRID
    )
    assert _extract_work_mode({"locationName": "Austin, TX"}) == ""


def test_greenhouse_work_mode():
    from apps.jobs.enums import WorkMode
    from apps.scraping.parsers.ats_greenhouse import _extract_work_mode

    assert _extract_work_mode({"location": {"name": "Remote"}}) == str(WorkMode.REMOTE)
    assert _extract_work_mode({"location": {"name": "Hybrid - London"}}) == str(WorkMode.HYBRID)
    assert _extract_work_mode({"location": "bad"}) == ""
    assert _extract_work_mode({}) == ""
