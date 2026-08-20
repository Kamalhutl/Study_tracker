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
    """Where a company sits in the career-URL detection pipeline."""

    PENDING = "pending"
    RUNNING = "running"
    NEEDS_REVIEW = "needs_review"
    VERIFIED = "verified"
    NOT_FOUND = "not_found"
    MANUAL = "manual"
    SKIPPED = "skipped"
    FAILED = "failed"


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

MIN_SCRAPE_INTERVAL_MINUTES = 30
DEFAULT_SCRAPE_INTERVAL_MINUTES = 300  # 5 hours
MAX_CONSECUTIVE_FAILURES = 5  # auto-pause threshold
MAX_BACKOFF_MINUTES = 24 * 60
