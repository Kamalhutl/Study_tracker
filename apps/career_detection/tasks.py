"""Celery tasks for career-url detection — PROMPT_3_SECTION_6 §6.6.

Two entry points:
  * ``detect_career_url``            — run detection for one company.
  * ``detect_pending_companies_task`` — enumerate PENDING companies and enqueue
    one ``detect_career_url`` per company (per-company retry/locking semantics).
"""

from __future__ import annotations

import logging
from typing import Any

from celery import shared_task

from apps.companies.enums import DetectionStatus
from apps.companies.exceptions import DetectionNotApplicable
from apps.scraping.exceptions import (
    FetchDomainBlocked,
    FetchNotFound,
    FetchRobotsDisallowed,
    FetchTimeout,
)
from config.celery import app

from .services import run_detection

logger = logging.getLogger("study_tracker.career_detection.tasks")

#: Non-transient failures — retrying can never succeed, so surface them.
_NO_RETRY = (FetchDomainBlocked, FetchRobotsDisallowed, FetchNotFound)


@app.task(  # type: ignore[untyped-decorator]
    bind=True,
    name="apps.career_detection.tasks.detect_career_url",
    max_retries=3,
    default_retry_delay=30,
    autoretry_for=(FetchTimeout,),
    retry_backoff=True,
    retry_backoff_max=300,
    retry_jitter=True,
)
def detect_career_url(self: Any, company_id: str) -> dict[str, object]:
    """Detect the career URL for one company.

    Returns a summary dict; raises on transient failures so Celery retries.
    """
    del self  # bound task; only used implicitly for retries by the decorator
    from apps.companies.models import Company

    company = Company.objects.filter(pk=company_id).first()
    if company is None:
        logger.warning("detect_career_url: company %s not found", company_id)
        return {"company_id": company_id, "status": "not_found"}
    if company.detection_status in {
        DetectionStatus.VERIFIED,
        DetectionStatus.SKIPPED,
    }:
        return {"company_id": company_id, "status": "skipped"}

    try:
        result = run_detection(company)
    except DetectionNotApplicable:
        return {"company_id": company_id, "status": "skipped"}
    except FetchTimeout:
        raise
    return _summarize(result)


@shared_task(name="apps.career_detection.tasks.detect_pending_companies")  # type: ignore[untyped-decorator]
def detect_pending_companies_task(limit: int = 50) -> dict[str, object]:
    """Enumerate PENDING companies and enqueue one task apiece."""
    from apps.companies.models import Company

    company_ids = list(
        Company.objects.pending_detection()
        .order_by("created_at")
        .values_list("pk", flat=True)[:limit]
    )
    for company_id in company_ids:
        detect_career_url.delay(str(company_id))
    return {"enqueued": len(company_ids), "company_ids": [str(c) for c in company_ids]}


def _summarize(result: dict[str, Any]) -> dict[str, object]:
    candidates = result["candidates"]
    return {
        "company_id": result["company_id"],
        "run_id": result.get("run_id"),
        "dry_run": result["dry_run"],
        "status": result["status"],
        "candidate_count": len(candidates),
        "best_score": result.get("best_score", 0),
    }
