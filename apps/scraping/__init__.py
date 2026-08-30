"""Scraping layer: URL-role classification, robots, throttling and fetching.

This is the ONLY place that imports Scrapling (``scraping.fetching``). Everything
else consumes the frozen surface below.
"""

from __future__ import annotations

default_app_config = "apps.scraping.apps.ScrapingConfig"

from .exceptions import (  # noqa: E402
    FetchBlocked,
    FetchBudgetExceeded,
    FetchDomainBlocked,
    FetchError,
    FetchNotFound,
    FetchRobotsDisallowed,
    FetchServerError,
    FetchTimeout,
    FetchTooLarge,
    ThrottleUnavailable,
)
from .fetching import (  # noqa: E402
    FetchMode,
    FetchResult,
    fetch,
    fetch_robots_raw,
    fetch_with_escalation,
    head_ok,
    session_for,
)
from .robots import (  # noqa: E402
    fetch_for_sitemaps,
    fetch_now,
    invalidate,
    is_allowed,
    parse,
)
from .throttle import acquire_slot  # noqa: E402

__all__ = [
    "FetchBlocked",
    "FetchBudgetExceeded",
    "FetchDomainBlocked",
    "FetchError",
    "FetchMode",
    "FetchNotFound",
    "FetchResult",
    "FetchRobotsDisallowed",
    "FetchServerError",
    "FetchTimeout",
    "FetchTooLarge",
    "ThrottleUnavailable",
    "acquire_slot",
    "fetch",
    "fetch_for_sitemaps",
    "fetch_now",
    "fetch_robots_raw",
    "fetch_with_escalation",
    "head_ok",
    "invalidate",
    "is_allowed",
    "parse",
    "session_for",
]
