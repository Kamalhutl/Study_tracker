import logging
from datetime import datetime, timedelta
from typing import Any

from celery import shared_task
from celery.app.task import Task
from django.utils import timezone

from apps.companies.enums import CareerSourceType, ScrapeHealth
from apps.companies.models import Company
from apps.jobs.services import apply_missing_strikes, upsert_job
from apps.scraping.fetching import FetchError, fetch, fetch_with_escalation
from apps.scraping.models import ScrapeError, ScrapeRun
from core.locks import LockNotAcquired, redis_lock

logger = logging.getLogger("study_tracker.scraping.tasks")

# Parser mapping
PARSER_MAP = {
    CareerSourceType.GREENHOUSE.value: "apps.scraping.parsers.ats_greenhouse",
    CareerSourceType.LEVER.value: "apps.scraping.parsers.ats_lever",
    CareerSourceType.ASHBY.value: "apps.scraping.parsers.ats_ashby",
    CareerSourceType.SMARTRECRUITERS.value: "apps.scraping.parsers.ats_smartrecruiters",
    CareerSourceType.OWN_CAREER_PAGE.value: "apps.scraping.spiders.static_jobs",
    CareerSourceType.UNKNOWN.value: "apps.scraping.spiders.static_jobs",
}

# URL templates for each ATS
URL_TEMPLATES = {
    CareerSourceType.GREENHOUSE.value: "https://boards-api.greenhouse.io/v1/boards/{ats_identifier}/jobs?content=true",
    CareerSourceType.LEVER.value: "https://api.lever.co/v0/postings/{ats_identifier}?mode=json",
    CareerSourceType.ASHBY.value: "https://jobs.ashbyhq.com/{ats_identifier}/json",
    CareerSourceType.SMARTRECRUITERS.value: "https://api.smartrecruiters.com/v1/companies/{ats_identifier}/postings",
}


def _get_parser_module(source_type: str) -> Any:
    """Import and return the parser module for the given source type."""
    if source_type not in PARSER_MAP:
        return None

    module_path = PARSER_MAP[source_type]
    try:
        module = __import__(module_path, fromlist=["parse"])
        return module
    except ImportError as e:
        logger.error("Failed to import parser %s: %s", module_path, e)
        return None


def _build_fetch_url(company: Company) -> str:
    """Build the appropriate fetch URL based on company's career source type."""
    source_type = company.career_source_type

    if source_type in URL_TEMPLATES:
        template = URL_TEMPLATES[source_type]
        return template.format(ats_identifier=company.ats_identifier or "")
    else:
        # For OWN_CAREER_PAGE and UNKNOWN, use the career_url
        return company.career_url or ""


def _use_fetch_with_escalation(source_type: str) -> bool:
    """Determine if we should use fetch_with_escalation for this source type."""
    return source_type in {
        CareerSourceType.OWN_CAREER_PAGE,
        CareerSourceType.UNKNOWN,
    }


@shared_task(bind=True, name="scraping.tasks.scrape_company", max_retries=0, queue="scraping")
def scrape_company(
    self: "Task[Any, Any]", company_id: str, *, triggered_by: str = "schedule"
) -> dict[str, Any]:
    """Core per-company scrape loop."""
    # Step 1: Load Company
    try:
        company = Company.objects.get(pk=company_id)
    except Company.DoesNotExist:
        return {"error": "not_found"}

    # Step 2: Acquire per-company Redis lock
    lock_key = f"scrape:{company_id}"
    try:
        with redis_lock(lock_key, timeout=3600, blocking=False):
            return _execute_scrape(company, triggered_by, lock_key)
    except LockNotAcquired:
        return {"skipped": "locked"}


def _execute_scrape(company: Company, triggered_by: str, lock_key: str) -> dict[str, Any]:
    """Execute the actual scrape logic within the lock context."""
    now = timezone.now()
    started_at = now

    # Step 3: Create ScrapeRun
    scrape_run = ScrapeRun.objects.create(
        company=company,
        status="running",
        triggered_by=triggered_by,
    )

    try:
        # Step 4-5: Determine parser and build URL
        source_type = company.career_source_type
        parser_module = _get_parser_module(source_type)

        if not parser_module:
            logger.error("No parser available for source type %s", source_type)
            scrape_run.status = "failed"
            scrape_run.error = {"message": f"No parser for {source_type}"}
            scrape_run.finished_at = timezone.now()
            scrape_run.duration_ms = int(
                (scrape_run.finished_at - started_at).total_seconds() * 1000
            )
            scrape_run.save()
            return {
                "company_id": str(company.id),
                "status": "failed",
                "jobs_found": 0,
                "jobs_added": 0,
                "jobs_updated": 0,
                "jobs_missing": 0,
                "duration_ms": scrape_run.duration_ms or 0,
            }

        fetch_url = _build_fetch_url(company)
        if not fetch_url:
            logger.error("No fetch URL available for company %s", company.name)
            scrape_run.status = "failed"
            scrape_run.error = {"message": "No fetch URL available"}
            scrape_run.finished_at = timezone.now()
            scrape_run.duration_ms = int(
                (scrape_run.finished_at - started_at).total_seconds() * 1000
            )
            scrape_run.save()
            return {
                "company_id": str(company.id),
                "status": "failed",
                "jobs_found": 0,
                "jobs_added": 0,
                "jobs_updated": 0,
                "jobs_missing": 0,
                "duration_ms": scrape_run.duration_ms or 0,
            }

        # Step 6: Fetch
        use_escalation = _use_fetch_with_escalation(source_type)
        try:
            if use_escalation:
                fetch_result = fetch_with_escalation(fetch_url, company=company)
            else:
                fetch_result = fetch(fetch_url, company=company)
        except FetchError as e:
            # Step 7 error handling: FetchError
            logger.error("Fetch failed for %s: %s", company.name, e)
            ScrapeError.objects.create(
                scrape_run=scrape_run,
                company=company,
                url=fetch_url,
                error_type=type(e).__name__,
                message=str(e),
                traceback="",
            )
            scrape_run.status = "failed"
            scrape_run.error = {"message": str(e), "type": type(e).__name__}
            scrape_run.finished_at = timezone.now()
            scrape_run.duration_ms = int(
                (scrape_run.finished_at - started_at).total_seconds() * 1000
            )
            scrape_run.save()

            # Update company health
            _update_company_health(company, success=False)

            return {
                "company_id": str(company.id),
                "status": "failed",
                "jobs_found": 0,
                "jobs_added": 0,
                "jobs_updated": 0,
                "jobs_missing": 0,
                "duration_ms": scrape_run.duration_ms or 0,
            }

        # Step 7: Call parser
        try:
            payloads = parser_module.parse(fetch_result, company=company)
        except Exception as e:
            # ParseError handling
            logger.error("Parse failed for %s: %s", company.name, e)
            ScrapeError.objects.create(
                scrape_run=scrape_run,
                company=company,
                url=fetch_url,
                error_type="ParseError",
                message=str(e),
                traceback="",
            )
            scrape_run.status = "partial"
            scrape_run.error = {"message": str(e), "type": "ParseError"}
            scrape_run.finished_at = timezone.now()
            scrape_run.duration_ms = int(
                (scrape_run.finished_at - started_at).total_seconds() * 1000
            )
            scrape_run.save()

            # Update company health
            _update_company_health(company, success=False)

            return {
                "company_id": str(company.id),
                "status": "partial",
                "jobs_found": 0,
                "jobs_added": 0,
                "jobs_updated": 0,
                "jobs_missing": 0,
                "duration_ms": scrape_run.duration_ms or 0,
            }

        # Step 8-9: Process payloads and tally results
        jobs_added = 0
        jobs_updated = 0
        jobs_unchanged = 0
        jobs_reopened = 0
        seen_job_ids = []

        for payload in payloads:
            try:
                # Ensure posted_at is serializable for raw_payload
                if "posted_at" in payload and isinstance(payload["posted_at"], datetime):
                    payload["posted_at"] = payload["posted_at"].isoformat()
                job, outcome = upsert_job(
                    company=company,
                    payload=payload,
                    scrape_run_id=str(scrape_run.id),
                )

                # Tally outcomes
                if outcome == "created":
                    jobs_added += 1
                elif outcome == "updated":
                    jobs_updated += 1
                elif outcome == "unchanged":
                    jobs_unchanged += 1
                elif outcome == "reopened":
                    jobs_reopened += 1

                seen_job_ids.append(job.pk)
            except Exception as e:
                logger.error("Failed to upsert job for %s: %s", company.name, e)
                continue

        # Step 10: Apply missing strikes
        try:
            missing_counts = apply_missing_strikes(
                company=company,
                seen_job_ids=seen_job_ids,
                scrape_run_id=str(scrape_run.id),
            )
            jobs_missing = sum(missing_counts.values())
        except Exception as e:
            logger.error("Failed to apply missing strikes for %s: %s", company.name, e)
            jobs_missing = 0

        # Step 11: Update company
        now = timezone.now()
        company.last_scraped_at = now
        company.next_scrape_at = now + timedelta(minutes=company.scrape_interval_minutes)

        # Update health based on success
        jobs_found = len(payloads)
        success = jobs_found > 0
        if success:
            company.consecutive_failures = 0
            company.scrape_health = ScrapeHealth.HEALTHY
        else:
            company.consecutive_failures += 1
            if company.consecutive_failures >= 5:
                company.scrape_health = ScrapeHealth.FAILING
            elif company.consecutive_failures >= 2:
                company.scrape_health = ScrapeHealth.DEGRADED

        company.save()

        # Step 12: Finalize ScrapeRun
        finished_at = timezone.now()
        duration_ms = int((finished_at - started_at).total_seconds() * 1000)

        status = "success" if jobs_found > 0 else "partial"

        scrape_run.finished_at = finished_at
        scrape_run.duration_ms = duration_ms
        scrape_run.jobs_found = jobs_found
        scrape_run.jobs_added = jobs_added
        scrape_run.jobs_updated = jobs_updated
        scrape_run.jobs_unchanged = jobs_unchanged
        scrape_run.jobs_missing = jobs_missing
        scrape_run.jobs_reopened = jobs_reopened
        scrape_run.status = status
        scrape_run.save()

        # Step 13: Release lock (handled by context manager)

        # Step 14: Return summary
        return {
            "company_id": str(company.id),
            "status": status,
            "jobs_found": jobs_found,
            "jobs_added": jobs_added,
            "jobs_updated": jobs_updated,
            "jobs_missing": jobs_missing,
            "duration_ms": duration_ms,
        }

    except Exception as e:
        # Outermost exception handling
        logger.error(
            "Unhandled exception in scrape_company for %s: %s", company.name, e, exc_info=True
        )
        scrape_run.status = "failed"
        scrape_run.error = {"message": str(e), "type": type(e).__name__}
        scrape_run.finished_at = timezone.now()
        scrape_run.duration_ms = int((scrape_run.finished_at - started_at).total_seconds() * 1000)
        scrape_run.save()

        _update_company_health(company, success=False)

        return {
            "company_id": str(company.id),
            "status": "failed",
            "jobs_found": 0,
            "jobs_added": 0,
            "jobs_updated": 0,
            "jobs_missing": 0,
            "duration_ms": scrape_run.duration_ms or 0,
        }


def _update_company_health(company: Company, success: bool) -> None:
    """Update company health based on scrape success."""
    if success:
        company.consecutive_failures = 0
        company.scrape_health = ScrapeHealth.HEALTHY
    else:
        company.consecutive_failures += 1
        if company.consecutive_failures >= 5:
            company.scrape_health = ScrapeHealth.FAILING
        elif company.consecutive_failures >= 2:
            company.scrape_health = ScrapeHealth.DEGRADED

    company.save()


@shared_task(name="scraping.tasks.refresh_all_companies", queue="scraping")
def refresh_all_companies() -> dict[str, Any]:
    """Beat entry-point that fans out to scrape_company."""
    # Step 1: Acquire global Redis lock
    lock_key = "global:scrape-cycle"
    try:
        with redis_lock(lock_key, timeout=4 * 60 * 60, blocking=False):  # 4 hours TTL
            return _execute_refresh_all()
    except LockNotAcquired:
        return {"skipped": "cycle_locked"}


def _execute_refresh_all() -> dict[str, Any]:
    """Execute the refresh logic within the lock context."""
    now = timezone.now()

    # Step 2: Query companies
    companies = (
        Company.objects.filter(
            is_verified=True,
            is_active=True,
        )
        .exclude(scrape_health=ScrapeHealth.FAILING)
        .filter(next_scrape_at__lte=now)
    )

    # Step 3: Dispatch scrape_company tasks
    count = 0
    for company in companies:
        scrape_company.apply_async(
            args=(str(company.id),),
            kwargs={"triggered_by": "schedule"},
            queue="scraping",
        )
        count += 1

    # Step 4: Release global lock (handled by context manager)

    # Step 5: Return result
    return {"dispatched": count, "at": now.isoformat()}
