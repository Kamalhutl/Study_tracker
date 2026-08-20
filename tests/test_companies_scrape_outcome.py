"""record_scrape_outcome — the health state machine (100% coverage required)."""

from datetime import datetime

import pytest
from django.utils import timezone

from apps.audit_logs.models import AuditLog
from apps.companies import services
from apps.companies.enums import ScrapeHealth
from tests.factories import CompanyFactory

BASE_INTERVAL = 300


def _company(**tweaks):
    defaults = {"slug": "smo", "scrape_interval_minutes": BASE_INTERVAL}
    defaults.update(tweaks)
    return CompanyFactory(**defaults)


def _minutes_between(a: datetime, b: datetime) -> float:
    return abs((a - b).total_seconds()) / 60


class TestSuccessPath:
    def test_unknown_to_healthy(self):
        company = _company(scrape_health=ScrapeHealth.UNKNOWN)
        now = timezone.now()
        out = services.record_scrape_outcome(company=company, success=True, jobs_seen=12, now=now)
        assert out.scrape_health == ScrapeHealth.HEALTHY
        assert out.consecutive_failures == 0
        assert out.total_scrapes == 1
        assert out.last_jobs_seen == 12
        assert out.last_failure_reason == ""
        assert out.last_successful_scrape_at == now
        assert _minutes_between(out.next_scrape_at, now) >= BASE_INTERVAL

    def test_success_after_failures_resets(self):
        company = _company(scrape_health=ScrapeHealth.FAILING, consecutive_failures=3)
        out = services.record_scrape_outcome(company=company, success=True, now=timezone.now())
        assert out.scrape_health == ScrapeHealth.HEALTHY
        assert out.consecutive_failures == 0

    def test_no_audit_on_steady_state(self):
        company = _company(scrape_health=ScrapeHealth.HEALTHY)
        services.record_scrape_outcome(company=company, success=True, now=timezone.now())
        assert AuditLog.objects.filter(action="company.scrape_outcome").count() == 0


class TestFailureLadder:
    @pytest.mark.parametrize(
        "failures,expected_health",
        [
            (1, ScrapeHealth.DEGRADED),
            (2, ScrapeHealth.DEGRADED),
            (3, ScrapeHealth.FAILING),
            (4, ScrapeHealth.FAILING),
        ],
    )
    def test_health_escalation(self, failures, expected_health):
        company = _company(scrape_health=ScrapeHealth.UNKNOWN, consecutive_failures=failures - 1)
        now = timezone.now()
        out = services.record_scrape_outcome(
            company=company, success=False, failure_reason="timeout", now=now
        )
        assert out.scrape_health == expected_health
        assert out.consecutive_failures == failures
        assert out.total_failures == 1
        assert out.is_active is True

    def test_fifth_failure_pauses(self):
        company = _company(scrape_health=ScrapeHealth.FAILING, consecutive_failures=4)
        out = services.record_scrape_outcome(
            company=company, success=False, failure_reason="boom", now=timezone.now()
        )
        assert out.scrape_health == ScrapeHealth.PAUSED
        assert out.is_active is False
        assert out.next_scrape_at is None

    @pytest.mark.parametrize(
        "failures,expected_span",
        [
            (1, BASE_INTERVAL),
            (2, BASE_INTERVAL * 2),
            (3, BASE_INTERVAL * 4),
            (4, 24 * 60),
        ],
    )
    def test_exponential_backoff(self, failures, expected_span):
        company = _company(scrape_health=ScrapeHealth.UNKNOWN, consecutive_failures=failures - 1)
        now = timezone.now()
        out = services.record_scrape_outcome(company=company, success=False, now=now)
        assert out.next_scrape_at is not None
        assert _minutes_between(out.next_scrape_at, now) >= expected_span

    def test_hard_cap_at_max_backoff(self):
        company = _company(scrape_health=ScrapeHealth.FAILING, consecutive_failures=3)
        now = timezone.now()
        out = services.record_scrape_outcome(company=company, success=False, now=now)
        assert _minutes_between(out.next_scrape_at, now) <= 24 * 60 + 60

    def test_failure_reason_truncated(self):
        company = _company()
        long_reason = "x" * 5000
        out = services.record_scrape_outcome(
            company=company, success=False, failure_reason=long_reason, now=timezone.now()
        )
        assert len(out.last_failure_reason) <= 2000


class TestAuditTransitions:
    def test_audit_only_on_transition(self):
        company = _company(scrape_health=ScrapeHealth.UNKNOWN)
        services.record_scrape_outcome(company=company, success=False, now=timezone.now())
        assert AuditLog.objects.filter(action="company.scrape_outcome").count() == 1
        services.record_scrape_outcome(company=company, success=False, now=timezone.now())
        assert AuditLog.objects.filter(action="company.scrape_outcome").count() == 1

    def test_auto_pause_writes_audit(self):
        company = _company(scrape_health=ScrapeHealth.FAILING, consecutive_failures=4)
        services.record_scrape_outcome(company=company, success=False, now=timezone.now())
        assert AuditLog.objects.filter(action="company.scrape_outcome").count() == 1

    def test_success_after_unknown_writes_audit(self):
        company = _company(scrape_health=ScrapeHealth.UNKNOWN)
        services.record_scrape_outcome(company=company, success=True, now=timezone.now())
        assert AuditLog.objects.filter(action="company.scrape_outcome").count() == 1
