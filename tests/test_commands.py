"""Management command tests: add_company, companies_due, seed_demo, rebuild_search_vectors."""

import json

import pytest
from django.conf import settings
from django.core.management import call_command
from django.core.management.base import CommandError

from apps.companies.models import Company
from apps.jobs.models import Job
from tests.factories import AdminUserFactory, CompanyFactory, JobFactory


@pytest.fixture
def actor():
    return AdminUserFactory()


class TestAddCompany:
    def test_case_a(self, actor, capsys):
        call_command(
            "add_company",
            "--name",
            "Cmd Co",
            "--website",
            "https://cmdco.example",
            "--actor-email",
            actor.email,
        )
        company = Company.objects.get(slug="cmd-co")
        assert company.detection_status == "pending"

    def test_case_b(self, actor, capsys):
        call_command(
            "add_company",
            "--name",
            "Cmd B Co",
            "--career-url",
            "https://boards.lever.co/cmdb",
            "--actor-email",
            actor.email,
        )
        company = Company.objects.get(slug="cmd-b-co")
        assert company.is_verified is True

    def test_exactly_one_mode_required(self, actor):
        with pytest.raises(CommandError):
            call_command("add_company", "--name", "X", "--actor-email", actor.email)
        with pytest.raises(CommandError):
            call_command(
                "add_company",
                "--name",
                "X",
                "--website",
                "https://x.example",
                "--career-url",
                "https://x.example/careers",
                "--actor-email",
                actor.email,
            )

    def test_missing_actor_fails(self):
        with pytest.raises(CommandError):
            call_command(
                "add_company",
                "--name",
                "X",
                "--website",
                "https://x.example",
                "--actor-email",
                "nobody@example.com",
            )


class TestCompaniesDue:
    def test_lists_only_due(self, capsys):
        due = CompanyFactory(slug="due-already")
        due.next_scrape_at = None
        due.save(update_fields=["next_scrape_at"])
        CompanyFactory(slug="not-due-yet")
        call_command("companies_due")
        out = capsys.readouterr().out
        assert due.name in out
        assert "not-due-yet" not in out

    def test_json_output(self, capsys):
        due = CompanyFactory(slug="json-due")
        due.next_scrape_at = None
        due.save(update_fields=["next_scrape_at"])
        call_command("companies_due", "--json")
        rows = json.loads(capsys.readouterr().out)
        assert any(r["name"].startswith("Company") for r in rows)

    def test_empty_message(self, capsys):
        call_command("companies_due")
        out = capsys.readouterr().out
        assert "No companies due" in out


class TestSeedDemo:
    def test_seeds_dataset(self, actor, capsys, monkeypatch):
        monkeypatch.setattr(settings, "ALLOW_DEMO_SEED", True, raising=False)
        call_command("seed_demo", "--actor-email", actor.email)
        assert Company.all_objects.filter(slug="acme-robotics").exists()
        assert Company.objects.filter(detection_status="needs_review").exists()
        assert Company.objects.filter(scrape_health="failing").exists()
        assert Company.objects.filter(scrape_health="paused").exists()
        job_statuses = set(Job.objects.values_list("status", flat=True))
        assert {"open", "draft", "closed"} <= job_statuses
        assert Job.objects.filter(manually_edited_fields__contains=["city"]).exists()
        assert Job.objects.filter(duplicate_of__isnull=False).exists()
        assert Job.objects.filter(reports__isnull=False).exists()

    def test_idempotent(self, actor, capsys, monkeypatch):
        monkeypatch.setattr(settings, "ALLOW_DEMO_SEED", True, raising=False)
        call_command("seed_demo", "--actor-email", actor.email)
        company_count = Company.all_objects.count()
        call_command("seed_demo", "--actor-email", actor.email)
        assert Company.all_objects.count() == company_count

    def test_refuses_when_debug_false(self, actor, monkeypatch):
        monkeypatch.setattr(settings, "DEBUG", False)
        monkeypatch.setattr(settings, "ALLOW_DEMO_SEED", False, raising=False)
        with pytest.raises(CommandError):
            call_command("seed_demo", "--actor-email", actor.email)


class TestRebuildSearchVectors:
    def test_full_rebuild(self, capsys):
        company = CompanyFactory(slug="rebuild-co")
        job = JobFactory(company=company, title="Rebuild Me")
        call_command("rebuild_search_vectors")
        assert Job.objects.search("rebuild").filter(pk=job.pk).exists()

    def test_per_company(self, capsys):
        company = CompanyFactory(slug="rebuild-target")
        JobFactory(company=company, title="Target Job")
        call_command("rebuild_search_vectors", "--company", "rebuild-target")
        assert Job.objects.search("target").filter(company=company).exists()

    def test_unknown_company(self, capsys):
        call_command("rebuild_search_vectors", "--company", "nope-nope")
        assert "nope-nope" in capsys.readouterr().err
