import logging
from datetime import datetime, timedelta
from typing import Any

from celery import shared_task
from celery.app.task import Task
from celery.exceptions import Retry, SoftTimeLimitExceeded
from django.conf import settings
from django.utils import timezone

from apps.companies.enums import MIN_SCRAPE_INTERVAL_MINUTES, CareerSourceType, ScrapeHealth
from apps.companies.models import Company
from apps.companies.services import record_scrape_outcome
from apps.jobs.enums import JobStatus
from apps.jobs.services import apply_missing_strikes, upsert_job
from apps.scraping.artifacts import store_artifact
from apps.scraping.exceptions import is_transient
from apps.scraping.fetching import FetchError, fetch, fetch_with_escalation
from apps.scraping.models import ScrapeError, ScrapeRun
from apps.scraping.sanity import RunVerdict, evaluate_run
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


def _clear_fetch_state(url: str) -> None:
    """Clear conditional GET state for the given URL (blank validators)."""
    if not url:
        return
    import hashlib

    from apps.scraping.models import SourceFetchState

    url_hash = hashlib.sha256(url.encode()).hexdigest()
    updated = SourceFetchState.objects.filter(url_hash=url_hash).update(
        etag="", last_modified="", body_hash=""
    )
    if updated:
        logger.debug("Cleared fetch state for URL %s", url)


@shared_task(
    bind=True,
    name="scraping.tasks.scrape_company",
    max_retries=settings.SCRAPE_MAX_RETRIES,
    soft_time_limit=settings.SCRAPE_SOFT_TIME_LIMIT,
    time_limit=settings.SCRAPE_TIME_LIMIT,
    queue="scraping",
)
def scrape_company(
    self: "Task[Any, Any]",
    company_id: str,
    *,
    triggered_by: str = "schedule",
    force_browser: bool = False,
) -> dict[str, Any]:
    try:
        company = Company.objects.get(pk=company_id)
    except Company.DoesNotExist:
        return {"error": "not_found"}

    lock_key = f"scrape:{company_id}"
    try:
        with redis_lock(lock_key, timeout=3600, blocking=False):
            return _execute_scrape(
                self, company, triggered_by, lock_key, force_browser=force_browser
            )
    except LockNotAcquired:
        return {"skipped": "locked"}


def _execute_scrape(
    self: "Task[Any, Any]",
    company: Company,
    triggered_by: str,
    lock_key: str,
    *,
    force_browser: bool = False,
) -> dict[str, Any]:
    now = timezone.now()
    started_at = now
    fetch_url = ""

    scrape_run = ScrapeRun.objects.create(
        company=company,
        status="running",
        triggered_by=triggered_by,
    )

    try:
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

        parser_name = getattr(parser_module, "PARSER_NAME", "unknown")
        parser_version = getattr(parser_module, "PARSER_VERSION", 0)
        parser_version_str = f"{parser_name}@{parser_version}"
        scrape_run.parser_version = parser_version_str
        scrape_run.save(update_fields=["parser_version"])

        def _should_store_artifact(run: ScrapeRun) -> bool:
            return (
                run.verdict in (RunVerdict.UNTRUSTED, RunVerdict.QUARANTINED)
                or run.status == "failed"
            )

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

        use_escalation = _use_fetch_with_escalation(source_type)
        needs_browser_escalation = False
        try:
            if force_browser:
                from apps.scraping.fetching import FetchMode

                fetch_result = fetch(fetch_url, mode=FetchMode.DYNAMIC, company=company)
            elif use_escalation:
                fetch_result = fetch_with_escalation(fetch_url, company=company)
                if fetch_result.escalation_reason and not force_browser:
                    needs_browser_escalation = True
            else:
                fetch_result = fetch(fetch_url, company=company)
        except FetchError as e:
            # Step 7 error handling: FetchError
            logger.error("Fetch failed for %s: %s", company.name, e)
            # Clear conditional GET state for this URL on failure
            _clear_fetch_state(fetch_url)
            if is_transient(e):
                # Retry with exponential backoff (Celery handles retry count)
                self.retry(exc=e)
            else:
                # Permanent failure: log error, mark run failed, update health
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
                scrape_run.verdict = RunVerdict.UNTRUSTED
                scrape_run.verdict_reason = f"FetchError: {str(e)[:100]}"
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
                    "error": str(e),
                    "error_type": type(e).__name__,
                }

        if needs_browser_escalation and not force_browser:
            defer_minutes = getattr(settings, "SCRAPE_DEFER_DELAY_MINUTES", 30)
            scrape_run.notes = "deferred_to_browser"
            scrape_run.status = "success"
            scrape_run.finished_at = timezone.now()
            scrape_run.duration_ms = int(
                (scrape_run.finished_at - started_at).total_seconds() * 1000
            )
            scrape_run.save()
            company.next_scrape_at = timezone.now() + timedelta(minutes=defer_minutes)
            company.save(update_fields=["next_scrape_at"])
            scrape_company.apply_async(
                args=(str(company.id),),
                kwargs={"triggered_by": triggered_by, "force_browser": True},
                queue="scraping_browser",
            )
            return {
                "company_id": str(company.id),
                "status": "deferred",
                "jobs_found": 0,
                "jobs_added": 0,
                "jobs_updated": 0,
                "jobs_missing": 0,
                "duration_ms": scrape_run.duration_ms or 0,
            }

        verdict = RunVerdict.TRUSTED
        if fetch_result.not_modified:
            scrape_run.notes = "not_modified"
            scrape_run.verdict = RunVerdict.TRUSTED
            scrape_run.verdict_reason = "Conditional GET indicated no changes"

            company.jobs.filter(status=JobStatus.OPEN, is_deleted=False).update(
                last_seen_at=timezone.now()
            )

            prior_jobs_seen = company.last_jobs_seen
            record_scrape_outcome(
                company=company,
                success=True,
                jobs_seen=prior_jobs_seen,
                now=timezone.now(),
            )

            jobs_found = prior_jobs_seen
            jobs_added = 0
            jobs_updated = 0
            jobs_unchanged = 0
            jobs_reopened = 0
            jobs_missing = 0
            seen_job_ids = []

            # Skip parser and apply_missing_strikes (go to finalization)
        else:
            # Step 8: Call parser
            try:
                payloads = parser_module.parse(fetch_result, company=company)
            except Exception as e:
                # Re-raise SoftTimeLimitExceeded to be handled by outer handler
                if isinstance(e, SoftTimeLimitExceeded):
                    raise
                # ParseError handling
                logger.error("Parse failed for %s: %s", company.name, e)
                # Clear conditional GET state on parse failure
                _clear_fetch_state(fetch_url)
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
                scrape_run.verdict = RunVerdict.UNTRUSTED
                scrape_run.verdict_reason = f"ParseError: {str(e)[:100]}"
                scrape_run.save()

                # Store artifact for failed parse if body exists
                if fetch_result and fetch_result.html:
                    store_artifact(
                        scrape_run=scrape_run,
                        company=company,
                        url=fetch_url,
                        body=fetch_result.html,
                    )

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

            # Step 9: Process payloads and tally results
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
                    # Inject parser version into payload for upsert_job
                    payload["parser_version"] = parser_version_str
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

            # Compute jobs_found after processing payloads
            jobs_found = len(payloads)

            # Step 9.5: Evaluate run sanity
            run_status = "success" if jobs_found > 0 else "failure"
            last_successful_run = (
                ScrapeRun.objects.filter(company=company, status="success")
                .order_by("-finished_at")
                .first()
            )
            last_jobs_seen = last_successful_run.jobs_found if last_successful_run else 0

            verdict, verdict_reason = evaluate_run(
                run_status=run_status,
                jobs_found=jobs_found,
                last_jobs_seen=last_jobs_seen,
            )
            scrape_run.verdict = verdict
            scrape_run.verdict_reason = verdict_reason
            scrape_run.save(update_fields=["verdict", "verdict_reason"])

            # Store artifact if verdict is UNTRUSTED or QUARANTINED and body exists
            if (
                verdict in (RunVerdict.UNTRUSTED, RunVerdict.QUARANTINED)
                and fetch_result
                and fetch_result.html
            ):
                store_artifact(
                    scrape_run=scrape_run,
                    company=company,
                    url=fetch_url,
                    body=fetch_result.html,
                )

            # If verdict is UNTRUSTED or QUARANTINED, clear conditional GET state
            if verdict in (RunVerdict.UNTRUSTED, RunVerdict.QUARANTINED):
                _clear_fetch_state(fetch_url)

            # Step 10: Apply missing strikes only for TRUSTED verdict
            if verdict == RunVerdict.TRUSTED:
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
            else:
                logger.warning(
                    "Skipping missing strikes for %s due to verdict %s",
                    company.name,
                    verdict,
                )
                scrape_run.verdict_reason = (
                    f"{scrape_run.verdict_reason or ''} (strikes skipped)"
                ).strip()
                scrape_run.save(update_fields=["verdict_reason"])
                jobs_missing = 0

        # Step 11: Update company (skip for not_modified path; record_scrape_outcome handles it)
        if not fetch_result.not_modified:
            now = timezone.now()
            company.last_scraped_at = now
            company.next_scrape_at = now + timedelta(minutes=company.scrape_interval_minutes)

            # Update health based on success
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

        if not force_browser and verdict == RunVerdict.TRUSTED:
            _maybe_apply_adaptive_interval(company=company, scrape_run=scrape_run)

        return {
            "company_id": str(company.id),
            "status": status,
            "jobs_found": jobs_found,
            "jobs_added": jobs_added,
            "jobs_updated": jobs_updated,
            "jobs_missing": jobs_missing,
            "duration_ms": duration_ms,
        }

    except Retry:
        # Celery retry exceptions must propagate out of the task
        raise
    except Exception as e:
        # Outermost exception handling
        logger.error(
            "Unhandled exception in scrape_company for %s: %s", company.name, e, exc_info=True
        )
        # Record a ScrapeError for the unhandled exception
        ScrapeError.objects.create(
            scrape_run=scrape_run,
            company=company,
            url=fetch_url,
            error_type=type(e).__name__,
            message=str(e),
            traceback="",
        )
        # Clear conditional GET state on unhandled exception
        if fetch_url:
            _clear_fetch_state(fetch_url)
        scrape_run.status = "failed"
        scrape_run.error = {"message": str(e), "type": type(e).__name__}
        scrape_run.verdict = RunVerdict.UNTRUSTED
        scrape_run.verdict_reason = f"Unhandled exception: {type(e).__name__}"
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


def compute_adaptive_interval(*, current_minutes: int, recent: list[tuple[int, int]]) -> int:
    min_interval = MIN_SCRAPE_INTERVAL_MINUTES
    max_interval = getattr(settings, "SCRAPE_INTERVAL_MAX_MINUTES", 1440)
    if len(recent) < 3:
        return current_minutes
    if all(ja == 0 and jm == 0 for ja, jm in recent[:3]):
        return min(current_minutes * 2, max_interval)
    newest_added, _newest_missing = recent[0]
    if newest_added > 0:
        return max(current_minutes // 2, min_interval)
    return current_minutes


def _maybe_apply_adaptive_interval(*, company: Company, scrape_run: ScrapeRun) -> None:
    from apps.companies.services import update_scrape_interval

    trusted_runs = (
        ScrapeRun.objects.filter(
            company=company,
            verdict=RunVerdict.TRUSTED,
        )
        .order_by("-finished_at")
        .only("jobs_added", "jobs_missing")[:3]
    )
    recent = [(r.jobs_added, r.jobs_missing) for r in trusted_runs]
    new_interval = compute_adaptive_interval(
        current_minutes=company.scrape_interval_minutes, recent=recent
    )
    if new_interval != company.scrape_interval_minutes:
        update_scrape_interval(company=company, minutes=new_interval, actor=None)


def _update_company_health(company: Company, success: bool) -> None:
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


@shared_task(name="scraping.tasks.purge_scrape_artifacts", queue="scraping")
def purge_scrape_artifacts() -> dict[str, Any]:
    """Delete scrape artifacts older than SCRAPE_ARTIFACT_RETENTION_DAYS."""
    from django.conf import settings
    from django.utils import timezone

    from apps.scraping.models import ScrapeArtifact

    retention_days = getattr(settings, "SCRAPE_ARTIFACT_RETENTION_DAYS", 14)
    cutoff = timezone.now() - timedelta(days=retention_days)

    deleted_total = 0
    batch_size = 1000

    while True:
        # Get a batch of old artifacts to delete
        ids = list(
            ScrapeArtifact.objects.filter(created_at__lt=cutoff).values_list("id", flat=True)[
                :batch_size
            ]
        )
        if not ids:
            break
        count, _ = ScrapeArtifact.objects.filter(id__in=ids).delete()
        deleted_total += count
        if count < batch_size:
            break

    return {"deleted": deleted_total, "cutoff": cutoff.isoformat()}


@shared_task(name="scraping.tasks.refresh_all_companies", queue="scraping")
def refresh_all_companies() -> dict[str, Any]:
    lock_key = "global:scrape-cycle"
    try:
        with redis_lock(lock_key, timeout=15 * 60, blocking=False):
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
