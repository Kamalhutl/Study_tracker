"""Management command tests: detect_career_url + detect_pending (§6.8)."""

from __future__ import annotations

from typing import Any
from unittest import mock

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import override_settings

from apps.career_detection.tests.fetch_fixtures import (
    FIXTURES_DIR,
    activate_scenario,
)
from apps.companies.models import CareerCandidateUrl, DetectionRun
from tests.factories import CompanyFactory


@pytest.fixture(autouse=True)
def high_budget(settings):
    """Mirror test_services: 25 default checks starve the probing strategies."""
    with override_settings(
        DETECTION_MAX_URL_CHECKS=500,
        DETECTION_TOTAL_BUDGET_SECONDS=60,
    ):
        yield


def _company(domain: str, **kwargs: Any) -> Any:
    return CompanyFactory(case_a=True, domain=domain, **kwargs)


class TestDetectCareerUrlCommand:
    def test_dry_run_verbose_persists_nothing(self, monkeypatch, capsys) -> None:
        company = _company("acmegreen.example.com", name="Green Co")
        scenario = activate_scenario(monkeypatch, "ats-greenhouse")

        call_command(
            "detect_career_url",
            "--company",
            company.slug,
            "--dry-run",
            "--verbose",
        )
        out = capsys.readouterr().out
        assert "status=success" in out
        assert "boards.greenhouse.io/acme-corp" in out
        assert "ats_host(+40)" in out  # trail visible per §6.8
        assert "Top trail breakdown:" in out
        assert CareerCandidateUrl.objects.count() == 0
        assert DetectionRun.objects.count() == 0
        # The homepage itself was fetched exactly once (strategy 1 + free reuse).
        assert scenario.call_log.count("fetch https://acmegreen.example.com/") == 1

    def test_real_run_persists_candidates(self, monkeypatch, capsys) -> None:
        company = _company("acmenav.example.com", name="Nav Co")
        activate_scenario(monkeypatch, "nav-header-footer")

        call_command("detect_career_url", "--company", str(company.pk))
        out = capsys.readouterr().out
        assert "status=success" in out
        run = DetectionRun.objects.get(company=company)
        assert run.status == "success"
        company.refresh_from_db()
        assert company.detection_status == "candidates_found"
        assert CareerCandidateUrl.objects.filter(company=company).exists()

    def test_unknown_company_raises_command_error(self) -> None:
        with pytest.raises(CommandError, match="Unknown company"):
            call_command("detect_career_url", "--company", "does-not-exist")

    def test_ineligible_company_raises(self, monkeypatch) -> None:
        company = _company(
            "acmegreen.example.com",
            name="Already Verified",
            is_verified=True,
            career_url="https://boards.greenhouse.io/acme-corp",
        )
        activate_scenario(monkeypatch, "ats-greenhouse")
        with pytest.raises(CommandError, match="verified"):
            call_command("detect_career_url", "--company", company.slug)

    def test_max_checks_flag_is_accepted(self, monkeypatch, capsys) -> None:
        company = _company("acmenone.example.com", name="None Co")
        activate_scenario(monkeypatch, "no-candidates")

        call_command(
            "detect_career_url",
            "--company",
            company.slug,
            "--dry-run",
            "--max-checks",
            "3",
        )
        # 3 checks starve the probe strategies -> clean partial stop (§6.5 step 5).
        assert "status=partial" in capsys.readouterr().out


class TestDetectPendingCommand:
    def test_lists_and_runs_inline(self, monkeypatch, capsys) -> None:
        pending = _company("acmegreen.example.com", name="Pending Green")
        done = _company(
            "already.example.com",
            name="Done Co",
            detection_status="candidates_found",
        )
        activate_scenario(monkeypatch, "ats-greenhouse")

        call_command("detect_pending", "--limit", "10")
        out = capsys.readouterr().out
        assert str(pending.pk) in out
        assert "Processed 1 companies" in out
        done.refresh_from_db()
        assert done.detection_status == "candidates_found"

    def test_enqueue_dispatches_without_running(self, monkeypatch, capsys) -> None:
        _company("acmegreen.example.com", name="Queue Me")
        activate_scenario(monkeypatch, "ats-greenhouse")

        with mock.patch("apps.career_detection.tasks.detect_career_url.delay") as delay:
            call_command("detect_pending", "--limit", "5", "--enqueue")

        assert delay.call_count == 1
        assert DetectionRun.objects.count() == 0
        assert "Enqueued detection for 1 companies" in capsys.readouterr().out

    def test_fixture_manifest_sanity(self) -> None:
        """Fixture manifests must be valid JSON with a domain (harness sanity)."""
        manifest_json = (FIXTURES_DIR / "ats-greenhouse" / "manifest.json").read_text()
        assert '"acmegreen.example.com"' in manifest_json
