"""Redis-based distributed lock with compare-and-delete release.

The scraping layer (STEP 12) will use this to make sure only one worker
runs a given scrape job at a time.
"""

import contextlib
import logging
import secrets
from collections.abc import Iterator
from typing import Any

from django.core.cache import cache

logger = logging.getLogger("study_tracker.locks")

LOCK_PREFIX = "lock:"
MAX_TIMEOUT = 60 * 60 * 24  # fail fast on stupid callers


class LockNotAcquired(Exception):
    """Raised (or used as context) when a lock cannot be acquired."""


class _ReleasedLock:
    """Marker for the `acquire` return value so `release()` is safe."""

    token: str


@contextlib.contextmanager
def redis_lock(
    key: str,
    timeout: int = 300,
    blocking: bool = False,
    blocking_timeout: float = 0,
) -> Iterator[Any]:
    """Acquire a distributed lock.

    Uses SETNX+EX semantically (Django cache ``add`` with timeout), with a
    random token; release does a compare-and-delete so a worker can never
    delete another worker's lock (even if this one expired a moment ago).
    Raises RuntimeError if the lock store is unreachable so callers notice.
    """
    token = secrets.token_urlsafe(32)
    lock_key = f"{LOCK_PREFIX}{key}"
    timeout = min(int(timeout), MAX_TIMEOUT)

    deadline = None
    if blocking_timeout and blocking_timeout > 0:
        import time

        deadline = time.monotonic() + blocking_timeout

    acquired = False
    while not acquired:
        try:
            acquired = bool(cache.add(lock_key, token, timeout=timeout))
        except Exception:  # Redis unreachable — surface loudly.
            logger.error("Redis unreachable while acquiring lock %r", key, exc_info=True)
            raise RuntimeError(f"Redis unavailable while acquiring lock {key!r}") from None

        if not acquired:
            if not blocking:
                raise LockNotAcquired(f"Could not acquire lock {key!r}")
            if deadline is not None and time.monotonic() >= deadline:
                raise LockNotAcquired(f"Timed out waiting for lock {key!r}")
            import time

            time.sleep(0.05)

    try:
        yield token
    finally:
        try:
            _release(lock_key, token)
        except Exception:
            logger.exception("Failed to release lock %r", key)


def _release(lock_key: str, token: str) -> None:
    """Atomic compare-and-delete via Lua on redis-py, safe fallback otherwise."""
    from django.core.cache import caches

    # Prefer the raw redis client for an atomic compare-and-delete.
    try:
        redis_backend = caches["default"]
        client = getattr(redis_backend, "client", None)
        if callable(client):
            client = client.get_client()
    except Exception:
        client = None

    if client is not None:
        script = """
        if redis.call('get', KEYS[1]) == ARGV[1] then
            return redis.call('del', KEYS[1])
        else
            return 0
        end
        """
        try:
            client.eval(script, 1, lock_key, token)
            return
        except Exception:
            logger.warning("Lua compare-and-delete failed; falling back", exc_info=True)

    # Safe fallback: only delete if the stored token is still ours.
    if cache.get(lock_key) == token:
        cache.delete(lock_key)
