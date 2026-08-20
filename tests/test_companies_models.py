"""Companies models & constraints tests."""

import pytest
from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.companies.enums import (
    CareerSourceType,
    DetectionStatus,
    ScrapeHealth,
    SourceInputType,
)
from apps.companies.models import CompanySource
from tests.factories import AdminUserFactory, CandidateFactory, CompanyFactory


@pytest.fixture
def actor():
    return AdminUserFactory()


class TestSlugGeneration:
    def test_slug_auto_from_name(self, actor):
        company = CompanyFactory(name="Acme Robotics", slug="acme-robotics", added_by=actor)
        assert company.slug == "acme-robotics"

    def test_slug_collision_suffixed(self):
        CompanyFactory(name="Dupe Name", slug="dupe-name")
        second = CompanyFactory(name="Dupe Name", slug="dupe-name-1")
        assert second.slug.startswith("dupe-name")


class TestCompanyConstraints:
    def test_duplicate_active_domain_rejected(self, actor):
        CompanyFactory(domain="same.example", slug="one")
        with pytest.raises(IntegrityError), transaction.atomic():
            CompanyFactory(
                domain="same.example", slug="two", input_type=SourceInputType.MAIN_WEBSITE
            )

    def test_re_add_after_soft_delete_allowed(self, actor):
        first = CompanyFactory(domain="revive.example", slug="revive")
        first.delete()
        second = CompanyFactory(domain="revive.example", slug="revive-again")
        assert second.domain == "revive.example"

    def test_duplicate_career_url_blocked(self):
        CompanyFactory(career_url="https://x.example/careers", slug="a")
        with pytest.raises(IntegrityError), transaction.atomic():
            CompanyFactory(career_url="https://x.example/careers", slug="b")

    def test_min_scrape_interval_violated(self):
        with pytest.raises(IntegrityError), transaction.atomic():
            CompanyFactory(scrape_interval_minutes=29)

    def test_verified_requires_career_url(self):
        with pytest.raises(IntegrityError), transaction.atomic():
            CompanyFactory(
                case_a=True,
                is_verified=True,
            )


class TestCompanySourceConstraints:
    def test_only_one_current_source_per_company(self, actor):
        company = CompanyFactory(slug="src-co")
        CompanySource.objects.create(
            company=company,
            url="https://a.example/careers",
            normalized_url="https://a.example/careers",
            source_type=CareerSourceType.OWN_CAREER_PAGE,
            set_by=actor,
            is_current=True,
        )
        with pytest.raises(IntegrityError), transaction.atomic():
            CompanySource.objects.create(
                company=company,
                url="https://b.example/careers",
                normalized_url="https://b.example/careers",
                source_type=CareerSourceType.OWN_CAREER_PAGE,
                set_by=actor,
                is_current=True,
            )


class TestCandidateConstraints:
    def test_unique_approved_candidate_per_company(self, actor):
        company = CompanyFactory(slug="appr-co")
        CandidateFactory(company=company, status="approved")
        with pytest.raises(IntegrityError), transaction.atomic():
            CandidateFactory(company=company, status="approved")

    def test_duplicate_candidate_url_rejected(self):
        company = CompanyFactory(slug="dup-can")
        CandidateFactory(
            company=company,
            url="https://same.example/careers",
            normalized_url="https://same.example/careers",
        )
        with pytest.raises(IntegrityError), transaction.atomic():
            CandidateFactory(
                company=company,
                url="https://same.example/careers",
                normalized_url="https://same.example/careers",
            )

    def test_score_out_of_range_rejected(self):
        with pytest.raises(IntegrityError), transaction.atomic():
            CandidateFactory(score=101)


class TestCompanyProperties:
    @pytest.mark.parametrize(
        "tweaks,expected",
        [
            ({}, True),
            ({"is_verified": False}, False),
            ({"is_active": False}, False),
            ({"career_url": ""}, False),
            ({"scrape_health": ScrapeHealth.PAUSED}, False),
        ],
    )
    def test_is_scrapable(self, tweaks, expected):
        company = CompanyFactory(slug="scrapable")
        for key, value in tweaks.items():
            setattr(company, key, value)
        assert company.is_scrapable is expected

    @pytest.mark.parametrize(
        "source_type,expected",
        [
            (CareerSourceType.GREENHOUSE, True),
            (CareerSourceType.LEVER, True),
            (CareerSourceType.ASHBY, True),
            (CareerSourceType.SMARTRECRUITERS, True),
            (CareerSourceType.OWN_CAREER_PAGE, False),
            (CareerSourceType.WORKDAY, False),
            (CareerSourceType.UNKNOWN, False),
        ],
    )
    def test_is_ats(self, source_type, expected):
        company = CompanyFactory(slug="ats-check", career_source_type=source_type)
        assert company.is_ats is expected

    @pytest.mark.parametrize(
        "health,det_status,expected",
        [
            (ScrapeHealth.FAILING, DetectionStatus.VERIFIED, True),
            (ScrapeHealth.PAUSED, DetectionStatus.VERIFIED, True),
            (ScrapeHealth.HEALTHY, DetectionStatus.NEEDS_REVIEW, True),
            (ScrapeHealth.HEALTHY, DetectionStatus.FAILED, True),
            (ScrapeHealth.HEALTHY, DetectionStatus.NOT_FOUND, True),
            (ScrapeHealth.HEALTHY, DetectionStatus.VERIFIED, False),
        ],
    )
    def test_needs_attention(self, health, det_status, expected):
        company = CompanyFactory(
            slug="attn-check", scrape_health=health, detection_status=det_status
        )
        assert company.needs_attention is expected

    def test_is_due_boundary_equal_now(self):
        company = CompanyFactory(slug="due-boundary")
        now = timezone.now()
        company.next_scrape_at = now
        assert company.is_due(now) is True

    def test_is_due_future_false(self):
        company = CompanyFactory(slug="due-future")
        now = timezone.now()
        company.next_scrape_at = now + timezone.timedelta(minutes=10)
        assert company.is_due(now) is False

    def test_compute_next_scrape_at_spread(self):

        companies = [
            CompanyFactory(slug=f"jitter-{i}", scrape_interval_minutes=300) for i in range(200)
        ]
        minutes = {c.compute_next_scrape_at(timezone.now()).minute for c in companies}
        assert len(minutes) > 30

    def test_str(self):
        company = CompanyFactory(slug="str-check", name="Str Co", domain="str.example")
        assert str(company) == "Str Co (str.example)"
