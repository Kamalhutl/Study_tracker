"""Company services — the ONLY sanctioned way to mutate Company state.

Produced from http real URLs only via these helpers:
``add_company_from_main_website`` (Case A) and ``add_company_from_direct_career_url``
(Case B). Every later step (detection, scraping, scheduling, user APIs) goes
through the functions here. Signatures are FROZEN — do not rename.
"""

import logging
from datetime import datetime
from typing import Any
from urllib.parse import urlparse

from django.db import transaction
from django.utils import timezone
from django.utils.text import slugify

from apps.audit_logs.services import record, snapshot
from core.utils import normalize_url

from .enums import (
    MAX_CONSECUTIVE_FAILURES,
    MIN_SCRAPE_INTERVAL_MINUTES,
    CandidateStatus,
    CareerSourceType,
    DetectionStatus,
    ScrapeHealth,
    SourceInputType,
)
from .exceptions import (
    BlockedDomain,
    CandidateAlreadyDecided,
    DuplicateCompany,
    InvalidCompanyTransition,
)
from .models import CareerCandidateUrl, Company, CompanySource

logger = logging.getLogger("study_tracker.companies")


# ---------------------------------------------------------------------------
# URL utilities (pure, no network)
# ---------------------------------------------------------------------------
def _host_of(url: str) -> str:
    cleaned = url.strip()
    if "://" not in cleaned:
        cleaned = f"https://{cleaned}"
    host = (urlparse(cleaned).hostname or "").lower()
    if host.startswith("www."):
        host = host[4:]
    return host


def _is_blocked(host: str) -> bool:
    from .enums import is_blocked_domain

    return is_blocked_domain(host)


def _extract_domain(url: str) -> str:
    return _host_of(url)


def _path_org(url: str) -> str:
    """First non-empty path segment of a career URL (ATS token / org slug)."""
    parsed = urlparse(url)
    parts = [p for p in parsed.path.split("/") if p]
    return parts[0] if parts else ""


_ALL_ATS = {
    CareerSourceType.GREENHOUSE,
    CareerSourceType.LEVER,
    CareerSourceType.ASHBY,
    CareerSourceType.SMARTRECRUITERS,
}


def sniff_source_type_from_url(url: str) -> tuple[CareerSourceType, str]:
    """Pattern-match a career URL to ``(source_type, ats_identifier)``. Pure, no IO.

    Raises ``BlockedDomain`` for hosts in ``BLOCKED_DOMAINS``.
    """
    url = url.strip()
    if "://" not in url:
        url = f"https://{url}"
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    if _is_blocked(host):
        raise BlockedDomain(f"Domain {host} is blocked")
    org = _path_org(url)

    sub = host.split(".")[0]  # left-most label
    if host == "boards.greenhouse.io" or host == "job-boards.greenhouse.io":
        return CareerSourceType.GREENHOUSE, org
    if host.endswith(".greenhouse.io"):
        return CareerSourceType.GREENHOUSE, sub
    if host == "jobs.lever.co":
        return CareerSourceType.LEVER, org
    if host.endswith(".jobs.lever.co"):
        return CareerSourceType.LEVER, sub
    if host == "jobs.ashbyhq.com":
        return CareerSourceType.ASHBY, org
    if host.endswith(".ashbyhq.com"):
        return CareerSourceType.ASHBY, sub
    if host in {"careers.smartrecruiters.com", "jobs.smartrecruiters.com"}:
        return CareerSourceType.SMARTRECRUITERS, org
    if host == "myworkdayjobs.com" or host.endswith(".myworkdayjobs.com"):
        return CareerSourceType.WORKDAY, ""
    return CareerSourceType.OWN_CAREER_PAGE, ""


def _unique_slug(name: str) -> str:
    base = slugify(name)[:200] or "company"
    slug = base
    counter = 1
    while Company.all_objects.filter(slug=slug).exists():
        suffix = f"-{counter}"
        slug = f"{base[: 280 - len(suffix)]}{suffix}"
        counter += 1
    return slug


def _reject_pending_candidates(company: Company, reason: str) -> None:
    company.candidates.filter(status=CandidateStatus.PENDING).update(
        status=CandidateStatus.REJECTED, reject_reason=reason
    )


def _dedupe_company(domain: str | None = None, career_url: str = "") -> None:
    existing = None
    if domain:
        existing = Company.all_objects.filter(domain=domain, is_deleted=False).first()
    if existing is None and career_url:
        existing = (
            Company.all_objects.filter(career_url=career_url, is_deleted=False)
            .exclude(career_url="")
            .first()
        )
    if existing is not None:
        raise DuplicateCompany(f"Company already tracked: {existing.name}")


# ---------------------------------------------------------------------------
# Add paths
# ---------------------------------------------------------------------------
def add_company_from_main_website(
    *, name: str, website_url: str, actor: Any, **optional_meta: object
) -> Company:
    """CASE A: admin gave the home page; detection (PROMPT 3) finds the career page."""
    name = (name or "").strip()
    if not name:
        from django.core.exceptions import ValidationError

        raise ValidationError("Company name is required")
    normalized = normalize_url(website_url)
    domain = _extract_domain(normalized)
    if not domain:
        from django.core.exceptions import ValidationError

        raise ValidationError(f"Could not extract a domain from {website_url!r}")
    if _is_blocked(domain):
        raise BlockedDomain(f"Domain {domain} is blocked")
    _dedupe_company(domain=domain)

    with transaction.atomic():
        company: Company = Company.objects.create(
            name=name,
            slug=_unique_slug(name),
            domain=domain,
            input_type=SourceInputType.MAIN_WEBSITE,
            input_url=website_url,
            added_by=actor,
            detection_status=DetectionStatus.PENDING,
            is_verified=False,
            career_url="",
            **optional_meta,
        )
        record(
            "company.created",
            actor=actor,
            instance=company,
            after=snapshot(company),
            source="ADMIN",
        )

    def _enqueue_detection() -> None:
        from apps.career_detection.tasks import detect_career_url

        detect_career_url.delay(str(company.id))

    transaction.on_commit(_enqueue_detection)
    return company


def add_company_from_direct_career_url(
    *,
    name: str,
    career_url: str,
    actor: Any,
    website_url: str = "",
    scrape_interval_minutes: int | None = None,
    **optional_meta: object,
) -> Company:
    """CASE B: admin already knows the career page — verified + scheduled immediately."""
    name = (name or "").strip()
    if not name:
        from django.core.exceptions import ValidationError

        raise ValidationError("Company name is required")
    if (
        scrape_interval_minutes is not None
        and scrape_interval_minutes < MIN_SCRAPE_INTERVAL_MINUTES
    ):
        from django.core.exceptions import ValidationError

        raise ValidationError(
            f"Scrape interval must be at least {MIN_SCRAPE_INTERVAL_MINUTES} minutes"
        )
    source_type, ats_identifier = sniff_source_type_from_url(career_url)
    normalized_career = normalize_url(career_url)
    domain = _extract_domain(normalized_career)
    if not domain:
        from django.core.exceptions import ValidationError

        raise ValidationError(f"Could not extract a domain from {career_url!r}")
    _dedupe_company(domain=domain, career_url=normalized_career)

    with transaction.atomic():
        company: Company = Company.objects.create(
            name=name,
            slug=_unique_slug(name),
            domain=domain,
            input_type=SourceInputType.DIRECT_CAREER,
            input_url=website_url or career_url,
            added_by=actor,
            career_url=career_url,
            career_source_type=source_type,
            ats_identifier=ats_identifier,
            career_url_set_by=actor,
            career_url_set_at=timezone.now(),
            detection_status=DetectionStatus.SKIPPED,
            is_verified=True,
            verified_by=actor,
            verified_at=timezone.now(),
            scrape_health=ScrapeHealth.UNKNOWN,
            **optional_meta,
        )
        if scrape_interval_minutes is not None:
            company.scrape_interval_minutes = scrape_interval_minutes
        company.next_scrape_at = company.compute_next_scrape_at()
        company.save(update_fields=["next_scrape_at", "scrape_interval_minutes"])
        CompanySource.objects.create(
            company=company,
            url=career_url,
            normalized_url=normalized_career,
            source_type=source_type,
            ats_identifier=ats_identifier,
            is_current=True,
            set_by=actor,
            reason="direct career url",
        )
        record(
            "company.created",
            actor=actor,
            instance=company,
            after=snapshot(company),
            source="ADMIN",
        )
        record(
            "company.verified",
            actor=actor,
            instance=company,
            before={},
            after=snapshot(company, ["career_url", "career_source_type", "is_verified"]),
            source="ADMIN",
        )
    return company


# ---------------------------------------------------------------------------
# Candidate lifecycle
# ---------------------------------------------------------------------------
def approve_career_candidate(
    *, candidate: CareerCandidateUrl, actor: Any, interval_minutes: int | None = None
) -> Company:
    """Human approval — the ONLY path from detection to scrapable."""
    if candidate.status != CandidateStatus.PENDING:
        raise CandidateAlreadyDecided(f"Candidate already {candidate.status}")
    company = candidate.company
    if (
        company.is_verified
        and bool(company.career_url)
        and normalize_url(company.career_url) != candidate.normalized_url
    ):
        raise InvalidCompanyTransition(
            "Company already verified with a different URL — use set_manual_career_url"
        )

    with transaction.atomic():
        candidate.status = CandidateStatus.APPROVED
        candidate.decided_by = actor
        candidate.decided_at = timezone.now()
        candidate.save(update_fields=["status", "decided_by", "decided_at"])
        company.candidates.filter(status=CandidateStatus.PENDING).exclude(pk=candidate.pk).update(
            status=CandidateStatus.REJECTED, reject_reason="another candidate approved"
        )

        if interval_minutes is not None:
            if interval_minutes < MIN_SCRAPE_INTERVAL_MINUTES:
                from django.core.exceptions import ValidationError

                raise ValidationError(f"interval_minutes must be >= {MIN_SCRAPE_INTERVAL_MINUTES}")
            company.scrape_interval_minutes = interval_minutes

        company.career_url = candidate.url
        company.career_source_type = candidate.guessed_type
        company.ats_identifier = candidate.ats_identifier
        company.career_url_set_by = actor
        company.career_url_set_at = timezone.now()
        company.detection_status = DetectionStatus.VERIFIED
        company.is_verified = True
        company.verified_by = actor
        company.verified_at = timezone.now()
        company.scrape_health = ScrapeHealth.UNKNOWN
        company.consecutive_failures = 0
        company.next_scrape_at = company.compute_next_scrape_at()
        company.save(
            update_fields=[
                "career_url",
                "career_source_type",
                "ats_identifier",
                "career_url_set_by",
                "career_url_set_at",
                "detection_status",
                "is_verified",
                "verified_by",
                "verified_at",
                "scrape_health",
                "consecutive_failures",
                "next_scrape_at",
                "scrape_interval_minutes",
                "updated_at",
            ]
        )

        CompanySource.objects.filter(company=company, is_current=True).update(
            is_current=False, retired_at=timezone.now()
        )
        CompanySource.objects.create(
            company=company,
            url=candidate.url,
            normalized_url=candidate.normalized_url,
            source_type=candidate.guessed_type,
            ats_identifier=candidate.ats_identifier,
            is_current=True,
            set_by=actor,
            reason="approved candidate",
        )
        record(
            "career_candidate.approved",
            actor=actor,
            instance=candidate,
            before={},
            after=snapshot(candidate, ["status", "decided_by", "decided_at"]),
            source="ADMIN",
        )
    return company


def reject_career_candidate(
    *, candidate: CareerCandidateUrl, actor: Any, reason: str = ""
) -> CareerCandidateUrl:
    """PENDING -> REJECTED; last pending candidate flips the company to NOT_FOUND."""
    if candidate.status != CandidateStatus.PENDING:
        raise CandidateAlreadyDecided(f"Candidate already {candidate.status}")
    with transaction.atomic():
        candidate.status = CandidateStatus.REJECTED
        candidate.decided_by = actor
        candidate.decided_at = timezone.now()
        candidate.reject_reason = reason
        candidate.save(update_fields=["status", "decided_by", "decided_at", "reject_reason"])

        company = candidate.company
        pending_left = company.candidates.filter(status=CandidateStatus.PENDING).exists()
        if company.detection_status == DetectionStatus.NEEDS_REVIEW and not pending_left:
            company.detection_status = DetectionStatus.NOT_FOUND
            company.save(update_fields=["detection_status", "updated_at"])
        record(
            "career_candidate.rejected",
            actor=actor,
            instance=candidate,
            before={},
            after=snapshot(candidate, ["status", "reject_reason", "decided_by", "decided_at"]),
            source="ADMIN",
        )
    return candidate


def set_manual_career_url(
    *, company: Company, career_url: str, actor: Any, verify: bool = True
) -> Company:
    """Admin overrides the career URL by hand at any time."""
    source_type, ats_identifier = sniff_source_type_from_url(career_url)
    normalized = normalize_url(career_url)
    other = (
        Company.all_objects.filter(career_url=normalized, is_deleted=False)
        .exclude(pk=company.pk)
        .exclude(career_url="")
        .first()
    )
    if other is not None:
        raise DuplicateCompany(f"Career URL already used by {other.name}")

    with transaction.atomic():
        before = snapshot(company)
        CompanySource.objects.filter(company=company, is_current=True).update(
            is_current=False, retired_at=timezone.now()
        )
        CompanySource.objects.create(
            company=company,
            url=career_url,
            normalized_url=normalized,
            source_type=source_type,
            ats_identifier=ats_identifier,
            is_current=True,
            set_by=actor,
            reason="manual override",
        )
        company.career_url = career_url
        company.career_source_type = source_type
        company.ats_identifier = ats_identifier
        company.career_url_set_by = actor
        company.career_url_set_at = timezone.now()
        company.detection_status = DetectionStatus.MANUAL
        company.is_verified = verify
        if verify:
            company.verified_by = actor
            company.verified_at = timezone.now()
        else:
            company.verified_by = None
            company.verified_at = None
        company.scrape_health = ScrapeHealth.UNKNOWN
        company.consecutive_failures = 0
        company.next_scrape_at = company.compute_next_scrape_at()
        company.save()
        record(
            "company.career_url_changed",
            actor=actor,
            instance=company,
            before=before,
            after=snapshot(company),
            source="ADMIN",
        )
    return company


def request_redetection(*, company: Company, actor: Any) -> Company:
    """Reset to PENDING; history is kept."""
    with transaction.atomic():
        _reject_pending_candidates(company, "redetection requested")
        company.detection_status = DetectionStatus.PENDING
        company.save(update_fields=["detection_status", "updated_at"])
        record(
            "company.redetection_requested",
            actor=actor,
            instance=company,
            before={},
            after=snapshot(company, ["detection_status"]),
            source="ADMIN",
        )

    def _enqueue_detection() -> None:
        from apps.career_detection.tasks import detect_career_url

        detect_career_url.delay(str(company.id))

    transaction.on_commit(_enqueue_detection)
    return company


# ---------------------------------------------------------------------------
# Scheduling controls
# ---------------------------------------------------------------------------
def pause_company(*, company: Company, actor: Any, reason: str = "") -> Company:
    with transaction.atomic():
        company.is_active = False
        company.scrape_health = ScrapeHealth.PAUSED
        company.next_scrape_at = None
        if reason:
            company.notes = reason
        company.save(
            update_fields=["is_active", "scrape_health", "next_scrape_at", "notes", "updated_at"]
        )
        record(
            "company.paused",
            actor=actor,
            instance=company,
            before={},
            after=snapshot(company, ["is_active", "scrape_health", "next_scrape_at"]),
            source="ADMIN",
        )
    return company


def resume_company(*, company: Company, actor: Any) -> Company:
    with transaction.atomic():
        company.is_active = True
        company.scrape_health = ScrapeHealth.UNKNOWN
        company.consecutive_failures = 0
        company.next_scrape_at = company.compute_next_scrape_at()
        company.save(
            update_fields=[
                "is_active",
                "scrape_health",
                "consecutive_failures",
                "next_scrape_at",
                "updated_at",
            ]
        )
        record(
            "company.resumed",
            actor=actor,
            instance=company,
            before={},
            after=snapshot(company, ["is_active", "scrape_health", "next_scrape_at"]),
            source="ADMIN",
        )
    return company


def archive_company(*, company: Company, actor: Any, reason: str = "") -> Company:
    """Soft-delete; unpublish every job so nothing orphaned stays visible."""
    from apps.jobs.services import unpublish_job

    with transaction.atomic():
        if reason:
            company.notes = reason
        company.save(update_fields=["notes", "updated_at"])
        for job in company.jobs.all().exclude(is_published=False):
            unpublish_job(job=job, actor=actor, reason="company archived")
        company.delete()  # soft delete
        record(
            "company.archived",
            actor=actor,
            instance=company,
            before={},
            after=snapshot(company, ["is_deleted", "deleted_at"]),
            source="ADMIN",
        )
    return company


def unarchive_company(*, company: Company, actor: Any) -> Company:
    with transaction.atomic():
        company.is_deleted = False
        company.deleted_at = None
        company.save(update_fields=["is_deleted", "deleted_at", "updated_at"])
        record(
            "company.unarchived",
            actor=actor,
            instance=company,
            before={},
            after=snapshot(company, ["is_deleted"]),
            source="ADMIN",
        )
    return company


def update_scrape_interval(*, company: Company, minutes: int, actor: Any) -> Company:
    if minutes < MIN_SCRAPE_INTERVAL_MINUTES:
        from django.core.exceptions import ValidationError

        raise ValidationError(
            f"Scrape interval must be at least {MIN_SCRAPE_INTERVAL_MINUTES} minutes"
        )
    with transaction.atomic():
        company.scrape_interval_minutes = minutes
        company.next_scrape_at = company.compute_next_scrape_at()
        company.save(update_fields=["scrape_interval_minutes", "next_scrape_at", "updated_at"])
        record(
            "company.scrape_interval_changed",
            actor=actor,
            instance=company,
            before={},
            after=snapshot(company, ["scrape_interval_minutes", "next_scrape_at"]),
            source="ADMIN",
        )
    return company


# ---------------------------------------------------------------------------
# Scrape outcome — the health state machine (PROMPT 5 calls this)
# ---------------------------------------------------------------------------
def record_scrape_outcome(
    *,
    company: Company,
    success: bool,
    failure_reason: str = "",
    jobs_seen: int = 0,
    now: datetime | None = None,
) -> Company:
    """Apply one scrape result to health/backoff state. Audit only on transitions."""
    target = now or timezone.now()
    previous_health = company.scrape_health
    previous_active = company.is_active

    company.total_scrapes += 1
    company.last_scraped_at = target

    if success:
        company.consecutive_failures = 0
        company.last_successful_scrape_at = target
        company.last_jobs_seen = jobs_seen
        company.last_failure_reason = ""
        company.scrape_health = ScrapeHealth.HEALTHY
        company.next_scrape_at = company.compute_next_scrape_at(target, backoff_factor=1)
    else:
        company.total_failures += 1
        company.consecutive_failures += 1
        company.last_failure_reason = failure_reason[:2000]
        failures = company.consecutive_failures
        if failures <= 2:
            company.scrape_health = ScrapeHealth.DEGRADED
        elif failures <= 4:
            company.scrape_health = ScrapeHealth.FAILING
        else:
            company.scrape_health = ScrapeHealth.PAUSED
        if failures >= MAX_CONSECUTIVE_FAILURES:
            company.is_active = False
            company.next_scrape_at = None
        else:
            factor = 2 ** (failures - 1)
            company.next_scrape_at = company.compute_next_scrape_at(target, backoff_factor=factor)

    transitioned = (
        company.scrape_health != previous_health
        or company.is_active != previous_active
        or company.next_scrape_at is None
    )
    with transaction.atomic():
        company.save()
        if transitioned:
            record(
                "company.scrape_outcome",
                actor=None,
                instance=company,
                before={},
                after=snapshot(
                    company,
                    [
                        "scrape_health",
                        "consecutive_failures",
                        "is_active",
                        "next_scrape_at",
                        "last_failure_reason",
                    ],
                ),
                source="SYSTEM",
            )
    return company


def reset_scrape_failures(*, company: Company, actor: Any) -> Company:
    """Admin clears failure counters (e.g. after fixing a broken source)."""
    with transaction.atomic():
        company.consecutive_failures = 0
        company.last_failure_reason = ""
        if company.scrape_health != ScrapeHealth.PAUSED:
            company.scrape_health = ScrapeHealth.UNKNOWN
        company.save(
            update_fields=[
                "consecutive_failures",
                "last_failure_reason",
                "scrape_health",
                "updated_at",
            ]
        )
        record(
            "company.failures_reset",
            actor=actor,
            instance=company,
            before={},
            after=snapshot(company, ["consecutive_failures", "scrape_health"]),
            source="ADMIN",
        )
    return company


def update_company_details(*, company: Company, actor: Any, **changes: object) -> Company:
    """Admin change-view edits for profile fields (keeps the services-only rule)."""
    allowed = {
        "name",
        "logo_url",
        "description",
        "hq_location",
        "industry",
        "size_bucket",
        "linkedin_url",
        "notes",
    }
    with transaction.atomic():
        before = snapshot(company)
        fields: list[str] = []
        for key, value in changes.items():
            if key not in allowed:
                continue
            setattr(company, key, value)
            fields.append(key)
        if "name" in fields:
            company.slug = _unique_slug(str(company.name))
        if fields:
            company.save(
                update_fields=(
                    [*fields, "slug", "updated_at"] if "name" in fields else [*fields, "updated_at"]
                )
            )
            record(
                "company.updated",
                actor=actor,
                instance=company,
                before=before,
                after=snapshot(company),
                source="ADMIN",
            )
    return company
