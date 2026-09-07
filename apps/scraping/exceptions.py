"""Fetch-error hierarchy. Scrapling/transport exceptions must NEVER escape ``fetching.py``.

Every exception carries a stable machine ``code`` plus the offending ``url`` so the
detection run log and the API layer can react without string-matching messages.
"""

from __future__ import annotations


class FetchError(Exception):
    """Base class for every fetch failure. ``url`` and ``code`` are always set."""

    code = "fetch_error"

    def __init__(self, message: str, *, url: str = "", code: str | None = None) -> None:
        self.url = url
        if code is not None:
            self.code = code
        super().__init__(message)

    def as_dict(self) -> dict[str, str]:
        return {"code": self.code, "url": self.url, "message": str(self)}


class FetchTimeout(FetchError):
    code = "fetch_timeout"


class FetchBlocked(FetchError):
    """403 / 429 / anti-bot wall."""

    code = "fetch_blocked"


class FetchNotFound(FetchError):
    """404 / 410."""

    code = "fetch_not_found"


class FetchServerError(FetchError):
    """5xx from the origin."""

    code = "fetch_server_error"


class FetchTooLarge(FetchError):
    """Response exceeded ``FETCH_MAX_RESPONSE_BYTES``."""

    code = "fetch_too_large"


class FetchRobotsDisallowed(FetchError):
    """robots.txt says no."""

    code = "fetch_robots_disallowed"


class FetchDomainBlocked(FetchError):
    """Host (or any redirect target) is in ``BLOCKED_DOMAINS``."""

    code = "fetch_domain_blocked"


class FetchBudgetExceeded(FetchError):
    """Throttle deadline or total-run budget exceeded."""

    code = "fetch_budget_exceeded"


class ThrottleUnavailable(FetchError):
    """Rate-limiter backend unreachable; refusing to fetch without a working throttle."""

    code = "throttle_unavailable"


# Transient exception classification for retry logic
TRANSIENT_EXCEPTIONS = (
    FetchTimeout,
    FetchServerError,
    FetchBlocked,
    ThrottleUnavailable,
)


def is_transient(exc: Exception) -> bool:
    """Return True if the exception is transient and should be retried."""
    return isinstance(exc, TRANSIENT_EXCEPTIONS)
