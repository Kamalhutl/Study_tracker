"""Enumerations and tuning constants for the companies domain."""

from django.db import models


class SourceInputType(models.TextChoices):
    """How a company was handed to us: home page (Case A) or direct career link (Case B)."""

    MAIN_WEBSITE = "main_website"
    DIRECT_CAREER = "direct_career"


class CareerSourceType(models.TextChoices):
    """What kind of careers source a company publishes."""

    OWN_CAREER_PAGE = "own_career_page"
    GREENHOUSE = "greenhouse"
    LEVER = "lever"
    ASHBY = "ashby"
    SMARTRECRUITERS = "smartrecruiters"
    WORKDAY = "workday"  # recognized, NOT supported in P1
    UNKNOWN = "unknown"


class DetectionStatus(models.TextChoices):
    """Where a company sits in the career-URL detection pipeline.

    Shared by ``Company.detection_status`` and ``DetectionRun.status`` (run-only
    values are SUCCESS/PARTIAL; company-only values are CANDIDATES_FOUND /
    NO_CANDIDATES).
    """

    PENDING = "pending"
    RUNNING = "running"
    NEEDS_REVIEW = "needs_review"
    VERIFIED = "verified"
    NOT_FOUND = "not_found"
    MANUAL = "manual"
    SKIPPED = "skipped"
    FAILED = "failed"
    CANDIDATES_FOUND = "candidates_found"
    NO_CANDIDATES = "no_candidates"
    SUCCESS = "success"
    PARTIAL = "partial"
    SUPERSEDED = "superseded"


class ScrapeHealth(models.TextChoices):
    """Rolling scrape-health state machine for a company."""

    UNKNOWN = "unknown"
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    FAILING = "failing"
    PAUSED = "paused"


class CandidateOrigin(models.TextChoices):
    """Where a candidate career URL came from during detection."""

    ROBOTS_TXT = "robots_txt"
    SITEMAP = "sitemap"
    HEADER_LINK = "header_link"
    FOOTER_LINK = "footer_link"
    COMMON_PATH = "common_path"
    SUBDOMAIN_GUESS = "subdomain_guess"
    JSON_LD = "json_ld"
    ATS_PATTERN = "ats_pattern"
    MANUAL = "manual"


class CandidateStatus(models.TextChoices):
    """Human decision state for a career-URL candidate."""

    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


# Domains we will never scrape or store jobs from (marketplace aggregators etc).
BLOCKED_DOMAINS: frozenset[str] = frozenset(
    {
        "linkedin.com",
        "in.linkedin.com",
        "naukri.com",
        "indeed.com",
        "in.indeed.com",
        "glassdoor.com",
        "glassdoor.co.in",
        "monster.com",
        "monsterindia.com",
        "shine.com",
        "timesjobs.com",
    }
)


def is_ats_host(host: str) -> bool:
    """True if ``host`` maps to a supported ATS in :data:`ATS_HOST_TABLE`."""
    host = (host or "").lower()
    for _source_type, exact_hosts, subdomain_suffix, _mode in ATS_HOST_TABLE:
        if host in exact_hosts:
            return True
        if (
            subdomain_suffix
            and host.endswith(subdomain_suffix)
            and host != subdomain_suffix.lstrip(".")
        ):
            return True
    return False


def is_blocked_domain(host: str) -> bool:
    """True if ``host`` (or a subdomain of it) is in :data:`BLOCKED_DOMAINS`.

    Subdomain matching: ``careers.linkedin.com`` matches ``linkedin.com``
    while ``notlinkedin.com`` does not.
    """
    if not host:
        return False
    host = host.lower()
    return any(host == domain or host.endswith(f".{domain}") for domain in BLOCKED_DOMAINS)


MIN_SCRAPE_INTERVAL_MINUTES = 30
DEFAULT_SCRAPE_INTERVAL_MINUTES = 300  # 5 hours
MAX_CONSECUTIVE_FAILURES = 5  # auto-pause threshold
MAX_BACKOFF_MINUTES = 24 * 60


# ---------------------------------------------------------------------------
# Canonical ATS host registry (PROMPT 16.6) — the single source of truth for
# mapping a career-URL host to a ``CareerSourceType``. ``sniff_source_type_from_url``
# is the only consumer; there is no second host list.
# ---------------------------------------------------------------------------
# Entry shape: (source_type, exact_hosts, subdomain_suffix, identifier_mode)
#   exact_hosts       -> host matches one of these strings verbatim.
#   subdomain_suffix  -> host ends with this (subdomain form) when not exact.
#   identifier_mode   -> "path": identifier is the first URL path segment for
#                        exact hosts, or the left-most host label for subdomains.
#                        "none": identifier stays empty in both cases.
ATS_HOST_TABLE: tuple[tuple[CareerSourceType, tuple[str, ...], str | None, str], ...] = (
    (
        CareerSourceType.GREENHOUSE,
        ("boards.greenhouse.io", "job-boards.greenhouse.io"),
        ".greenhouse.io",
        "path",
    ),
    (CareerSourceType.LEVER, ("jobs.lever.co",), ".jobs.lever.co", "path"),
    (CareerSourceType.ASHBY, ("jobs.ashbyhq.com",), ".ashbyhq.com", "path"),
    (
        CareerSourceType.SMARTRECRUITERS,
        ("careers.smartrecruiters.com", "jobs.smartrecruiters.com"),
        None,
        "path",
    ),
    (CareerSourceType.WORKDAY, ("myworkdayjobs.com",), ".myworkdayjobs.com", "none"),
)
