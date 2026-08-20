"""Small, dependency-free helpers reused across the whole project."""

import hashlib
import re
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

from django.http import HttpRequest

TRACKING_PARAMS = {
    "utm_source",
    "utm_medium",
    "utm_campaign",
    "utm_term",
    "utm_content",
    "gclid",
    "fbclid",
}
DEFAULT_PORTS = {"http": "80", "https": "443"}
_SCHEME_RE = re.compile(r"^[a-zA-Z][a-zA-Z0-9+.-]*$")


def normalize_url(url: str) -> str:
    """Normalize a URL for canonical comparison (career-dedupe in STEP 5).

    - lowercase scheme + host; strip default ports
    - strip trailing slash from the path
    - drop fragments and common UTM/tracking params
    - sort remaining query params deterministically
    """
    if not url or not isinstance(url, str):
        return url
    url = url.strip()
    if not url:
        return url

    parsed = urlparse(url)
    scheme = parsed.scheme.lower()
    host = parsed.hostname or ""
    host = host.lower().strip(".")
    if host.endswith("."):
        host = host.rstrip(".")

    port = parsed.port
    if port is not None and str(port) == DEFAULT_PORTS.get(scheme):
        port = None

    path = parsed.path
    if path.endswith("/"):
        path = path.rstrip("/")
    path = re.sub(r"/{2,}", "/", path)

    query = [
        (key, value)
        for key, value in parse_qsl(parsed.query, keep_blank_values=True)
        if key.lower() not in TRACKING_PARAMS
    ]
    query.sort(key=lambda pair: (pair[0], pair[1]))

    return urlunparse((scheme, _netloc(host, port), path, "", urlencode(query, doseq=True), ""))


def _netloc(host: str, port: int | None) -> str:
    if port is None:
        return host
    return f"{host}:{port}"


def client_ip(request: HttpRequest) -> str:
    """Best-effort client IP. Trusts X-Forwarded-For's first hop, then REMOTE_ADDR."""
    forwarded = str(request.META.get("HTTP_X_FORWARDED_FOR", ""))
    if forwarded:
        first_hop = forwarded.split(",", 1)[0].strip()
        if first_hop:
            return first_hop
    return str(request.META.get("REMOTE_ADDR", ""))


def sha256_of(*parts: str) -> str:
    """Stable hex digest of one or more parts joined with ``\\x1f``.

    Used for job-content fingerprints: ``sha256_of(title, location, description)``.
    """
    return hashlib.sha256("\x1f".join(parts).encode("utf-8")).hexdigest()
