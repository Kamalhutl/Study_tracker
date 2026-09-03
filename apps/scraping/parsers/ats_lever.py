import logging
from datetime import UTC, datetime
from typing import Any

from apps.companies.models import Company
from apps.scraping.fetching import FetchResult

logger = logging.getLogger("study_tracker.scraping.parsers.lever")


def _strip_html(html: str) -> str:
    """Strip HTML tags from a string."""
    import re

    if not html:
        return ""
    text = re.sub(r"<[^>]+>", "", html)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def parse(fetch_result: FetchResult, *, company: Company) -> list[dict[str, Any]]:
    """Parse Lever API response into job payloads."""
    try:
        data = fetch_result.selector.json()
        jobs = data if isinstance(data, list) else []
    except Exception as e:
        logger.warning("Lever parse failed for %s: %s", company.name, e)
        return []

    payloads = []
    for job in jobs:
        try:
            payload = {
                "source_job_id": str(job.get("id") or ""),
                "source_url": str(job.get("hostedUrl") or ""),
                "apply_url": str(job.get("applyUrl") or job.get("hostedUrl") or ""),
                "title": str(job.get("text") or ""),
                "location_raw": _extract_location(job),
                "description": _extract_description(job),
                "description_html": str(job.get("description") or ""),
                "department": _extract_department(job),
                "job_type": _extract_job_type(job),
                "work_mode": _extract_work_mode(job),
                "experience_level": "",
                "posted_at": _parse_posted_at(job.get("createdAt")),
                "extraction_confidence": 90,
            }
            payloads.append(payload)
        except Exception as e:
            logger.warning("Failed to parse Lever job %s: %s", job.get("id", "unknown"), e)
            continue

    return payloads


def _extract_location(job: dict[str, Any]) -> str:
    """Extract location from Lever job data."""
    categories = job.get("categories")
    if isinstance(categories, dict):
        return str(categories.get("location") or "")
    return ""


def _extract_department(job: dict[str, Any]) -> str:
    """Extract department from Lever job data."""
    categories = job.get("categories")
    if isinstance(categories, dict):
        return str(categories.get("department") or categories.get("team") or "")
    return ""


def _extract_description(job: dict[str, Any]) -> str:
    """Extract description from Lever job data."""
    description_plain = job.get("descriptionPlain")
    if description_plain:
        return str(description_plain)
    description_html = job.get("description")
    return _strip_html(str(description_html or ""))


def _parse_posted_at(created_at: Any) -> datetime | None:
    """Parse Lever createdAt timestamp (milliseconds since epoch)."""
    if not created_at:
        return None
    try:
        if isinstance(created_at, int | float):
            return datetime.fromtimestamp(created_at / 1000, tz=UTC)
        elif isinstance(created_at, str):
            try:
                dt = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
                return dt.replace(tzinfo=UTC)
            except ValueError:
                return datetime.fromtimestamp(float(created_at) / 1000, tz=UTC)
    except (ValueError, TypeError):
        return None
    return None


def _extract_work_mode(job: dict[str, Any]) -> str:
    """Map Lever workplaceType to a WorkMode value."""
    from apps.jobs.enums import WorkMode

    raw = str(job.get("workplaceType") or "").strip().lower().replace("-", "")
    if raw == "remote":
        return str(WorkMode.REMOTE)
    if raw == "hybrid":
        return str(WorkMode.HYBRID)
    if raw == "onsite":
        return str(WorkMode.ONSITE)
    return ""


def _extract_job_type(job: dict[str, Any]) -> str:
    """Map Lever categories.commitment to a JobType value."""
    from apps.jobs.enums import JobType

    categories = job.get("categories")
    if not isinstance(categories, dict):
        return ""
    raw = str(categories.get("commitment") or "").strip().lower().replace("-", "").replace(" ", "")
    if raw == "fulltime":
        return str(JobType.FULL_TIME)
    if raw == "parttime":
        return str(JobType.PART_TIME)
    if raw == "contract":
        return str(JobType.CONTRACT)
    if raw == "internship" or raw == "intern":
        return str(JobType.INTERNSHIP)
    if raw == "temporary":
        return str(JobType.TEMPORARY)
    if raw == "freelance":
        return str(JobType.FREELANCE)
    return ""
