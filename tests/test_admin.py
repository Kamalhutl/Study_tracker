"""Admin portal tests — add flows, actions, dashboard, query budgets."""

import re
from unittest import mock

import pytest
from django.test import Client, TestCase

from apps.companies.models import Company
from tests.factories import (
    AdminUserFactory,
    CandidateFactory,
    CompanyFactory,
    DetectionRunFactory,
    JobFactory,
)

ADMIN = "/admin/"


def _inline_management_fields(client, url):
    page = client.get(url).content.decode()
    return dict(
        re.findall(
            r'type="hidden" name="([^"]+-(?:TOTAL|INITIAL|MIN_NUM|MAX_NUM)_FORMS)" value="(\d+)"',
            page,
        )
    )


@pytest.fixture
def client():
    c = Client()
    c.force_login(AdminUserFactory())
    return c


class TestDashboard:
    def test_index_renders_counts(self, client):
        CompanyFactory(slug="dash-a")
        CompanyFactory(slug="dash-b", case_a=True)
        JobFactory()
        DetectionRunFactory(status="running")
        response = client.get(ADMIN)
        assert response.status_code == 200
        body = response.content.decode()
        assert "Operations dashboard" in body
        assert "Due now" in body
        assert "Last 10 detection runs" in body


class TestAddCompanyFlows:
    def test_main_website_add_view(self, client):
        response = client.post(
            "/admin/companies/company/add-main-website/",
            {"name": "Flux Robotics", "website_url": "https://flux.example"},
            follow=True,
        )
        assert response.status_code == 200
        company = Company.objects.get(slug="flux-robotics")
        assert company.detection_status == "pending"
        assert company.next_scrape_at is None

    def test_career_url_add_view(self, client):
        response = client.post(
            "/admin/companies/company/add-career-url/",
            {"name": "Green Co", "career_url": "https://boards.greenhouse.io/greenco"},
            follow=True,
        )
        assert response.status_code == 200
        company = Company.objects.get(slug="green-co")
        assert company.is_verified is True
        assert company.next_scrape_at is not None
        assert company.career_source_type == "greenhouse"

    def test_add_views_render_form(self, client):
        for url in ("add-main-website/", "add-career-url/"):
            response = client.get(f"/admin/companies/company/{url}")
            assert response.status_code == 200

    def test_default_add_view_blocked(self, client):
        response = client.get("/admin/companies/company/add/")
        assert response.status_code == 302 or response.status_code == 403


class TestCandidateActions:
    def test_approve_action_verifies_company(self, client):
        company = CompanyFactory(case_a=True, slug="act-approve")
        candidate = CandidateFactory(company=company)
        response = client.post(
            "/admin/companies/careercandidateurl/",
            {"action": "approve_selected", "_selected_action": [str(candidate.pk)]},
            follow=True,
        )
        assert response.status_code == 200
        company.refresh_from_db()
        assert company.is_verified is True

    def test_approve_two_candidates_one_company_refused(self, client):
        company = CompanyFactory(case_a=True, slug="act-refuse")
        c1 = CandidateFactory(company=company)
        c2 = CandidateFactory(company=company)
        response = client.post(
            "/admin/companies/careercandidateurl/",
            {"action": "approve_selected", "_selected_action": [str(c1.pk), str(c2.pk)]},
            follow=True,
        )
        assert response.status_code == 200
        assert "Refused" in response.content.decode()
        company.refresh_from_db()
        assert company.is_verified is False


class TestDetectionAction:
    def test_run_detection_now_enqueues_per_company(self, client):
        """§6.7: the action enqueues tasks; ineligible companies are named."""
        eligible = CompanyFactory(case_a=True, slug="act-detect-a")
        CompanyFactory(case_a=True, slug="act-detect-b", is_deleted=True)
        with (
            mock.patch("apps.career_detection.tasks.detect_career_url.delay") as delay,
            TestCase.captureOnCommitCallbacks(execute=True) as callbacks,
        ):
            response = client.post(
                "/admin/companies/company/",
                {
                    "action": "run_detection_now_selected",
                    "_selected_action": [str(eligible.pk)],
                },
                follow=True,
            )
        assert response.status_code == 200
        body = response.content.decode()
        assert delay.call_count == 1
        delay.assert_called_once_with(str(eligible.pk))
        assert len(callbacks) == 1
        assert "Skipped" in body

    def test_run_detection_now_skips_verified(self, client):
        verified = CompanyFactory(slug="act-detect-verified")
        with (
            mock.patch("apps.career_detection.tasks.detect_career_url.delay") as delay,
            TestCase.captureOnCommitCallbacks(execute=True),
        ):
            response = client.post(
                "/admin/companies/company/",
                {
                    "action": "run_detection_now_selected",
                    "_selected_action": [str(verified.pk)],
                },
                follow=True,
            )
        assert response.status_code == 200
        delay.assert_not_called()
        assert "Skipped" in response.content.decode()


class TestJobAdmin:
    def test_change_save_routes_through_edit_job_fields(self, client):
        job = JobFactory(pending_review=True)
        post = {
            "title": job.title,
            "source_url": job.source_url,
            "description": "Edited by admin",
            "location_raw": "Pune",
            "company": str(job.company_id),
            "_save": "Save",
        }
        post.update(_inline_management_fields(client, f"/admin/jobs/job/{job.pk}/change/"))
        response = client.post(f"/admin/jobs/job/{job.pk}/change/", post, follow=True)
        assert response.status_code == 200
        job.refresh_from_db()
        assert job.description == "Edited by admin"
        assert "description" in job.manually_edited_fields
        assert job.needs_review is False

    def test_changelist_review_queue_link(self, client):
        JobFactory(pending_review=True)
        response = client.get("/admin/jobs/job/")
        assert response.status_code == 200
        assert "Review queue (1)" in response.content.decode()

    def test_job_actions(self, client):
        job = JobFactory()
        client.post(
            "/admin/jobs/job/",
            {"action": "close_selected", "_selected_action": [str(job.pk)]},
            follow=True,
        )
        job.refresh_from_db()
        assert job.status == "closed"

    def test_publish_action(self, client):
        job = JobFactory(draft=True)
        client.post(
            "/admin/jobs/job/",
            {"action": "publish_selected", "_selected_action": [str(job.pk)]},
            follow=True,
        )
        job.refresh_from_db()
        assert job.is_published is True


class TestQueryBudgets:
    def test_company_changelist_no_n1(self, client, django_assert_max_num_queries):
        for i in range(50):
            CompanyFactory(slug=f"q-co-{i}")
        with django_assert_max_num_queries(14):
            response = client.get(ADMIN + "companies/company/")
        assert response.status_code == 200

    def test_job_changelist_no_n1(self, client, django_assert_max_num_queries):
        company = CompanyFactory(slug="q-jobs")
        for i in range(50):
            JobFactory(
                company=company,
                title=f"Q Job {i}",
                source_url=f"https://jobs.example/q/{i}",
                normalized_source_url=f"https://jobs.example/q/{i}",
                content_hash=f"q{i:040d}",
            )
        with django_assert_max_num_queries(14):
            response = client.get(ADMIN + "jobs/job/")
        assert response.status_code == 200
