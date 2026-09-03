import logging
import re
from datetime import UTC, datetime
from typing import Any

from apps.companies.models import Company
from apps.scraping.fetching import FetchResult

logger = logging.getLogger("study_tracker.scraping.parsers.greenhouse")


def _strip_html(html: str) -> str:
    """Strip HTML tags from a string."""
    if not html:
        return ""
    # Remove script and style elements
    text = re.sub(r"<script.*?</script>", "", html, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<style.*?</style>", "", text, flags=re.DOTALL | re.IGNORECASE)
    # Remove all HTML tags
    text = re.sub(r"<[^>]+>", "", text)
    # Replace multiple whitespace with single space
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def parse(fetch_result: FetchResult, *, company: Company) -> list[dict[str, Any]]:
    """Parse Greenhouse API response into job payloads."""
    try:
        data = fetch_result.selector.json()
        jobs = data.get("jobs", [])
    except Exception as e:
        logger.warning("Greenhouse parse failed for %s: %s", company.name, e)
        return []

    if not isinstance(jobs, list):
        logger.warning("Greenhouse response missing 'jobs' list for %s", company.name)
        return []

    payloads = []
    for job in jobs:
        try:
            payload = {
                "source_job_id": str(job.get("id") or ""),
                "source_url": str(job.get("absolute_url") or ""),
                "apply_url": str(job.get("absolute_url") or ""),
                "title": str(job.get("title") or ""),
                "location_raw": _extract_location(job),
                "description": _strip_html(str(job.get("content") or "")),
                "description_html": str(job.get("content") or ""),
                "department": _extract_department(job),
                "job_type": "",
                "work_mode": _extract_work_mode(job),
                "experience_level": "",
                "posted_at": _parse_posted_at(job.get("updated_at")),
                "extraction_confidence": 90,
            }
            payloads.append(payload)
        except Exception as e:
            logger.warning("Failed to parse Greenhouse job %s: %s", job.get("id", "unknown"), e)
            continue

    return payloads


def _extract_location(job: dict[str, Any]) -> str:
    """Extract location from Greenhouse job data."""
    location = job.get("location")
    if isinstance(location, dict):
        return str(location.get("name") or "")
    return str(location) if location else ""


def _extract_department(job: dict[str, Any]) -> str:
    """Extract department from Greenhouse job data."""
    departments = job.get("departments")
    if departments and isinstance(departments, list):
        first_dept = departments[0]
        if isinstance(first_dept, dict):
            return str(first_dept.get("name") or "")
        return str(first_dept)
    return ""


def _parse_posted_at(updated_at: Any) -> datetime | None:
    """Parse Greenhouse updated_at timestamp."""
    if not updated_at:
        return None
    try:
        if isinstance(updated_at, str):
            # Handle ISO format like "2025-01-15T10:00:00Z"
            dt = datetime.fromisoformat(updated_at.replace("Z", "+00:00"))
            return dt.replace(tzinfo=UTC)
        elif isinstance(updated_at, int | float):
            # Handle Unix timestamp
            return datetime.fromtimestamp(updated_at, tz=UTC)
    except (ValueError, TypeError):
        return None
    return None


def _extract_work_mode(job: dict[str, Any]) -> str:
    """Extract work mode from Greenhouse job data."""
    from apps.scraping.parsers._common import work_mode_from_text

    location = job.get("location")
    name = location.get("name") if isinstance(location, dict) else ""
    return work_mode_from_text(name, job.get("title"))
