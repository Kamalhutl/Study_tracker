"""Enumerations and tuning constants for the jobs domain."""

from django.db import models


class JobStatus(models.TextChoices):
    OPEN = "open"
    POSSIBLY_CLOSED = "possibly_closed"  # missed 1 scrape
    LIKELY_CLOSED = "likely_closed"  # missed 2 scrapes
    CLOSED = "closed"  # missed 3 scrapes, or explicit
    DRAFT = "draft"  # scraped but not published yet


class JobType(models.TextChoices):
    FULL_TIME = "full_time"
    PART_TIME = "part_time"
    INTERNSHIP = "internship"
    CONTRACT = "contract"
    TEMPORARY = "temporary"
    FREELANCE = "freelance"
    UNKNOWN = "unknown"


class WorkMode(models.TextChoices):
    ONSITE = "onsite"
    REMOTE = "remote"
    HYBRID = "hybrid"
    UNKNOWN = "unknown"


class ExperienceLevel(models.TextChoices):
    FRESHER = "fresher"
    ENTRY = "entry"
    MID = "mid"
    SENIOR = "senior"
    LEAD = "lead"
    UNKNOWN = "unknown"


class ReportReason(models.TextChoices):
    EXPIRED = "expired"
    BROKEN_LINK = "broken_link"
    WRONG_INFO = "wrong_info"
    DUPLICATE = "duplicate"
    SPAM = "spam"
    OTHER = "other"


class ReportStatus(models.TextChoices):
    OPEN = "open"
    ACCEPTED = "accepted"
    REJECTED = "rejected"


MISSING_STATUS_LADDER = {
    1: JobStatus.POSSIBLY_CLOSED,
    2: JobStatus.LIKELY_CLOSED,
    3: JobStatus.CLOSED,
}
MAX_MISSING_COUNT = 3
