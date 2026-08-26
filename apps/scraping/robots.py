"""The only robots.txt parser in the project (scraping).

Small, deterministic, dependency-free. Rules are fetched per-domain (through
``fetching.fetch_robots_raw`` — this module never imports Scrapling directly and
never re-enters the robots check), cached in memory for an hour, and parsed into
per-user-agent blocks selected by longest-prefix/"*" matching.

Robots data has the session-surf policy (PROMPT 5): a blocking robots.txt is
NOT a "skip the domain" signal — it only stops *crawling* it. Strategies consume
rules through the targeted kills/counts/surfing gates below.
"""

from __future__ import annotations

import contextlib
import logging
import time
from dataclasses import dataclass, field
from urllib.parse import urlsplit, urlunparse

logger = logging.getLogger("study_tracker.scraping.robots")

USER_AGENT_KEY = "StudyTrackerBot/1.0"
DEFAULT_CRAWL_DELAY = 1.0
CACHE_TTL_SECONDS = 60 * 60
_MAX_BODY_BYTES = 256 * 1024

_CACHE: dict[str, tuple[float, RobotRules]] = {}


@dataclass(frozen=True)
class Rule:
    path: str


@dataclass
class RulesBlock:
    user_agents: list[str] = field(default_factory=list)  # as written (lowercased)
    allow: list[Rule] = field(default_factory=list)
    disallow: list[Rule] = field(default_factory=list)
    crawl_delay: float = DEFAULT_CRAWL_DELAY
    session_probes: list[str] = field(default_factory=list)

    def matches(self, ua: str) -> str | None:
        """Longest matching UA entry for ``ua`` (prefix or exact), or None."""
        ua_lower = ua.lower()
        best: str | None = None
        for entry in self.user_agents:
            if entry != "*" and not ua_lower.startswith(entry):
                continue
            if best is None or len(entry) > len(best):
                best = entry
        return best

    def allowed(self, path: str) -> tuple[bool, str | None]:
        """Robots-spec precedence: no rules -> allow; more-specific rule wins."""
        if not self.disallow:
            return True, None
        specific_disallow = self._most_specific(path, self.disallow)
        if specific_disallow is None:
            return True, None
        specific_allow = self._most_specific(path, self.allow)
        if specific_allow and len(specific_allow) > len(specific_disallow):
            return True, specific_allow
        return False, specific_disallow

    @staticmethod
    def _most_specific(path: str, rules: list[Rule]) -> str | None:
        best: str | None = None
        for r in rules:
            if path.startswith(r.path):
                best = r.path  # keep sorting callers ascending so last match wins
        return best


@dataclass
class RobotRules:
    blocks: list[RulesBlock] = field(default_factory=list)
    sitemaps: list[str] = field(default_factory=list)
    fetched: bool = False

    def select_for(self, ua: str) -> RulesBlock:
        """Pick the block whose UA entry best matches ``ua`` (longest wins)."""
        best: tuple[int, RulesBlock] | None = None
        star: RulesBlock | None = None
        for block in self.blocks:
            matched = block.matches(ua)
            if matched is None:
                continue
            if matched == "*":
                star = block
                continue
            if best is None or len(matched) > best[0]:
                best = (len(matched), block)
        if best is not None:
            return best[1]
        return star or (self.blocks[0] if self.blocks else RulesBlock())


# PUBLIC API — everything above is internal.


def fetch_robots_raw(url: str, *, user_agent: str | None = None) -> tuple[int, str]:
    """Stable module-level binding of the wire helper (deferred import: the body
    avoids the fetching->robots circular import while keeping this name patchable
    in tests and used by the parser below)."""
    from .fetching import fetch_robots_raw as _raw

    return _raw(url, user_agent=user_agent)


def is_allowed(url: str) -> bool:
    """True when our crawler may request ``url`` (or no robots data exists).

    A blocked domain / failed fetch yields *allowed* from the parser itself —
    locking robots data in is a strategy-policy concern, not a parser one.
    """
    parts = urlsplit(url)
    path = parts.path or "/"
    return parse(url, user_agent=USER_AGENT_KEY).allowed(path)[0]


def parse(url: str, *, user_agent: str = "*") -> RulesBlock:
    """Rules applying to ``user_agent`` for ``url``'s domain."""
    return _fetch_rules(url).select_for(user_agent)


def fetch_now(url: str, *, body: str, strict: bool = True) -> RobotRules:
    """Build full rules from a raw body, bypassing the network (tests/CLI)."""
    return _parse_body(_robots_url(url), body)


def fetch_for_sitemaps(url: str) -> list[str]:
    """Sitemap URLs from any block (site-wide list / Surface contracts)."""
    return list(_fetch_rules(url).sitemaps)


# ——— internals ———


def _fetch_rules(url: str) -> RobotRules:
    now = time.monotonic()
    key = (urlsplit(url).netloc or "").lower()
    cached = _CACHE.get(key)
    if cached and (now - cached[0]) < CACHE_TTL_SECONDS:
        return cached[1]

    status, body = fetch_robots_raw(_robots_url(url), user_agent=USER_AGENT_KEY)
    rules = _parse_body(_robots_url(url), body)
    rules.fetched = True
    _CACHE[key] = (now, rules)
    return rules


def invalidate(url: str) -> None:
    _CACHE.pop((urlsplit(url).netloc or "").lower(), None)


def _robots_url(url: str) -> str:
    parts = urlsplit(url)
    return urlunparse((parts.scheme, parts.netloc, "/robots.txt", "", "", ""))


def _parse_body(robots_url: str, body: str) -> RobotRules:
    rules = RobotRules()
    current: RulesBlock | None = None
    current_has_ua_line = False
    for raw_line in body[:_MAX_BODY_BYTES].splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if ":" not in line:
            continue
        key, _, value = line.partition(":")
        key = key.strip().lower()
        value = value.strip()
        if key == "user-agent" and value:
            if current is None or current_has_ua_line:
                current = RulesBlock([value.lower()])
                rules.blocks.append(current)
                current_has_ua_line = True
            else:
                current.user_agents.append(value.lower())
            continue
        if key == "sitemap" and value:
            rules.sitemaps.append(value)
            continue
        if current is None:
            # Rules before any User-agent line (informal) apply to "*".
            implicit = RulesBlock(["*"])
            rules.blocks.append(implicit)
            current = implicit
            current_has_ua_line = True
        _apply_rule(current, key, value)
    return rules


def _apply_rule(block: RulesBlock, key: str, value: str) -> None:
    if key == "allow":
        block.allow.append(Rule(value))
    elif key == "disallow":
        if value:
            block.disallow.append(Rule(value))
    elif key == "crawl-delay":
        with contextlib.suppress(TypeError, ValueError):
            block.crawl_delay = float(value)
    elif key == "session-probe":
        block.session_probes.append(value)
