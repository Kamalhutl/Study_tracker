# Task Context: A5-CARRY — Five carry-over items before A6

Session ID: 2026-09-04-a5-carry
Created: 2026-09-04T00:00:00Z (approx)
Status: in_progress

## Current Request
Execute prompta5.md end to end. Do not ask questions — make senior-engineer decisions and record them.

## Context Files (Standards to Follow)
None discovered (no .opencode/context/ exists). Rely on existing project patterns.

## Reference Files (Source Material)
- apps/jobs/models.py
- apps/jobs/services.py
- apps/jobs/filters.py
- apps/jobs/admin.py
- apps/jobs/management/commands/backfill_sanitized_html.py
- requirements/ (all .txt files)
- docs/api_v1_jobs.md (to create/update)

## External Docs Fetched
None needed.

## Components
1. Null `search_vector` row: identified (Job 74f23f8e, \"Draft Internship\", zero-length description/html) — legitimate, document as-is.
   - Documented: Job 74f23f8e has empty description and html, so null is valid. No fix needed.
2. `search_vector` maintenance: currently manual via `refresh_search_vector()` called from `upsert_job` (services.py lines 268,347,585). `bulk_update` and `.update()` bypass it. Fix: replace with database trigger (PostgreSQL) that updates on INSERT/UPDATE of title, description, or company_id. Remove manual update calls.
3. Search mechanism: `/api/v1/jobs/?q=` uses trigram (TrigramSimilarity). `search_vector` is unused. Decision: keep trigram as authoritative. Drop `search_vector` column, its GIN index, and all related code (refresh_search_vector, admin action, rebuild command). Document in docs/api_v1_jobs.md.
4. Toolchain pinning: pin exact versions of mypy, django-stubs, django-stubs-ext, djangorestframework-stubs, Django, nh3 from current installed versions. Add README note explaining pinning due to past breakages.
5. Remove bleach and types-bleach (unused, nh3 is used).
6. Fix iteration guard in backfill_sanitized_html.py: use ceiling division for max_iterations.
7. Run gates: black, ruff, mypy, migration checks, pytest with coverage flags. Paste verbatim output.

## Constraints
- Follow Django patterns.
- Use existing test suite; add regression test for search vector bypass.
- Ensure coverage does not regress (fail_under=88).
- Do not change production code to match expectations; report surprises.

## Exit Criteria
- [ ] Null row identified and documented.
- [ ] search_vector maintenance moved to trigger; manual updates removed.
- [ ] search_vector column dropped; related code removed.
- [ ] Search decision documented in docs/api_v1_jobs.md.
- [ ] Toolchain pinned in requirements/ with README note.
- [ ] bleach and types-bleach removed.
- [ ] Iteration guard fixed.
- [ ] All gates pass (black, ruff, mypy, migration checks, pytest) with verbatim output pasted.
- [ ] Completion percentage reported.