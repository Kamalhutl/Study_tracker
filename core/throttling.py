"""Throttling extras.

Global anon/user throttle classes come from DRF defaults; the scoped
``auth`` throttle is the stock ``ScopedRateThrottle`` keyed off
``throttle_scope = "auth"`` on login/register views. The envelope handler
turns any ``Throttled`` exception into ``rate_limited`` + ``retry_after``.
"""

import logging
import secrets

from django.conf import settings
from rest_framework.throttling import AnonRateThrottle

logger = logging.getLogger("study_tracker.throttling")


class ServiceTokenAnonThrottle(AnonRateThrottle):
    """Rate-limit exemption for server-to-server SSR traffic.

    This class grants rate-limit exemption only. It is not authentication
    and confers no permission. Requests bearing a valid service token skip
    anonymous throttling entirely; all other requests are throttled at the
    configured anon rate.
    """

    def get_cache_key(self, request, view):  # type: ignore[override]
        token = request.META.get("HTTP_X_SERVICE_TOKEN", "")
        expected = getattr(settings, "SSR_SERVICE_TOKEN", "")
        if expected and token and secrets.compare_digest(token, expected):
            return None
        if token and expected and not secrets.compare_digest(token, expected):
            logger.warning(
                "Invalid X-Service-Token presented for %s",
                request.path,
            )
        return super().get_cache_key(request, view)
