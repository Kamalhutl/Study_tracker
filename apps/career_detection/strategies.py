"""The 8 detection strategies — PROMPT_3_SECTION_6 §6.3.

Run in the exact order below (cheapest first). Every strategy is independently
testable, catches its own fetch exceptions (appending to ``ctx.notes``), and only
lets :class:`FetchBudgetExceeded` propagate so the orchestrator can mark the run
``partial``. HTTP-mode fetches go through ``apps.scraping.fetching``; browsers are
picked up by escalation where needed.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from collections.abc import Callable
from typing import Any, TypeVar
from urllib.parse import urljoin

from django.conf import settings

from apps.companies.enums import CareerSourceType
from apps.companies.services import _is_blocked, sniff_source_type_from_url
from apps.scraping import FetchMode, fetch, fetch_with_escalation, head_ok
from apps.scraping import robots as robots_mod
from apps.scraping.exceptions import (
    FetchBudgetExceeded,
    FetchDomainBlocked,
    FetchError,
    ThrottleUnavailable,
)
from core.utils import normalize_url

from . import extract
from .scoring import score_candidate
from .types import ORIGIN_COSTS, DetectionContext, RawCandidate

logger = logging.getLogger("study_tracker.career_detection.strategies")
# Simple per-run fetch cache and DNS/circuit breaker
_fetch_cache: dict[str, Any] = {}
_dns_cache: dict[str, Any] = {}
_host_failures: defaultdict[str, int] = defaultdict(int)
_HOST_DEAD_THRESHOLD = 3

T = TypeVar("T")

_ALL_ATS_TYPES = {
    CareerSourceType.GREENHOUSE,
    CareerSourceType.LEVER,
    CareerSourceType.ASHBY,
    CareerSourceType.SMARTRECRUITERS,
}

# ATS board URL patterns used for company-slug guesses (<= 4 guesses max).
ATS_GUESS_PATTERNS: dict[CareerSourceType, Callable[[str], str]] = {
    CareerSourceType.GREENHOUSE: lambda slug: f"https://boards.greenhouse.io/{slug}",
    CareerSourceType.LEVER: lambda slug: f"https://jobs.lever.co/{slug}",
    CareerSourceType.ASHBY: lambda slug: f"https://jobs.ashbyhq.com/{slug}",
    CareerSourceType.SMARTRECRUITERS: lambda slug: f"https://{slug}.smartrecruiters.com/",
}

MAX_ATS_GUESSES = 4
SITEMAP_MAX_DOCS = 3
SITEMAP_MAX_URLS_PER_DOC = 5000
SITEMAP_MAX_STORED_URLS = 10000


def _normalize(url: str) -> str:
    """Absolute http(s) candidate URL, standardized for dedupe keys."""
    if "://" not in url:
        url = f"https://{url}"
    # Strip default ports
    from urllib.parse import urlparse

    parsed = urlparse(url)
    if parsed.port in (80, 443):
        # remove port from netloc
        url = url.replace(f":{parsed.port}", "")
    # Unify www. prefix: we keep whatever is given, but for comparison we might want to be consistent.
    # We'll keep as given but ensure trailing slash normalized.
    url = url.rstrip("/")
    if not url.endswith("/"):
        url = url + "/"
    return str(normalize_url(url))


def _candidate_for_url(
    url: str, *, origin: str, evidence: dict[str, Any], via: str
) -> RawCandidate | None:
    if not url.lower().startswith(("http://", "https://")):
        return None
    return RawCandidate(url=_normalize(url), origin=origin, evidence=evidence, discovered_via=via)


def _provisional(ctx: DetectionContext) -> list[tuple[RawCandidate, int]]:
    """Candidates ranked by current score — used by later strategies & sorting."""
    scored: list[tuple[RawCandidate, int]] = []
    for candidate in ctx.candidates.values():
        evidence = _scoring_evidence(ctx, candidate)
        score, _ = score_candidate(url=candidate.url, evidence=evidence)
        scored.append((candidate, score))
    scored.sort(
        key=lambda pair: (
            -pair[1],
            ORIGIN_COSTS.get(pair[0].origin, 99),
            len(pair[0].url),
            pair[0].url,
        )
    )
    return scored


def _scoring_evidence(ctx: DetectionContext, candidate: RawCandidate) -> dict[str, Any]:
    evidence = dict(candidate.evidence)
    evidence.setdefault("domain", ctx.domain)
    if _normalize(candidate.url) in ctx.sitemap_urls:
        evidence.setdefault("in_sitemap", True)
    return evidence


class AtsPatternStrategy:
    """#1 — fetch the homepage once, harvest every anchor, sniff for ATS boards,
    plus up to 4 company-slug guesses per supported ATS pattern."""

    name = "ats_pattern"
    cost = 2

    def run(self, ctx: DetectionContext) -> list[RawCandidate]:
        result = self._fetch_homepage(ctx)
        if result is not None:
            for href, text in extract.links_from_html(result.html, result.final_url):
                self._sniff_anchor(ctx, href, text)
        self._slash_guesses(ctx)
        return list(ctx.candidates.values())

    def _fetch_homepage(self, ctx: DetectionContext) -> Any | None:
        ctx.spend(1)
        # Retry with www fallback on 403 or connection error
        urls_to_try = [ctx.root_url]
        # Add www version if root is bare
        if not ctx.root_url.startswith("https://www."):
            www_url = ctx.root_url.replace("https://", "https://www.")
            if www_url != ctx.root_url:
                urls_to_try.append(www_url)
        # Also try bare if root is www
        if ctx.root_url.startswith("https://www."):
            bare_url = ctx.root_url.replace("https://www.", "https://")
            if bare_url != ctx.root_url:
                urls_to_try.append(bare_url)
        for url in urls_to_try:
            try:
                result = fetch(url, mode=FetchMode.HTTP)
                if not (200 <= result.status_code < 300):
                    ctx.homepage_error = f"{url} returned {result.status_code}"
                    ctx.notes.append(
                        f"ats_pattern: homepage {url} unreachable: returned {result.status_code}"
                    )
                    continue
                ctx.homepage = result
                return result
            except FetchBudgetExceeded:
                raise
            except ThrottleUnavailable:
                raise
            except (FetchDomainBlocked, FetchError) as exc:
                ctx.homepage_error = str(exc)
                ctx.notes.append(f"ats_pattern: homepage {url} unreachable: {exc}")
                continue
            except Exception as exc:
                ctx.homepage_error = str(exc)
                ctx.notes.append(f"ats_pattern: homepage {url} error: {exc}")
                continue
        return None

    def _sniff_anchor(self, ctx: DetectionContext, href: str, text: str) -> None:
        if not href.lower().startswith(("http://", "https://")):
            return
        try:
            source_type, identifier = sniff_source_type_from_url(href)
        except Exception:
            ctx.notes.append(f"ats_pattern: skipped anchor {href}")
            return
        if source_type in _ALL_ATS_TYPES:
            candidate = _candidate_for_url(
                href,
                origin="ats_pattern",
                evidence={
                    "ats_source": source_type.value,
                    "ats_identifier": identifier,
                },
                via=text[:80] or "homepage anchor",
            )
            if candidate:
                ctx.add(candidate)

    def _guess_slugs(self, ctx: DetectionContext) -> list[str]:
        """Candidate board slugs, best-first: the domain label ("stripe" from
        stripe.com) outranks the internal Company.slug, which may be unrelated
        to the company's real ATS handle. Deduped, order-stable."""
        slugs: list[str] = []
        domain_label = extract.registrable_domain(ctx.domain).split(".", 1)[0]
        for s in (domain_label, getattr(ctx.company, "slug", "") or ""):
            if s and s not in slugs:
                slugs.append(s)
        return slugs

    def _slash_guesses(self, ctx: DetectionContext) -> None:
        spent = 0
        for slug in self._guess_slugs(ctx):
            for _source_type, build in ATS_GUESS_PATTERNS.items():
                if spent >= MAX_ATS_GUESSES:
                    return  # §6.3 #1: max 4 slug guesses total
                spent += 1
                url = build(slug)
                if not self._probe_guess(ctx, url, slug):
                    continue
                try:
                    sniffed, identifier = sniff_source_type_from_url(url)
                except Exception:
                    continue
                candidate = _candidate_for_url(
                    url,
                    origin="ats_pattern",
                    evidence={"ats_source": sniffed.value, "ats_identifier": identifier},
                    via=f"{self.name} slug guess",
                )
                if candidate:
                    ctx.add(candidate)

    def _probe_guess(self, ctx: DetectionContext, url: str, slug: str) -> bool:
        """One GET per guess (the check itself), requiring corroboration: ATS
        hosts serve 200 for *any* slug (Ashby wildcard, Greenhouse demo boards),
        so a bare status proves nothing — the org handle must appear in the
        rendered title/text, or the page must declare JobPosting JSON-LD."""
        ctx.spend(1)
        try:
            result = fetch(url, mode=FetchMode.HTTP)
        except FetchBudgetExceeded:
            raise
        except Exception as exc:
            ctx.notes.append(f"ats_pattern: guess {url}: {exc}")
            return False
        if result.status_code < 200 or result.status_code >= 300:
            return False
        title = extract.title_from_html(result.html)
        haystack = f"{title} {extract.visible_text(result.html)[:2000]}".lower()
        if slug.lower() in haystack or extract.page_has_jobposting(result.html):
            return True
        ctx.notes.append(f"ats_pattern: guess {url}: 200 but no trace of {slug!r}; ignored")
        return False


class NavLinkStrategy:
    """#2 — FREE: reuses the homepage response from strategy 1 (never refetches)."""

    name = "nav_link"
    cost = 1

    def run(self, ctx: DetectionContext) -> list[RawCandidate]:
        homepage = ctx.homepage
        if homepage is None:
            ctx.notes.append("nav_link: no homepage response to scan")
            return []
        base = homepage.final_url or ctx.root_url
        self._region(ctx, homepage.html, base, "header", "header_link", "nav_header")
        self._region(ctx, homepage.html, base, "footer", "footer_link", "nav_footer")
        return list(ctx.candidates.values())

    def _region(
        self,
        ctx: DetectionContext,
        html: str,
        base: str,
        region: str,
        origin: str,
        evidence_flag: str,
    ) -> None:
        for href, text in extract.region_links_from_html(html, base, region):
            hit = extract.path_has_career_keyword(href) or extract.text_has_career_keyword(text)
            if not hit:
                continue
            candidate = _candidate_for_url(
                href,
                origin=origin,
                evidence={evidence_flag: True},
                via=f"{region} link: {text[:60]}",
            )
            if candidate:
                ctx.add(candidate)


class RobotsStrategy:
    """#3 — robots.txt Allow/Disallow career paths + Sitemap: capture."""

    name = "robots"
    cost = 2

    def run(self, ctx: DetectionContext) -> list[RawCandidate]:
        block = self._rules(ctx)
        if block is None:
            return list(ctx.candidates.values())
        for rule in [*block.allow, *block.disallow]:
            if not extract.path_has_career_keyword(rule.path):
                continue
            url = _normalize(urljoin(ctx.root_url, rule.path))
            candidate = _candidate_for_url(
                url,
                origin="robots_txt",
                evidence=(
                    {"robots_disallowed": True}
                    if not self._in_allow(rule.path, block.allow)
                    else {}
                ),
                via=f"robots {rule.path}",
            )
            if candidate:
                ctx.add(candidate)
        for sitemap in robots_mod.fetch_for_sitemaps(ctx.root_url):
            if sitemap not in ctx.robots_sitemaps:
                ctx.robots_sitemaps.append(sitemap)
        return list(ctx.candidates.values())

    def _rules(self, ctx: DetectionContext) -> Any | None:
        ctx.spend(1)
        try:
            return robots_mod.parse(ctx.root_url)
        except FetchBudgetExceeded:
            raise
        except Exception as exc:
            ctx.notes.append(f"robots: parse failed: {exc}")
            return None

    @staticmethod
    def _in_allow(path: str, allow: list[Any]) -> bool:
        return any(rule.path == path for rule in allow)


class SitemapStrategy:
    """#4 — consume robots sitemaps (or defaults), one index level deep, <=3 docs."""

    name = "sitemap"
    cost = 3

    def run(self, ctx: DetectionContext) -> list[RawCandidate]:
        queue = list(ctx.robots_sitemaps) or [
            _normalize(urljoin(ctx.root_url, "/sitemap.xml")),
            _normalize(urljoin(ctx.root_url, "/sitemap_index.xml")),
        ]
        fetched = 0
        for doc_url in queue:
            if fetched >= SITEMAP_MAX_DOCS:
                break
            fetched += 1
            doc_url = _normalize(doc_url)
            body = self._fetch(ctx, doc_url)
            if body is None:
                continue
            is_index, locs = extract.parse_sitemap(body)
            if is_index:
                for child in locs:
                    if fetched >= SITEMAP_MAX_DOCS:
                        break
                    fetched += 1
                    child_body = self._fetch(ctx, child)
                    if child_body is None:
                        continue
                    self._consume(ctx, child, child_body)
            else:
                # A plain (non-index) robots sitemap is already leaf content.
                self._consume(ctx, doc_url, body)
        return list(ctx.candidates.values())

    def _fetch(self, ctx: DetectionContext, url: str) -> str | None:
        ctx.spend(1)
        try:
            result = fetch(url, mode=FetchMode.HTTP)
        except FetchBudgetExceeded:
            raise
        except Exception as exc:
            ctx.notes.append(f"sitemap: {url}: {exc}")
            return None
        return result.html

    def _consume(self, ctx: DetectionContext, doc_url: str, body: str) -> None:
        _, urls = extract.parse_sitemap(body)
        stored = 0
        for url in urls[:SITEMAP_MAX_URLS_PER_DOC]:
            if stored >= SITEMAP_MAX_STORED_URLS:
                break
            normalized = _normalize(url)
            ctx.sitemap_urls.add(normalized)
            stored += 1
            if not extract.path_has_career_keyword(url):
                continue
            candidate = _candidate_for_url(
                normalized,
                origin="sitemap",
                evidence={},
                via=f"sitemap {doc_url}",
            )
            if candidate:
                ctx.add(candidate)


class CommonPathStrategy:
    """#5 — probe each DETECTION_COMMON_PATHS path with a ranged HEAD probe."""

    name = "common_path"
    cost = 3

    def run(self, ctx: DetectionContext) -> list[RawCandidate]:
        for path in settings.DETECTION_COMMON_PATHS:
            url = _normalize(urljoin(ctx.root_url, path))
            if url in ctx.candidates:
                continue
            ctx.spend(1)
            try:
                ok, _status = head_ok(url)
            except FetchBudgetExceeded:
                raise
            except Exception as exc:
                ctx.notes.append(f"common_path: {url}: {exc}")
                continue
            if not ok:
                continue
            candidate = _candidate_for_url(
                url, origin="common_path", evidence={}, via="common path probe"
            )
            if candidate:
                ctx.add(candidate)
        return list(ctx.candidates.values())


class SubdomainStrategy:
    """#6 — probe <career-prefix>.<registrable domain>/ for each guess prefix."""

    name = "subdomain_guess"
    cost = 3

    def run(self, ctx: DetectionContext) -> list[RawCandidate]:
        base = extract.registrable_domain(ctx.domain)
        for prefix in settings.DETECTION_COMMON_SUBDOMAINS:
            url = _normalize(f"https://{prefix}.{base}/")
            if url in ctx.candidates:
                continue
            ctx.spend(1)
            try:
                # Use GET instead of HEAD because some servers don't support HEAD
                result = fetch(url, mode=FetchMode.HTTP)
                if result.status_code < 200 or result.status_code >= 300:
                    continue
            except FetchBudgetExceeded:
                raise
            except Exception as exc:
                ctx.notes.append(f"subdomain_guess: {url}: {exc}")
                continue
            candidate = _candidate_for_url(
                url, origin="subdomain_guess", evidence={}, via="subdomain guess"
            )
            if candidate:
                ctx.add(candidate)
        return list(ctx.candidates.values())


class JsonLdStrategy:
    """#7 — probe the top 5 provisional candidates for JobPosting JSON-LD."""

    name = "json_ld"
    cost = 3

    def run(self, ctx: DetectionContext) -> list[RawCandidate]:
        for candidate, _score in _provisional(ctx)[:5]:
            evidence = dict(candidate.evidence)
            ctx.spend(1)
            try:
                result = fetch(candidate.url, mode=FetchMode.HTTP)
            except FetchBudgetExceeded:
                raise
            except Exception as exc:
                ctx.notes.append(f"json_ld: {candidate.url}: {exc}")
                continue
            if extract.page_has_jobposting(result.html):
                evidence["json_ld_jobposting"] = True
            evidence.setdefault("http_status", result.status_code)
            if result.status_code < 400:
                evidence.setdefault("http_200", True)
            ctx.add(
                RawCandidate(
                    url=candidate.url,
                    origin=candidate.origin,
                    evidence=evidence,
                    discovered_via=candidate.discovered_via,
                )
            )
        return list(ctx.candidates.values())


class VerifyStrategy:
    """#8 — final enrichment of the leading candidates via escalation fetch.

    On an ATS short-circuit this only runs against the winning ATS candidate.
    """

    name = "verify"
    cost = 3

    def run(self, ctx: DetectionContext) -> list[RawCandidate]:
        provisional = _provisional(ctx)
        if ctx.ats_short_circuit:
            targets = [
                pair
                for pair in provisional
                if pair[0].origin == "ats_pattern"
                and pair[1] >= settings.DETECTION_MIN_CANDIDATE_SCORE
            ][:1]
        else:
            targets = provisional[: settings.DETECTION_MAX_CANDIDATES]
        rejected: list[str] = []
        for candidate, _score in targets:
            if not self._verify_one(ctx, candidate):
                rejected.append(candidate.url)
        for url in rejected:
            # §6.9 security rule: a hop that lands off-company (e.g. a careers
            # path 301-ing to LinkedIn) is dead — never scored, never persisted.
            ctx.candidates.pop(url, None)
        return list(ctx.candidates.values())

    def _verify_one(self, ctx: DetectionContext, candidate: RawCandidate) -> bool:
        """Enrich ``candidate`` in place; return False when the final URL must be
        rejected (redirected to a blocked or foreign host)."""
        evidence = dict(candidate.evidence)
        ctx.spend(1)
        try:
            result = fetch_with_escalation(candidate.url)
        except FetchBudgetExceeded:
            raise
        except Exception as exc:
            ctx.notes.append(f"verify: {candidate.url}: {exc}")
            return True
        final_url = result.final_url or candidate.url
        final_host = extract.host_of(final_url)
        request_host = extract.host_of(candidate.url)
        # Dedupe: if final_url differs, collapse candidates by final_url
        if final_url != candidate.url:
            # We will later dedupe in _rank? We'll add a note.
            # For now, store redirect info.
            evidence["redirected_to"] = final_url
        if final_host and request_host and final_host != request_host:
            # If the request came from an ATS, allow redirect to the company's own domain.
            if extract.is_ats_host(request_host):
                company_registrable = extract.registrable_domain(ctx.domain)
                trusted = not _is_blocked(final_host) and extract.is_own_host(
                    final_host, company_registrable
                )
            else:
                registrable = extract.registrable_domain(request_host)
                trusted = not _is_blocked(final_host) and (
                    extract.is_own_host(final_host, registrable) or extract.is_ats_host(final_host)
                )
            if not trusted:
                ctx.notes.append(
                    f"verify: {candidate.url} redirected to untrusted {final_host}; rejected"
                )
                return False
        html = result.html
        status = result.status_code
        links = extract.links_from_html(html, result.final_url)
        job_links = extract.count_job_links(links)
        postings = extract.job_postings_from_json_ld(html)
        title = extract.title_from_html(html)

        evidence["http_status"] = status
        if 200 <= status < 300 or status == 206:
            evidence["http_200"] = True
        if job_links >= 3:
            evidence["multiple_job_links"] = True
        if postings:
            evidence["json_ld_jobposting"] = True
        trailing = extract.trailing_component(candidate.url)
        if len(postings) == 1 and (trailing.isdigit() or _looks_uuid(trailing)):
            evidence["single_posting"] = True
        if extract.text_has_career_keyword(title):
            evidence["title_keyword"] = True
        if extract.has_no_openings_text(html):
            evidence["explicit_no_openings"] = True
        evidence["sample_job_titles"] = extract.sample_titles_from_html(
            html, links, settings.DETECTION_SAMPLE_TITLE_LIMIT
        )
        ctx.add(
            RawCandidate(
                url=candidate.url,
                origin=candidate.origin,
                evidence=evidence,
                discovered_via=candidate.discovered_via,
            )
        )
        return True


def _looks_uuid(s: str) -> bool:
    return bool(len(s) == 32 and all(c in "0123456789abcdefABCDEF" for c in s))


def get_strategies() -> list[Any]:
    return [
        AtsPatternStrategy(),
        NavLinkStrategy(),
        RobotsStrategy(),
        SitemapStrategy(),
        CommonPathStrategy(),
        SubdomainStrategy(),
        JsonLdStrategy(),
        VerifyStrategy(),
    ]
