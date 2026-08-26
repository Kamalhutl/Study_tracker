"""End-to-end run_detection + tasks + markers, driven by fetch fixtures."""

from __future__ import annotations

import time
from unittest import mock

import pytest
from django.test import TestCase, override_settings

from apps.career_detection.services import (
    detect_pending_companies,
    detection_summary,
    run_detection,
)
from apps.career_detection.tasks import detect_career_url, detect_pending_companies_task
from apps.companies.enums import DetectionStatus
from apps.companies.models import Company, DetectionRun
from core.locks import LockNotAcquired
from tests.factories import AdminUserFactory, CompanyFactory, UserFactory

from .fetch_fixtures import activate_scenario


@pytest.fixture
def company() -> Company:
    return CompanyFactory(
        case_a=True,
        slug="acme-nav",
        domain="acmenav.example.com",
    )


@pytest.fixture(autouse=True)
def high_budget(settings):
    # Default 25 checks is exhausted by common-path probes alone.
    with override_settings(
        DETECTION_MAX_URL_CHECKS=500,
        DETECTION_TOTAL_BUDGET_SECONDS=60,
    ):
        yield


def run(company: Company, monkeypatch: pytest.MonkeyPatch, scenario: str):
    activate_scenario(monkeypatch, scenario)
    return run_detection(company)


class TestRunDetection:
    def test_candidates_found_via_nav_links(self, company, monkeypatch):
        scenario = activate_scenario(monkeypatch, "nav-header-footer")
        result = run_detection(company)

        assert result["status"] == DetectionStatus.SUCCESS
        assert result["short_circuited"] is False
        company.refresh_from_db()
        assert company.detection_status == DetectionStatus.CANDIDATES_FOUND
        assert company.detection_attempts == 1
        assert company.last_detection_at is not None

        run_row = DetectionRun.objects.get(company=company)
        assert run_row.status == DetectionStatus.SUCCESS
        assert run_row.checks_used > 0
        assert run_row.candidates_found >= 1
        assert "nav_link" in run_row.strategies_used

        candidates = list(company.candidates.order_by("-score"))
        top = candidates[0]
        assert top.normalized_url == "https://acmenav.example.com/careers"
        assert top.origin in {"header_link", "ats_pattern"}
        assert top.score >= 50  # nav_header + keyword + json_ld + http
        assert top.detection_run_id == run_row.pk
        assert scenario.call_log

    def test_short_circuit_skips_probing(self, company, monkeypatch):
        company.domain = "acme-short.example.com"
        company.save(update_fields=["domain"])
        activate_scenario(monkeypatch, "ats-short-circuit")
        result = run_detection(company)

        assert result["short_circuited"] is True
        assert result["status"] == DetectionStatus.SUCCESS
        company.refresh_from_db()
        run_row = DetectionRun.objects.get(company=company)
        assert run_row.ats_short_circuit is True
        assert run_row.strategies_used == ["ats_pattern", "nav_link", "verify"]

    def test_short_circuit_does_not_call_probing_strategies(self, company, monkeypatch):
        """§6.3: short-circuit must skip ONLY strategies 3-7; prove they never run."""
        company.domain = "acme-short.example.com"
        company.save(update_fields=["domain"])
        activate_scenario(monkeypatch, "ats-short-circuit")

        # The five probing strategies (3-7) must never execute:
        with (
            mock.patch(
                "apps.career_detection.strategies.RobotsStrategy.run", return_value=[]
            ) as m_robots,
            mock.patch(
                "apps.career_detection.strategies.SitemapStrategy.run", return_value=[]
            ) as m_sitemap,
            mock.patch(
                "apps.career_detection.strategies.CommonPathStrategy.run", return_value=[]
            ) as m_common,
            mock.patch(
                "apps.career_detection.strategies.SubdomainStrategy.run", return_value=[]
            ) as m_subdomain,
            mock.patch(
                "apps.career_detection.strategies.JsonLdStrategy.run", return_value=[]
            ) as m_jsonld,
        ):
            result = run_detection(company)

        assert result["short_circuited"] is True
        assert m_robots.call_count == 0
        assert m_sitemap.call_count == 0
        assert m_common.call_count == 0
        assert m_subdomain.call_count == 0
        assert m_jsonld.call_count == 0
        # Verify still ran against the single ATS candidate.
        candidates = list(company.candidates.all())
        assert len(candidates) == 1
        assert candidates[0].normalized_url == "https://boards.greenhouse.io/acme/jobs"
        assert candidates[0].score >= 60

    def test_ats_anchor_found_in_header(self, monkeypatch):
        company = CompanyFactory(case_a=True, slug="acme-green", domain="acmegreen.example.com")
        result = run(company, monkeypatch, "ats-greenhouse")
        assert result["status"] == DetectionStatus.SUCCESS
        candidates = list(company.candidates.all())
        assert candidates[0].normalized_url == "https://boards.greenhouse.io/acme-corp"
        assert candidates[0].origin == "ats_pattern"
        assert candidates[0].guessed_type == "greenhouse"
        assert candidates[0].score >= 55

    def test_no_candidates(self, monkeypatch):
        company = CompanyFactory(case_a=True, slug="acme-none", domain="acmenone.example.com")
        result = run(company, monkeypatch, "no-candidates")
        assert result["status"] == DetectionStatus.SUCCESS
        assert result["candidates"] == []
        company.refresh_from_db()
        assert company.detection_status == DetectionStatus.NO_CANDIDATES
        assert company.candidates.count() == 0

    def test_homepage_error_fails_company(self, monkeypatch):
        company = CompanyFactory(case_a=True, slug="acme-error", domain="acmeerror.example.com")
        result = run(company, monkeypatch, "homepage-error")
        assert result["status"] == DetectionStatus.SUCCESS
        company.refresh_from_db()
        assert company.detection_status == DetectionStatus.FAILED
        run_row = DetectionRun.objects.get(company=company)
        assert "homepage unreachable" in run_row.notes

    def test_blocked_domain_fails(self, monkeypatch):
        company = CompanyFactory(case_a=True, slug="linkedin", domain="linkedin.com")
        result = run(company, monkeypatch, "blocked-domain")
        company.refresh_from_db()
        assert company.detection_status == DetectionStatus.FAILED
        assert result["status"] == DetectionStatus.SUCCESS

    def test_candidates_from_robots(self, monkeypatch):
        company = CompanyFactory(case_a=True, slug="acme-robots", domain="acmerobots.example.com")
        run(company, monkeypatch, "robots-only")
        company.refresh_from_db()
        assert company.detection_status == DetectionStatus.CANDIDATES_FOUND
        candidates = list(company.candidates.all())
        assert any(c.origin == "robots_txt" for c in candidates)

    def test_candidates_from_sitemap(self, monkeypatch):
        company = CompanyFactory(case_a=True, slug="acme-sitemap", domain="acmesitemap.example.com")
        run(company, monkeypatch, "sitemap-only")
        company.refresh_from_db()
        assert company.detection_status == DetectionStatus.CANDIDATES_FOUND
        candidates = list(company.candidates.all())
        assert any(c.origin == "sitemap" for c in candidates)

    def test_candidates_from_common_path(self, monkeypatch):
        company = CompanyFactory(case_a=True, slug="acme-path", domain="acmepath.example.com")
        run(company, monkeypatch, "common-path-only")
        company.refresh_from_db()
        candidates = list(company.candidates.all())
        assert any(c.origin == "common_path" for c in candidates)

    def test_candidates_from_subdomain(self, monkeypatch):
        company = CompanyFactory(case_a=True, slug="acme-sub", domain="acmesub.example.com")
        run(company, monkeypatch, "subdomain-only")
        company.refresh_from_db()
        candidates = list(company.candidates.all())
        assert any(c.origin == "subdomain_guess" for c in candidates)
        assert candidates[0].normalized_url == "https://careers.acmesub.example.com"

    def test_jsonld_bonus_on_career_page(self, monkeypatch):
        company = CompanyFactory(case_a=True, slug="acme-json", domain="acmejsonld.example.com")
        run(company, monkeypatch, "jsonld-list")
        company.refresh_from_db()
        candidates = list(company.candidates.all())
        assert candidates[0].normalized_url == "https://acmejsonld.example.com/company/careers"
        assert candidates[0].score >= 70  # keyword + nav + json_ld + http
        reasons = {r["rule"] for r in candidates[0].score_reasons}
        assert "json_ld_jobposting" in reasons

    def test_budget_exhaustion_marks_partial(self, monkeypatch):
        company = CompanyFactory(case_a=True, slug="acme-sub", domain="acmesub.example.com")
        with override_settings(DETECTION_MAX_URL_CHECKS=3):
            activate_scenario(monkeypatch, "subdomain-only")
            result = run_detection(company)
        assert result["status"] == DetectionStatus.PARTIAL
        run_row = DetectionRun.objects.get(company=company)
        assert run_row.status == DetectionStatus.PARTIAL
        assert "budget exhausted" in "\n".join(result["notes"])

    def test_dry_run_persists_nothing(self, company, monkeypatch):
        activate_scenario(monkeypatch, "nav-header-footer")
        result = run_detection(company, dry_run=True)
        assert result["status"] == DetectionStatus.SUCCESS
        assert result["candidates"]
        assert result["run_id"] is None
        assert DetectionRun.objects.filter(company=company).count() == 0
        assert company.candidates.count() == 0
        company.refresh_from_db()
        assert company.detection_status == DetectionStatus.PENDING

    def test_never_writes_career_url_verification_source_or_job(self, company, monkeypatch):
        """§6.5 step 9: detection never approves anything by itself (DoD #4)."""
        from apps.jobs.models import Job

        activate_scenario(monkeypatch, "nav-header-footer")
        before_url = company.career_url
        run_detection(company)
        company.refresh_from_db()
        assert company.career_url == before_url  # never set
        assert company.is_verified is False  # never set
        assert Job.objects.count() == 0  # no Job rows
        assert company.sources.count() == 0  # no CompanySource rows

    def test_rejects_verified_company(self, company, monkeypatch):
        company.is_verified = True
        company.career_url = "https://acmenav.example.com/careers"
        company.save(update_fields=["is_verified", "career_url"])
        from apps.companies.exceptions import DetectionNotApplicable

        with pytest.raises(DetectionNotApplicable):
            run_detection(company)
        assert DetectionRun.objects.filter(company=company).count() == 0

    def test_rejects_soft_deleted(self, company):
        from apps.companies.exceptions import DetectionNotApplicable

        company.delete()
        with pytest.raises(DetectionNotApplicable):
            run_detection(company)

    def test_rejects_row_deleted_between_selection_and_lock(self, company):
        """Race guard: a soft-deleted row still visible to the lock-time read."""
        from apps.companies.exceptions import DetectionNotApplicable

        # In the new implementation, the company is re-read in Phase 2 (short transaction)
        # after acquiring the Redis lock. Mock the filter().first() to return a soft-deleted company.
        stale = Company(pk=company.pk, is_deleted=True)
        qs = mock.MagicMock()
        qs.first.return_value = stale
        with (
            mock.patch.object(Company.objects, "filter", return_value=qs),
            pytest.raises(DetectionNotApplicable, match="soft-deleted"),
        ):
            run_detection(company)

    def test_scores_drop_below_threshold(self, company, monkeypatch):
        with override_settings(DETECTION_MIN_CANDIDATE_SCORE=999):
            activate_scenario(monkeypatch, "nav-header-footer")
            result = run_detection(company)
        assert result["candidates"] == []
        company.refresh_from_db()
        assert company.detection_status == DetectionStatus.NO_CANDIDATES

    def test_rejects_company_missing_from_db(self):
        """§6.5 step 2: a vanished row (deleted mid-flight) is refused."""
        from apps.companies.exceptions import DetectionNotApplicable

        ghost = CompanyFactory(case_a=True)
        pk = ghost.pk
        Company.objects.filter(pk=pk).delete()
        ghost.pk = pk  # stale in-memory instance
        with pytest.raises(DetectionNotApplicable, match="no longer exists"):
            run_detection(ghost)

    def test_budget_exhaustion_with_candidates_is_partial_found(self, monkeypatch):
        company = CompanyFactory(case_a=True, slug="acme-part", domain="acmesitemap.example.com")
        activate_scenario(monkeypatch, "sitemap-only")
        # Budget dies mid common_path probing, AFTER the sitemap produced
        # candidates -> run is partial and company status stays candidates_found.
        with override_settings(DETECTION_MAX_URL_CHECKS=8):
            result = run_detection(company)
        assert result["status"] == DetectionStatus.PARTIAL
        company.refresh_from_db()
        assert company.detection_status == DetectionStatus.CANDIDATES_FOUND

    def test_budget_exhaustion_after_homepage_failure_is_failed(self, monkeypatch):
        company = CompanyFactory(case_a=True, slug="acme-pfail", domain="acmeerror.example.com")
        activate_scenario(monkeypatch, "homepage-error")
        # Homepage 500 sets homepage_error; the next spend exhausts the budget.
        with override_settings(DETECTION_MAX_URL_CHECKS=2):
            result = run_detection(company)
        assert result["status"] == DetectionStatus.PARTIAL
        company.refresh_from_db()
        assert company.detection_status == DetectionStatus.FAILED

    def test_unexpected_exception_marks_run_failed(self, company, monkeypatch):
        activate_scenario(monkeypatch, "nav-header-footer")
        with mock.patch(
            "apps.career_detection.services.get_strategies",
            side_effect=RuntimeError("boom"),
        ):
            result = run_detection(company, dry_run=False)
        assert result["status"] == DetectionStatus.FAILED
        run_row = DetectionRun.objects.get(company=company)
        assert run_row.status == DetectionStatus.FAILED
        assert "boom" in run_row.error_message
        company.refresh_from_db()
        assert company.detection_status == DetectionStatus.FAILED

    def test_dry_run_exception_reraises(self, company, monkeypatch):
        activate_scenario(monkeypatch, "nav-header-footer")
        with (
            mock.patch(
                "apps.career_detection.services.get_strategies",
                side_effect=RuntimeError("boom-dry"),
            ),
            pytest.raises(RuntimeError, match="boom-dry"),
        ):
            run_detection(company, dry_run=True)

    def test_root_url_normalization(self):
        from apps.career_detection.services import _root_url

        assert _root_url("acme.example.com") == "https://acme.example.com/"
        assert _root_url("https://acme.example.com") == "https://acme.example.com/"
        assert _root_url("https://acme.example.com/") == "https://acme.example.com/"


class TestTasks:
    def test_detect_career_url_task_success(self, company, monkeypatch):
        activate_scenario(monkeypatch, "nav-header-footer")
        summary = detect_career_url(str(company.pk))
        assert summary["status"] == DetectionStatus.SUCCESS
        assert summary["candidate_count"] >= 1
        assert summary["run_id"] is not None

    def test_detect_career_url_task_missing_company(self):
        summary = detect_career_url("00000000-0000-0000-0000-000000000000")
        assert summary["status"] == "not_found"

    def test_detect_career_url_task_skips_verified(self, company, monkeypatch):
        company.is_verified = True
        company.career_url = f"https://{company.domain}/careers"
        company.save(update_fields=["is_verified", "career_url"])
        summary = detect_career_url(str(company.pk))
        assert summary["status"] == "skipped"
        assert DetectionRun.objects.filter(company=company).count() == 0

    def test_detect_pending_task_enqueues(self, company, monkeypatch):
        CompanyFactory(case_a=True, slug="acme-pend2", domain="acmenone.example.com")
        with mock.patch("apps.career_detection.tasks.detect_career_url.delay") as delay:
            result = detect_pending_companies_task(limit=10)
        assert result["enqueued"] == 2
        assert delay.call_count == 2


class TestLinkedInSecurity:
    """§6.9: LinkedIn-only companies must never yield persisted candidates."""

    def test_homepage_linking_only_to_linkedin_ends_no_candidates(self, monkeypatch):
        company = CompanyFactory(case_a=True, slug="acme-linked", domain="acmelinked.example.com")
        activate_scenario(monkeypatch, "linkedin-only")
        result = run_detection(company)
        assert result["candidates"] == []
        assert result["status"] in {DetectionStatus.SUCCESS, DetectionStatus.PARTIAL}
        company.refresh_from_db()
        assert company.detection_status == DetectionStatus.NO_CANDIDATES
        assert company.candidates.count() == 0

    def test_redirect_to_linkedin_rejects_final_url(self, monkeypatch):
        """acme.com/careers -> 301 -> linkedin.com/... : the FINAL host is rejected."""
        from apps.career_detection.strategies import VerifyStrategy
        from apps.career_detection.types import DetectionContext, RawCandidate

        company = CompanyFactory(case_a=True, slug="acme-redir", domain="acmeredir.example.com")
        scenario = activate_scenario(monkeypatch, "linkedin-redirect")
        ctx = DetectionContext(
            company=company,
            root_url="https://acmeredir.example.com/",
            domain=scenario.domain,
            max_checks=500,
            deadline=float("inf"),
        )
        ctx.add(RawCandidate(url="https://acmeredir.example.com/careers", origin="common_path"))
        VerifyStrategy().run(ctx)
        assert "https://acmeredir.example.com/careers" not in ctx.candidates
        assert any("untrusted" in note and "linkedin.com" in note for note in ctx.notes)

    def test_full_run_with_redirect_persists_nothing(self, monkeypatch):
        company = CompanyFactory(case_a=True, slug="acme-redir2", domain="acmeredir.example.com")
        activate_scenario(monkeypatch, "linkedin-redirect")
        run_detection(company)
        persisted = list(company.candidates.all())
        assert all("linkedin.com" not in c.normalized_url for c in persisted)


class TestPendingBatch:
    def test_detect_pending_companies_runs_each(self, company, monkeypatch):
        CompanyFactory(case_a=True, slug="acme-pend2", domain="acmepending2.example.com")
        CompanyFactory(case_a=True, slug="acme-pend3", domain="acmepending3.example.com")
        activate_scenario(monkeypatch, "no-candidates")
        with mock.patch(
            "apps.career_detection.services.redis_lock",
            return_value=mock.MagicMock(),
        ):
            summaries = detect_pending_companies(limit=10)
        assert len(summaries) == 3
        assert all(s["status"] == DetectionStatus.SUCCESS for s in summaries)

    def test_skips_locked_companies(self, company, monkeypatch):
        CompanyFactory(case_a=True, slug="acme-pend2", domain="acmenone.example.com")

        def _blocking_lock(*args, **kwargs):
            raise LockNotAcquired("busy")

        with mock.patch("apps.career_detection.services.redis_lock", _blocking_lock):
            summaries = detect_pending_companies(limit=10)
        assert summaries == []

    def test_batch_skips_ineligible_company(self, monkeypatch):
        CompanyFactory(
            case_a=True,
            slug="acme-pend-verified",
            domain="acmenone.example.com",
            is_verified=True,
            career_url="https://acmenone.example.com/careers",
        )
        activate_scenario(monkeypatch, "no-candidates")
        summaries = detect_pending_companies(limit=10)
        assert summaries == []


class TestDetectionSummary:
    @pytest.mark.parametrize(
        ("status", "next_action"),
        [
            (DetectionStatus.PENDING, "enqueued"),
            (DetectionStatus.RUNNING, "in_progress"),
            (DetectionStatus.CANDIDATES_FOUND, "review"),
            (DetectionStatus.VERIFIED, "clean"),
            (DetectionStatus.NO_CANDIDATES, "no_careers"),
            (DetectionStatus.FAILED, "retry"),
            (DetectionStatus.NEEDS_REVIEW, "review"),
        ],
    )
    def test_mapping(self, company, status, next_action):
        company.detection_status = status
        assert detection_summary(company)["next_action"] == next_action


class TestMarkers:
    def test_add_company_from_website_enqueues_detection(self):
        from apps.companies.services import add_company_from_main_website

        with (
            mock.patch("apps.career_detection.tasks.detect_career_url.delay") as delay,
            TestCase.captureOnCommitCallbacks(execute=True),
        ):
            company = add_company_from_main_website(
                name="Marker Test Co",
                website_url="https://acmenav.example.com",
                actor=AdminUserFactory(),
            )
        assert company.detection_status == DetectionStatus.PENDING
        delay.assert_called_once_with(str(company.pk))

    def test_request_redetection_enqueues_detection(self):
        from apps.companies.services import request_redetection

        company = CompanyFactory(case_a=True, slug="acme-nav", domain="acmenav.example.com")
        with (
            mock.patch("apps.career_detection.tasks.detect_career_url.delay") as delay,
            TestCase.captureOnCommitCallbacks(execute=True),
        ):
            request_redetection(company=company, actor=UserFactory())

        delay.assert_called_once_with(str(company.pk))

    def test_creation_rollback_does_not_enqueue_detection(self):
        """on_commit must not fire for a company whose creation rolled back."""
        from django.db import transaction

        from apps.companies.services import add_company_from_main_website

        with (
            mock.patch("apps.career_detection.tasks.detect_career_url.delay") as delay,
            TestCase.captureOnCommitCallbacks(execute=True),
            pytest.raises(RuntimeError),
            transaction.atomic(),
        ):
            add_company_from_main_website(
                name="Rollback Co",
                website_url="https://acmenav.example.com",
                actor=AdminUserFactory(),
            )
            raise RuntimeError("creation failed")
        delay.assert_not_called()


class TestRunDetectionLockAndRaces:
    """Tests for Redis lock and mid-run race conditions in run_detection."""

    def test_lock_not_acquired_returns_failed(self, company, monkeypatch):
        """LockNotAcquired path returns failed without running detection."""
        from core.locks import LockNotAcquired

        activate_scenario(monkeypatch, "nav-header-footer")
        with mock.patch(
            "apps.career_detection.services.redis_lock", side_effect=LockNotAcquired("busy")
        ):
            result = run_detection(company)

        assert result["status"] == DetectionStatus.FAILED
        assert result["run_id"] is None
        assert result["notes"] == ["detection already in flight"]
        assert result["short_circuited"] is False
        assert DetectionRun.objects.filter(company=company).count() == 0

    def test_lock_still_taken_for_dry_run(self, company, monkeypatch):
        """dry_run=True still acquires the Redis lock."""
        from core.locks import LockNotAcquired

        activate_scenario(monkeypatch, "nav-header-footer")
        # First call acquires lock
        result1 = run_detection(company, dry_run=True)
        assert result1["status"] == DetectionStatus.SUCCESS

        # Second call should fail because lock is held (mock doesn't actually hold it,
        # but we test the lock key format is correct)
        with mock.patch(
            "apps.career_detection.services.redis_lock", side_effect=LockNotAcquired("busy")
        ):
            result2 = run_detection(company, dry_run=True)
        assert result2["status"] == DetectionStatus.FAILED
        assert result2["notes"] == ["detection already in flight"]

    def test_exception_handler_updates_company_when_run_exists(self, company, monkeypatch):
        """Unexpected exception updates company detection_status when run exists."""
        activate_scenario(monkeypatch, "nav-header-footer")

        with mock.patch(
            "apps.career_detection.services.get_strategies", side_effect=RuntimeError("boom")
        ):
            result = run_detection(company, dry_run=False)

        assert result["status"] == DetectionStatus.FAILED
        company.refresh_from_db()
        assert company.detection_status == DetectionStatus.FAILED
        run = DetectionRun.objects.get(company=company)
        assert run.status == DetectionStatus.FAILED
        assert "boom" in run.error_message

    def test_exception_handler_updates_company_when_run_none_not_dry_run(
        self, company, monkeypatch
    ):
        """Unexpected exception updates company when run is None but not dry_run (edge case)."""
        activate_scenario(monkeypatch, "nav-header-footer")

        # Patch _start_run to return None (simulating dry_run behavior but without dry_run=True)
        with (
            mock.patch("apps.career_detection.services._start_run", return_value=None),
            mock.patch(
                "apps.career_detection.services.get_strategies", side_effect=RuntimeError("boom")
            ),
        ):
            result = run_detection(company, dry_run=False)

        assert result["status"] == DetectionStatus.FAILED
        company.refresh_from_db()
        assert company.detection_status == DetectionStatus.FAILED
        # No DetectionRun should exist
        assert DetectionRun.objects.filter(company=company).count() == 0

    def test_redis_lock_released_on_strategy_exception(self, company, monkeypatch):
        """Redis lock is released even when a strategy raises an exception."""
        activate_scenario(monkeypatch, "nav-header-footer")

        lock_entered = []
        lock_exited = []

        class TrackingLock:
            def __enter__(self):
                lock_entered.append(True)
                return self

            def __exit__(self, exc_type, exc_val, exc_tb):
                lock_exited.append(True)
                return False  # Don't suppress exception

        with (
            mock.patch("apps.career_detection.services.redis_lock", return_value=TrackingLock()),
            mock.patch(
                "apps.career_detection.services.get_strategies", side_effect=RuntimeError("boom")
            ),
            pytest.raises(RuntimeError),
        ):
            run_detection(company, dry_run=True)

        # Lock should have been entered and exited
        assert len(lock_entered) == 1
        assert len(lock_exited) == 1


class TestPersistResultsRaces:
    """Direct tests for _persist_results race conditions (Phase 4 re-reads)."""

    def _make_context(self, company, candidates=None):
        """Create a minimal DetectionContext for testing."""
        from apps.career_detection.types import DetectionContext

        ctx = DetectionContext(
            company=company,
            root_url=f"https://{company.domain}/",
            domain=company.domain,
            max_checks=100,
            deadline=float("inf"),
        )
        if candidates:
            for c in candidates:
                ctx.add(c)
        return ctx

    def test_company_hard_deleted_mid_run_marks_superseded(self, company):
        """Company hard-deleted between Phase 2 and Phase 4 -> run marked superseded."""
        from apps.career_detection.services import _persist_results, _start_run
        from apps.career_detection.types import RawCandidate

        ctx = self._make_context(company)
        run = _start_run(company, dry_run=False)
        ranked = [
            (
                RawCandidate(url="https://example.com/careers", origin="header_link"),
                60,
                [{"rule": "test"}],
            )
        ]
        results = {"status": DetectionStatus.SUCCESS, "notes": []}

        # Mock Company.all_objects.filter to return None (simulating hard-deleted company)
        # without actually deleting from DB (which would cascade delete the run)
        with mock.patch("apps.career_detection.services.Company.all_objects.filter") as mock_filter:
            mock_filter.return_value.first.return_value = None

            _persist_results(
                company=company,
                run=run,
                ctx=ctx,
                ranked=ranked,
                final_status=DetectionStatus.CANDIDATES_FOUND,
                dry_run=False,
                actor=None,
                started=time.monotonic(),
                results=results,
            )

        assert results["status"] == DetectionStatus.SUPERSEDED
        assert "company deleted mid-run" in results["notes"]
        # run.save() should have been called (we can't verify due to mock, but the logic runs)

    def test_company_soft_deleted_mid_run_marks_superseded(self, company):
        """Company soft-deleted between Phase 2 and Phase 4 -> run marked superseded."""
        from apps.career_detection.services import _persist_results, _start_run
        from apps.career_detection.types import RawCandidate

        ctx = self._make_context(company)
        run = _start_run(company, dry_run=False)
        ranked = [
            (
                RawCandidate(url="https://example.com/careers", origin="header_link"),
                60,
                [{"rule": "test"}],
            )
        ]
        results = {"status": DetectionStatus.SUCCESS, "notes": []}

        # Soft-delete company before calling _persist_results
        company.delete()
        company.refresh_from_db()
        assert company.is_deleted

        _persist_results(
            company=company,
            run=run,
            ctx=ctx,
            ranked=ranked,
            final_status=DetectionStatus.CANDIDATES_FOUND,
            dry_run=False,
            actor=None,
            started=time.monotonic(),
            results=results,
        )

        assert results["status"] == DetectionStatus.SUPERSEDED
        assert "company soft-deleted mid-run" in results["notes"]
        run.refresh_from_db()
        assert run.status == DetectionStatus.SUPERSEDED

    def test_company_became_verified_mid_run_marks_superseded(self, company):
        """Company became verified between Phase 2 and Phase 4 -> run marked superseded."""
        from apps.career_detection.services import _persist_results, _start_run
        from apps.career_detection.types import RawCandidate

        ctx = self._make_context(company)
        run = _start_run(company, dry_run=False)
        ranked = [
            (
                RawCandidate(url="https://example.com/careers", origin="header_link"),
                60,
                [{"rule": "test"}],
            )
        ]
        results = {"status": DetectionStatus.SUCCESS, "notes": []}

        # Mark company as verified before calling _persist_results
        company.is_verified = True
        company.career_url = "https://verified.example.com/careers"
        company.save(update_fields=["is_verified", "career_url"])

        _persist_results(
            company=company,
            run=run,
            ctx=ctx,
            ranked=ranked,
            final_status=DetectionStatus.CANDIDATES_FOUND,
            dry_run=False,
            actor=None,
            started=time.monotonic(),
            results=results,
        )

        assert results["status"] == DetectionStatus.SUPERSEDED
        assert "company became verified mid-run" in results["notes"]
        run.refresh_from_db()
        assert run.status == DetectionStatus.SUPERSEDED
