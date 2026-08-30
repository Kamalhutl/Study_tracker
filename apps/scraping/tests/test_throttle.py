"""Throttle tests — everything on an injectable fake clock/sleep, never real time."""

from unittest.mock import patch

from django.core.cache import cache
from django.test import SimpleTestCase, override_settings

from apps.scraping.exceptions import FetchBudgetExceeded, ThrottleUnavailable
from apps.scraping.throttle import acquire_slot

RATE = 3


class _FakeClock:
    def __init__(self) -> None:
        self.t = 1000.0

    def __call__(self) -> float:
        return self.t

    def advance(self, seconds: float) -> None:
        self.t += seconds


@override_settings(CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}})
class AcquireSlotTests(SimpleTestCase):
    def setUp(self) -> None:
        cache.clear()
        self.clock = _FakeClock()
        self.slept: list[float] = []
        self.clock_side_effects = 0

    def _sleep(self, seconds: float) -> None:
        self.slept.append(seconds)
        self.clock.advance(seconds)

    def test_under_rate_passes_immediately(self) -> None:
        for _ in range(RATE):
            acquire_slot(
                "good.example", rate_per_minute=RATE, _clock=self.clock, _sleep=self._sleep
            )
        self.assertEqual(self.slept, [])

    def test_over_rate_blocks_until_window_rotates(self) -> None:
        for _ in range(RATE):
            acquire_slot("rot.example", rate_per_minute=RATE, _clock=self.clock, _sleep=self._sleep)
        # Allowed *in aggregate per window* — an 4th request in the same window is held.
        self.clock.advance(0.1)
        self.assertRaises(
            FetchBudgetExceeded,
            acquire_slot,
            "rot.example",
            rate_per_minute=RATE,
            timeout=0.2,
            _clock=self.clock,
            _sleep=self._sleep,
        )
        self.assertGreaterEqual(sum(self.slept), 0.1)
        # Next window frees capacity.
        self.clock.advance(61.0)
        acquire_slot(
            "rot.example", rate_per_minute=RATE, timeout=1, _clock=self.clock, _sleep=self._sleep
        )

    def test_rate_disable_never_blocks(self) -> None:
        for _ in range(10):
            acquire_slot("free.example", rate_per_minute=0, _clock=self.clock, _sleep=self._sleep)
        self.assertEqual(self.slept, [])

    def test_domains_are_isolated(self) -> None:
        for _ in range(RATE):
            acquire_slot("a.example", rate_per_minute=RATE, _clock=self.clock, _sleep=self._sleep)
        # Different domain is unaffected.
        acquire_slot(
            "b.example", rate_per_minute=RATE, timeout=1, _clock=self.clock, _sleep=self._sleep
        )

    def test_throttle_unavailable_when_redis_down(self) -> None:
        """Redis connection error is wrapped in ThrottleUnavailable, no traceback."""
        with (
            patch("django.core.cache.cache.add", side_effect=ConnectionError("redis down")),
            self.assertRaises(ThrottleUnavailable) as cm,
        ):
            acquire_slot(
                "down.example",
                rate_per_minute=RATE,
                _clock=self.clock,
                _sleep=self._sleep,
            )
        self.assertEqual(cm.exception.code, "throttle_unavailable")
        self.assertIn("rate-limiter backend unreachable", str(cm.exception))


@override_settings(CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}})
class JitterTests(SimpleTestCase):
    def test_jitter_sleeps_randomly_after_slot(self) -> None:
        cache.clear()
        clock = _FakeClock()
        slept: list[float] = []
        with patch("random.uniform", lambda a, b: (a + b) / 2):
            acquire_slot(
                "jitter.example",
                rate_per_minute=5,
                _clock=clock,
                _sleep=slept.append,
                jitter_ms=(100, 500),
            )
        self.assertEqual(len(slept), 1)
        self.assertGreaterEqual(slept[0], 0.1)
        self.assertLessEqual(slept[0], 0.5)

    def test_jitter_disabled_by_default(self) -> None:
        cache.clear()
        clock = _FakeClock()
        slept: list[float] = []
        acquire_slot(
            "nojitter.example",
            rate_per_minute=5,
            _clock=clock,
            _sleep=slept.append,
        )
        self.assertEqual(slept, [])
