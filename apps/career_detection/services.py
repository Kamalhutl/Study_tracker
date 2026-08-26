"""Detection orchestration — PROMPT_3_SECTION_6 §6.5.

Single entry point: :func:`run_detection`. Everything that can fail is
contained; the DetectionRun row is always finished with a real status and a
human-readable note. Network statements of truth: strategies fetch, this module
decides.
"""

from __future__ import annotations

import logging
import time
from typing import Any

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from apps.audit_logs.services import record
from apps.companies.enums import (
    CandidateOrigin,
    CareerSourceType,
    DetectionStatus,
)
from apps.companies.exceptions import DetectionNotApplicable
from apps.companies.models import CareerCandidateUrl, Company, DetectionRun
from apps.scraping.exceptions import FetchBudgetExceeded
from core.locks import LockNotAcquired, redis_lock

from .scoring import score_candidate
from .strategies import _scoring_evidence, get_strategies
from .types import DetectionContext, RawCandidate

logger = logging.getLogger("study_tracker.career_detection.services")

LOCK_TTL_SECONDS = 300


def run_detection(
    company: Company,
    *,
    actor: Any = None,
    dry_run: bool = False,
    max_checks: int | None = None,
) -> dict[str, Any]:
    """Run the full §6.5 pipeline for one Company.

    Returns a summary dict:
        company_id, run_id, dry_run, status, candidates, best_score,
        checks_used, notes (list), short_circuited (bool)

    ``dry_run=True`` persists nothing (audit trail included): all candidates and
    the run row are kept in memory only.

    Phases:
    1. Guard (Redis, no DB transaction): acquire per-company lock.
    2. Eligibility + run row (short transaction): re-read company, create run.
    3. Strategies (NO transaction, NO row lock): all network I/O here.
    4. Persist (short transaction): write candidates, finalize run, audit log.
    """
    # Phase 1: Guard — Redis lock, no DB transaction
    lock_key = f"detect:{company.pk}"
    try:
        # Non-blocking; TTL comfortably above 120s detection budget
        with redis_lock(lock_key, timeout=LOCK_TTL_SECONDS, blocking=False):
            return _run_detection_phased(
                company, actor=actor, dry_run=dry_run, max_checks=max_checks
            )
    except LockNotAcquired:
        logger.warning("Detection already in flight for company %s; skipping", company.pk)
        return {
            "company_id": str(company.pk),
            "run_id": None,
            "dry_run": dry_run,
            "status": DetectionStatus.FAILED,
            "candidates": [],
            "best_score": 0,
            "checks_used": 0,
            "notes": ["detection already in flight"],
            "short_circuited": False,
        }


def _candidate_summaries(
    ranked: list[tuple[RawCandidate, int, list[dict[str, Any]]]],
) -> list[dict[str, Any]]:
    return [{"url": c.url, "origin": c.origin, "score": s, "trail": t} for c, s, t in ranked]


def _run_detection_phased(
    company: Company,
    *,
    actor: Any = None,
    dry_run: bool = False,
    max_checks: int | None = None,
) -> dict[str, Any]:
    """Internal implementation with four phases: Guard, Eligibility, Strategies, Persist."""

    # Phase 2: Eligibility + run row (short transaction)
    run = None
    with transaction.atomic():
        company = Company.objects.filter(pk=company.pk).first()
        if company is None:
            raise DetectionNotApplicable("Company no longer exists")
        if company.is_deleted:
            raise DetectionNotApplicable("Company is soft-deleted")
        if company.is_verified and bool(company.career_url):
            raise DetectionNotApplicable("Company is already verified with a career URL")

        started = time.monotonic()
        ctx = DetectionContext(
            company=company,
            root_url=_root_url(company.domain),
            domain=company.domain,
            max_checks=max_checks or settings.DETECTION_MAX_URL_CHECKS,
            deadline=started + settings.DETECTION_TOTAL_BUDGET_SECONDS,
        )
        run = _start_run(company, dry_run=dry_run)

    # Phase 3: Strategies (NO transaction, NO row lock)
    results: dict[str, Any] = {
        "company_id": str(company.pk),
        "run_id": str(run.pk) if run is not None else None,
        "dry_run": dry_run,
        "status": DetectionStatus.FAILED,
        "candidates": [],
        "best_score": 0,
        "checks_used": 0,
        "notes": [],
        "short_circuited": False,
    }

    try:
        _execute(ctx)
        ranked, short_circuited = _rank(ctx)
        results["short_circuited"] = short_circuited
        results["checks_used"] = ctx.checks_used
        results["notes"] = list(ctx.notes)

        if ctx.homepage_error:
            final_status = DetectionStatus.FAILED
        elif not ranked:
            final_status = DetectionStatus.NO_CANDIDATES
        else:
            final_status = DetectionStatus.CANDIDATES_FOUND
            results["candidates"] = _candidate_summaries(ranked)
            results["best_score"] = max(s for _, s, _ in ranked)

        # Phase 4: Persist (short transaction) — re-read company and re-check eligibility
        _persist_results(
            company=company,
            run=run,
            ctx=ctx,
            ranked=ranked,
            final_status=final_status,
            dry_run=dry_run,
            actor=actor,
            started=started,
            results=results,
        )
        results["status"] = DetectionStatus.SUCCESS
    except FetchBudgetExceeded as exc:
        ctx.notes.append(f"budget exhausted: {exc}")
        results["notes"] = list(ctx.notes)
        results["checks_used"] = ctx.checks_used
        partial_ranked = _rank(ctx)[0]
        if ctx.homepage_error:
            partial_status = DetectionStatus.FAILED
        elif partial_ranked:
            partial_status = DetectionStatus.CANDIDATES_FOUND
        else:
            partial_status = DetectionStatus.NO_CANDIDATES
        results["candidates"] = _candidate_summaries(partial_ranked)
        results["best_score"] = max((s for _, s, _ in partial_ranked), default=0)

        _persist_results(
            company=company,
            run=run,
            ctx=ctx,
            ranked=partial_ranked,
            final_status=partial_status,
            dry_run=dry_run,
            actor=actor,
            started=started,
            results=results,
            run_status=DetectionStatus.PARTIAL,
        )
        results["status"] = DetectionStatus.PARTIAL
    except Exception as exc:
        logger.exception("Detection failed for company %s", company)
        results["status"] = DetectionStatus.FAILED
        results["notes"] = [*list(ctx.notes), str(exc)]
        if run is not None and not dry_run:
            with transaction.atomic():
                # Update company detection_status
                company = Company.objects.filter(pk=company.pk).first()
                if company is not None:
                    company.detection_status = DetectionStatus.FAILED
                    company.save(update_fields=["detection_status"])

                run.status = DetectionStatus.FAILED
                run.finished_at = timezone.now()
                run.error_message = str(exc)
                run.notes = "\n".join([*ctx.notes, str(exc)])[:2000]
                run.save(update_fields=["status", "finished_at", "error_message", "notes"])
        elif run is None and not dry_run:
            # run was None but not dry_run - shouldn't happen, but guard
            company = Company.objects.filter(pk=company.pk).first()
            if company is not None:
                company.detection_status = DetectionStatus.FAILED
                company.save(update_fields=["detection_status"])
        if dry_run:
            raise

    return results


def _persist_results(
    company: Company,
    run: DetectionRun | None,
    ctx: DetectionContext,
    ranked: list[tuple[RawCandidate, int, list[dict[str, Any]]]],
    final_status: str,
    dry_run: bool,
    actor: Any,
    started: float,
    results: dict[str, Any],
    run_status: str | None = None,
) -> None:
    """Phase 4: short transaction to persist results. Re-reads company and re-checks eligibility."""
    if dry_run:
        return

    with transaction.atomic():
        # Re-read company and re-check eligibility (race guard)
        # Use all_objects to include soft-deleted companies
        company = Company.all_objects.filter(pk=company.pk).first()
        if company is None:
            # Company deleted mid-run: mark run superseded if it exists
            if run is not None:
                run.status = DetectionStatus.SUPERSEDED
                run.finished_at = timezone.now()
                run.notes = "company deleted mid-run"
                run.save(update_fields=["status", "finished_at", "notes"])
            results["status"] = DetectionStatus.SUPERSEDED
            results["notes"].append("company deleted mid-run")
            return

        if company.is_deleted:
            if run is not None:
                run.status = DetectionStatus.SUPERSEDED
                run.finished_at = timezone.now()
                run.notes = "company soft-deleted mid-run"
                run.save(update_fields=["status", "finished_at", "notes"])
            results["status"] = DetectionStatus.SUPERSEDED
            results["notes"].append("company soft-deleted mid-run")
            return

        if company.is_verified and bool(company.career_url):
            if run is not None:
                run.status = DetectionStatus.SUPERSEDED
                run.finished_at = timezone.now()
                run.notes = "company became verified mid-run"
                run.save(update_fields=["status", "finished_at", "notes"])
            results["status"] = DetectionStatus.SUPERSEDED
            results["notes"].append("company became verified mid-run")
            return

        # All checks passed — persist
        candidate_rows = ranked[: settings.DETECTION_MAX_CANDIDATES]
        assert run is not None, "run is only None for dry runs"

        finished = timezone.now()
        company.detection_status = final_status
        company.detection_attempts = company.detection_attempts + 1
        company.last_detection_at = finished
        company.save(
            update_fields=[
                "detection_status",
                "detection_attempts",
                "last_detection_at",
            ]
        )

        for candidate, score, trail in candidate_rows:
            _upsert_candidate(run, company, candidate, score, trail)

        run.finished_at = finished
        run.duration_ms = int((time.monotonic() - started) * 1000)
        run.status = run_status or (
            DetectionStatus.SUCCESS
            if final_status != DetectionStatus.FAILED
            else DetectionStatus.FAILED
        )
        run.urls_checked = ctx.checks_used
        run.checks_used = ctx.checks_used
        run.candidates_found = len(candidate_rows)
        run.ats_short_circuit = ctx.ats_short_circuit
        run.strategies_used = _strategies_used(ctx)
        run.notes = "\n".join(ctx.notes)[:2000]
        run.log += [
            {"ts": finished.isoformat(), "msg": "detection finished", "status": final_status}
        ]
        run.save(
            update_fields=[
                "status",
                "finished_at",
                "duration_ms",
                "urls_checked",
                "checks_used",
                "candidates_found",
                "ats_short_circuit",
                "strategies_used",
                "notes",
                "log",
            ]
        )

    record(
        "detection.completed",
        actor=actor,
        instance=run,
        after={"status": run.status, "candidates": len(candidate_rows), "checks": ctx.checks_used},
        source="SYSTEM",
    )


def _root_url(domain: str) -> str:
    domain = (domain or "").strip().lower()
    if "://" not in domain:
        domain = f"https://{domain.strip('/')}"
    return domain.rstrip("/") + "/"


def _start_run(company: Company, *, dry_run: bool) -> DetectionRun | None:
    if dry_run:
        return None
    return DetectionRun.objects.create(
        company=company,
        status=DetectionStatus.RUNNING,
        log=[{"ts": timezone.now().isoformat(), "msg": "detection started"}],
    )


def _execute(ctx: DetectionContext) -> None:
    strategies = get_strategies()
    for strategy in strategies:
        if ctx.ats_short_circuit:
            # Skip strategies 3-7; only the Verify step (last) still runs.
            if strategy.name == "verify":
                strategy.run(ctx)
            continue
        strategy.run(ctx)
        # After strategies 1-2 (free + ATS harvest), a confident ATS hit
        # short-circuits the expensive probing (6.5 step 5).
        if strategy.name == "nav_link":
            ctx.ats_short_circuit = _ats_hit_confirmed(ctx)


def _ats_hit_confirmed(ctx: DetectionContext) -> bool:
    """True when the top ATS candidate already clears the short-circuit score."""
    threshold = settings.DETECTION_ATS_SHORTCIRCUIT_SCORE
    for candidate in ctx.candidates.values():
        if candidate.origin != "ats_pattern":
            continue
        evidence = _scoring_evidence(ctx, candidate)
        score, _ = score_candidate(url=candidate.url, evidence=evidence)
        if score >= threshold:
            return True
    return False


def _rank(
    ctx: DetectionContext,
) -> tuple[list[tuple[RawCandidate, int, list[dict[str, Any]]]], bool]:
    """Sort candidates: score desc, strategy cost asc, URL length asc, URL asc."""
    ranked: list[tuple[RawCandidate, int, list[dict[str, Any]]]] = []
    for candidate in ctx.candidates.values():
        evidence = _scoring_evidence(ctx, candidate)
        score, trail = score_candidate(url=candidate.url, evidence=evidence)
        if score >= settings.DETECTION_MIN_CANDIDATE_SCORE:
            ranked.append((candidate, score, trail))

    from .types import ORIGIN_COSTS

    ranked.sort(
        key=lambda pair: (
            -pair[1],
            ORIGIN_COSTS.get(pair[0].origin, 99),
            len(pair[0].url),
            pair[0].url,
        )
    )
    return ranked[: settings.DETECTION_MAX_CANDIDATES], ctx.ats_short_circuit


def _upsert_candidate(
    run: DetectionRun | None,
    company: Company,
    candidate: RawCandidate,
    score: int,
    trail: list[dict[str, Any]],
) -> None:
    CareerCandidateUrl.objects.update_or_create(
        company=company,
        normalized_url=candidate.url,
        defaults={
            "detection_run": run,
            "url": candidate.url,
            "score": score,
            "score_reasons": trail,
            "origin": CandidateOrigin(candidate.origin),
            "discovered_via": candidate.discovered_via,
            "page_title": candidate.evidence.get("title") or "",
            "http_status": candidate.evidence.get("http_status"),
            "sample_job_titles": candidate.evidence.get("sample_job_titles") or [],
            "guessed_type": candidate.evidence.get("ats_source") or CareerSourceType.UNKNOWN,
            "ats_identifier": candidate.evidence.get("ats_identifier", ""),
        },
    )


def _strategies_used(ctx: DetectionContext) -> list[str]:
    names = [strategy.name for strategy in get_strategies()]
    if ctx.ats_short_circuit:
        # §6.3: the short-circuit skips ONLY strategies 3-7 (robots, sitemap,
        # common_path, subdomain_guess, json_ld). NavLinkStrategy (2) always
        # runs because it reuses the homepage fetch at zero cost, and
        # VerifyStrategy (8) always runs on the surviving candidates.
        skipped = {"robots", "sitemap", "common_path", "subdomain_guess", "json_ld"}
        names = [name for name in names if name not in skipped]
    return names


def detect_pending_companies(limit: int = 50) -> list[dict[str, Any]]:
    """Run detection for every PENDING company (normally via the Celery task)."""
    out: list[dict[str, Any]] = []
    companies = Company.objects.pending_detection().order_by("created_at")[:limit]
    for company in companies:
        lock_key = f"detection:{company.pk}"
        try:
            with redis_lock(lock_key, timeout=LOCK_TTL_SECONDS):
                out.append(run_detection(company))
        except LockNotAcquired:
            logger.warning("Detection lock held for company %s; skipping", company.pk)
        except DetectionNotApplicable as exc:
            logger.info("Detection not applicable for %s: %s", company.pk, exc)
    return out


def detection_summary(company: Company) -> dict[str, Any]:
    """Admin-facing status text for a company (used by the change page help)."""
    status = company.detection_status
    next_action = {
        DetectionStatus.PENDING.value: "enqueued",
        DetectionStatus.RUNNING.value: "in_progress",
        DetectionStatus.CANDIDATES_FOUND.value: "review",
        DetectionStatus.VERIFIED.value: "clean",
        DetectionStatus.NO_CANDIDATES.value: "no_careers",
        DetectionStatus.FAILED.value: "retry",
        DetectionStatus.NEEDS_REVIEW.value: "review",
    }.get(status, "review")
    return {"status": status, "next_action": next_action}
