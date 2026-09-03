# Task Context: A5-FIX2 — Sanitizer replacement, input cap, toolchain pinning, search_vector

Session ID: 2026-09-03-a5-fix2
Created: 2026-09-03T21:06:00Z
Status: in_progress

## Current Request
Execute PROMPT A5-FIX2 end-to-end: Replace bleach with nh3, add sanitizer input cap, pin type-checking toolchain, resolve search_vector issues.

## Context Files (Standards to Follow)
- .opencode/context/core/standards/code-quality.md (MANDATORY - will load if exists)

## Reference Files (Source Material to Look At)
- apps/jobs/services.py (current _sanitize_html function using bleach)
- apps/jobs/management/commands/backfill_sanitized_html.py (uses _sanitize_html)
- apps/jobs/migrations/0003_backfill_description_html_sanitized.py (uses bleach directly)
- apps/jobs/tests/test_backfill_sanitized.py (hanging test with 1MB nested tags)
- config/settings/base.py (needs SANITIZE_MAX_INPUT_BYTES)
- requirements/dev.txt (needs toolchain pinning)
- requirements/base.txt (needs nh3, remove bleach)
- apps/jobs/models.py (search_vector field)
- apps/jobs/services.py (refresh_search_vector function)
- apps/jobs/filters.py (TrigramSimilarity for q filter)
- apps/jobs/querysets.py (search method using search_vector)
- docs/api_v1_jobs.md (needs search mechanism documentation)

## External Docs Fetched
- nh3 documentation for allowlist configuration and performance characteristics

## Components
1. Sanitizer replacement: Replace bleach with nh3 maintaining exact same allowlist semantics
2. Input cap: Add SANITIZE_MAX_INPUT_BYTES with truncate-or-flag behavior
3. Fix hanging test: Reduce payload to 50KB, add wall-clock assertion, add cap test
4. Toolchain pinning: Pin mypy, django-stubs, stubs-ext, drf-stubs, Django, nh3
5. Search vector resolution: Identify null row cause, fix bypass, confirm single mechanism

## Constraints
- Must maintain exact same allowlist semantics: tags p br strong em u ul ol li h3 h4 a code pre blockquote; on a only href/title; force rel="nofollow noopener noreferrer" and target="_blank"; permitted schemes http, https, mailto; strip <script>, <style>, <iframe>, all on* handlers, javascript: and data: URLs
- Single implementation: _sanitize_html used by both upsert_job and backfill_sanitized_html
- A5-FIX tests must pass unchanged
- After --force re-sanitize: expect 170 / 170 / 0 and all leak counts 0
- Input cap must never break a scrape - truncate or flag and continue
- Toolchain pinning must preserve Django 5.2.17

## Exit Criteria
- [ ] nh3 replacing bleach with same allowlist semantics
- [ ] A5-FIX tests passing unchanged
- [ ] --force re-sanitize reporting Updated: 170
- [ ] SANITIZE_MAX_INPUT_BYTES (default 512 KiB) with documented behavior
- [ ] Hanging test identified, payload reduced to 50KB, wall-clock assertion added, cap test added
- [ ] Toolchain pinned in requirements/ + README note
- [ ] The one null search_vector row explained and fixed
- [ ] search_vector maintenance mechanism identified and bypass fixed
- [ ] Exactly one search mechanism for q, decision documented in docs/api_v1_jobs.md
- [ ] All gates green with test count and coverage percentage reported
- [ ] Project completion percentage reported (target: 63%)

## Senior Engineer Decisions Recorded
1. **Sanitizer choice**: nh3 over bleach for security (maintained) and performance (Rust-based)
2. **Input cap behavior**: Truncate at cap before sanitizing, log job id with byte size, continue scrape
3. **Search mechanism**: Keep TrigramSimilarity (pg_trgm) as primary, document search_vector as legacy
4. **Null search_vector**: Will be identified and fixed during implementation
5. **Test payload**: Reduce from 1MB to 50KB for meaningful testing without pathological runtime