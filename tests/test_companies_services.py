"""Companies services — add paths, candidate lifecycle, scheduling, audit rows."""

import pytest
from django.core.exceptions import ValidationError

from apps.audit_logs.models import AuditLog
from apps.companies import services
from apps.companies.enums import (
    CareerSourceType,
    DetectionStatus,
    ScrapeHealth,
    SourceInputType,
)
from apps.companies.exceptions import (
    BlockedDomain,
    CandidateAlreadyDecided,
    DuplicateCompany,
    InvalidCompanyTransition,
)
from apps.companies.models import Company, CompanySource
from apps.jobs.models import Job
from tests.factories import (
    AdminUserFactory,
    CandidateFactory,
    CompanyFactory,
    CompanySourceFactory,
    JobFactory,
)


@pytest.fixture
def actor():
    return AdminUserFactory()


def _audit(action: str) -> int:
    return AuditLog.objects.filter(action=action).count()


class TestCaseA:
    def test_creates_pending_unverified(self, actor):
        company = services.add_company_from_main_website(
            name="Website Co", website_url="https://website.example", actor=actor
        )
        assert company.input_type == SourceInputType.MAIN_WEBSITE
        assert company.detection_status == DetectionStatus.PENDING
        assert company.is_verified is False
        assert company.career_url == ""
        assert company.next_scrape_at is None
        assert company.domain == "website.example"

    def test_duplicate_domain_raises(self, actor):
        services.add_company_from_main_website(
            name="Dupe Co", website_url="https://dupe.example", actor=actor
        )
        with pytest.raises(DuplicateCompany):
            services.add_company_from_main_website(
                name="Dupe Co 2", website_url="https://dupe.example", actor=actor
            )

    def test_blocked_domain_raises(self, actor):
        with pytest.raises(BlockedDomain):
            services.add_company_from_main_website(
                name="Nope", website_url="https://linkedin.com/company/x", actor=actor
            )

    def test_audit_row_written(self, actor):
        services.add_company_from_main_website(
            name="Audit Co", website_url="https://auditco.example", actor=actor
        )
        assert _audit("company.created") == 1


class TestCaseB:
    def test_creates_verified_scheduled(self, actor):
        company = services.add_company_from_direct_career_url(
            name="Direct Co", career_url="https://direct.example/careers", actor=actor
        )
        assert company.input_type == SourceInputType.DIRECT_CAREER
        assert company.detection_status == DetectionStatus.SKIPPED
        assert company.is_verified is True
        assert company.career_url == "https://direct.example/careers"
        assert company.next_scrape_at is not None
        assert company.scrape_health == ScrapeHealth.UNKNOWN
        assert company.verified_by == actor

    def test_source_history_created(self, actor):
        company = services.add_company_from_direct_career_url(
            name="Hist Co", career_url="https://boards.greenhouse.io/histco", actor=actor
        )
        source = CompanySource.objects.get(company=company, is_current=True)
        assert source.url == company.career_url
        assert source.reason == "direct career url"

    def test_greenhouse_sniffed(self, actor):
        company = services.add_company_from_direct_career_url(
            name="Gh Co", career_url="https://boards.greenhouse.io/acmejobs", actor=actor
        )
        assert company.career_source_type == CareerSourceType.GREENHOUSE
        assert company.ats_identifier == "acmejobs"

    def test_short_interval_rejected(self, actor):
        with pytest.raises(ValidationError):
            services.add_company_from_direct_career_url(
                name="Fast Co",
                career_url="https://fast.example/careers",
                actor=actor,
                scrape_interval_minutes=10,
            )

    def test_interval_applied(self, actor):
        company = services.add_company_from_direct_career_url(
            name="Interval Co",
            career_url="https://interval.example/careers",
            actor=actor,
            scrape_interval_minutes=60,
        )
        assert company.scrape_interval_minutes == 60

    def test_audit_rows_written(self, actor):
        services.add_company_from_direct_career_url(
            name="Audit B Co", career_url="https://auditb.example/careers", actor=actor
        )
        assert _audit("company.created") == 1
        assert _audit("company.verified") == 1


class TestApproveCandidate:
    def test_full_approval_path(self, actor):
        company = CompanyFactory(case_a=True, slug="cand-co")
        CompanySourceFactory(company=company)
        candidate = CandidateFactory(
            company=company,
            url="https://boards.lever.co/approve-me",
            normalized_url="https://boards.lever.co/approve-me",
        )
        sibling = CandidateFactory(
            company=company, url="https://board2.example", normalized_url="https://board2.example"
        )

        updated = services.approve_career_candidate(candidate=candidate, actor=actor)

        candidate.refresh_from_db()
        sibling.refresh_from_db()
        assert candidate.status == "approved"
        assert candidate.decided_by == actor
        assert sibling.status == "rejected"
        assert sibling.reject_reason == "another candidate approved"

        assert updated.is_verified is True
        assert updated.detection_status == DetectionStatus.VERIFIED
        assert updated.career_url == candidate.url
        assert updated.career_source_type == candidate.guessed_type
        assert updated.consecutive_failures == 0
        assert updated.next_scrape_at is not None
        assert updated.scrape_health == ScrapeHealth.UNKNOWN

        current = CompanySource.objects.get(company=company, is_current=True)
        assert current.url == candidate.url
        assert current.reason == "approved candidate"
        assert CompanySource.objects.filter(company=company, is_current=False).count() >= 1

        assert _audit("career_candidate.approved") == 1

    def test_approve_twice_raises(self, actor):
        company = CompanyFactory(case_a=True, slug="twice-co")
        candidate = CandidateFactory(company=company)
        services.approve_career_candidate(candidate=candidate, actor=actor)
        with pytest.raises(CandidateAlreadyDecided):
            services.approve_career_candidate(candidate=candidate, actor=actor)

    def test_approve_second_candidate_refused(self, actor):
        company = CompanyFactory(case_a=True, slug="two-cand")
        c1 = CandidateFactory(company=company)
        c2 = CandidateFactory(company=company)
        services.approve_career_candidate(candidate=c1, actor=actor)
        c2.refresh_from_db()
        with pytest.raises(CandidateAlreadyDecided):
            services.approve_career_candidate(candidate=c2, actor=actor)

    def test_verified_with_different_url_raises(self, actor):
        company = CompanyFactory(
            slug="different-url", career_url="https://original.example/careers"
        )
        c1 = CandidateFactory(company=company)
        with pytest.raises(InvalidCompanyTransition):
            services.approve_career_candidate(candidate=c1, actor=actor)


class TestRejectCandidate:
    def test_rejects_and_keeps_company_review(self, actor):
        company = CompanyFactory(needs_review=True, slug="rej-co")
        c1 = CandidateFactory(company=company)
        CandidateFactory(company=company)
        services.reject_career_candidate(candidate=c1, actor=actor, reason="bad url")
        c1.refresh_from_db()
        assert c1.status == "rejected"
        assert c1.reject_reason == "bad url"
        company.refresh_from_db()
        assert company.detection_status == DetectionStatus.NEEDS_REVIEW

    def test_last_pending_flips_to_not_found(self, actor):
        company = CompanyFactory(needs_review=True, slug="last-co")
        candidate = CandidateFactory(company=company)
        services.reject_career_candidate(candidate=candidate, actor=actor)
        company.refresh_from_db()
        assert company.detection_status == DetectionStatus.NOT_FOUND

    def test_audit_row(self, actor):
        company = CompanyFactory(needs_review=True, slug="rej-audit")
        services.reject_career_candidate(candidate=CandidateFactory(company=company), actor=actor)
        assert _audit("career_candidate.rejected") == 1


class TestManualCareerUrl:
    def test_retires_old_source_and_audits(self, actor):
        company = CompanyFactory(slug="man-co")
        old = CompanySourceFactory(company=company)
        services.set_manual_career_url(
            company=company, career_url="https://boards.greenhouse.io/newco", actor=actor
        )
        company.refresh_from_db()
        old.refresh_from_db()
        assert old.is_current is False
        assert old.retired_at is not None
        assert company.career_url == "https://boards.greenhouse.io/newco"
        assert company.career_source_type == CareerSourceType.GREENHOUSE
        assert company.detection_status == DetectionStatus.MANUAL
        assert _audit("company.career_url_changed") == 1

    def test_audit_has_before_after(self, actor):
        company = CompanyFactory(slug="man-audit")
        services.set_manual_career_url(
            company=company, career_url="https://other.example/careers", actor=actor
        )
        row = AuditLog.objects.get(action="company.career_url_changed")
        assert row.before and row.after


class TestRedetection:
    def test_resets_status_and_rejects_pending(self, actor):
        company = CompanyFactory(slug="redet-co")
        c1 = CandidateFactory(company=company)
        services.request_redetection(company=company, actor=actor)
        c1.refresh_from_db()
        company.refresh_from_db()
        assert company.detection_status == DetectionStatus.PENDING
        assert c1.status == "rejected"
        assert c1.reject_reason == "redetection requested"
        assert _audit("company.redetection_requested") == 1


class TestPauseResume:
    def test_pause_resume_roundtrip(self, actor):
        company = CompanyFactory(slug="pr-co")
        services.pause_company(company=company, actor=actor, reason="demo maintenance")
        company.refresh_from_db()
        assert company.is_active is False
        assert company.scrape_health == ScrapeHealth.PAUSED
        assert company.next_scrape_at is None
        assert company.notes == "demo maintenance"

        services.resume_company(company=company, actor=actor)
        company.refresh_from_db()
        assert company.is_active is True
        assert company.scrape_health == ScrapeHealth.UNKNOWN
        assert company.consecutive_failures == 0
        assert company.next_scrape_at is not None
        assert _audit("company.paused") == 1
        assert _audit("company.resumed") == 1


class TestArchive:
    def test_archive_unpublishes_jobs(self, actor):
        company = CompanyFactory(slug="arch-co")
        jobs = [JobFactory(company=company) for _ in range(3)]
        services.archive_company(company=company, actor=actor)
        archived = Company.all_objects.get(pk=company.pk)
        assert archived.is_deleted is True
        assert all(Job.objects.get(pk=j.pk).is_published is False for j in jobs)
        assert _audit("company.archived") == 1

    def test_unarchive_restores(self, actor):
        company = CompanyFactory(slug="unarch-co")
        services.archive_company(company=company, actor=actor)
        services.unarchive_company(company=company, actor=actor)
        company.refresh_from_db()
        assert company.is_deleted is False
        assert _audit("company.unarchived") == 1


class TestScrapeInterval:
    def test_below_minimum_raises(self, actor):
        company = CompanyFactory(slug="min-int")
        with pytest.raises(ValidationError):
            services.update_scrape_interval(company=company, minutes=20, actor=actor)

    def test_updates_and_recomputes(self, actor):
        company = CompanyFactory(slug="new-int")
        services.update_scrape_interval(company=company, minutes=120, actor=actor)
        company.refresh_from_db()
        assert company.scrape_interval_minutes == 120
        assert company.next_scrape_at is not None
        assert _audit("company.scrape_interval_changed") == 1


class TestFailuresReset:
    def test_resets_failures_and_audits(self, actor):
        company = CompanyFactory(
            slug="reset-co",
            scrape_health=ScrapeHealth.FAILING,
            consecutive_failures=4,
            total_failures=9,
            last_failure_reason="demo outage",
        )
        services.reset_scrape_failures(company=company, actor=actor)
        company.refresh_from_db()
        assert company.consecutive_failures == 0
        assert company.last_failure_reason == ""
        assert company.scrape_health == ScrapeHealth.UNKNOWN
        assert company.total_failures == 9  # history survives
        assert _audit("company.failures_reset") == 1

    def test_paused_company_stays_paused(self, actor):
        company = CompanyFactory(slug="paused-reset", scrape_health=ScrapeHealth.PAUSED)
        services.reset_scrape_failures(company=company, actor=actor)
        company.refresh_from_db()
        assert company.scrape_health == ScrapeHealth.PAUSED


class TestDetailsUpdate:
    def test_updates_allowed_fields(self, actor):
        company = CompanyFactory(name="Old Name", slug="details-co")
        services.update_company_details(
            company=company,
            actor=actor,
            hq_location="Bengaluru",
            description="New description",
            career_url="https://hax.example",  # should be ignored (not allowed)
        )
        company.refresh_from_db()
        assert company.hq_location == "Bengaluru"
        assert company.description == "New description"
        assert company.career_url == f"https://{company.domain}/careers"
        assert _audit("company.updated") == 1
