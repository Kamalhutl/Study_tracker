"""upsert_job — the single write path for scraped jobs (100% coverage required)."""

from django.utils import timezone

from apps.audit_logs.models import AuditLog
from apps.jobs import services
from apps.jobs.enums import JobStatus
from apps.jobs.models import Job, JobStatusEvent
from tests.factories import CompanyFactory

PAYLOAD = {
    "source_job_id": "gh-1",
    "source_url": "https://boards.greenhouse.io/acme/gh-1",
    "title": "Senior Backend Engineer",
    "location_raw": "Remote, India",
    "description": "Build Python/Django services and mentor juniors.",
    "extraction_confidence": 90,
}


def _ats_company():
    return CompanyFactory(slug="upsert-ats", ats=True)


def _custom_company():
    return CompanyFactory(slug="upsert-custom", career_source_type="own_career_page")


class TestCreate:
    def test_creates_open_job(self):
        company = _custom_company()
        job, outcome = services.upsert_job(company=company, payload=PAYLOAD)
        assert outcome == "created"
        assert job.status == JobStatus.OPEN
        assert job.missing_count == 0
        assert job.source_job_id == "gh-1"
        assert job.first_seen_at is not None
        assert job.last_seen_at == job.first_seen_at
        assert job.extraction_confidence == 90
        assert JobStatusEvent.objects.filter(
            job=job, trigger="scrape", to_status=JobStatus.OPEN
        ).exists()
        assert AuditLog.objects.filter(action="job.created").count() == 1

    def test_ats_high_confidence_autopublishes(self):
        company = _ats_company()
        job, _ = services.upsert_job(company=company, payload=PAYLOAD)
        assert job.is_published is True
        assert job.published_at is not None
        assert job.needs_review is False

    def test_ats_low_confidence_needs_review(self):
        company = _ats_company()
        payload = {**PAYLOAD, "extraction_confidence": 50}
        job, _ = services.upsert_job(company=company, payload=payload)
        assert job.is_published is False
        assert job.needs_review is True
        assert job.review_reason == "low confidence"

    def test_custom_source_needs_review(self):
        company = _custom_company()
        job, _ = services.upsert_job(company=company, payload=PAYLOAD)
        assert job.is_published is False
        assert job.needs_review is True
        assert job.review_reason == "custom source"

    def test_unparseable_confidence_defaults_to_zero(self):
        company = _custom_company()
        payload = {**PAYLOAD, "extraction_confidence": "not-a-number"}
        job, _ = services.upsert_job(company=company, payload=payload)
        assert job.extraction_confidence == 0


class TestIdempotency:
    def test_same_payload_twice_is_unchanged(self):
        company = _custom_company()
        job, _ = services.upsert_job(company=company, payload=PAYLOAD)
        before = job.last_seen_at
        job2, outcome = services.upsert_job(company=company, payload=PAYLOAD)
        assert outcome == "unchanged"
        assert job2.pk == job.pk
        assert job2.last_seen_at >= before
        assert AuditLog.objects.filter(action="job.created").count() == 1

    def test_match_by_source_job_id_when_url_changed(self):
        company = _custom_company()
        services.upsert_job(company=company, payload=PAYLOAD)
        moved = {
            **PAYLOAD,
            "source_url": "https://boards.greenhouse.io/acme/new-url",
            "title": "Super Senior Backend Engineer",
        }
        job, outcome = services.upsert_job(company=company, payload=moved)
        assert outcome == "updated"
        assert job.source_job_id == "gh-1"
        assert job.title == "Super Senior Backend Engineer"

    def test_match_by_content_hash(self):
        company = _custom_company()
        services.upsert_job(company=company, payload=PAYLOAD)
        churn = dict(PAYLOAD)
        churn.pop("source_job_id")
        churn["source_url"] = "https://totally-new.example/jobs/1"
        job, outcome = services.upsert_job(company=company, payload=churn)
        assert outcome == "updated"
        assert job.pk == Job.objects.get(company=company).pk


class TestReopen:
    def test_closed_job_rediscovered_reopens(self):
        company = _custom_company()
        job, _ = services.upsert_job(company=company, payload=PAYLOAD)
        job2, _ = services.upsert_job(company=company, payload=PAYLOAD)  # unchanged
        # simulate ladder closure
        job2.status = JobStatus.CLOSED
        job2.closed_at = timezone.now()
        job2.save(update_fields=["status", "closed_at"])
        job3, outcome = services.upsert_job(company=company, payload=PAYLOAD)
        assert outcome == "reopened"
        assert job3.status == JobStatus.OPEN
        assert job3.closed_at is None
        assert job3.reopened_count == 1
        assert JobStatusEvent.objects.filter(job=job3, trigger="reopen").exists()
        assert AuditLog.objects.filter(action="job.reopened").count() == 1

    def test_manual_status_job_not_reopened(self):
        company = _custom_company()
        job, _ = services.upsert_job(company=company, payload=PAYLOAD)
        job.status = JobStatus.CLOSED
        job.closed_at = timezone.now()
        job.is_manual_status = True
        job.save(update_fields=["status", "closed_at", "is_manual_status"])
        job2, outcome = services.upsert_job(company=company, payload=PAYLOAD)
        assert outcome == "updated"
        assert job2.status == JobStatus.CLOSED


class TestManualEditProtection:
    def test_manually_edited_field_not_overwritten(self):
        company = _custom_company()
        job, _ = services.upsert_job(company=company, payload=PAYLOAD)
        services.edit_job_fields(job=job, changes={"title": "Manually Set Title"}, actor=None)
        scraped = {**PAYLOAD, "title": "Scraper Title"}
        job2, outcome = services.upsert_job(company=company, payload=scraped)
        job2.refresh_from_db()
        assert job2.title == "Manually Set Title"
        assert outcome == "unchanged"

    def test_content_change_on_custom_source_flags_review(self):
        company = _custom_company()
        job, _ = services.upsert_job(company=company, payload=PAYLOAD)
        changed = {**PAYLOAD, "description": "Completely different description now."}
        job2, outcome = services.upsert_job(company=company, payload=changed)
        assert outcome == "updated"
        assert job2.needs_review is True
        assert job2.review_reason == "content changed"

    def test_content_change_on_ats_no_review(self):
        company = _ats_company()
        job, _ = services.upsert_job(company=company, payload=PAYLOAD)
        changed = {**PAYLOAD, "description": "New description."}
        job2, outcome = services.upsert_job(company=company, payload=changed)
        assert outcome == "updated"
        assert job2.needs_review is False


class TestQueryCounts:
    def test_unchanged_upsert_uses_few_queries(self, django_assert_max_num_queries):
        company = _custom_company()
        services.upsert_job(company=company, payload=PAYLOAD)
        with django_assert_max_num_queries(4):
            services.upsert_job(company=company, payload=PAYLOAD)
