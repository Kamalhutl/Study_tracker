"""sniff_source_type_from_url — 100% coverage required (DoD item 4)."""

import pytest

from apps.companies.enums import BLOCKED_DOMAINS, CareerSourceType
from apps.companies.exceptions import BlockedDomain
from apps.companies.services import sniff_source_type_from_url


@pytest.mark.parametrize(
    "url,expected_type,expected_id",
    [
        ("https://boards.greenhouse.io/acme", CareerSourceType.GREENHOUSE, "acme"),
        ("https://boards.greenhouse.io/acme/jobs/123", CareerSourceType.GREENHOUSE, "acme"),
        ("https://job-boards.greenhouse.io/acme", CareerSourceType.GREENHOUSE, "acme"),
        ("https://acme.greenhouse.io", CareerSourceType.GREENHOUSE, "acme"),
        ("https://acme.greenhouse.io/jobs", CareerSourceType.GREENHOUSE, "acme"),
        ("https://jobs.lever.co/acme", CareerSourceType.LEVER, "acme"),
        ("https://jobs.lever.co/acme/eng", CareerSourceType.LEVER, "acme"),
        ("https://acme.jobs.lever.co", CareerSourceType.LEVER, "acme"),
        ("https://acme.jobs.lever.co/eng", CareerSourceType.LEVER, "acme"),
        ("https://jobs.ashbyhq.com/acme", CareerSourceType.ASHBY, "acme"),
        ("https://acme.ashbyhq.com", CareerSourceType.ASHBY, "acme"),
        ("https://careers.smartrecruiters.com/acme", CareerSourceType.SMARTRECRUITERS, "acme"),
        ("https://jobs.smartrecruiters.com/acme/team", CareerSourceType.SMARTRECRUITERS, "acme"),
        ("https://myworkdayjobs.com/acme", CareerSourceType.WORKDAY, ""),
        ("HTTPS://ACME.MYWORKDAYJOBS.COM", CareerSourceType.WORKDAY, ""),
        ("https://acme.myworkdayjobs.com/", CareerSourceType.WORKDAY, ""),
        ("https://careers.acme.example/", CareerSourceType.OWN_CAREER_PAGE, ""),
        ("careers.acme.example/jobs", CareerSourceType.OWN_CAREER_PAGE, ""),
        ("https://acme.example/careers?v=2#top", CareerSourceType.OWN_CAREER_PAGE, ""),
        ("https://www.acme.example/careers", CareerSourceType.OWN_CAREER_PAGE, ""),
        ("https://boards.lever.co/acme", CareerSourceType.OWN_CAREER_PAGE, ""),
        ("https://acme.jobs/", CareerSourceType.OWN_CAREER_PAGE, ""),
        ("https://acme.example", CareerSourceType.OWN_CAREER_PAGE, ""),
    ],
)
def test_sniff_shapes(url, expected_type, expected_id):
    source_type, identifier = sniff_source_type_from_url(url)
    assert source_type == expected_type
    assert identifier == expected_id


@pytest.mark.parametrize("domain", sorted(BLOCKED_DOMAINS))
def test_blocked_domains_raise(domain):
    with pytest.raises(BlockedDomain):
        sniff_source_type_from_url(f"https://{domain}/careers")


@pytest.mark.parametrize("domain", sorted(BLOCKED_DOMAINS))
def test_blocked_subdomains_raise(domain):
    with pytest.raises(BlockedDomain):
        sniff_source_type_from_url(f"https://jobs.{domain}")
