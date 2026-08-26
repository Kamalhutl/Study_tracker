"""Core detection types: RawCandidate, DetectionContext, Strategy protocol.

Frozen shapes from PROMPT_3_SECTION_6 §6.2. ``DetectionContext.add`` implements
the merge rule: evidence dicts merge (``True`` wins over absent/``False``, lists
concatenate and dedupe), ATS-sourced evidence claims the recorded origin, and
otherwise the cheapest origin (lowest strategy cost) is kept; a normalized URL
is never duplicated.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from apps.scraping.exceptions import FetchBudgetExceeded

# origin -> strategy cost, for the "cheapest origin wins" merge rule.
# header/footer links come from the free homepage reuse (cost 1).
ORIGIN_COSTS: dict[str, int] = {
    "header_link": 1,
    "footer_link": 1,
    "ats_pattern": 2,
    "robots_txt": 2,
    "sitemap": 3,
    "common_path": 3,
    "subdomain_guess": 3,
    "json_ld": 3,
    "manual": 1,
}


@dataclass(frozen=True)
class RawCandidate:
    """A URL proposed by a strategy, before scoring."""

    url: str  # absolute, normalized, http(s) only
    origin: str  # a CandidateOrigin value from apps.companies.enums
    evidence: dict[str, Any] = field(default_factory=dict)
    discovered_via: str = ""  # short human string for the audit trail


@dataclass
class DetectionContext:
    """Mutable shared state for one detection run."""

    company: Any  # Company instance
    root_url: str  # normalized https://<company domain>/
    domain: str
    max_checks: int = 0
    checks_used: int = 0
    deadline: float = 0.0  # monotonic() deadline
    candidates: dict[str, RawCandidate] = field(default_factory=dict)
    sitemap_urls: set[str] = field(default_factory=set)
    robots_sitemaps: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    ats_short_circuit: bool = False
    homepage: Any = None  # FetchResult of the root URL, shared across strategies
    homepage_error: str = ""  # non-empty when the root URL itself was unreachable

    def budget_left(self) -> bool:
        """Checks remaining AND wall-clock time remaining."""
        import time

        return self.checks_used < self.max_checks and time.monotonic() < self.deadline

    def spend(self, n: int = 1) -> None:
        """Consume ``n`` URL checks; raise :class:`FetchBudgetExceeded` when spent."""
        self.checks_used += n
        if not self.budget_left():
            raise FetchBudgetExceeded(f"Detection budget exhausted after {self.checks_used} checks")

    def add(self, candidate: RawCandidate) -> None:
        """Add or merge a candidate keyed by normalized URL (see module docstring)."""
        key = candidate.url
        existing = self.candidates.get(key)
        if existing is None:
            self.candidates[key] = candidate
            return
        # Merge evidence: True wins, lists concatenate+dedupe, scalars keep existing.
        merged = dict(existing.evidence)
        for k, v in candidate.evidence.items():
            prev = merged.get(k)
            if prev is None:
                merged[k] = v
            elif v is True and prev is not True:
                merged[k] = True
            elif isinstance(prev, list) and isinstance(v, list):
                merged[k] = list(dict.fromkeys([*prev, *v]))
        # --- Merge rule -----------------------------------------------------------
        # Origin: ATS evidence outranks everything (the strongest signal);
        # otherwise the cheapest origin (free nav scans first) wins ties.
        origin = existing.origin
        if "ats_source" in candidate.evidence and "ats_source" not in existing.evidence:
            origin = candidate.origin
        elif "ats_source" in existing.evidence:
            origin = existing.origin
        elif ORIGIN_COSTS.get(candidate.origin, 0) < ORIGIN_COSTS.get(origin, 0):
            origin = candidate.origin
        self.candidates[key] = RawCandidate(
            url=existing.url,
            origin=origin,
            evidence=merged,
            discovered_via="; ".join(
                s for s in (existing.discovered_via, candidate.discovered_via) if s
            ),
        )


class Strategy(Protocol):
    name: str
    cost: int  # 1 = cheap/no-network, 2 = one fetch, 3 = many fetches

    def run(self, ctx: DetectionContext) -> list[RawCandidate]: ...
