"""Deterministic candidate rubric — PROMPT_3_SECTION_6 §6.4.

Pure function: no network, no DB, no settings mutation, no clock. The caller
(``services.run_detection``) attaches evidence through the strategy layer and then
asks this module to grade it. The returned trail is the admin-visible explanation.
"""

from __future__ import annotations

from typing import Any

from apps.companies.enums import is_blocked_domain

from .extract import (
    is_ats_host,
    is_career_subdomain_host,
    is_own_host,
    is_workday_host,
    path_has_career_keyword,
    path_has_noise_token,
    path_of,
)


def _host(url: str) -> str:
    if "://" not in (url or ""):
        url = f"https://{url}"
    from urllib.parse import urlparse

    return (urlparse(url).hostname or "").lower()


def _scheme(url: str) -> str:
    from urllib.parse import urlparse

    return (urlparse(url).scheme or "").lower()


def _path_segments(path: str) -> list[str]:
    """Split on ``/`` keeping empties — the spec counts a leading empty for depth."""
    return path.split("/")


def _query_count(url: str) -> int:
    from urllib.parse import urlparse

    return len(urlparse(url).query.split("&")) if urlparse(url).query else 0


def _bad_status(evidence: dict[str, Any]) -> bool:
    status = evidence.get("http_status")
    if status is None:
        return False
    code = int(status)
    return code < 200 or code >= 300


def _is_pdf_or_asset(url: str, evidence: dict[str, Any]) -> bool:
    path = path_of(url)
    if path.lower().endswith(
        (".pdf", ".doc", ".docx", ".zip", ".jpg", ".png", ".svg", ".xml", ".json")
    ):
        return True
    content_type = evidence.get("content_type")
    return (
        isinstance(content_type, str) and bool(content_type) and "html" not in content_type.lower()
    )


def score_candidate(*, url: str, evidence: dict[str, Any]) -> tuple[int, list[dict[str, Any]]]:
    """Return (score clamped 0..100, ordered list of applied-rule dicts).

    Evidence contract (absent flags count as False):
        domain                  str   company registrable domain (foreign_host check)
        http_status             int   final HTTP status (bad_status when non-2xx)
        content_type            str   response Content-Type (pdf_or_asset)
        json_ld_jobposting            bool  page has a JobPosting
        multiple_job_links            bool  >=3 distinct job-posting-looking links
        single_posting                bool  one JobPosting + numeric/UUID trailing segment
        nav_header / nav_footer       bool  linked from header/nav / footer
        in_sitemap                    bool  URL appears in the site's sitemap
        title_keyword                 bool  <title> contains a career keyword
        explicit_no_openings          bool  page states there are no open positions
        http_200                      bool  confirmed 2xx response
    """
    trail: list[dict[str, Any]] = []

    # --- Hard disqualifiers (first; any hit short-circuits) -----------------
    host = _host(url)
    if is_blocked_domain(host):
        return (0, [_rule("blocked_domain", 0, f"host {host} is blocked")])

    if _bad_status(evidence):
        return (0, [_rule("bad_status", 0, f"final HTTP status {evidence['http_status']}")])

    if _scheme(url) not in {"http", "https"}:
        return (0, [_rule("bad_scheme", 0, f"scheme {_scheme(url) or 'missing'}")])

    registrable = evidence.get("domain") or ""
    if not registrable:
        return (
            0,
            [
                _rule(
                    "missing_domain_evidence",
                    0,
                    "evidence['domain'] is required for foreign_host check",
                )
            ],
        )
    if not (is_own_host(host, registrable) or is_ats_host(host) or is_workday_host(host)):
        return (0, [_rule("foreign_host", 0, f"host {host} is not the company's domain")])

    # --- Positive rules (spec order) ----------------------------------------
    if is_ats_host(host):
        trail.append(_rule("ats_host", 40, f"host {host} matches a supported ATS"))
    if evidence.get("json_ld_jobposting"):
        trail.append(_rule("json_ld_jobposting", 30, "page declares a JobPosting"))
    if path_has_career_keyword(path_of(url)):
        trail.append(_rule("career_path_keyword", 25, "path contains a career keyword"))
    if evidence.get("multiple_job_links"):
        trail.append(_rule("multiple_job_links", 20, "3+ job-posting-looking links"))
    if is_career_subdomain_host(host):
        trail.append(_rule("career_subdomain", 18, f"{host.split('.')[0]} is a career subdomain"))
    if evidence.get("nav_header"):
        trail.append(_rule("nav_header", 15, "linked from the header/nav"))
    if evidence.get("title_keyword"):
        trail.append(_rule("title_keyword", 15, "title contains a career keyword"))
    if evidence.get("nav_footer"):
        trail.append(_rule("nav_footer", 10, "linked from the footer"))
    if evidence.get("in_sitemap"):
        trail.append(_rule("in_sitemap", 10, "appears in the sitemap"))
    if evidence.get("http_200"):
        trail.append(_rule("http_200", 5, "confirmed 2xx"))
    if evidence.get("explicit_no_openings"):
        trail.append(_rule("explicit_no_openings", 5, "page states no open positions"))

    score = sum(r["points"] for r in trail)

    # --- Negative rules (spec order) ----------------------------------------
    if _is_pdf_or_asset(url, evidence):
        trail.append(_rule("pdf_or_asset", -40, "URL is a file / non-HTML response"))
        score -= 40
    if path_has_noise_token(path_of(url)):
        trail.append(_rule("noise_path", -30, "path contains a noise token"))
        score -= 30
    if is_workday_host(host):
        trail.append(_rule("workday", -20, "Workday board — recognized, unsupported in P1"))
        score -= 20
    if evidence.get("single_posting"):
        trail.append(_rule("single_posting", -15, "one detail page, not a listing"))
        score -= 15
    # deep_path: two or more non-empty segments below root
    segments = [s for s in _path_segments(path_of(url)) if s]
    if len(segments) >= 2:
        trail.append(_rule("deep_path", -10, "path deeper than 2 segments"))
        score -= 10
    if _query_count(url) >= 2:
        trail.append(_rule("query_heavy", -5, "2+ query parameters"))
        score -= 5

    clamped = max(0, min(100, score))
    return clamped, trail


def _rule(rule: str, points: int, detail: str) -> dict[str, Any]:
    return {"rule": rule, "points": points, "detail": detail}
