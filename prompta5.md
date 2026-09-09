# PROMPT 16.6 — company identity: keys, not hostnames

STANDING RULES (restated; your session resets lose these)
- File contents via the editor tool only. No heredocs, no `cat >`, no shell
  redirection, no multi-line quoted strings. One single-line shell command per call.
- `upsert_job` and `apply_missing_strikes` have FROZEN signatures.
- `record_scrape_outcome` is the only writer of company health state.
- Admins never write Company fields directly. Every mutation goes through
  `apps/companies/services.py`.
- Sequential work only. No sub-agents, no parallel batches.
- Do not report DONE while any item in your own todo list is unchecked.

0. Commit and push everything in the working tree first, excluding node_modules
   and .next. Paste the commit SHA and the GitHub Actions run URL it triggers,
   plus the conclusion of each of the three CI jobs separately.

1. REPORT FIRST, no code yet. Answer all four:
   a. Which companies currently have an ATS host in `domain`? One line each:
      slug | domain | career_url | is_active | ats_identifier
   b. Paste the exact condition on `uniq_active_company_domain` (models.py:111-115).
   c. Does `_dedupe_company` (services.py:133) filter on `is_active`? Quote the
      queryset. If the service check and the DB constraint disagree about what
      counts as a collision, say so explicitly.
   d. Two rows appear to hold `figma.com` — `figma` and `Smoke Lever Co`. How?

2. Create one canonical ATS host table in `apps/companies/enums.py`, mapping host
   to `CareerSourceType`. Include `job-boards.greenhouse.io` alongside
   `boards.greenhouse.io`. Rewire `sniff_source_type_from_url` to read from it.
   One mapping, one test suite, one truth — no second list anywhere.

3. `domain` means the company's own domain. In Case B, when the career URL host is
   in that table, leave `domain` null and populate `ats_identifier` from the URL
   path. Never write an ATS host into `domain` again.

4. Dedup by identity: when `ats_identifier` is set, key on
   (`career_source_type`, `ats_identifier`); otherwise key on `domain`. Add a
   partial unique constraint for the ATS key. Both checks must use the same
   is_active condition as the constraints they back.

5. Data migration: for existing rows whose `domain` is an ATS host, set `domain`
   to null and backfill `ats_identifier` from `career_url`.

6. Report why the `netflix` row has an empty slug, then give it a real one through
   the service layer.

7. Tests:
   - Two Lever companies with different org slugs both created via Case B.
   - Same org slug twice -> DuplicateCompany.
   - `job-boards.greenhouse.io/foo` sniffs as GREENHOUSE, not UNKNOWN.
   - No company row ends with an ATS host in `domain`.

DONE WHEN
- `make gates` exits 0 — paste coverage percentage and test count.
- `audit_public_surface` exits 0.
- `make web-smoke` exits 0.
- Pushed, with the CI run URL and all three job conclusions pasted.
