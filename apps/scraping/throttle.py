"""Redis-backed per-domain token-bucket throttle.

The bucket must hold ACROSS Celery workers — a per-process limiter is useless at
1000 companies. The Django cache backend is Redis in prod and LocMem in tests;
``cache.add``/``cache.incr`` are atomic in both, so a fixed 60s window counter is
safe to share between workers.

Signature is FROZEN: ``acquire_slot(domain, *, rate_per_minute, timeout=30.0)``.
The ``_clock`` / ``_sleep`` kwargs are injectable so tests can fake time — no
test may call ``time.sleep``.
"""

from __future__ import annotations

import contextlib
import logging
import random
import time
from collections.abc import Callable

from django.conf import settings
from django.core.cache import cache

from .exceptions import FetchBudgetExceeded, ThrottleUnavailable

logger = logging.getLogger("study_tracker.scraping.throttle")

_WINDOW_SECONDS = 60
_POLL_SECONDS = 0.05


def acquire_slot(
    domain: str,
    *,
    rate_per_minute: int = 0,
    timeout: float = 30.0,
    _clock: Callable[[], float] = time.monotonic,
    _sleep: Callable[[float], None] = time.sleep,
    jitter_ms: tuple[int, int] | None = None,
) -> None:
    """Block until a request slot is free for ``domain`` (or timeout).

    Holds no per-process state — every worker competes for the same Redis keys,
    so the aggregate request rate per domain can never exceed the budget.

    :param rate_per_minute: max requests per 60s window. ``<=0`` disables limiting.
    :param timeout: max seconds to wait; raises :class:`FetchBudgetExceeded`.
    :param jitter_ms: ``(min_ms, max_ms)`` randomized delay after the slot is won,
        so we never look like a metronome. Read from settings by the caller.
    """
    if rate_per_minute is None or rate_per_minute <= 0:
        return

    deadline = _clock() + timeout
    while True:
        window = int(_clock() // _WINDOW_SECONDS)
        counter_key = f"throttle:{domain}:{window}"
        try:
            cache.add(counter_key, 0, timeout=_WINDOW_SECONDS * 2)
            count = cache.incr(counter_key)
        except ValueError:
            # LocMem edge: the key can be evicted between add and incr; retry.
            if _clock() >= deadline:
                raise FetchBudgetExceeded(
                    f"Timed out waiting for a fetch slot for {domain!r}",
                    url=domain,
                ) from None
            _sleep(_POLL_SECONDS)
            continue
        except Exception as exc:
            # Redis connection errors (and any other backend failure) bubble up as
            # ThrottleUnavailable so callers can fail fast without a traceback.
            raise ThrottleUnavailable(
                "rate-limiter backend unreachable, refusing to fetch",
                url=domain,
            ) from exc

        if count <= rate_per_minute:
            if jitter_ms and jitter_ms[1] > 0:
                _sleep(random.uniform(jitter_ms[0], jitter_ms[1]) / 1000.0)
            return

        # Over budget: give the token back and wait for the window to roll over.
        with contextlib.suppress(ValueError):  # eviction between incr and decr
            cache.decr(counter_key)
        if _clock() >= deadline:
            raise FetchBudgetExceeded(
                f"Timed out waiting for a fetch slot for {domain!r}",
                url=domain,
            )
        _sleep(_POLL_SECONDS)


def scrape_jitter(domain: str) -> None:
    """Small randomized pause using ``FETCH_PER_DOMAIN_JITTER_MS`` defaults."""
    lo, hi = settings.FETCH_PER_DOMAIN_JITTER_MS
    if hi > 0:
        time.sleep(random.uniform(lo, hi) / 1000.0)
