from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from rest_framework import status

from apps.companies.models import Company
from apps.jobs.enums import JobStatus
from apps.jobs.models import Job
from core.utils import normalize_url

User = get_user_model()


class CompaniesAPITests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(email="admin@example.com", password="pass")
        self.company = Company.objects.create(
            name="Active Corp",
            slug="active-corp",
            domain="activecorp.com",
            input_type="main_website",
            input_url="https://activecorp.com",
            added_by=self.user,
            is_verified=True,
            is_active=True,
            is_deleted=False,
            career_url="https://activecorp.com/careers",
            last_successful_scrape_at=None,
        )
        self.paused_company = Company.objects.create(
            name="Paused Corp",
            slug="paused-corp",
            domain="pausedcorp.com",
            input_type="main_website",
            input_url="https://pausedcorp.com",
            added_by=self.user,
            is_verified=True,
            is_active=True,
            is_deleted=False,
            career_url="https://pausedcorp.com/careers",
            scrape_health="paused",
        )
        self.unverified_company = Company.objects.create(
            name="Unverified Corp",
            slug="unverified-corp",
            domain="unverifiedcorp.com",
            input_type="main_website",
            input_url="https://unverifiedcorp.com",
            added_by=self.user,
            is_verified=False,
            is_active=True,
            is_deleted=False,
            career_url="",
        )
        self.inactive_company = Company.objects.create(
            name="Inactive Corp",
            slug="inactive-corp",
            domain="inactivecorp.com",
            input_type="main_website",
            input_url="https://inactivecorp.com",
            added_by=self.user,
            is_verified=True,
            is_active=False,
            is_deleted=False,
            career_url="https://inactivecorp.com/careers",
        )
        self.deleted_company = Company.objects.create(
            name="Deleted Corp",
            slug="deleted-corp",
            domain="deletedcorp.com",
            input_type="main_website",
            input_url="https://deletedcorp.com",
            added_by=self.user,
            is_verified=True,
            is_active=True,
            is_deleted=True,
            career_url="https://deletedcorp.com/careers",
        )

        # Jobs for active corp
        self.public_job = Job.objects.create(
            company=self.company,
            title="Engineer",
            status=JobStatus.OPEN,
            is_published=True,
            is_deleted=False,
            source_url="https://activecorp.com/jobs/1",
            normalized_source_url=normalize_url("https://activecorp.com/jobs/1"),
            source_job_id="1",
            description="desc",
            content_hash="hash1",
            title_normalized="engineer",
            location_raw="NYC",
            city="New York",
        )
        self.closed_job = Job.objects.create(
            company=self.company,
            title="Manager",
            status=JobStatus.CLOSED,
            closed_at=timezone.now(),
            is_published=True,
            is_deleted=False,
            source_url="https://activecorp.com/jobs/2",
            normalized_source_url=normalize_url("https://activecorp.com/jobs/2"),
            source_job_id="2",
            description="desc",
            content_hash="hash2",
            title_normalized="manager",
            location_raw="NYC",
            city="New York",
        )
        self.unpublished_job = Job.objects.create(
            company=self.company,
            title="Intern",
            status=JobStatus.OPEN,
            is_published=False,
            is_deleted=False,
            source_url="https://activecorp.com/jobs/3",
            normalized_source_url=normalize_url("https://activecorp.com/jobs/3"),
            source_job_id="3",
            description="desc",
            content_hash="hash3",
            title_normalized="intern",
            location_raw="NYC",
            city="New York",
        )

        # For query count test
        self.company2 = Company.objects.create(
            name="Another Corp",
            slug="another-corp",
            domain="anothercorp.com",
            input_type="main_website",
            input_url="https://anothercorp.com",
            added_by=self.user,
            is_verified=True,
            is_active=True,
            is_deleted=False,
            career_url="https://anothercorp.com/careers",
        )

    def test_list_returns_only_verified_active_companies(self):
        url = reverse("companies:company-list")
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        slugs = [item["slug"] for item in response.data["results"]]
        self.assertIn("active-corp", slugs)
        self.assertIn("paused-corp", slugs)
        self.assertNotIn("unverified-corp", slugs)
        self.assertNotIn("inactive-corp", slugs)
        self.assertNotIn("deleted-corp", slugs)

    def test_unverified_slug_404(self):
        url = reverse("companies:company-detail", kwargs={"slug": "unverified-corp"})
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_inactive_slug_404(self):
        url = reverse("companies:company-detail", kwargs={"slug": "inactive-corp"})
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_deleted_slug_404(self):
        url = reverse("companies:company-detail", kwargs={"slug": "deleted-corp"})
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_paused_company_visible(self):
        url = reverse("companies:company-detail", kwargs={"slug": "paused-corp"})
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["slug"], "paused-corp")

    def test_open_jobs_count_excludes_non_public_jobs(self):
        url = reverse("companies:company-detail", kwargs={"slug": "active-corp"})
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["open_jobs_count"], 1)  # only public_job

    def test_company_jobs_endpoint_returns_only_public_jobs(self):
        url = reverse("companies:company-jobs", kwargs={"slug": "active-corp"})
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        job_slugs = [job["slug"] for job in response.data["results"]]
        self.assertEqual(len(job_slugs), 1)
        self.assertEqual(job_slugs[0], self.public_job.slug)

    def test_no_private_fields_in_response(self):
        url = reverse("companies:company-detail", kwargs={"slug": "active-corp"})
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        forbidden = [
            "input_url",
            "added_by",
            "career_url_set_by",
            "detection_status",
            "detection_attempts",
            "next_scrape_at",
            "last_scraped_at",
            "scrape_health",
            "consecutive_failures",
            "total_scrapes",
            "total_failures",
            "last_failure_reason",
            "last_jobs_seen",
            "notes",
            "verified_by",
        ]
        for field in forbidden:
            self.assertNotIn(field, response.data)

    def test_query_count_on_list(self):
        # Ensure no N+1: we expect 1 query for companies + 1 for counts (subquery)
        # plus maybe pagination count. We'll just check it's not excessive.
        with self.assertNumQueries(2):  # one for list, one for count (paginator)
            url = reverse("companies:company-list")
            self.client.get(url)
