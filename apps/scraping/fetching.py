"""THE ONLY FILE IN THE PROJECT THAT MAY ``import scrapling``.

Hard architectural rule (PROMPT 3 §1.7): every fetch in the system goes through
here. Scrapling is the single, swappable fetch layer; nothing else may import it.
Detection strategies, tasks and admin only ever see the ``FetchResult`` surface.

API signatures confirmed directly from ``Scrapling-main`` (v0.4.14):
- ``Fetcher.get(url, *, timeout, retries, retry_delay, impersonate, follow_redirects,
  max_redirects, verify, headers, stealthy_headers, ...)`` -> Response
- ``Response`` is a ``Selector`` subclass with ``.url`` (final), ``.status``,
  ``.reason``, ``.headers``, ``.body`` (bytes), ``.encoding``, ``.json()``, ``.css()``
- ``DynamicFetcher.fetch(url, *, headless, network_idle, load_dom, timeout_ms...,
  capture_xhr=regex, ...)`` / ``StealthyFetcher.fetch(...)``
- No HEAD support on ``Fetcher`` (``static.md``: "OPTIONS and HEAD methods are not
  supported") — ``head_ok`` uses a ranged GET instead. See PART 6.
"""

from __future__ import annotations

import hashlib
import json
import logging
from contextlib import AbstractContextManager
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlparse

from django.conf import settings

from core.utils import normalize_url

from . import robots as robots
from .exceptions import (
    FetchBlocked,
    FetchDomainBlocked,
    FetchError,
    FetchNotFound,
    FetchRobotsDisallowed,
    FetchServerError,
    FetchTimeout,
    FetchTooLarge,
)
from .throttle import acquire_slot

logger = logging.getLogger("study_tracker.scraping.fetching")

# Scrapling — the one and only place the library is imported.
from scrapling.fetchers import (  # noqa: E402
    DynamicFetcher,
    Fetcher,
    FetcherSession,
    StealthyFetcher,
)

_BLOCKED: frozenset[str] = frozenset()
try:
    from apps.companies.enums import BLOCKED_DOMAINS

    _BLOCKED = frozenset(BLOCKED_DOMAINS)
except Exception:  # pragma: no cover — defensive; companies is always installed
    _BLOCKED = frozenset()


# Adaptive-selector storage: learned element profiles survive site redesigns and
# restarts. Enabled lazily; a missing/unwritable dir degrades gracefully.
_ADAPTIVE_READY = False
try:
    _storage_dir = Path(str(settings.FETCH_ADAPTIVE_STORAGE_DIR))
    _storage_dir.mkdir(parents=True, exist_ok=True)
    _adaptive_db = str(_storage_dir / "adaptive.db")
    for _fetcher in (Fetcher, DynamicFetcher, StealthyFetcher):
        _fetcher.adaptive = True
        _fetcher.storage_args = {"storage_file": _adaptive_db}
    _ADAPTIVE_READY = True
except Exception as exc:  # pragma: no cover — local dev without /data
    logger.warning("Adaptive storage unavailable (%s); continuing without persistence", exc)


def _blocked_host(url_or_host: str) -> bool:
    if not url_or_host:
        return False
    host = (
        urlparse(url_or_host if "://" in url_or_host else f"https://{url_or_host}").hostname or ""
    )
    host = host.lower()
    return any(host == b or host.endswith(f".{b}") for b in _BLOCKED)


def _domain_of(url: str) -> str:
    return (urlparse(url).hostname or "").lower()


def _ensure_scheme(url: str) -> str:
    """https:// prefix for scheme-less input (normalize_url keeps them as-is)."""
    return url if "://" in url else f"https://{url}"


class FetchMode(StrEnum):
    HTTP = "http"
    DYNAMIC = "dynamic"
    STEALTHY = "stealthy"


@dataclass(frozen=True)
class FetchResult:
    url: str  # requested (normalized)
    final_url: str  # after redirects
    status_code: int
    html: str
    selector: Any  # Scrapling Selector — the ONLY leaked library object
    fetcher_used: FetchMode
    elapsed_ms: int
    from_cache: bool
    escalation_reason: str
    not_modified: bool = False
    xhr_payloads: list[dict[str, Any]] = field(default_factory=list)

    def _abs(self, href: str) -> str | None:
        if not href:
            return None
        href = href.strip()
        if href.startswith(("#", "mailto:", "tel:", "javascript:", "data:")):
            return None
        try:
            return urljoin(self.final_url, href)
        except ValueError:
            return None

    def links(self) -> list[tuple[str, str]]:
        """All ``(absolute_href, anchor_text)`` pairs on the page, deduped by href."""
        seen: set[str] = set()
        out: list[tuple[str, str]] = []
        for a in self.selector.css("a"):
            href = a.attrib.get("href")
            absolute = self._abs(str(href)) if href else None
            if not absolute:
                continue
            key = normalize_url(absolute)
            if key in seen:
                continue
            seen.add(key)
            text = a.get_all_text(strip=True)
            out.append((absolute, str(text)))
        return out

    def title(self) -> str:
        t = self.selector.css("title::text").get()
        if t:
            return str(t).strip()
        og = self.selector.css('meta[property="og:title"]::attr(content)').get()
        return str(og).strip() if og else ""

    def text(self) -> str:
        return str(self.selector.get_all_text(strip=True))

    def json_ld(self) -> list[dict[str, Any]]:
        """Parsed JSON-LD blocks; silently skips malformed entries."""
        out: list[dict[str, Any]] = []
        for script in self.selector.css('script[type="application/ld+json"]'):
            raw = script.get_all_text(ignore_tags=[])
            try:
                data = json.loads(str(raw))
            except (TypeError, ValueError):
                continue
            if isinstance(data, list):
                out.extend(item for item in data if isinstance(item, dict))
            elif isinstance(data, dict):
                out.append(data)
        return out

    def region_links(self, region: str) -> list[tuple[str, str]]:
        """Links inside ``header``/``nav``/``footer``. Header includes nav (scores higher)."""
        selector = {
            "header": "header a, nav a",
            "nav": "nav a",
            "footer": "footer a",
        }.get(region, " a")
        if region not in selector:  # pragma: no cover
            selector = " a"
        seen: set[str] = set()
        out: list[tuple[str, str]] = []
        for a in self.selector.css(selector):
            href = a.attrib.get("href")
            absolute = self._abs(str(href)) if href else None
            if not absolute:
                continue
            key = normalize_url(absolute)
            if key in seen:
                continue
            seen.add(key)
            out.append((absolute, str(a.get_all_text(strip=True))))
        return out


def _classify(exc: Exception, url: str) -> FetchError:
    """Turn any transport/Scrapling exception into our hierarchy."""
    if isinstance(exc, FetchError):
        return exc
    message = str(exc).lower()
    if "timed out" in message or "timeout" in message or "cancelled" in message:
        return FetchTimeout(f"Request timed out: {exc}", url=url)
    return FetchError(f"Fetch failed: {exc}", url=url)


def _user_agent() -> str:
    return str(settings.FETCH_USER_AGENT)


def _proxy_for() -> dict[str, str]:
    proxy = str(settings.FETCH_PROXY or "")
    if not proxy:
        return {}
    if not (proxy.startswith("http://") or proxy.startswith("https://")):
        proxy = f"http://{proxy}"
    return {"http": proxy, "https": proxy}


def _http_get(
    url: str, *, timeout: int | None, method: str = "GET", headers: dict[str, str] | None = None
) -> Any:
    """Plain Scrapling HTTP request returning the raw ``Response`` (library object)."""
    kwargs: dict[str, Any] = {
        "timeout": timeout or settings.FETCH_TIMEOUT_SECONDS,
        "retries": 1,
        "retry_delay": 0,
        "impersonate": "chrome",
        "follow_redirects": "safe",
        "max_redirects": settings.FETCH_MAX_REDIRECTS,
        "verify": True,
        "proxies": _proxy_for(),
    }
    request_headers: dict[str, str] = {"User-Agent": _user_agent()}
    if headers:
        request_headers.update(headers)
    if method == "GET":
        return Fetcher.get(url, headers=request_headers, **kwargs)
    if method == "HEAD":
        raise FetchError("Scrapling Fetcher does not implement HEAD", url=url)
    raise FetchError(f"Unsupported method {method!r}", url=url)


def _dynamic_get(
    url: str, *, timeout: int | None, network_idle: bool = True, xhr_pattern: str | None = None
) -> Any:
    kwargs: dict[str, Any] = {
        "headless": True,
        "load_dom": True,
        "network_idle": network_idle,
        "timeout": (timeout or settings.FETCH_TIMEOUT_SECONDS) * 1000,
        "extra_headers": {"User-Agent": _user_agent()},
    }
    if xhr_pattern:
        kwargs["capture_xhr"] = xhr_pattern
    return DynamicFetcher.fetch(url, **kwargs)


def _stealth_get(url: str, *, timeout: int | None) -> Any:
    return StealthyFetcher.fetch(
        url,
        headless=True,
        load_dom=True,
        timeout=(timeout or settings.FETCH_TIMEOUT_SECONDS) * 1000,
        extra_headers={"User-Agent": _user_agent()},
    )


def _to_fetch_result(url: str, response: Any, mode: FetchMode, elapsed_ms: int) -> FetchResult:
    body = bytes(getattr(response, "body", b""))
    if len(body) > settings.FETCH_MAX_RESPONSE_BYTES:
        raise FetchTooLarge(
            f"Response body {len(body)} bytes exceeds limit {settings.FETCH_MAX_RESPONSE_BYTES}",
            url=url,
        )
    encoding = getattr(response, "encoding", None) or "utf-8"
    return FetchResult(
        url=url,
        final_url=str(getattr(response, "url", url)),
        status_code=int(getattr(response, "status", 0)),
        html=body.decode(encoding, errors="replace"),
        selector=response,
        fetcher_used=mode,
        elapsed_ms=elapsed_ms,
        from_cache=False,
        escalation_reason="",
    )


def fetch(
    url: str,
    *,
    mode: FetchMode = FetchMode.HTTP,
    timeout: int | None = None,
    company: Any = None,
    obey_robots: bool | None = None,
    capture_xhr: bool = False,
    xhr_pattern: str | None = None,
) -> FetchResult:
    """Fetch one URL through the Scrapling layer.

    Order of operations (all mandatory): normalize -> blocked-domain reject ->
    robots check -> throttle slot -> dispatch -> size cap -> blocked re-check
    (redirect target) -> status mapping. Every Scrapling exception is wrapped.
    """
    from django.utils import timezone

    from .models import SourceFetchState

    url = str(normalize_url(_ensure_scheme(url)))
    if _blocked_host(url):
        raise FetchDomainBlocked(f"Domain for {url} is blocked", url=url)

    if obey_robots is None:
        obey_robots = settings.FETCH_ROBOTS_OBEY
    if obey_robots and not robots.is_allowed(url):
        raise FetchRobotsDisallowed(f"robots.txt disallows {url}", url=url)

    domain = _domain_of(url)
    acquire_slot(
        domain,
        rate_per_minute=settings.FETCH_PER_DOMAIN_RATE,
        jitter_ms=settings.FETCH_PER_DOMAIN_JITTER_MS,
    )

    if mode is FetchMode.DYNAMIC and not settings.FETCH_ALLOW_DYNAMIC:
        raise FetchError("Dynamic fetching is disabled (FETCH_ALLOW_DYNAMIC=False)", url=url)
    if mode is FetchMode.STEALTHY and not settings.FETCH_ALLOW_STEALTHY:
        raise FetchError("Stealthy fetching is disabled (FETCH_ALLOW_STEALTHY=False)", url=url)

    # Conditional GET state — only for plain HTTP fetches
    conditional_enabled = getattr(settings, "SCRAPE_CONDITIONAL_GET_ENABLED", True)
    state = None
    conditional_headers = {}
    if mode == FetchMode.HTTP and conditional_enabled:
        url_hash = hashlib.sha256(url.encode()).hexdigest()
        state = SourceFetchState.objects.filter(url_hash=url_hash).first()
        if state:
            if state.etag:
                conditional_headers["If-None-Match"] = state.etag
            if state.last_modified:
                conditional_headers["If-Modified-Since"] = state.last_modified

    import time

    started = time.perf_counter()
    try:
        if mode is FetchMode.HTTP:
            # Pass conditional headers if any
            headers = conditional_headers if conditional_headers else None
            response = _http_get(url, timeout=timeout, headers=headers)
        elif mode is FetchMode.DYNAMIC:
            response = _dynamic_get(
                url, timeout=timeout, xhr_pattern=xhr_pattern if capture_xhr else None
            )
        else:
            response = _stealth_get(url, timeout=timeout)
    except Exception as exc:
        raise _classify(exc, url) from exc
    elapsed_ms = int((time.perf_counter() - started) * 1000)

    if _blocked_host(getattr(response, "url", url)):
        raise FetchDomainBlocked(
            f"Redirect for {url} landed on a blocked domain", url=getattr(response, "url", url)
        )

    status = int(getattr(response, "status", 0))

    # Handle 304 Not Modified
    if status == 304:
        # Update hit count and last fetched time
        if state:
            state.hit_count += 1
            state.last_fetched_at = timezone.now()
            state.save(update_fields=["hit_count", "last_fetched_at"])
        # Return a result with not_modified=True, no html/selector
        return FetchResult(
            url=url,
            final_url=url,  # same as requested
            status_code=304,
            html="",
            selector=None,  # No selector for 304
            fetcher_used=mode,
            elapsed_ms=elapsed_ms,
            from_cache=False,
            escalation_reason="",
            not_modified=True,
            xhr_payloads=[],
        )

    # Map other error statuses
    if status in (404, 410):
        raise FetchNotFound(f"{url} returned {status}", url=url)
    if status in (403, 429):
        raise FetchBlocked(f"{url} was blocked ({status})", url=url)
    if status >= 500:
        raise FetchServerError(f"{url} returned {status}", url=url)

    # For 200 or other success, proceed normally
    result = _to_fetch_result(url, response, mode, elapsed_ms)

    # Body-hash comparison for unchanged detection (only for HTTP and conditional enabled)
    if mode == FetchMode.HTTP and conditional_enabled and status == 200:
        body_bytes = bytes(getattr(response, "body", b""))
        body_hash = hashlib.sha256(body_bytes).hexdigest()
        if state and state.body_hash and state.body_hash == body_hash:
            # Body unchanged: treat as not_modified
            # Update hit count and last fetched
            state.hit_count += 1
            state.last_fetched_at = timezone.now()
            state.save(update_fields=["hit_count", "last_fetched_at"])
            # Return a not_modified result but we have html and selector from the fetch.
            # We'll set not_modified=True and keep the html/selector but downstream should skip parsing.
            # We'll use dataclasses.replace to set not_modified.
            from dataclasses import replace

            result = replace(result, not_modified=True)
            # Note: we still have html and selector, but tasks will check not_modified and skip.
        else:
            # Changed: update state with new validators and body_hash
            etag = response.headers.get("ETag") or response.headers.get("Etag") or ""
            last_modified = response.headers.get("Last-Modified") or ""
            # Use update_or_create to create if not exists
            SourceFetchState.objects.update_or_create(
                url_hash=hashlib.sha256(url.encode()).hexdigest(),
                defaults={
                    "url": url,
                    "etag": etag,
                    "last_modified": last_modified,
                    "body_hash": body_hash,
                    "last_fetched_at": timezone.now(),
                    # hit_count and miss_count: if state existed, we increment miss_count; else defaults 0
                },
            )
            # If state existed, increment miss_count
            if state:
                state.miss_count += 1
                state.save(update_fields=["miss_count"])
            else:
                # New state, miss_count defaults to 0
                pass

    # For non-200 or when conditional disabled, still update state if we got a 200 and have no state? Actually we only do above.
    # Also handle capture_xhr
    if capture_xhr and mode is FetchMode.DYNAMIC:
        for xhr in getattr(response, "captured_xhr", []):
            try:
                payload = json.loads(bytes(getattr(xhr, "body", b"")).decode("utf-8", "replace"))
            except (TypeError, ValueError):
                payload = {}
            result.xhr_payloads.append(payload)
    return result


def head_ok(url: str, *, company: Any = None, timeout: int | None = None) -> tuple[bool, int]:
    """Cheap existence probe. HEAD isn't supported by Scrapling's Fetcher, so this
    sends a ranged GET (``Range: bytes=0-0``); a 2xx means the path exists.

    Raises :class:`FetchDomainBlocked` for a blocked host (that is never a probe —
    it is a stop signal). Any other ordinary HTTP failure returns ``(False, status)``.
    """
    url = str(normalize_url(_ensure_scheme(url)))
    if _blocked_host(url):
        raise FetchDomainBlocked(f"Domain for {url} is blocked", url=url)
    if settings.FETCH_ROBOTS_OBEY and not robots.is_allowed(url):
        return False, 0
    domain = _domain_of(url)
    try:
        acquire_slot(domain, rate_per_minute=settings.FETCH_PER_DOMAIN_RATE)
        response = _http_get(url, timeout=timeout, headers={"Range": "bytes=0-0"})
    except FetchError as exc:
        if isinstance(exc, FetchDomainBlocked):
            raise
        return False, 0
    except Exception:
        return False, 0
    status = int(getattr(response, "status", 0))
    if _blocked_host(getattr(response, "url", url)):
        raise FetchDomainBlocked(
            "Redirect landed on a blocked domain", url=getattr(response, "url", url)
        )
    return (200 <= status < 400), status


def _clear_validators_for_url(url: str) -> None:
    """Clear conditional GET state for a URL (blank validators)."""
    if not url:
        return
    from .models import SourceFetchState

    url_hash = hashlib.sha256(url.encode()).hexdigest()
    SourceFetchState.objects.filter(url_hash=url_hash).update(
        etag="", last_modified="", body_hash=""
    )


def fetch_with_escalation(
    url: str, *, company: Any = None, timeout: int | None = None
) -> FetchResult:
    """If a SPA is detected (few anchors / little text / bare root) ``HTTP`` escalates
    to a real browser exactly once. When ``FETCH_ALLOW_DYNAMIC`` is false the HTTP
    result is returned unchanged (the SPA trigger is recorded on the result either
    way).
    """
    from dataclasses import replace

    result = fetch(url, mode=FetchMode.HTTP, timeout=timeout, company=company)

    links = result.links()
    text = result.text()
    root_marker = any(
        marker in result.html for marker in ('<div id="root">', '<div id="app">', "<app-root")
    )
    reasons: list[str] = []
    if len(links) < 5:
        reasons.append(f"only {len(links)} anchors")
    if len(text) < 500:
        reasons.append(f"visible text {len(text)} chars")
    if root_marker and not links:
        reasons.append("SPA root marker with no anchors")

    if not settings.FETCH_ALLOW_DYNAMIC:
        # Browsers off: keep the HTTP copy but record why it might be JS-rendered.
        return replace(result, escalation_reason="; ".join(reasons))

    # Clear stored validators before browser escalation - browser body hashes must never overwrite HTTP ones.
    _clear_validators_for_url(url)

    try:
        dynamic = fetch(url, mode=FetchMode.DYNAMIC, timeout=timeout, company=company)
    except FetchError:
        # A page that wants JS but can't render is still worth keeping the HTTP copy.
        return result

    reason = "; ".join(reasons)
    return FetchResult(
        url=url,
        final_url=dynamic.final_url,
        status_code=dynamic.status_code,
        html=dynamic.html,
        selector=dynamic.selector,
        fetcher_used=FetchMode.DYNAMIC,
        elapsed_ms=result.elapsed_ms + dynamic.elapsed_ms,
        from_cache=False,
        escalation_reason=reason,
        xhr_payloads=dynamic.xhr_payloads,
    )


def session_for(domain: str) -> AbstractContextManager[Any]:
    """A reusable connection pool for one domain within a single detection run.

    One pool per run, not per request — callers use it as ``with session_for(d) as s``.
    """
    return FetcherSession(
        impersonate="chrome",
        timeout=settings.FETCH_TIMEOUT_SECONDS,
        retries=1,
        retry_delay=0,
        follow_redirects="safe",
        max_redirects=settings.FETCH_MAX_REDIRECTS,
        headers={"User-Agent": _user_agent()},
    )


def fetch_robots_raw(url: str, *, user_agent: str | None = None) -> tuple[int, str]:
    """Direct robots.txt fetch for ``robots.py`` — no robots re-entry, no redirect traps."""
    if _blocked_host(url):
        return 0, ""
    domain = _domain_of(url)
    acquire_slot(
        domain, rate_per_minute=settings.FETCH_PER_DOMAIN_RATE, jitter_ms=(0, 0)
    )  # robots reads don't jitter
    try:
        headers: dict[str, str] = {"User-Agent": user_agent or _user_agent()}
        response = _http_get(url, timeout=None, headers=headers)
    except Exception:
        return 0, ""
    status = int(getattr(response, "status", 0))
    if status != 200:
        return status, ""
    encoding = getattr(response, "encoding", None) or "utf-8"
    return status, bytes(getattr(response, "body", b"")).decode(encoding, errors="replace")


__all__ = [
    "FetchBlocked",
    "FetchDomainBlocked",
    "FetchError",
    "FetchMode",
    "FetchNotFound",
    "FetchResult",
    "FetchRobotsDisallowed",
    "FetchServerError",
    "FetchTimeout",
    "FetchTooLarge",
    "fetch",
    "fetch_robots_raw",
    "fetch_with_escalation",
    "head_ok",
    "session_for",
]
