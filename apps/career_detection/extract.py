"""Pure extraction helpers for career detection — no network, no Scrapling, no IO.

Everything here operates on raw HTML strings and URLs so fixtures and unit tests
can exercise every branch without the fetch layer. The single source of truth
for career/noise keywords lives here (PROMPT_3_SECTION_6 §6.3).

Matching rule (documented, tested):
  PATH matching — split the path on ``/``; each segment is split on ``-`` and ``_``
  into "components". A keyword matches when a component equals the keyword or
  starts with it (``/company/careers/`` matches ``careers``; ``/carerra-tires/``
  does NOT match ``career`` because no component starts with ``career``).
  TEXT matching — the keyword must appear bounded by word characters: ``(?<![a-z0-9])kw(?![a-z0-9])``,
  so "We Are Hiring!" matches ``we-are-hiring``.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable
from html.parser import HTMLParser
from typing import Any
from urllib.parse import urljoin, urlparse

from django.conf import settings

CAREER_KEYWORDS: tuple[str, ...] = (
    "career",
    "careers",
    "job",
    "jobs",
    "vacancy",
    "vacancies",
    "opening",
    "openings",
    "hiring",
    "we-are-hiring",
    "work-with-us",
    "join-us",
    "join-our-team",
    "opportunities",
    "recruitment",
    "employment",
)

NOISE_TOKENS: tuple[str, ...] = (
    "blog",
    "news",
    "press",
    "investor",
    "privacy",
    "terms",
    "cookie",
    "login",
    "signin",
    "signup",
    "cart",
    "checkout",
    "support",
    "help",
    "case-study",
    "webinar",
    "event",
    "podcast",
    "glossary",
    "pricing",
    "template",
    "templates",
    "resources",
    "library",
    "examples",
)

# Known supported ATS registrable hosts (suffix match, see §6.4 ats_host/foreign_host).
ATS_SUFFIXES: tuple[str, ...] = (
    "greenhouse.io",
    "lever.co",
    "ashbyhq.com",
    "smartrecruiters.com",
)

WORKDAY_SUFFIX = "myworkdayjobs.com"

_UUID_RE = re.compile(r"(?i)^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
_JSONLD_SCRIPT_RE = re.compile(
    r"<script[^>]*type=[\"']application/ld\+json[\"'][^>]*>(.*?)</script>",
    re.I | re.S,
)


# ---------------------------------------------------------------------------
# URL / host helpers
# ---------------------------------------------------------------------------
def host_of(url: str) -> str:
    """Lowercased hostname of a URL (https:// prefixed when scheme-less)."""
    if "://" not in (url or ""):
        url = f"https://{url}"
    return (urlparse(url).hostname or "").lower()


def path_of(url: str) -> str:
    return urlparse(url).path or "/"


def is_ats_host(host: str) -> bool:
    return any(host == suffix or host.endswith(f".{suffix}") for suffix in ATS_SUFFIXES)


def is_workday_host(host: str) -> bool:
    return host == WORKDAY_SUFFIX or host.endswith(f".{WORKDAY_SUFFIX}")


def is_career_subdomain_host(host: str) -> bool:
    """True when the host's leftmost label is a career subdomain prefix."""
    prefix = host.split(".", 1)[0]
    return prefix in settings.DETECTION_COMMON_SUBDOMAINS


def registrable_domain(host: str) -> str:
    """Strip www and the career subdomain prefixes we guess on, for cross-host checks.

    Best-effort (no PSL database): careers.acme.com -> acme.com, www.acme.com ->
    acme.com, acme.co.uk -> acme.co.uk. An IP or host with a single label is
    returned unchanged.
    """
    host = host.lower().strip(".")
    parts = host.split(".")
    prefixes = {"www", *settings.DETECTION_COMMON_SUBDOMAINS, "work", "hiring"}
    while len(parts) > 2 and parts[0] in prefixes:
        parts = parts[1:]
    return ".".join(parts)


def is_own_host(host: str, registrable: str) -> bool:
    """Host is the company's registrable domain or a subdomain of it."""
    return bool(registrable) and (host == registrable or host.endswith(f".{registrable}"))


# ---------------------------------------------------------------------------
# Keyword matching (see module docstring for the exact rule)
# ---------------------------------------------------------------------------
def _components(path_or_segment: str) -> list[str]:
    out: list[str] = []
    for segment in path_or_segment.split("/"):
        for part in segment.split("-"):
            for comp in part.split("_"):
                if comp:
                    out.append(comp.lower())
    return out


def _component_matches(components: Iterable[str], keywords: Iterable[str]) -> bool:
    for comp in components:
        for kw in keywords:
            if comp == kw or comp.startswith(kw):
                return True
    return False


def path_has_keyword(path: str, keywords: Iterable[str] = CAREER_KEYWORDS) -> bool:
    return _component_matches(_components(path), keywords)


def path_has_career_keyword(path: str) -> bool:
    return path_has_keyword(path, CAREER_KEYWORDS)


def path_has_noise_token(path: str) -> bool:
    return path_has_keyword(path, NOISE_TOKENS)


def text_has_keyword(text: str, keywords: Iterable[str] = CAREER_KEYWORDS) -> bool:
    """Word-bounded match on the lowercased text AND its hyphen-normalized form
    (``Join Us`` -> ``join-us``), so multi-word link text matches hyphenated
    keywords while ``carerra`` never matches ``career``."""
    lowered = (text or "").lower()
    if any(re.search(rf"(?<![a-z0-9]){re.escape(kw)}(?![a-z0-9])", lowered) for kw in keywords):
        return True
    normalized = re.sub(r"[\s_]+", "-", lowered)
    return any(
        re.search(rf"(?<![a-z0-9]){re.escape(kw)}(?![a-z0-9])", normalized) for kw in keywords
    )


def text_has_career_keyword(text: str) -> bool:
    return text_has_keyword(text, CAREER_KEYWORDS)


# ---------------------------------------------------------------------------
# JSON-LD (moved here from the old apps/scraping/scoring.py — §6.0)
# ---------------------------------------------------------------------------
def parsed_json_ld(html: str) -> list[dict[str, Any]]:
    """Every top-level dict/list declared in application/ld+json scripts."""
    out: list[dict[str, Any]] = []
    for match in _JSONLD_SCRIPT_RE.finditer(html or ""):
        raw = match.group(1)
        try:
            data = json.loads(raw)
        except (TypeError, ValueError):
            continue
        if isinstance(data, list):
            out.extend(item for item in data if isinstance(item, dict))
        elif isinstance(data, dict):
            out.append(data)
    return out


def _walk_jsonld(
    node: Any, target_types: set[str], _seen: set[int] | None = None
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    if _seen is None:
        _seen = set()
    if id(node) in _seen:
        return out
    _seen.add(id(node))
    if isinstance(node, list):
        for item in node:
            out.extend(_walk_jsonld(item, target_types, _seen))
        return out
    if not isinstance(node, dict):
        return out
    node_type = str(node.get("@type", "")).lower()
    if any(tt in node_type for tt in target_types):
        out.append(node)
    for value in node.values():
        out.extend(_walk_jsonld(value, target_types, _seen))
    return out


def job_postings_from_json_ld(html: str) -> list[dict[str, Any]]:
    """JobPosting nodes from parsed JSON-LD, nested/``@graph`` aware."""
    return _walk_jsonld(parsed_json_ld(html), {"jobposting"})


def has_itemlist_jobpostings(html: str) -> bool:
    """An ItemList/CollectionPage that also contains a JobPosting somewhere."""
    nodes = parsed_json_ld(html)
    container = _walk_jsonld(nodes, {"itemlist", "collectionpage"})
    if not container:
        return False
    return bool(_walk_jsonld(nodes, {"jobposting"}))


def page_has_jobposting(html: str) -> bool:
    return bool(job_postings_from_json_ld(html)) or has_itemlist_jobpostings(html)


# ---------------------------------------------------------------------------
# Anchor / link harvesting (pure — moved here per §6.0)
# ---------------------------------------------------------------------------
class _AnchorCollector(HTMLParser):
    """Collects ``(href, text)`` for every <a>, optionally only inside a tag set.

    ``target_tags=None`` collects every anchor on the page (used by
    ``links_from_html``); a tag set restricts to header/nav/footer regions.
    """

    def __init__(self, target_tags: set[str] | None) -> None:
        super().__init__(convert_charrefs=True)
        self.target_tags = target_tags
        self._stack: list[str] = []
        self._open_anchors: list[dict[str, Any]] = (
            []
        )  # {"inside": bool, "href": str, "parts": [..]}
        self.anchors: list[tuple[str, str]] = []

    def _inside_target(self) -> bool:
        if self.target_tags is None:
            return True
        return any(tag in self.target_tags for tag in self._stack)

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self._stack.append(tag)
        if tag != "a":
            return
        href = ""
        for name, value in attrs:
            if name.lower() == "href" and value:
                href = value
        self._open_anchors.append({"inside": self._inside_target(), "href": href, "parts": []})

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        # <a .../> has no text; nothing to record.
        self._stack.append(tag)

    def handle_endtag(self, tag: str) -> None:
        if tag == "a" and self._open_anchors:
            item = self._open_anchors.pop()
            if item["inside"]:
                self.anchors.append((item["href"], " ".join(item["parts"]).strip()))
        if self._stack and self._stack[-1] == tag:
            self._stack.pop()
        else:
            try:
                self._stack.reverse()
                self._stack.remove(tag)
                self._stack.reverse()
            except ValueError:
                pass

    def handle_data(self, data: str) -> None:
        if self._open_anchors:
            for item in self._open_anchors:
                item["parts"].append(data)


_REGION_TAGS: dict[str, set[str]] = {
    "header": {"header", "nav"},  # header includes nav per §6.3
    "nav": {"nav"},
    "footer": {"footer"},
}
_ALL_TAGS = {"header", "nav", "footer"}


def _region_tags(region: str) -> set[str]:
    return _REGION_TAGS.get(region, _ALL_TAGS)


def links_from_html(html: str, base_url: str) -> list[tuple[str, str]]:
    """All (absolute_href, anchor_text) pairs on a page, deduped by URL."""
    collector = _AnchorCollector(None)
    collector.feed(html or "")
    collector.close()
    seen: set[str] = set()
    out: list[tuple[str, str]] = []
    for href, text in collector.anchors:
        absolute = _absolute(base_url, href)
        if not absolute or absolute in seen:
            continue
        seen.add(absolute)
        out.append((absolute, text))
    return out


def region_links_from_html(html: str, base_url: str, region: str) -> list[tuple[str, str]]:
    """Links inside ``header`` (incl. ``nav``) / ``nav`` / ``footer``, deduped."""
    collector = _AnchorCollector(_region_tags(region))
    collector.feed(html or "")
    collector.close()
    seen: set[str] = set()
    out: list[tuple[str, str]] = []
    for href, text in collector.anchors:
        absolute = _absolute(base_url, href)
        if not absolute or absolute in seen:
            continue
        seen.add(absolute)
        out.append((absolute, text))
    return out


def _absolute(base_url: str, href: str) -> str | None:
    if not href:
        return None
    href = href.strip()
    if href.startswith(("#", "mailto:", "tel:", "javascript:", "data:")):
        return None
    try:
        return urljoin(base_url, href)
    except ValueError:
        return None


def title_from_html(html: str) -> str:
    m = re.search(r"<title[^>]*>(.*?)</title>", html or "", re.I | re.S)
    if m:
        title = re.sub(r"<[^>]+>", "", m.group(1)).strip()
        if title:
            return title
    m = re.search(
        r'<meta[^>]+property=[\'"]og:title[\'"][^>]*content=[\'"]([^\'"]+)[\'"]', html or "", re.I
    )
    if m:
        return m.group(1).strip()
    return ""


def visible_text(html: str) -> str:
    stripped = re.sub(r"<script.*?</script>|<style.*?</style>", " ", html or "", flags=re.I | re.S)
    stripped = re.sub(r"<[^>]+>", " ", stripped)
    return re.sub(r"\s+", " ", stripped).strip()


def has_no_openings_text(html: str) -> bool:
    text = visible_text(html).lower()
    patterns = (
        r"\bno\s+(?:current\s+)?open(?:ing|ings| positions| roles| role)?\b(?!.*(?:apply|see list))",
        r"\bno\s+(?:open\s+)?(?:positions|roles|vacancies)\b",
        r"\bnothing available\b",
        r"\bnot currently hiring\b",
        r"\bno\s+job\s+opportunities\b",
        r"\bno\s+(?:open\s+)?recruitments?\b",
    )
    return any(re.search(p, text) for p in patterns)


# ---------------------------------------------------------------------------
# Job-postin-g link + title heuristics (evidence for VerifyStrategy)
# ---------------------------------------------------------------------------
def _trailing_component(path: str) -> str:
    return path.rstrip("/").rsplit("/", 1)[-1] if path else ""


def trailing_component(url: str) -> str:
    """Final path segment of a URL (used to spot single-posting detail pages)."""
    return _trailing_component(urlparse(url).path)


def looks_like_job_posting(url: str, text: str = "") -> bool:
    u = url.split("#", 1)[0]
    parsed = urlparse(u)
    host = (parsed.hostname or "").lower()
    path = parsed.path

    if "/req0" in path:  # Workday posting path
        return True
    if host.endswith(".jobs.lever.co") or host == "jobs.lever.co":
        return "/o/" in path
    if host == "boards.greenhouse.io" or host == "job-boards.greenhouse.io":
        segments = [s for s in path.split("/") if s]
        return len(segments) >= 2 and (
            _trailing_component(path).isdigit() or _ends_with_digit(segments[-1])
        )
    if host == "jobs.ashbyhq.com":
        segments = [s for s in path.split("/") if s]
        return bool(segments) and (len(segments[-1]) >= 6 or segments[-1].isdigit())
    if host.endswith("smartrecruiters.com"):
        return "position" in path.lower() or (
            "career" in path.lower() and len(path.split("/")) >= 4
        )
    if host.endswith("myworkdayjobs.com"):
        return "job" in path.lower() or "req" in path.lower()

    trailing = _trailing_component(path)
    if trailing and (trailing.isdigit() or _UUID_RE.match(trailing) or _uuid_compact(trailing)):
        return True
    lowered = path.lower()
    if any(
        k in lowered for k in ("/job/", "/jobs/", "/position/", "/vacancy", "/opening", "/apply/")
    ):
        return True
    return bool(text) and text_has_keyword(
        text, ("apply", "position", "job", "requisition", "see details", "view role")
    )


def _ends_with_digit(segment: str) -> bool:
    return bool(re.search(r"(?i)(?:-\d+|_\d+)$", segment))


def _uuid_compact(s: str) -> bool:
    return len(s) == 32 and all(c in "0123456789abcdefABCDEF" for c in s)


def sample_titles_from_html(html: str, links: list[tuple[str, str]], limit: int) -> list[str]:
    """Prefer JSON-LD titles, then job-looking link texts; deduped and capped."""
    out: list[str] = []
    seen: set[str] = set()
    for posting in job_postings_from_json_ld(html):
        title = (posting.get("title") or "").strip()
        if title and title.lower() not in seen:
            seen.add(title.lower())
            out.append(title)
    for _, text in links:
        text = text.strip()
        if not text or len(text) > 60 or len(text) < 3:
            continue
        if any(w in NOISE_TOKENS for w in text.lower().split()):
            continue
        if text.lower() in seen:
            continue
        seen.add(text.lower())
        out.append(text)
        if len(out) >= limit:
            break
    return out[:limit]


def count_job_links(links: list[tuple[str, str]]) -> int:
    return sum(1 for href, text in links if looks_like_job_posting(href, text))


# ---------------------------------------------------------------------------
# Sitemap XML parsing (sitemaps added at: sitemap.xml / sitemap_index.xml)
# ---------------------------------------------------------------------------
def parse_sitemap(body: str) -> tuple[bool, list[str]]:
    """Return ``(is_index, locs)``. Index docs yield child sitemap URLs; urlset
    yields page URLs. Only http(s) locs are kept and deduped in document order."""
    if not body:
        return False, []
    body = body[: 5 * 1024 * 1024]
    is_index = "<sitemapindex" in body.lower()
    locs = [m.strip() for m in re.findall(r"<loc>\s*(.*?)\s*</loc>", body, re.I | re.S)]
    cleaned: list[str] = []
    seen: set[str] = set()
    for loc in locs:
        if loc.lower().startswith(("http://", "https://")) and loc not in seen:
            seen.add(loc)
            cleaned.append(loc)
    return is_index, cleaned
