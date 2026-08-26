"""Deterministic fetch fixture harness for career-detection tests.

Patches the transport layer so every network call in the strategy pipeline is
served from a per-scenario manifest. Scenarios live under
``apps/career_detection/tests/fixtures/detection/<scenario>/`` and contain:

    manifest.json:
        {
          "domain": "example.com",
          "robots": {"status": 404, "body": "..."} | null,   # null = default 404
          "responses": {
             "<url>": {"status": 200, "body_file": "homepage.html",
                        "final_url": "<url>"}               # fetch()-able URLs
          },
          "heads": {"<url>": 206}                            # head_ok() 2xx wins
        }

Everything that is not registered either 404s (heads) or fails loudly
(``fetch`` raises FetchNotFound; unknown manifests raise AssertionError).
The robots txt is served through ``apps.scraping.robots.fetch_robots_raw`` so
the real robots parser (cache + precedence) is exercised; scenarios must use
unique domains because the robots cache is keyed by netloc.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from pytest import MonkeyPatch

from apps.scraping.exceptions import FetchDomainBlocked, FetchError, FetchNotFound
from apps.scraping.fetching import FetchMode, FetchResult

FIXTURES_DIR = Path(__file__).parent / "fixtures" / "detection"

BLOCKED_DOMAINS = {
    "linkedin.com",
    "indeed.com",
    "glassdoor.com",
    "monster.com",
    "ziprecruiter.com",
}


@dataclass
class FixtureResponse:
    status: int
    body: str
    final_url: str

    @property
    def raise_exc(self) -> FetchError | None:
        if self.status in (404, 410):
            return FetchNotFound(f"{self.final_url} returned {self.status}", url=self.final_url)
        if self.status == 0 or self.status >= 500:
            from apps.scraping.exceptions import FetchServerError

            return FetchServerError(f"{self.final_url} returned {self.status}", url=self.final_url)
        if self.status in (403, 429):
            from apps.scraping.exceptions import FetchBlocked

            return FetchBlocked(f"{self.final_url} was blocked", url=self.final_url)
        return None


@dataclass
class Scenario:
    name: str
    domain: str
    responses: dict[str, FixtureResponse]
    heads: dict[str, int]
    robots_body: str | None
    robots_status: int = 404
    call_log: list[str] = field(default_factory=list)

    @classmethod
    def load(cls, name: str) -> Scenario:
        path = FIXTURES_DIR / name / "manifest.json"
        manifest = json.loads(path.read_text())
        domain = str(manifest["domain"]).lower()
        responses: dict[str, FixtureResponse] = {}
        for url, spec in manifest.get("responses", {}).items():
            body = ""
            if spec.get("body_file"):
                body = (path.parent / spec["body_file"]).read_text()
            elif spec.get("body"):
                body = spec["body"]
            status = int(spec.get("status", 200))
            final_url = str(spec.get("final_url") or url)
            responses[_key(url)] = FixtureResponse(status, body, final_url)
        robots = manifest.get("robots")
        robots_body = None
        robots_status = 404
        if robots:
            robots_status = int(robots.get("status", 200))
            robots_body = robots.get("body")
            if robots.get("body_file"):
                robots_body = (path.parent / robots["body_file"]).read_text()
        heads = {_key(u): int(s) for u, s in manifest.get("heads", {}).items()}
        return cls(name, domain, responses, heads, robots_body, robots_status)

    def fetch(self, url: str, **kwargs: Any) -> FetchResult:
        self.call_log.append(f"fetch {url}")
        key = _key(url)
        if key not in self.responses and _is_blocked(url):
            raise FetchDomainBlocked(f"Domain for {url} is blocked", url=url)
        response = self.responses.get(key)
        if response is None:
            raise FetchNotFound(f"No fixture for {url}", url=url)
        if response.raise_exc is not None:
            raise response.raise_exc
        return FetchResult(
            url=url,
            final_url=response.final_url,
            status_code=response.status,
            html=response.body,
            selector=None,  # strategies extract from raw HTML text, never selector
            fetcher_used=FetchMode.HTTP,
            elapsed_ms=1,
            from_cache=False,
            escalation_reason="",
        )

    def head_ok(self, url: str) -> tuple[bool, int]:
        self.call_log.append(f"head {url}")
        if _is_blocked(url):
            raise FetchDomainBlocked(f"Domain for {url} is blocked", url=url)
        status = self.heads.get(_key(url), 404)
        return (200 <= status < 400), status

    def robots_raw(self, url: str, *, user_agent: str | None = None) -> tuple[int, str]:
        self.call_log.append(f"robots {url}")
        return (self.robots_status, self.robots_body or "")


def _key(url: str) -> str:
    """Normalize: lowercase scheme+host, drop default port and trailing slash."""
    parts = urlsplit(url)
    host = (parts.hostname or "").lower()
    port = f":{parts.port}" if parts.port and parts.port not in (80, 443) else ""
    path = parts.path.rstrip("/")
    if not path:
        path = "/"
    return f"{parts.scheme}://{host}{port}{path}"


def _is_blocked(url: str) -> bool:
    host = (urlsplit(url).hostname or "").lower()
    return any(host == d or host.endswith("." + d) for d in BLOCKED_DOMAINS)


def activate_scenario(monkeypatch: MonkeyPatch, scenario: str | Scenario) -> Scenario:
    """Patch the transport names the strategies import, return the scenario."""
    if isinstance(scenario, str):
        scenario = Scenario.load(scenario)
    monkeypatch.setattr("apps.career_detection.strategies.fetch", scenario.fetch)
    monkeypatch.setattr("apps.career_detection.strategies.head_ok", scenario.head_ok)
    monkeypatch.setattr("apps.career_detection.strategies.fetch_with_escalation", scenario.fetch)
    monkeypatch.setattr("apps.scraping.robots.fetch_robots_raw", scenario.robots_raw)
    # Robots cache is netloc-keyed; expire before touching this domain.
    import apps.scraping.robots as robots_mod

    robots_mod.invalidate(f"https://{scenario.domain}")
    return scenario
