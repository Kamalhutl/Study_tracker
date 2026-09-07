import logging
from typing import Any

from apps.companies.models import Company
from apps.scraping.fetching import FetchResult

logger = logging.getLogger("study_tracker.scraping.parsers.smartrecruiters")
PARSER_NAME = "smartrecruiters"
PARSER_VERSION = 1


def parse(fetch_result: FetchResult, *, company: Company) -> list[dict[str, Any]]:
    """Parse SmartRecruiters API response into job payloads."""
    try:
        data = fetch_result.selector.json()
        jobs = data.get("content") or []
    except Exception as e:
        logger.warning("SmartRecruiters parse failed for %s: %s", company.name, e)
        return []

    if not isinstance(jobs, list):
        logger.warning("SmartRecruiters response missing 'content' list for %s", company.name)
        return []

    payloads = []
    for job in jobs:
        try:
            payload = {
                "source_job_id": str(job.get("id") or ""),
                "source_url": str(job.get("ref") or ""),
                "apply_url": str(job.get("ref") or ""),
                "title": str(job.get("name") or ""),
                "location_raw": _build_location(job.get("location") or {}),
                "description": "",  # SmartRecruiters listing API does not include full description
                "description_html": "",
                "department": _extract_department(job),
                "job_type": "",
                "work_mode": _extract_work_mode(job.get("location") or {}),
                "experience_level": "",
                "posted_at": None,  # not in listing endpoint
                "extraction_confidence": 60,  # flag for review
            }
            payloads.append(payload)
        except Exception as e:
            logger.warning(
                "Failed to parse SmartRecruiters job %s: %s", job.get("id", "unknown"), e
            )
            continue

    return payloads


def _build_location(location: dict[str, Any]) -> str:
    """Build location string from SmartRecruiters location data."""
    if not isinstance(location, dict):
        return ""

    parts = []
    if location.get("city"):
        parts.append(str(location["city"]))
    if location.get("region"):
        parts.append(str(location["region"]))
    if location.get("country"):
        parts.append(str(location["country"]))

    location_str = ", ".join(parts) if parts else ""

    if location.get("remote", False):
        if location_str:
            location_str += " (Remote)"
        else:
            location_str = "Remote"

    return location_str


def _extract_department(job: dict[str, Any]) -> str:
    """Extract department from SmartRecruiters job data."""
    department = job.get("department")
    if isinstance(department, dict):
        return str(department.get("label") or "")
    return ""


def _extract_work_mode(location: dict[str, Any]) -> str:
    """Extract work mode from SmartRecruiters location data."""
    if isinstance(location, dict) and location.get("remote", False):
        return "remote"
    return ""
