from django.conf import settings
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import User
from apps.companies.models import Company
from apps.exams.models import ConductingBody, Exam
from apps.jobs.models import Job, JobStatus


@override_settings(SITE_BASE_URL="https://example.com")
class SitemapTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(email="test@example.com", password="pass")
        self.company = Company.objects.create(
            name="Test Co",
            slug="test-co",
            domain="test.com",
            is_verified=True,
            is_active=True,
            input_type="manual",
            input_url="https://test.com",
            career_url="https://test.com/careers",
            added_by=self.user,
        )
        self.job = Job.objects.create(
            company=self.company,
            status=JobStatus.OPEN,
            is_published=True,
            slug="test-job",
            title="Test Job",
            source_url="https://test.com/job",
            normalized_source_url="https://test.com/job",
            content_hash="abc123",
        )
        body = ConductingBody.objects.create(
            name="Body",
            slug="body",
            body_type="central",
            is_active=True,
        )
        self.exam = Exam.objects.create(
            conducting_body=body,
            name="Test Exam",
            slug="test-exam",
            category="other",
            level="national",
            is_active=True,
        )

    def test_sitemap_index(self):
        resp = self.client.get(reverse("sitemap-index"))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "sitemap-jobs.xml")
        self.assertContains(resp, "sitemap-companies.xml")
        self.assertContains(resp, "sitemap-exams.xml")
        self.assertContains(resp, "sitemap-static.xml")

    def test_job_sitemap_contains_open_published_job(self):
        resp = self.client.get(reverse("sitemap-section", kwargs={"section": "jobs"}))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, f"<loc>{settings.SITE_BASE_URL}/jobs/{self.job.slug}/</loc>")
        self.assertContains(
            resp, f"<lastmod>{timezone.localtime(self.job.last_seen_at).date()}</lastmod>"
        )

    def test_job_sitemap_excludes_closed_draft_duplicate_deleted(self):
        from django.utils import timezone

        closed = Job.objects.create(
            company=self.company,
            status=JobStatus.CLOSED,
            is_published=True,
            title="Closed",
            slug="closed",
            source_url="https://test.com/closed",
            normalized_source_url="https://test.com/closed",
            content_hash="def456",
            closed_at=timezone.now(),
        )
        draft = Job.objects.create(
            company=self.company,
            status=JobStatus.DRAFT,
            is_published=False,
            title="Draft",
            slug="draft",
            source_url="https://test.com/draft",
            normalized_source_url="https://test.com/draft",
            content_hash="ghi789",
        )
        duplicate = Job.objects.create(
            company=self.company,
            status=JobStatus.OPEN,
            is_published=True,
            title="Duplicate",
            slug="duplicate",
            source_url="https://test.com/duplicate",
            normalized_source_url="https://test.com/duplicate",
            content_hash="jkl012",
            duplicate_of=self.job,
        )
        soft_deleted = Job.objects.create(
            company=self.company,
            status=JobStatus.OPEN,
            is_published=True,
            title="Deleted",
            slug="deleted",
            source_url="https://test.com/deleted",
            normalized_source_url="https://test.com/deleted",
            content_hash="mno345",
            is_deleted=True,
        )
        resp = self.client.get(reverse("sitemap-section", kwargs={"section": "jobs"}))
        self.assertNotContains(resp, f"/jobs/{closed.slug}/")
        self.assertNotContains(resp, f"/jobs/{draft.slug}/")
        self.assertNotContains(resp, f"/jobs/{duplicate.slug}/")
        self.assertNotContains(resp, f"/jobs/{soft_deleted.slug}/")

    def test_locations_start_with_site_base_url(self):
        resp = self.client.get(reverse("sitemap-section", kwargs={"section": "jobs"}))
        content = resp.content.decode()
        self.assertIn(f"<loc>{settings.SITE_BASE_URL}/jobs/", content)
        self.assertNotIn("<loc>http://testserver", content)
        # SITE_BASE_URL may be localhost in tests, so we only check that it's not testserver

    def test_job_loc_equals_canonical_url(self):
        # Assume serializer canonical_url is SITE_BASE_URL + /jobs/slug/
        resp = self.client.get(reverse("sitemap-section", kwargs={"section": "jobs"}))
        self.assertContains(resp, f"<loc>{settings.SITE_BASE_URL}/jobs/{self.job.slug}/</loc>")

    def test_lastmod_present_for_jobs(self):
        resp = self.client.get(reverse("sitemap-section", kwargs={"section": "jobs"}))
        self.assertContains(resp, "<lastmod>")

    def test_company_sitemap_excludes_unverified_and_inactive(self):
        unverified = Company.objects.create(
            name="Unverified",
            slug="unverified",
            domain="unverified.com",
            is_verified=False,
            is_active=True,
            input_type="manual",
            input_url="https://unverified.com",
            career_url="",
            added_by=self.user,
        )
        inactive = Company.objects.create(
            name="Inactive",
            slug="inactive",
            domain="inactive.com",
            is_verified=True,
            is_active=False,
            input_type="manual",
            input_url="https://inactive.com",
            career_url="https://inactive.com/careers",
            added_by=self.user,
        )
        resp = self.client.get(reverse("sitemap-section", kwargs={"section": "companies"}))
        self.assertNotContains(resp, f"/companies/{unverified.slug}/")
        self.assertNotContains(resp, f"/companies/{inactive.slug}/")

    def test_robots_txt(self):
        resp = self.client.get("/robots.txt")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp["Content-Type"], "text/plain")
        self.assertContains(resp, "Disallow: /admin/")
        self.assertContains(resp, "Disallow: /api/")
        self.assertContains(resp, f"Sitemap: {settings.SITE_BASE_URL}/sitemap.xml")

    def test_job_sitemap_query_count(self):
        with self.assertNumQueries(1):
            resp = self.client.get(reverse("sitemap-section", kwargs={"section": "jobs"}))
            self.assertEqual(resp.status_code, 200)

    def test_exam_sitemap_includes_inactive_excludes_deleted(self):
        # Inactive exams remain indexed because exams are cyclical: the exam entity
        # persists while only the ExamCycle changes, and these pages are searched
        # year-round. is_active is a UI ranking signal, not an index-eligibility signal.
        inactive_exam = Exam.objects.create(
            conducting_body=self.exam.conducting_body,
            name="Inactive Exam",
            slug="inactive-exam",
            category="other",
            level="national",
            is_active=False,
        )
        deleted_exam = Exam.objects.create(
            conducting_body=self.exam.conducting_body,
            name="Deleted Exam",
            slug="deleted-exam",
            category="other",
            level="national",
            is_active=True,
            is_deleted=True,
        )
        resp = self.client.get(reverse("sitemap-section", kwargs={"section": "exams"}))
        self.assertContains(resp, f"/exams/{inactive_exam.slug}/")
        self.assertNotContains(resp, f"/exams/{deleted_exam.slug}/")
