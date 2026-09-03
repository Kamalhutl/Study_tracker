import logging
from datetime import UTC, datetime
from typing import Any

from apps.companies.models import Company
from apps.jobs.enums import JobType
from apps.scraping.fetching import FetchResult

logger = logging.getLogger("study_tracker.scraping.parsers.ashby")


# Mapping from Ashby employmentType to JobType enum
EMPLOYMENT_TYPE_MAP = {
    "FullTime": JobType.FULL_TIME,
    "PartTime": JobType.PART_TIME,
    "Contract": JobType.CONTRACT,
    "Internship": JobType.INTERNSHIP,
    "Temporary": JobType.TEMPORARY,
    "Freelance": JobType.FREELANCE,
}


def _strip_html(html: str) -> str:
    """Strip HTML tags from a string."""
    import re

    if not html:
        return ""
    text = re.sub(r"<[^>]+>", "", html)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def parse(fetch_result: FetchResult, *, company: Company) -> list[dict[str, Any]]:
    """Parse Ashby API response into job payloads."""
    try:
        data = fetch_result.selector.json()
        jobs = data.get("jobPostings") or []
    except Exception as e:
        logger.warning("Ashby parse failed for %s: %s", company.name, e)
        return []

    if not isinstance(jobs, list):
        logger.warning("Ashby response missing 'jobPostings' list for %s", company.name)
        return []

    payloads = []
    for job in jobs:
        try:
            payload = {
                "source_job_id": str(job.get("id") or ""),
                "source_url": str(job.get("jobUrl") or ""),
                "apply_url": str(job.get("applyUrl") or job.get("jobUrl") or ""),
                "title": str(job.get("title") or ""),
                "location_raw": str(job.get("locationName") or ""),
                "description": _extract_description(job),
                "description_html": str(job.get("descriptionHtml") or ""),
                "department": str(job.get("departmentName") or ""),
                "job_type": _map_job_type(str(job.get("employmentType") or "")),
                "work_mode": _extract_work_mode(job),
                "experience_level": "",
                "posted_at": _parse_posted_at(job.get("publishedAt")),
                "extraction_confidence": 90,
            }
            payloads.append(payload)
        except Exception as e:
            logger.warning("Failed to parse Ashby job %s: %s", job.get("id", "unknown"), e)
            continue

    return payloads


def _extract_description(job: dict[str, Any]) -> str:
    """Extract description from Ashby job data."""
    description_social = job.get("descriptionSocial")
    if description_social:
        return str(description_social)
    description_html = job.get("descriptionHtml")
    return _strip_html(str(description_html or ""))


def _map_job_type(employment_type: str) -> str:
    """Map Ashby employmentType to JobType enum value."""
    if not employment_type:
        return ""
    return EMPLOYMENT_TYPE_MAP.get(employment_type, "")


def _parse_posted_at(published_at: Any) -> datetime | None:
    """Parse Ashby publishedAt timestamp."""
    if not published_at:
        return None
    try:
        if isinstance(published_at, str):
            dt = datetime.fromisoformat(published_at.replace("Z", "+00:00"))
            return dt.replace(tzinfo=UTC)
        elif isinstance(published_at, int | float):
            return datetime.fromtimestamp(published_at, tz=UTC)
    except (ValueError, TypeError):
        return None
    return None


def _extract_work_mode(job: dict[str, Any]) -> str:
    """Extract work mode from Ashby job data."""
    from apps.jobs.enums import WorkMode
    from apps.scraping.parsers._common import work_mode_from_text

    if job.get("isRemote") is True:
        return str(WorkMode.REMOTE)
    return work_mode_from_text(job.get("locationName"), job.get("title"))
