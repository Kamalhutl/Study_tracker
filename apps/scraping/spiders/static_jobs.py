import logging
from typing import Any
from urllib.parse import urlparse

from apps.companies.models import Company
from apps.scraping.fetching import FetchResult
from core.utils import normalize_url

logger = logging.getLogger("study_tracker.scraping.spiders.static_jobs")
PARSER_NAME = "static"
PARSER_VERSION = 1

# Noise tokens to exclude from hrefs
NOISE_TOKENS = [
    "#",
    "mailto:",
    "linkedin.com",
    "twitter.com",
    "facebook.com",
    "javascript:",
]


def extract(fetch_result: FetchResult, *, company: Company) -> list[dict[str, Any]]:
    """Extract job links from static HTML career pages."""
    if not company.career_url:
        return []

    domain = urlparse(company.career_url).hostname or ""
    candidates = []

    # Find all anchor tags
    for a in fetch_result.selector.css("a"):
        href = a.attrib.get("href", "")
        text = a.get_all_text(strip=True)

        # Skip if text is too short or too long
        if len(text) < 5 or len(text) > 120:
            continue

        # Skip if href contains noise tokens
        if any(noise in href.lower() for noise in NOISE_TOKENS):
            continue

        # Build absolute URL
        absolute_href = _build_absolute_url(href, fetch_result.final_url)
        if not absolute_href:
            continue

        # Check if URL is on the same domain
        if not _is_same_domain(absolute_href, domain):
            continue

        candidates.append(
            {
                "title": text,
                "source_url": absolute_href,
                "apply_url": absolute_href,
                "source_job_id": "",
                "location_raw": "",
                "description": "",
                "description_html": "",
                "department": "",
                "job_type": "",
                "work_mode": "",
                "experience_level": "",
                "posted_at": None,
                "extraction_confidence": 40,
            }
        )

    # Dedupe by normalized source_url
    seen_urls = set()
    unique_candidates = []
    for candidate in candidates:
        normalized_url = normalize_url(candidate["source_url"])
        if normalized_url not in seen_urls:
            seen_urls.add(normalized_url)
            unique_candidates.append(candidate)

    # Return at most 200 results
    return unique_candidates[:200]


def _build_absolute_url(href: str, base_url: str) -> str | None:
    """Build absolute URL from href and base URL."""
    if not href or href.startswith(("#", "mailto:", "tel:", "javascript:", "data:")):
        return None

    try:
        from urllib.parse import urljoin

        absolute = urljoin(base_url, href)
        # Remove fragments
        absolute = absolute.split("#")[0]
        return absolute
    except Exception:
        return None


def _is_same_domain(url: str, expected_domain: str) -> bool:
    """Check if URL is on the same domain as expected_domain."""
    if not expected_domain:
        return True

    try:
        parsed = urlparse(url)
        actual_domain = parsed.hostname or ""
        return actual_domain.lower() == expected_domain.lower()
    except Exception:
        return False
