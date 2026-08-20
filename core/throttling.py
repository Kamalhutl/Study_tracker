"""Throttling extras.

Global anon/user throttle classes come from DRF defaults; the scoped
``auth`` throttle is the stock ``ScopedRateThrottle`` keyed off
``throttle_scope = "auth"`` on login/register views. The envelope handler
turns any ``Throttled`` exception into ``rate_limited`` + ``retry_after``.
"""
