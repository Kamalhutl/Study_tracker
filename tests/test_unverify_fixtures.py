"""Tests for unverify_fixtures and audit_public_surface commands."""

import contextlib

import pytest
from django.conf import settings
from django.core.management import call_command

from apps.accounts.models import User
from apps.companies.models import Company
from tests.factories import AdminUserFactory, CompanyFactory


@pytest.fixture(autouse=True)
def _flush_cache():
    yield


@pytest.fixture
def actor():
    return AdminUserFactory(email="admin@example.com")


@pytest.fixture
def fixture_company(actor):
    return CompanyFactory(
        slug="acme-robotics-test", name="Acme Robotics X", domain="acme.example", is_verified=True
    )


@pytest.fixture
def fixture_user():
    return User.objects.create_user(
        email="fixture@example.com",
        password="demo-pass-123",
        is_active=True,
    )


class TestUnverifyFixturesDryRun:
    def test_dry_run_writes_nothing(self, fixture_company, fixture_user, monkeypatch, capsys):
        monkeypatch.setattr(settings, "ALLOW_DEMO_SEED", True, raising=False)
        call_command("unverify_fixtures")
        fixture_company.refresh_from_db()
        assert fixture_company.is_verified is True
        fixture_user.refresh_from_db()
        assert fixture_user.is_active is True
        out = capsys.readouterr().out
        assert "DRY RUN" in out


class TestUnverifyFixturesApply:
    def test_apply_unverifies(self, fixture_company, fixture_user, monkeypatch, capsys):
        monkeypatch.setattr(settings, "ALLOW_DEMO_SEED", True, raising=False)
        call_command("unverify_fixtures", "--apply")
        fixture_company.refresh_from_db()
        assert fixture_company.is_verified is False
        out = capsys.readouterr().out
        assert "APPLY" in out

    def test_apply_deactivates_users(self, fixture_company, fixture_user, monkeypatch, capsys):
        monkeypatch.setattr(settings, "ALLOW_DEMO_SEED", True, raising=False)
        call_command("unverify_fixtures", "--apply")
        fixture_user.refresh_from_db()
        assert fixture_user.is_active is False

    def test_idempotent_on_second_run(self, fixture_company, fixture_user, monkeypatch, capsys):
        monkeypatch.setattr(settings, "ALLOW_DEMO_SEED", True, raising=False)
        call_command("unverify_fixtures", "--apply")
        call_command("unverify_fixtures", "--apply")
        fixture_company.refresh_from_db()
        assert fixture_company.is_verified is False
        fixture_user.refresh_from_db()
        assert fixture_user.is_active is False
        out = capsys.readouterr().out
        assert "skip (already unverified)" in out
        assert "skip (already inactive)" in out


class TestUnverifyCompanyService:
    def test_clears_fields_leaves_others(self, fixture_company):
        from apps.companies.services import unverify_company

        fixture_company.is_active = True
        fixture_company.career_url = "https://acme.example/careers"
        fixture_company.save(update_fields=["is_active", "career_url"])
        unverify_company(company=fixture_company)
        fixture_company.refresh_from_db()
        assert fixture_company.is_verified is False
        assert fixture_company.verified_by is None
        assert fixture_company.verified_at is None
        assert fixture_company.is_active is True
        assert fixture_company.career_url == "https://acme.example/careers"


class TestAuditPublicSurface:
    def test_clean_db_exits_0(self, monkeypatch, capsys):
        monkeypatch.setattr(settings, "ALLOW_DEMO_SEED", True, raising=False)
        Company.all_objects.all().delete()
        User.objects.filter(email__endswith="@example.com").delete()
        with pytest.raises(SystemExit) as exc_info:
            call_command("audit_public_surface")
        assert exc_info.value.code == 0
        out, err = capsys.readouterr()
        assert "STAYS VERIFIED" in out
        assert "SUMMARY verified=0 violations=0 clean=0" in out
        assert err == ""

    def test_planted_bad_row_exits_1(self, fixture_company, monkeypatch):
        monkeypatch.setattr(settings, "ALLOW_DEMO_SEED", True, raising=False)
        with pytest.raises(SystemExit) as exc_info:
            call_command("audit_public_surface")
        assert exc_info.value.code == 1

    def test_zero_writes(self, fixture_company, monkeypatch):
        monkeypatch.setattr(settings, "ALLOW_DEMO_SEED", True, raising=False)
        verified_before = fixture_company.is_verified
        with contextlib.suppress(SystemExit):
            call_command("audit_public_surface")
        fixture_company.refresh_from_db()
        assert fixture_company.is_verified == verified_before
