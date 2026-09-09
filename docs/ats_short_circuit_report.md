# ATS Short-Circuit Report

## 1. What sets `ats_short_circuit` and under what score threshold

`ats_short_circuit` is set in `apps/career_detection/services.py:387`, inside `_execute()`, immediately after `NavLinkStrategy` (strategy 2) runs:

```python
ctx.ats_short_circuit = _ats_hit_confirmed(ctx)
```

The function `_ats_hit_confirmed` (`services.py:397-415`) iterates over candidates with `origin == "ats_pattern"` and returns `True` if any of these hold:

- The candidate's score (via `score_candidate()`) >= `settings.DETECTION_ATS_SHORTCIRCUIT_SCORE` (default **60**, defined in `config/settings/base.py:284`).
- The candidate's `ats_identifier` evidence matches the org slug derived from the company domain.
- The org slug appears as a path segment in the candidate URL.

If none of the ATS-pattern candidates meet these criteria, it returns `False`.

## 2. What behaviour changes downstream when it is true

When `ctx.ats_short_circuit` is `True`:

- **Strategy loop** (`services.py:372-376`): strategies 3-7 (robots, sitemap, common_path, subdomain_guess, json_ld) are skipped. Only `VerifyStrategy` still runs.
- **VerifyStrategy** (`strategies.py:507-513`): instead of verifying up to `DETECTION_MAX_CANDIDATES` provisional candidates, it filters to only `ats_pattern`-origin candidates scoring >= `DETECTION_MIN_CANDIDATE_SCORE` and verifies at most 1.
- **Ranking** (`services.py:454`): the short-circuit flag is passed through but ranking itself is unchanged; confirmed ATS candidates sort first regardless.
- **Strategies used log** (`services.py:485-491`): the run record omits the 5 skipped strategy names.

## 3. How it interacts with `DETECTION_MAX_URL_CHECKS`

`DETECTION_MAX_URL_CHECKS` (default **60**, `base.py:279`) sets `ctx.max_checks` at `services.py:116`. Each URL fetch calls `ctx.spend()` (`types.py:66-70`), incrementing `checks_used` and raising `FetchBudgetExceeded` when `checks_used >= max_checks`.

The short-circuit reduces checks consumed by skipping strategies 3-7, which would otherwise spend checks on robots.txt fetches, sitemap parsing, common-path probes, subdomain guesses, and JSON-LD extraction. When the short-circuit fires, the remaining budget is spent only on verifying the single ATS candidate. If the short-circuit never fires, all 60 checks can be consumed across all 8 strategies.

## 4. Why it has never been true across 17 detection runs

The short-circuit requires an `ats_pattern`-origin candidate to exist after `NavLinkStrategy` runs. The `ats_pattern` origin is only produced by `ATSPatternStrategy` (strategy 1). The condition fails when:

- **No ATS pattern matched**: the company's domain does not match any known ATS hostname pattern (Greenhouse, Lever, Ashby, SmartRecruiters, Workday), so strategy 1 produces zero `ats_pattern` candidates. `_ats_hit_confirmed` iterates an empty set and returns `False`.
- **Score below 60 and no org-slug match**: even if an ATS candidate exists, if its score is < 60 AND the org slug doesn't appear in the URL or `ats_identifier`, the function returns `False`.

For demo/fixture companies using `.example` domains, the ATS pattern matcher may produce candidates (e.g., `boards.greenhouse.io/acmerobotics`), but the org slug extracted from the `.example` domain won't match the ATS identifier in the URL, and the score may fall below 60 depending on evidence. This makes the short-circuit reachable in principle but unlikely for fixture data.

For real companies on custom career pages (no ATS hosting), strategy 1 produces no `ats_pattern` candidates at all, making the condition unreachable.

**Reachability**: The condition IS reachable for companies added via `add_company_from_direct_career_url` with a known ATS URL where the org slug matches the domain. However, such companies are created with `is_verified=True` and `detection_status=SKIPPED` (`services.py:242-243`), so detection never runs for them. Detection only runs for Case A companies (`add_company_from_main_website`), which start unverified — and those typically lack ATS-hosted career URLs until detection finds one. This creates a catch-22: the short-circuit is designed for ATS URLs, but ATS URLs skip detection entirely.

</parameter>
</invoke>