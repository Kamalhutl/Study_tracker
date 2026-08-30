"""``manage.py run_smoke`` — verify the whole scraping pipeline against 1-3 real sites.

Checks robots fetch+parse, head probe and HTTP fetch (optionally browser
escalation). Transport-only — scoring/strategies live in the detection app.
Safe: rate-limited, robots-obeying, one shot per URL. Reads ``FETCH_SMOKE_URLS``;
with an empty list it prints OFFLINE and exits 0 (so CI stays green without network).

Exit code: 0 = all probes passed (or offline), 1 = a probe failed.
"""

from __future__ import annotations

from typing import Any

from django.conf import settings
from django.core.management.base import BaseCommand

from apps.scraping import (
    FetchError,
    FetchResult,
    ThrottleUnavailable,
    fetch,
    fetch_with_escalation,
    head_ok,
    parse,
)


class Command(BaseCommand):
    help = "Smoke-test the scraping pipeline against real URLs."

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument("urls", nargs="*", help="Override FETCH_SMOKE_URLS.")
        parser.add_argument(
            "--dynamic",
            action="store_true",
            help="Also exercise browser escalation even when disabled globally.",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        urls = options["urls"] or list(settings.FETCH_SMOKE_URLS or [])
        if not urls:
            self.stdout.write(
                self.style.WARNING("OFFLINE: no FETCH_SMOKE_URLS, skipping smoke run")
            )
            return

        failures = 0
        for url in urls:
            failures += self._probe(url, dynamic=options["dynamic"])
        if failures:
            raise SystemExit(1)
        self.stdout.write(self.style.SUCCESS(f"SMOKE OK: {len(urls)} url(s) passed"))

    def _probe(self, url: str, *, dynamic: bool) -> int:
        self.stdout.write(f"\n== {url}")
        failed = 0

        # 1. robots: fetch -> parse -> is_allowed (must not raise or hang)
        try:
            block = parse(url)
            from urllib.parse import urlsplit

            path = urlsplit(url).path or "/"
            allowed, matched = block.allowed(path)
            self.stdout.write(
                f"  robots : {len(block.allow)}+{len(block.disallow)} rules for "
                f"{block.user_agents or ['*']} | crawldelay={block.crawl_delay}s | "
                f"allowed={allowed} ({matched or 'default'})"
            )
        except ThrottleUnavailable as exc:
            self.stdout.write(self.style.ERROR(f"  robots : THROTTLE_DOWN {exc}"))
            failed += 1
        except Exception as exc:
            self.stdout.write(self.style.ERROR(f"  robots : FAIL {exc!r}"))
            failed += 1

        # 2. head probe (must not raise for ordinary HTTP failures)
        try:
            ok, status = head_ok(url)
            self.stdout.write(f"  head   : {'OK' if ok else 'MISS'} (status={status})")
        except ThrottleUnavailable as exc:
            self.stdout.write(self.style.ERROR(f"  head   : THROTTLE_DOWN {exc}"))
            failed += 1
        except Exception as exc:
            self.stdout.write(self.style.ERROR(f"  head   : FAIL {exc!r}"))
            failed += 1

        # 3. full fetch (HTTP, then optional browser escalation)
        result: FetchResult
        try:
            result = fetch_with_escalation(url) if dynamic else fetch(url)
            verdict = f"HTTP {result.status_code} {len(result.html)}B in {result.elapsed_ms}ms"
            title = result.title().strip()
            if title:
                verdict += f" | title={title[:60]!r}"
            jobs = result.json_ld()
            if jobs:
                verdict += f" | JSON-LD({len(jobs)})"
            self.stdout.write(f"  fetch  : {verdict}")
            if result.escalation_reason:
                self.stdout.write(f"  detect : SPA-like ({result.escalation_reason})")
        except ThrottleUnavailable as exc:
            self.stdout.write(self.style.ERROR(f"  fetch  : THROTTLE_DOWN {exc}"))
            failed += 1
        except FetchError as exc:
            self.stdout.write(self.style.ERROR(f"  fetch  : FAIL {exc}"))
            failed += 1
        return failed
