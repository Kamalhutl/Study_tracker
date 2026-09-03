"""score_candidate — every rule fires and never fires; the 10 spec examples."""

from __future__ import annotations

from typing import Any

import pytest

from apps.career_detection.scoring import score_candidate

DOMAIN = "example.com"


def rules(score: int, trail: list[dict[str, Any]]) -> set[str]:
    assert 0 <= score <= 100
    return {r["rule"] for r in trail}


# --- Hard disqualifiers ------------------------------------------------------


def test_blocked_domain_disqualifies():
    score, trail = score_candidate(url="https://indeed.com/careers", evidence={"domain": DOMAIN})
    assert score == 0
    assert rules(score, trail) == {"blocked_domain"}


def test_blocked_domain_matches_subdomain():
    score, trail = score_candidate(url="https://www.indeed.com/careers", evidence={})
    assert score == 0
    assert "blocked_domain" in rules(score, trail)


def test_missing_domain_evidence_disqualifies():
    # foreign_host must fail closed when evidence['domain'] is absent or empty
    score, trail = score_candidate(url="https://example.com/careers", evidence={})
    assert score == 0
    assert rules(score, trail) == {"missing_domain_evidence"}

    score, trail = score_candidate(url="https://example.com/careers", evidence={"domain": ""})
    assert score == 0
    assert rules(score, trail) == {"missing_domain_evidence"}


def test_bad_status_disqualifies():
    score, trail = score_candidate(
        url="https://example.com/careers",
        evidence={"domain": DOMAIN, "http_status": 404},
    )
    assert score == 0
    assert "bad_status" in rules(score, trail)


def test_bad_status_31x_disqualifies():
    score, trail = score_candidate(
        url="https://example.com/careers",
        evidence={"domain": DOMAIN, "http_status": 302},
    )
    assert score == 0
    assert "bad_status" in rules(score, trail)


def test_no_status_is_not_bad():
    score, _ = score_candidate(url="https://example.com/careers", evidence={"domain": DOMAIN})
    assert score > 0


def test_bad_scheme_disqualifies():
    for scheme in ("ftp://", "file://", "javascript:", "mailto:"):
        score, trail = score_candidate(
            url=f"{scheme}example.com/careers" if "://" in scheme else f"{scheme}example",
            evidence={"domain": DOMAIN},
        )
        assert score == 0, scheme
        assert "bad_scheme" in rules(score, trail)


def test_foreign_host_disqualifies_when_domain_known():
    score, trail = score_candidate(url="https://evil.net/careers", evidence={"domain": DOMAIN})
    assert score == 0
    assert "foreign_host" in rules(score, trail)


def test_foreign_host_allows_ats_hosts():
    score, trail = score_candidate(
        url="https://boards.greenhouse.io/acme", evidence={"domain": DOMAIN}
    )
    assert "foreign_host" not in rules(score, trail)
    assert "ats_host" in rules(score, trail)


def test_own_host_accepts_www_and_subdomains():
    for host in ("www.example.com", "jobs.example.com", "example.com"):
        score, trail = score_candidate(url=f"https://{host}/careers", evidence={"domain": DOMAIN})
        assert "foreign_host" not in rules(score, trail)


# --- Positives --------------------------------------------------------------


def test_every_positive_rule():
    score, trail = score_candidate(
        url="https://careers.example.com/jobs",
        evidence={
            "domain": DOMAIN,
            "json_ld_jobposting": True,
            "multiple_job_links": True,
            "nav_header": True,
            "nav_footer": True,
            "title_keyword": True,
            "in_sitemap": True,
            "http_200": True,
            "explicit_no_openings": True,
        },
    )
    assert rules(score, trail) == {
        "career_path_keyword",
        "career_subdomain",
        "nav_header",
        "nav_footer",
        "in_sitemap",
        "http_200",
        "explicit_no_openings",
        "title_keyword",
        "json_ld_jobposting",
        "multiple_job_links",
    }
    assert score == 100  # clamped (18+25+15+10+10+5+5+15+30+20 = 153)


def test_ats_host_fires_for_board_host():
    score, trail = score_candidate(
        url="https://boards.greenhouse.io/acme", evidence={"domain": DOMAIN, "http_200": True}
    )
    assert "ats_host" in rules(score, trail)
    assert score == 45


def test_ats_host_fires_for_smartrecruiters():
    score, trail = score_candidate(
        url="https://careers.smartrecruiters.com/acme", evidence={"domain": DOMAIN}
    )
    assert "ats_host" in rules(score, trail)
    assert "career_subdomain" in rules(score, trail)  # careers. prefix


def test_career_path_keyword_fires_on_segments():
    # Single segment: score 25
    url = "https://example.com/careers"
    score, trail = score_candidate(url=url, evidence={"domain": DOMAIN})
    assert "career_path_keyword" in rules(score, trail)
    assert score == 25
    # Hyphenated single segment: score 25
    url = "https://example.com/jobs-at-company"
    score, trail = score_candidate(url=url, evidence={"domain": DOMAIN})
    assert "career_path_keyword" in rules(score, trail)
    assert score == 25
    # Two segments: deep_path applies, score 25-10=15
    url = "https://example.com/landing/careers"
    score, trail = score_candidate(url=url, evidence={"domain": DOMAIN})
    assert "career_path_keyword" in rules(score, trail)
    assert "deep_path" in rules(score, trail)
    assert score == 15


def test_career_path_keyword_does_not_fire_on_partial_segment():
    scope, trail = score_candidate(
        url="https://example.com/carerra-tires", evidence={"domain": DOMAIN}
    )
    assert "career_path_keyword" not in rules(scope, trail)


def test_career_subdomain_fires_for_jobs_subdomain():
    score, trail = score_candidate(url="https://jobs.example.com/", evidence={"domain": DOMAIN})
    assert "career_subdomain" in rules(score, trail)


def test_workday_host_negative():
    score, trail = score_candidate(
        url="https://acme.myworkdayjobs.com/careers", evidence={"domain": "acme.com"}
    )
    assert "workday" in rules(score, trail)
    assert "ats_host" not in rules(score, trail)
    assert score == 5  # 25 keyword - 20 workday


# --- Negatives ---------------------------------------------------------------


def test_pdf_and_asset_extensions():
    for ext in (".pdf", ".doc", ".docx", ".zip", ".jpg", ".png", ".svg", ".xml", ".json"):
        score, trail = score_candidate(
            url=f"https://example.com/careers{ext}", evidence={"domain": DOMAIN}
        )
        assert "pdf_or_asset" in rules(score, trail), ext
        assert score == 0, ext  # 25 keyword - 40 asset, clamped at 0


def test_pdf_extension_overrides_good_trail():
    score, trail = score_candidate(
        url="https://example.com/careers.pdf",
        evidence={"domain": DOMAIN, "http_200": True, "nav_header": True},
    )
    assert score == 25 + 5 + 15 - 40


def test_content_type_non_html_fires():
    score, trail = score_candidate(
        url="https://example.com/careers",
        evidence={"domain": DOMAIN, "content_type": "application/json", "http_200": True},
    )
    assert "pdf_or_asset" in rules(score, trail)


def test_content_type_html_ok():
    score, trail = score_candidate(
        url="https://example.com/careers",
        evidence={"domain": DOMAIN, "content_type": "text/html; charset=utf-8"},
    )
    assert "pdf_or_asset" not in rules(score, trail)
    assert score == 25


def test_noise_path_negative():
    score, trail = score_candidate(
        url="https://example.com/blog/careers", evidence={"domain": DOMAIN}
    )
    assert "noise_path" in rules(score, trail)
    assert score == 0  # 25 keyword - 30 noise, clamped


def test_template_noise_token():
    """Defect 5: template, templates, resources, library, examples are noise tokens."""
    for token in ("template", "templates", "resources", "library", "examples"):
        score, trail = score_candidate(
            url=f"https://example.com/{token}/careers", evidence={"domain": DOMAIN}
        )
        assert "noise_path" in rules(score, trail)
        # career keyword in path but noise token also present -> score reduced
        # 25 - 30 = -5 clamped to 0
        assert score == 0


def test_single_posting_negative():
    score, trail = score_candidate(
        url="https://example.com/careers/3033",
        evidence={"domain": DOMAIN, "single_posting": True},
    )
    assert "single_posting" in rules(score, trail)
    # deep_path also applies (2 segments), so score = 25 -15 -10 = 0
    assert "deep_path" in rules(score, trail)
    assert score == 0


def test_deep_path_negative():
    score, trail = score_candidate(
        url="https://example.com/company/careers/engineering/senior-backend-42",
        evidence={"domain": DOMAIN},
    )
    assert "deep_path" in rules(score, trail)
    assert score == 25 - 10  # example 4: 35


def test_deep_path_fires_for_two_segments_below_root():
    """Defect 5: deep_path should fire for paths with 2+ non-empty segments."""
    # Two segments: "careers" and "devops" -> deep_path should fire
    score, trail = score_candidate(
        url="https://example.com/careers/devops",
        evidence={"domain": DOMAIN},
    )
    assert "deep_path" in rules(score, trail)
    assert score == 25 - 10
    # One segment: "careers" -> no deep_path
    score, trail = score_candidate(
        url="https://example.com/careers",
        evidence={"domain": DOMAIN},
    )
    assert "deep_path" not in rules(score, trail)
    assert score == 25


def test_shallow_path_not_deep():
    score, trail = score_candidate(url="https://example.com/careers/", evidence={"domain": DOMAIN})
    assert "deep_path" not in rules(score, trail)


def test_query_heavy_negative():
    score, trail = score_candidate(
        url="https://example.com/careers?utm=1&ref=2&f=3", evidence={"domain": DOMAIN}
    )
    assert "query_heavy" in rules(score, trail)
    assert score == 25 - 5


def test_one_query_not_heavy():
    score, trail = score_candidate(
        url="https://example.com/careers?v=1", evidence={"domain": DOMAIN}
    )
    assert "query_heavy" not in rules(score, trail)
    assert score == 25


# --- Clamping + trail -------------------------------------------------------


def test_score_clamped_to_zero():
    score, trail = score_candidate(
        url="https://example.com/team/blog/careers", evidence={"domain": DOMAIN}
    )
    assert score == 0
    assert "noise_path" in rules(score, trail)


def test_score_clamped_to_one_hundred():
    score, trail = score_candidate(
        url="https://example.com/careers",
        evidence={
            "domain": DOMAIN,
            "json_ld_jobposting": True,
            "multiple_job_links": True,
            "nav_header": True,
            "title_keyword": True,
            "in_sitemap": True,
            "http_200": True,
        },
    )
    assert score == 100


def test_trail_is_ordered():
    _, trail = score_candidate(
        url="https://example.com/careers",
        evidence={"domain": DOMAIN, "json_ld_jobposting": True},
    )
    assert [r["rule"] for r in trail] == ["json_ld_jobposting", "career_path_keyword"]


def test_absent_evidence_counts_false():
    score, trail = score_candidate(url="https://example.com/x", evidence={"domain": DOMAIN})
    assert rules(score, trail) == set()


# --- The 10 spec worked examples (PROMPT_3_SECTION_6 §6.4, exact integers) ---


@pytest.mark.parametrize(
    ("url", "evidence", "expected", "expected_trail"),
    [
        # 1. ATS board host: 40 + 5 + 20
        (
            "https://boards.greenhouse.io/acme",
            {"domain": "acme.com", "http_200": True, "multiple_job_links": True},
            65,
            {"ats_host", "http_200", "multiple_job_links"},
        ),
        # 2. Own-host careers page, full positive trail: 25+5+15+15+20+10
        (
            "https://acme.com/careers",
            {
                "domain": "acme.com",
                "http_200": True,
                "nav_header": True,
                "title_keyword": True,
                "multiple_job_links": True,
                "in_sitemap": True,
            },
            90,
            {
                "career_path_keyword",
                "http_200",
                "nav_header",
                "title_keyword",
                "multiple_job_links",
                "in_sitemap",
            },
        ),
        # 3. Career subdomain: 18 + 5 + 10 + 30
        (
            "https://careers.acme.com/",
            {
                "domain": "acme.com",
                "http_200": True,
                "nav_footer": True,
                "json_ld_jobposting": True,
            },
            63,
            {"career_subdomain", "http_200", "nav_footer", "json_ld_jobposting"},
        ),
        # 4. Deep detail page: 25-15-10+5+30 (deep_path derived from path)
        (
            "https://acme.com/careers/engineering/senior-backend-42",
            {
                "domain": "acme.com",
                "single_posting": True,
                "http_200": True,
                "json_ld_jobposting": True,
            },
            35,
            {
                "career_path_keyword",
                "single_posting",
                "deep_path",
                "http_200",
                "json_ld_jobposting",
            },
        ),
        # 5. Noise path cancels the keyword, clamped at 0: 25-30+5, deep_path also applies (2 segments) -> 25-30-10+5 = -10 clamped to 0
        (
            "https://acme.com/blog/we-are-hiring-2024",
            {"domain": "acme.com", "http_200": True},
            0,
            {"career_path_keyword", "noise_path", "http_200", "deep_path"},
        ),
        # 6. Asset extension cancels the keyword, clamped at 0: 25-40+5
        (
            "https://acme.com/careers.pdf",
            {"domain": "acme.com", "http_200": True},
            0,
            {"career_path_keyword", "pdf_or_asset", "http_200"},
        ),
        # 7. Blocked domain: 0, single-rule trail
        (
            "https://linkedin.com/company/acme/jobs",
            {
                "domain": "acme.com",
                "http_200": True,
                "json_ld_jobposting": True,
                "nav_header": True,
            },
            0,
            {"blocked_domain"},
        ),
        # 8. Non-2xx status: 0, single-rule trail
        (
            "https://acme.com/careers",
            {"domain": "acme.com", "http_status": 404},
            0,
            {"bad_status"},
        ),
        # 9. Explicitly no openings still proves it is the careers page: 25+5+5+15+15
        (
            "https://acme.com/careers",
            {
                "domain": "acme.com",
                "explicit_no_openings": True,
                "http_200": True,
                "nav_header": True,
                "title_keyword": True,
            },
            65,
            {
                "career_path_keyword",
                "explicit_no_openings",
                "http_200",
                "nav_header",
                "title_keyword",
            },
        ),
        # 10. Workday board, recorded but never suggested: 25-20+5
        (
            "https://acme.myworkdayjobs.com/careers",
            {"domain": "acme.com", "http_200": True},
            10,
            {"career_path_keyword", "workday", "http_200"},
        ),
    ],
)
def test_spec_worked_examples(
    url: str, evidence: dict[str, Any], expected: int, expected_trail: set[str]
):
    # Spec table now supplies `domain` — foreign_host must not fire for these.
    score, trail = score_candidate(url=url, evidence={**evidence})
    assert score == expected, [r["rule"] for r in trail]
    assert {r["rule"] for r in trail} == expected_trail
