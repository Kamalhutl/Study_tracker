from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from apps.companies.models import Company
from apps.jobs.models import Job
from apps.jobs.services import upsert_job
from core.utils import normalize_url

User = get_user_model()


class JobSlugTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(email="testuser@example.com", password="testpass")
        self.company = Company.objects.create(
            name="TestCorp",
            slug="testcorp",
            domain="testcorp.com",
            input_type="main_website",
            input_url="https://testcorp.com",
            added_by=self.user,
            detection_status="pending",
            is_verified=False,
            career_url="",
        )

    def test_slug_generated_on_create(self):
        payload = {
            "title": "Senior Engineer",
            "location_raw": "San Francisco, CA",
            "city": "San Francisco",
            "state": "CA",
            "country": "USA",
            "source_url": "https://testcorp.com/jobs/123",
            "source_job_id": "123",
            "description": "Test description",
        }
        job, outcome = upsert_job(company=self.company, payload=payload)
        self.assertEqual(outcome, "created")
        self.assertIsNotNone(job.slug)
        self.assertTrue(job.slug.startswith("senior-engineer-testcorp-san-francisco"))

    def test_slug_unique_across_jobs(self):
        payload1 = {
            "title": "Engineer",
            "location_raw": "NYC",
            "city": "New York",
            "source_url": "https://testcorp.com/jobs/1",
            "source_job_id": "1",
            "description": "desc1",
        }
        job1, _ = upsert_job(company=self.company, payload=payload1)
        payload2 = {
            "title": "Engineer",
            "location_raw": "NYC",
            "city": "New York",
            "source_url": "https://testcorp.com/jobs/2",
            "source_job_id": "2",
            "description": "desc2",
        }
        job2, _ = upsert_job(company=self.company, payload=payload2)
        self.assertNotEqual(job1.slug, job2.slug)
        self.assertTrue(job1.slug.startswith("engineer-testcorp-new-york"))
        self.assertTrue(job2.slug.startswith("engineer-testcorp-new-york"))

    def test_upsert_does_not_change_slug(self):
        payload = {
            "title": "Original Title",
            "location_raw": "Boston",
            "city": "Boston",
            "source_url": "https://testcorp.com/jobs/123",
            "source_job_id": "123",
            "description": "desc",
        }
        job, _ = upsert_job(company=self.company, payload=payload)
        original_slug = job.slug
        payload2 = {
            "title": "Updated Title",
            "location_raw": "Boston",
            "city": "Boston",
            "source_url": "https://testcorp.com/jobs/123",
            "source_job_id": "123",
            "description": "new desc",
        }
        job2, outcome = upsert_job(company=self.company, payload=payload2)
        self.assertEqual(outcome, "updated")
        self.assertEqual(job2.slug, original_slug)

    def test_title_change_does_not_change_slug(self):
        payload = {
            "title": "Old Title",
            "location_raw": "Chicago",
            "city": "Chicago",
            "source_url": "https://testcorp.com/jobs/456",
            "source_job_id": "456",
            "description": "desc",
        }
        job, _ = upsert_job(company=self.company, payload=payload)
        original_slug = job.slug
        job.title = "Brand New Title"
        job.save()
        job.refresh_from_db()
        self.assertEqual(job.slug, original_slug)

    def test_backfill_migration_logic(self):
        # Create a job without slug
        job = Job.objects.create(
            company=self.company,
            title="Backfill Me",
            location_raw="Seattle",
            city="Seattle",
            source_url="https://testcorp.com/jobs/789",
            normalized_source_url=normalize_url("https://testcorp.com/jobs/789"),
            source_job_id="789",
            description="desc",
            content_hash="hash",
            title_normalized="backfill-me",
        )
        self.assertIsNone(job.slug)
        # Run backfill function directly
        import importlib

        from django.apps import apps

        backfill_module = importlib.import_module("apps.jobs.migrations.0006_backfill_job_slug")
        backfill_module.backfill_slugs(apps, None)
        job.refresh_from_db()
        self.assertIsNotNone(job.slug)
        self.assertTrue(job.slug.startswith("backfill-me-testcorp-seattle"))

    def test_both_urls_return_same_payload(self):
        payload = {
            "title": "Slug Test",
            "location_raw": "Denver",
            "city": "Denver",
            "source_url": "https://testcorp.com/jobs/999",
            "source_job_id": "999",
            "description": "test",
        }
        job, _ = upsert_job(company=self.company, payload=payload)
        # Make the job public for access
        job.is_published = True
        job.save()
        url_uuid = reverse("jobs:job-detail", kwargs={"pk": job.id})
        url_slug = reverse("jobs:job-detail-slug", kwargs={"slug": job.slug})
        response_uuid = self.client.get(url_uuid)
        response_slug = self.client.get(url_slug)
        self.assertEqual(response_uuid.status_code, 200)
        self.assertEqual(response_slug.status_code, 200)
        self.assertEqual(response_uuid.json(), response_slug.json())
