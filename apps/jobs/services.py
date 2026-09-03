"""Job services — the single write path for scraped jobs and admin ops.

``upsert_job`` and ``apply_missing_strikes`` are FROZEN signatures consumed by
PROMPT 5 (scraping). Never hard-delete a job here.
"""

import logging
import re
from collections.abc import Iterable
from datetime import timedelta
from typing import Any

import nh3
from django.db import transaction
from django.db.models import F
from django.utils import timezone

from apps.audit_logs.services import record, snapshot
from core.utils import normalize_url, sha256_of

from .enums import (
    MAX_MISSING_COUNT,
    MISSING_STATUS_LADDER,
    JobStatus,
    ReportReason,
    ReportStatus,
)
from .models import Job, JobReport, JobStatusEvent, SavedJob

# Allowed HTML tags and attributes for sanitizing description_html
_ALLOWED_TAGS = frozenset(
    {
        "p",
        "br",
        "strong",
        "em",
        "u",
        "ul",
        "ol",
        "li",
        "h3",
        "h4",
        "a",
        "code",
        "pre",
        "blockquote",
    }
)

# Create a single Cleaner instance for reuse (thread-safe)
_SANITIZE_CLEANER = nh3.Cleaner(
    tags=_ALLOWED_TAGS,
    attributes={
        "*": set(),  # No attributes on any tag by default
        "a": {"href", "title", "target"},  # Only these attributes on <a>
    },
    link_rel="nofollow noopener noreferrer",
    url_schemes={"http", "https", "mailto"},
    set_tag_attribute_values={"a": {"target": "_blank"}},
    strip_comments=True,
)


def _sanitize_html(html: str, job_id: str | None = None) -> str:
    if not html:
        return ""

    # Check input size against cap
    from django.conf import settings

    max_bytes = getattr(settings, "SANITIZE_MAX_INPUT_BYTES", 512 * 1024)

    if len(html.encode("utf-8")) > max_bytes:
        # Truncate at the cap before sanitizing
        truncated_html = html.encode("utf-8")[:max_bytes].decode("utf-8", errors="replace")
        if job_id:
            logger.warning(
                "Sanitizer input cap exceeded for job %s: %d bytes truncated to %d bytes",
                job_id,
                len(html.encode("utf-8")),
                max_bytes,
            )
        html = truncated_html

    return _SANITIZE_CLEANER.clean(html)


logger = logging.getLogger("study_tracker.jobs")

_PUNCT_RE = re.compile(r"[^\w\s]+", re.UNICODE)

_UPDATABLE_FIELDS = (
    "title",
    "description",
    "description_html",
    "description_html_sanitized",
    "apply_url",
    "location_raw",
    "city",
    "state",
    "country",
    "work_mode",
    "job_type",
    "experience_level",
    "min_experience_years",
    "max_experience_years",
    "salary_min",
    "salary_max",
    "salary_currency",
    "salary_period",
    "department",
    "skills",
    "education_required",
    "posted_at",
    "deadline_at",
)


def _title_normalized(title: str) -> str:
    return _PUNCT_RE.sub("", title.lower()).strip()


def _payload_hash(title: str, location_raw: str, description: str) -> str:
    return sha256_of(title, location_raw, description)


def _hash_for(payload: dict[str, Any], job: Job | None = None) -> str:
    """Hash of the stored content after edits: manually-edited fields never count as
    material change, so a scraper re-fetch of an edited job stays ``unchanged``."""
    edited = frozenset(job.manually_edited_fields) if job is not None else frozenset()
    title = job.title if job is not None and "title" in edited else str(payload.get("title", ""))
    location = (
        job.location_raw
        if job is not None and "location_raw" in edited
        else str(payload.get("location_raw", ""))
    )
    description = (
        job.description
        if job is not None and "description" in edited
        else str(payload.get("description", "") or "")
    )
    return _payload_hash(title, location, description)


def _confidence(payload: dict[str, Any]) -> int:
    try:
        return max(0, min(100, int(payload.get("extraction_confidence", 0))))
    except (TypeError, ValueError):
        return 0


def _update_values(payload: dict[str, Any], job: Job | None = None) -> dict[str, Any]:
    edited = frozenset(job.manually_edited_fields) if job is not None else frozenset()
    values: dict[str, Any] = {}
    for field in _UPDATABLE_FIELDS:
        if field in edited or field not in payload:
            continue
        candidate = payload[field]
        if job is not None and getattr(job, field, None) == candidate:
            continue
        values[field] = candidate
    return values


# ---------------------------------------------------------------------------
# The single write path for scraped jobs
# ---------------------------------------------------------------------------
def upsert_job(
    *,
    company: Any,
    payload: dict[str, Any],
    scrape_run_id: str | None = None,
    actor: Any = None,
) -> tuple[Job, str]:
    """Create/update a scraped job. Returns ``(job, outcome)``.

    outcome ∈ {"created", "updated", "unchanged", "reopened"}
    """
    src_job_id = str(payload.get("source_job_id") or "").strip()
    source_url = str(payload.get("source_url") or "")
    title = str(payload.get("title") or "").strip()
    location_raw = str(payload.get("location_raw") or "")
    description = str(payload.get("description") or "")
    norm_url = normalize_url(source_url)
    title_norm = _title_normalized(title)
    hash_value = _payload_hash(title, location_raw, description)

    match = None
    qs = company.jobs.all()
    if src_job_id:
        match = qs.filter(source_job_id=src_job_id).first()
    if match is None and norm_url:
        match = qs.filter(normalized_source_url=norm_url).first()
    if match is None and norm_url:
        match = qs.filter(title_normalized=title_norm, normalized_source_url=norm_url).first()
    if match is None:
        match = qs.filter(content_hash=hash_value).order_by("first_seen_at").first()

    if match is None:
        return _create_job(
            company=company,
            payload=payload,
            src_job_id=src_job_id,
            norm_url=norm_url,
            title_norm=title_norm,
            hash_value=hash_value,
            scrape_run_id=scrape_run_id,
        )
    return _update_job(
        job=match,
        company=company,
        payload=payload,
        norm_url=norm_url,
        scrape_run_id=scrape_run_id,
    )


def _create_job(
    *,
    company: Any,
    payload: dict[str, Any],
    src_job_id: str,
    norm_url: str,
    title_norm: str,
    hash_value: str,
    scrape_run_id: str | None,
) -> tuple[Job, str]:
    title = str(payload.get("title") or "").strip()
    now = timezone.now()
    confidence = _confidence(payload)
    is_ats = company.is_ats
    auto_publish = is_ats and confidence >= 70
    values = {
        "status": JobStatus.OPEN,
        "missing_count": 0,
        "first_seen_at": now,
        "last_seen_at": now,
        "source_job_id": src_job_id,
        "normalized_source_url": norm_url,
        "title_normalized": title_norm,
        "content_hash": hash_value,
        "source_url": str(payload.get("source_url") or ""),
        "title": title,
        "description": str(payload.get("description") or ""),
        "description_html": str(payload.get("description_html") or ""),
        "description_html_sanitized": _sanitize_html(str(payload.get("description_html") or "")),
        "location_raw": str(payload.get("location_raw") or ""),
        "extraction_confidence": confidence,
        "raw_payload": payload,
        "is_published": auto_publish,
        "published_at": now if auto_publish else None,
        "needs_review": not auto_publish,
        "review_reason": (
            "" if auto_publish else ("custom source" if not is_ats else "low confidence")
        ),
    }
    values.update({k: v for k, v in _update_values(payload).items() if k not in values})
    with transaction.atomic():
        job = Job.objects.create(company=company, **values)
        JobStatusEvent.objects.create(
            job=job,
            from_status="",
            to_status=JobStatus.OPEN,
            trigger="scrape",
            scrape_run_id=scrape_run_id,
        )
        record(
            "job.created",
            instance=job,
            before={},
            after=snapshot(job),
            source="SYSTEM",
        )
    return job, "created"


def _update_job(
    *,
    job: Job,
    company: Any,
    payload: dict[str, Any],
    norm_url: str,
    scrape_run_id: str | None,
) -> tuple[Job, str]:
    now = timezone.now()
    values = _update_values(payload, job)
    outcome = "updated"
    old_status = job.status

    reopen = (
        old_status in {JobStatus.POSSIBLY_CLOSED, JobStatus.LIKELY_CLOSED, JobStatus.CLOSED}
        and not job.is_manual_status
    )

    if reopen:
        outcome = "reopened"
        job.status = JobStatus.OPEN
        job.closed_at = None
        job.reopened_count += 1

    effective_hash = _hash_for(payload, job)
    material_change = effective_hash != job.content_hash
    url_changed = str(payload.get("source_url") or "") != job.source_url
    if (
        not reopen
        and not values
        and not url_changed
        and not material_change
        and old_status == JobStatus.OPEN
    ):
        outcome = "unchanged"
        Job.objects.filter(pk=job.pk).update(last_seen_at=now, missing_count=0)
        return job, outcome

    with transaction.atomic():
        for key, value in values.items():
            setattr(job, key, value)
        if url_changed:
            job.source_url = str(payload.get("source_url") or "")
            job.normalized_source_url = norm_url
        if material_change:
            job.content_hash = effective_hash
        if material_change and not company.is_ats:
            job.needs_review = True
            job.review_reason = "content changed"
        job.last_seen_at = now
        job.missing_count = 0
        job.save()

        if outcome == "reopened":
            JobStatusEvent.objects.create(
                job=job,
                from_status=old_status,
                to_status=JobStatus.OPEN,
                trigger="reopen",
                scrape_run_id=scrape_run_id,
            )
            record(
                "job.reopened",
                instance=job,
                before={},
                after=snapshot(job, ["status", "closed_at", "reopened_count"]),
                source="SYSTEM",
            )
    return job, outcome


# ---------------------------------------------------------------------------
# The 3-strike ladder
# ---------------------------------------------------------------------------
def apply_missing_strikes(
    *, company: Any, seen_job_ids: Iterable[Any], scrape_run_id: str | None = None
) -> dict[str, Any]:
    """Apply one missing-strike round to a company's unseen jobs.

    NEVER deletes rows — closed jobs stay forever with a Closed label.
    """
    counts = {"possibly_closed": 0, "likely_closed": 0, "closed": 0, "untouched": 0}
    scope = (
        company.jobs.filter(
            status__in=[
                JobStatus.OPEN,
                JobStatus.POSSIBLY_CLOSED,
                JobStatus.LIKELY_CLOSED,
            ]
        )
        .exclude(is_manual_status=True)
        .order_by("pk")
    )
    if scope.exists() and not seen_job_ids:
        logger.warning(
            "Scrape for %s returned zero jobs; skipping strikes (empty_result_guard)",
            company.name,
        )
        return {"skipped": True, "reason": "empty_result_guard"}

    seen = set(seen_job_ids or [])
    pending = list(scope.exclude(pk__in=seen)) if seen else []
    if not seen:
        pending = list(scope)

    now = timezone.now()

    for start in range(0, len(pending), 500):
        batch = pending[start : start + 500]
        events: list[JobStatusEvent] = []
        for job in batch:
            new_missing = job.missing_count + 1
            if new_missing > MAX_MISSING_COUNT:
                new_missing = MAX_MISSING_COUNT
            new_status = MISSING_STATUS_LADDER[new_missing]
            old_status = job.status
            changed = old_status != new_status
            if new_status == JobStatus.CLOSED:
                job.closed_at = now
            job.status = new_status
            job.missing_count = new_missing
            if changed:
                events.append(
                    JobStatusEvent(
                        job=job,
                        from_status=old_status,
                        to_status=new_status,
                        missing_count=new_missing,
                        trigger="ladder",
                        scrape_run_id=scrape_run_id,
                    )
                )
            if new_status == JobStatus.POSSIBLY_CLOSED:
                counts["possibly_closed"] += 1
            elif new_status == JobStatus.LIKELY_CLOSED:
                counts["likely_closed"] += 1
            elif new_status == JobStatus.CLOSED:
                counts["closed"] += 1
            else:  # pragma: no cover - unreachable: ladder only maps to the three statuses above
                counts["untouched"] += 1
        Job.objects.bulk_update(batch, ["status", "missing_count", "closed_at"], batch_size=500)
        if events:
            JobStatusEvent.objects.bulk_create(events, batch_size=500)
    return counts


# ---------------------------------------------------------------------------
# Publishing / review / lifecycle
# ---------------------------------------------------------------------------
def publish_job(*, job: Job, actor: Any, reason: str = "") -> Job:
    with transaction.atomic():
        if not job.is_published:
            job.is_published = True
            job.published_at = job.published_at or timezone.now()
            job.save(update_fields=["is_published", "published_at", "updated_at"])
        record(
            "job.published",
            actor=actor,
            instance=job,
            before={},
            after=snapshot(job, ["is_published", "published_at"]),
            source="ADMIN",
        )
    return job


def unpublish_job(*, job: Job, actor: Any, reason: str = "") -> Job:
    with transaction.atomic():
        if job.is_published:
            job.is_published = False
            job.save(update_fields=["is_published", "updated_at"])
        record(
            "job.unpublished",
            actor=actor,
            instance=job,
            before={},
            after=snapshot(job, ["is_published"]),
            source="ADMIN",
        )
    return job


def mark_job_closed(*, job: Job, actor: Any, reason: str = "") -> Job:
    with transaction.atomic():
        if job.status != JobStatus.CLOSED:
            old_status = job.status
            job.status = JobStatus.CLOSED
            job.closed_at = timezone.now()
            job.is_manual_status = True
            job.save(update_fields=["status", "closed_at", "is_manual_status", "updated_at"])
            JobStatusEvent.objects.create(
                job=job,
                from_status=old_status,
                to_status=JobStatus.CLOSED,
                trigger="admin",
                actor=actor,
                note=reason,
            )
        record(
            "job.closed",
            actor=actor,
            instance=job,
            before={},
            after=snapshot(job, ["status", "closed_at"]),
            source="ADMIN",
        )
    return job


def reopen_job(*, job: Job, actor: Any, reason: str = "") -> Job:
    with transaction.atomic():
        old_status = job.status
        job.status = JobStatus.OPEN
        job.closed_at = None
        job.is_manual_status = False
        job.missing_count = 0
        job.reopened_count += 1
        job.save(
            update_fields=[
                "status",
                "closed_at",
                "is_manual_status",
                "missing_count",
                "reopened_count",
                "updated_at",
            ]
        )
        JobStatusEvent.objects.create(
            job=job,
            from_status=old_status,
            to_status=JobStatus.OPEN,
            trigger="reopen",
            actor=actor,
            note=reason,
        )
        record(
            "job.reopened",
            actor=actor,
            instance=job,
            before={},
            after=snapshot(job, ["status", "reopened_count"]),
            source="ADMIN",
        )
    return job


def mark_duplicate(*, job: Job, canonical: Job, actor: Any) -> Job:
    if job.pk == canonical.pk:
        raise ValueError("A job cannot be a duplicate of itself")
    current: Job | None = canonical
    seen: set[Any] = set()
    while current is not None and current.duplicate_of_id is not None:
        if current.duplicate_of_id == job.pk or current.pk in seen:
            raise ValueError("Duplicate cycle detected")
        seen.add(current.pk)
        current = current.duplicate_of
    with transaction.atomic():
        job.duplicate_of = canonical
        if job.is_published:
            job.is_published = False
        job.save(update_fields=["duplicate_of", "is_published", "updated_at"])
        record(
            "job.marked_duplicate",
            actor=actor,
            instance=job,
            before={},
            after=snapshot(job, ["duplicate_of", "is_published"]),
            source="ADMIN",
        )
    return job


_EDITABLE_FIELDS = frozenset(_UPDATABLE_FIELDS)


def edit_job_fields(*, job: Job, changes: dict[str, Any], actor: Any) -> Job:
    """The ONLY sanctioned way to edit scraped content (admin uses this)."""
    unknown = set(changes) - _EDITABLE_FIELDS
    if unknown:
        from django.core.exceptions import ValidationError

        raise ValidationError(f"Unknown editable fields: {sorted(unknown)}")

    with transaction.atomic():
        before = snapshot(job)
        edited = set(job.manually_edited_fields)
        for key, value in changes.items():
            setattr(job, key, value)
            edited.add(key)
        job.manually_edited_fields = sorted(edited)
        job.title_normalized = _title_normalized(job.title)
        job.content_hash = _payload_hash(job.title, job.location_raw, job.description)
        job.needs_review = False
        job.review_reason = ""
        job.reviewed_by = actor
        job.reviewed_at = timezone.now()
        job.save()
        record(
            "job.fields_edited",
            actor=actor,
            instance=job,
            before=before,
            after=snapshot(job),
            source="ADMIN",
        )
    return job


def approve_job_review(*, job: Job, actor: Any) -> Job:
    with transaction.atomic():
        job.needs_review = False
        job.review_reason = ""
        job.reviewed_by = actor
        job.reviewed_at = timezone.now()
        if not job.is_published:
            job.is_published = True
            job.published_at = timezone.now()
        job.save()
        record(
            "job.review.approved",
            actor=actor,
            instance=job,
            before={},
            after=snapshot(job, ["needs_review", "is_published"]),
            source="ADMIN",
        )
    return job


def reject_job_review(*, job: Job, actor: Any, reason: str) -> Job:
    with transaction.atomic():
        job.needs_review = False
        job.review_reason = reason
        job.reviewed_by = actor
        job.reviewed_at = timezone.now()
        job.save()
        record(
            "job.review.rejected",
            actor=actor,
            instance=job,
            before={},
            after=snapshot(job, ["needs_review", "review_reason"]),
            source="ADMIN",
        )
    return job


# ---------------------------------------------------------------------------
# Reports / saves
# ---------------------------------------------------------------------------
def submit_job_report(*, job: Job, user: Any, reason: str, detail: str = "") -> JobReport:
    if reason not in ReportReason.values:
        from django.core.exceptions import ValidationError

        raise ValidationError(f"Unknown report reason: {reason}")
    with transaction.atomic():
        report, created = JobReport.objects.get_or_create(
            job=job,
            user=user,
            status=ReportStatus.OPEN,
            defaults={"reason": reason, "detail": detail},
        )
        if not created:
            from django.core.exceptions import ValidationError

            raise ValidationError("An open report for this job already exists")
        Job.objects.filter(pk=job.pk).update(report_count=F("report_count") + 1)
        open_count = job.reports.filter(status=ReportStatus.OPEN).count()
        if open_count >= 3 and job.is_published:
            Job.objects.filter(pk=job.pk).update(needs_review=True, review_reason="user reports")
        record(
            "job.reported",
            actor=user,
            instance=report,
            before={},
            after=snapshot(report),
            source="API",
        )
    return report


def resolve_report(*, report: JobReport, actor: Any, accept: bool, note: str = "") -> JobReport:
    with transaction.atomic():
        report.status = ReportStatus.RESOLVED if accept else ReportStatus.REJECTED
        report.resolved_by = actor
        report.resolved_at = timezone.now()
        report.resolution_note = note
        report.save()
        if accept and report.reason == ReportReason.EXPIRED:
            mark_job_closed(job=report.job, actor=actor, reason="report accepted")
        record(
            "job.report.resolved",
            actor=actor,
            instance=report,
            before={},
            after=snapshot(report, ["status", "resolved_by", "resolved_at"]),
            source="ADMIN",
        )
    return report


def save_job(*, user: Any, job: Job) -> SavedJob:
    with transaction.atomic():
        saved, created = SavedJob.objects.get_or_create(user=user, job=job)
        if created:
            Job.objects.filter(pk=job.pk).update(save_count=F("save_count") + 1)
        record(
            "job.saved",
            actor=user,
            instance=saved,
            before={},
            after=snapshot(saved, ["job", "user"]),
            source="API",
        )
    return saved


def unsave_job(*, user: Any, job: Job) -> None:
    with transaction.atomic():
        deleted, _ = SavedJob.objects.filter(user=user, job=job).delete()
        if deleted:
            Job.objects.filter(pk=job.pk, save_count__gt=0).update(save_count=F("save_count") - 1)
        record(
            "job.unsaved",
            actor=user,
            instance=job,
            before={},
            after={},
            source="API",
        )


# ---------------------------------------------------------------------------
# Search vectors
# ---------------------------------------------------------------------------


def compute_trust_label(job: Job) -> str:
    """Pure function — no DB writes. Freshness note built from last_seen_at."""
    from apps.companies.enums import CareerSourceType

    parts: list[str] = []
    if job.company.is_verified and job.company.is_ats:
        parts.append("Verified source")
    elif job.company.career_source_type == CareerSourceType.OWN_CAREER_PAGE:
        parts.append("Official career page")
    if job.last_seen_at is not None and timezone.now() - job.last_seen_at <= timedelta(hours=6):
        parts.append("Checked recently")
    return " | ".join(parts)
