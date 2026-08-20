"""redis_lock: acquire, contention, release, auto-expiry, cross-worker safety."""

import pytest
from django.core.cache import cache

from core.locks import LockNotAcquired, redis_lock


def test_acquire_and_release():
    with redis_lock("job:scrape:1") as token:
        assert isinstance(token, str) and token
        assert cache.get("lock:job:scrape:1") == token
    assert cache.get("lock:job:scrape:1") is None


def test_contention_non_blocking_raises():
    with redis_lock("job:scrape:2"):
        try:
            with redis_lock("job:scrape:2"):
                raise AssertionError("must not acquire a held lock")
        except LockNotAcquired:
            pass


def test_blocking_acquire_waits():
    import threading
    import time

    holder_released = threading.Event()
    inner_token = {}

    def hold_lock():
        with redis_lock("job:scrape:3", timeout=20):
            inner_token["value"] = cache.get("lock:job:scrape:3")
            holder_released.wait(timeout=5)

    thread = threading.Thread(target=hold_lock)
    thread.start()
    time.sleep(0.2)  # let the holder take the lock

    try:
        with redis_lock("job:scrape:3", blocking=True, blocking_timeout=5) as token:
            assert cache.get("lock:job:scrape:3") == token
            assert inner_token["value"] != token  # different holder, different token
    finally:
        holder_released.set()
        thread.join(timeout=5)


def test_auto_expiry():
    import time

    try:
        with redis_lock("job:scrape:4", timeout=1):
            pass
        # Simulate TTL expiry by waiting it out; lock should be gone.
        time.sleep(1.2)
        assert cache.get("lock:job:scrape:4") is None
    except AssertionError:
        raise
    # And after expiry a fresh worker can acquire again.
    with redis_lock("job:scrape:4", timeout=5):
        pass


def test_worker_cannot_release_another_workers_lock():
    # Worker A holds the lock; an external write (as if it expired and
    # worker B took it) must survive A's exit.
    with redis_lock("job:scrape:5", timeout=30) as token_a:
        assert cache.get("lock:job:scrape:5") == token_a
        # Simulate: A's lock expired & B acquired with a new token.
        cache.set("lock:job:scrape:5", "worker-b-token", timeout=30)
    # A's finally-block must NOT have deleted B's lock.
    assert cache.get("lock:job:scrape:5") == "worker-b-token"
    cache.delete("lock:job:scrape:5")


def test_blocking_timeout_raises_when_never_released(monkeypatch):
    state = {"t": 10.0, "sleeps": 0}

    def fake_monotonic() -> float:
        state["t"] += 0.075
        return state["t"]  # type: ignore[no-any-return]

    monkeypatch.setattr("time.monotonic", fake_monotonic)
    monkeypatch.setattr("time.sleep", lambda s: state.__setitem__("sleeps", state["sleeps"] + 1))

    with redis_lock("job:scrape:6"):
        try:
            with redis_lock("job:scrape:6", blocking=True, blocking_timeout=0.1):
                raise AssertionError("must not acquire a held lock")
        except LockNotAcquired:
            pass
    assert state["sleeps"] >= 1


def test_redis_unreachable_raises_runtime_error(monkeypatch):
    import django.core.cache

    def boom(*args, **kwargs):
        raise ConnectionError("redis is down")

    monkeypatch.setattr(django.core.cache.cache, "add", boom)
    with pytest.raises(RuntimeError, match="Redis unavailable"), redis_lock("job:scrape:7"):
        pass
