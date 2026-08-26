# PROMPT A — BASELINE HARDENING

## ROLE

You are a senior Django engineer doing a **consolidation pass** on a work-in-progress
tree. You are not adding features. Your job is to take this repo to a **provably clean
baseline** so the next feature prompt can be trusted.

Stack: Django 5.2, DRF, Postgres 16, Redis 7, Celery + Beat, `scrapling[fetchers]==0.4.14`,
Django-Admin-first ops portal.
Apps: `accounts`, `audit_logs`, `companies`, `jobs`, `scraping`, `career_detection`.

**Why this prompt exists:** previous sessions reported "green" and "clean" several times
while black, mypy, and coverage were in fact failing. Those reports were generated from
partial runs. This pass exists to replace claims with evidence.

---

## GROUND RULES

1. **No new features.** No new models, no new endpoints, no new detection strategies, no
   new settings beyond what a listed fix requires. If you find yourself designing
   something, stop — you have left the scope.
2. **No new migrations** unless a fix genuinely requires one. If one is required, say so
   loudly and explain why.
3. **No suppression to make a check pass.** Specifically forbidden:
   - lowering `fail_under`
   - relaxing any mypy strictness flag
   - adding paths to a mypy/ruff/coverage exclude list
   - bare `# type: ignore` (must be `# type: ignore[specific-code]` + a one-line reason)
   - bare `# noqa` (must carry a rule code)
   - `# pragma: no cover` on anything reachable
4. **Never** modify `CELERY_BEAT_SCHEDULE` — it stays `{}`. The `# STEP 12` marker belongs
   to a later prompt.
5. **Never** modify the `# PROMPT 5: "Scrape now"` marker in `apps/companies/admin.py`.
6. **Every claim needs pasted raw output plus the exit code.** Never write "clean" or
   "green" without it. If a command fails, paste the failure — do not summarize it.
7. Do the steps in order. Later steps depend on earlier ones actually being done.
8. **Do not ask questions mid-way.** If something is genuinely ambiguous, pick the more
   conservative option, proceed, and record the decision in PART 6.

---

## STEP 1 — ESTABLISH GROUND TRUTH (measure before changing anything)

Run all of these from the project root, on the **full** tree. Do not scope pytest to a
single app or a subset of test files — that is exactly what produced the misleading 58%
figure previously.

```bash
pytest --cov=apps --cov=core --cov-branch --cov-report=term-missing -q ; echo "EXIT=$?"
ruff check apps core config tests                                      ; echo "EXIT=$?"
black --check apps core config tests                                   ; echo "EXIT=$?"
mypy .                                                                 ; echo "EXIT=$?"
python manage.py makemigrations --check --dry-run                      ; echo "EXIT=$?"
```

Paste all five outputs verbatim, with exit codes. This is your **before** snapshot.

Also report:
- total test count collected
- total coverage %
- the mypy error count
- the list of files black would reformat

Do not fix anything yet. Measure first.

---

## STEP 2 — FORMATTING (mechanical, no judgement)

```bash
black apps core config tests
ruff check --fix apps core config tests
```

Then re-run both in `--check` mode and paste clean output. Commit this on its own so the
formatting churn never mixes with logic changes:

```bash
git add -A && git commit -m "style: black + ruff autofix across the tree"
```

---

## STEP 3 — THE LOCK / TRANSACTION BUG IN `run_detection` (highest-value fix)

### The problem

`apps/career_detection/services.py` currently wraps the **entire** detection run in a
single `transaction.atomic()` block and takes a `select_for_update()` row lock inside it,
then performs network I/O for up to `DETECTION_TOTAL_BUDGET_SECONDS` (120s) while holding
both.

Consequences at the target scale of 1000 companies with parallel workers:
- a Postgres row lock held for up to 2 minutes per company
- a DB connection pinned `idle in transaction` for the whole run, exhausting the pool
- `select_for_update` blocking any admin edit of that company row
- one slow site degrading unrelated work

`core.locks.redis_lock` is already imported in this module but is only used in the batch
path. The per-company concurrency guard specified for `run_detection` was never wired.

### The fix

Restructure `run_detection` into three phases:

1. **Guard (Redis, no DB transaction).** Acquire `redis_lock(f"detect:{company.id}")`
   non-blocking with a TTL comfortably above the detection budget. If not acquired,
   return early indicating a run is already in flight — do not queue behind it.
2. **Eligibility + run row (short transaction).** Re-read the company, check
   soft-deleted / already-verified, create the `DetectionRun` row with
   `status=running`. Commit. Keep this transaction to milliseconds.
3. **Strategies (NO transaction, NO row lock).** Run all fetching and scoring with no
   DB transaction open. This is where the 120 seconds is spent.
4. **Persist (short transaction).** One `transaction.atomic()` around only the writes:
   upsert `CareerCandidateUrl` rows, set `company.detection_status`, finish the
   `DetectionRun`, write the audit log.

Requirements:
- Remove `select_for_update()` from the long-running path entirely. Use the Redis lock
  for mutual exclusion, which is what it is for.
- Re-read the company inside phase 4 and re-check eligibility before writing, because
  time has passed since phase 2. If it became verified or soft-deleted meanwhile, abort
  the write, mark the run `superseded`, and log it. Add a test for this race.
- The Redis lock must be released even when a strategy raises. Verify by test.
- Preserve all existing outcome semantics exactly: `candidates_found`, `no_candidates`,
  `failed`, `partial`, and `dry_run` persisting nothing. All existing tests for those
  paths must still pass unchanged — if you have to edit an existing assertion, justify
  it in PART 6.
- `dry_run=True` must still take the lock (a dry run and a real run must not race).

---

## STEP 4 — FAIL-CLOSED SECURITY CHECKS

### 4a. `foreign_host` currently fails open

In `apps/career_detection/scoring.py`, the `foreign_host` disqualifier is written roughly as:

```python
registrable = evidence.get("domain") or ""
if registrable and not (is_own_host(host, registrable) or is_ats_host(host)):
    return (0, ...)
```

If `evidence["domain"]` is missing, the check silently does nothing. In practice the
strategy layer sets it via `setdefault`, so this is latent rather than live — but
`score_candidate` is a public pure function and a security disqualifier must not depend on
a caller remembering to populate a key.

Make it fail **closed**: if `domain` is absent or empty, that is a programming error.
Raise a clear `ValueError` (or return a disqualified score with an explicit
`missing_domain_evidence` rule — pick one, document which and why). Add a test asserting
the fail-closed behaviour, and keep `score_candidate` at 100% line and branch coverage.

### 4b. `_is_blocked` is a private cross-app import

`scoring.py` imports `_is_blocked` from `apps.companies.services`. A leading-underscore
function is by convention module-private; importing it across app boundaries makes it an
undeclared public API that a future refactor will silently break.

Promote it: expose a public `is_blocked_domain(host: str) -> bool` in
`apps/companies/enums.py` (next to `BLOCKED_DOMAINS`, where it belongs), have
`apps/companies/services.py` delegate to it, and update `scoring.py` to import the public
name. Behaviour must not change — keep subdomain matching identical. Existing
blocked-domain tests must pass untouched.

---

## STEP 5 — TYPES

Drive `mypy .` to zero errors under the existing strict `django-stubs` settings. This bar
is already proven achievable: an earlier milestone reached mypy-clean on 85 source files
with these same settings, so treat any urge to relax config as a wrong turn.

Rules:
- Fix the actual types. Do not annotate `Any` to silence an error where a real type is
  knowable.
- Where a `# type: ignore` is genuinely unavoidable (e.g. a django-stubs generic that the
  Django 5.2 runtime class does not support), use the specific error code, add a one-line
  comment stating the runtime reason, and list every such ignore in PART 6.
- Report the error count after each pass so the convergence is visible: e.g.
  `150 -> 88 -> 31 -> 0`.

---

## STEP 6 — COVERAGE, HONESTLY

1. Re-run the **full** suite with branch coverage. Report the real total.
2. Bring these to the required bars and paste the per-file numbers from `coverage.json`:
   - `apps/career_detection/scoring.py::score_candidate` — **100% line + branch**
   - `apps/career_detection/services.py::run_detection` — **100% line + branch**
   - `apps/scraping/fetching.py` — **≥ 95%**
   - total — **≥ 88%**
3. The two management commands `detect_career_url` and `detect_pending` previously showed
   **0.00%** coverage. Determine whether that was a partial-run artifact or a genuine
   gap, state which, and if genuine, cover them.
4. Reconcile the threshold mismatch: `pyproject.toml` sets `fail_under=88` while
   `.github/workflows/ci.yml` asserts 85%. Align both to **88** so CI cannot pass
   something the local gate would reject.

Write tests to close gaps. Do not delete or weaken a test to raise a percentage.

---

## STEP 7 — REPO HYGIENE

1. `.gitignore` currently contains `.env` three times and a malformed `*.swp.env` line
   (a mangled `*.swp` + `.env`). Deduplicate and fix. Verify `.env` is still ignored and
   still untracked afterwards.
2. Confirm these are ignored and untracked: `.venv/`, `.coverage`, `coverage.json`,
   `.mypy_cache/`, `.ruff_cache/`, `__pycache__/`, `celerybeat-schedule`, `var/`,
   `*.zip`. Paste `git status --porcelain` showing a clean tree at the end.
3. `docs/prompts/` is empty and the previous git history was lost. Do not attempt
   recovery. Just confirm the directory exists and is committed (a `.gitkeep` is fine).
4. Confirm `git log --oneline | head` shows your commits from this pass.

---

## STEP 8 — FINAL VERIFICATION (the actual gate)

Run every command and paste raw output with exit codes. Every one must be zero.

```bash
ruff check apps core config tests                                      ; echo "EXIT=$?"
black --check apps core config tests                                   ; echo "EXIT=$?"
mypy .                                                                 ; echo "EXIT=$?"
python manage.py makemigrations --check --dry-run                      ; echo "EXIT=$?"
pytest --cov=apps --cov=core --cov-branch --cov-report=term-missing -q ; echo "EXIT=$?"
python manage.py check --deploy --settings config.settings.prod        ; echo "EXIT=$?"
grep -rn "import scrapling\|from scrapling" apps/ core/ config/ tests/
git status --porcelain
```

Plus:

- `docker compose ps` — `db` and `redis` healthy, `web`/`worker`/`beat` up.
- Fresh-database migration proof: create a scratch database, run `migrate` against it,
  confirm success, drop it. Paste the tail of the output.
- `grep -n "CELERY_BEAT_SCHEDULE" config/settings/base.py` — still `{}`.
- `grep -n 'PROMPT 5' apps/companies/admin.py` — marker still present, untouched.
- Socket guard proof: temporarily point one test at a real URL, show it ERRORs with the
  socket guard message, then revert and show the suite green again.

---

## STEP 9 — LIVE SMOKE TEST (the one thing fixtures cannot prove)

Fixtures test the code you wrote against the internet you imagined. This step tests it
against the real one.

Run `python manage.py detect_career_url --company <slug> --verbose --dry-run` against
**five real companies**, one of each kind:

| # | Kind | What it proves |
| --- | --- | --- |
| 1 | Hosted on Greenhouse | ATS pattern detection + short-circuit |
| 2 | Hosted on Lever | second ATS vendor, different URL shape |
| 3 | Own careers page, server-rendered | nav/path/sitemap strategies |
| 4 | JS-heavy SPA careers page | escalation to the dynamic fetcher |
| 5 | No careers page at all | correct `no_candidates`, no false positive |

For each, paste: the company, the strategies that ran, every candidate with its score,
and the full scoring trail for the winner. Then state whether the result is correct and,
if a score looks wrong, which rule misfired.

Finally, on one real company: approve the winning candidate through the ops admin and
show the company flipping to verified with `next_scrape_at` populated. Paste the before
and after field values.

Rate-limit yourself: these are real sites. Honor robots.txt, keep the configured
per-domain limits, and do not loop.

---

## STEP 10 — DEFINITION OF DONE

1. `.env` untracked, `.gitignore` deduplicated and correct.
2. ruff, `black --check`, `mypy .` all exit 0 — with **zero** new suppressions.
3. `makemigrations --check --dry-run` — no changes.
4. Full suite green. Total coverage **≥ 88%**, branch coverage on.
5. `score_candidate` and `run_detection` both **100% line + branch**.
6. `apps/scraping/fetching.py` **≥ 95%**.
7. `check --deploy` against prod settings — zero issues.
8. `run_detection` holds **no** DB transaction and **no** row lock during network I/O;
   mutual exclusion is via `redis_lock`; the release-on-exception and
   became-ineligible-mid-run races are both tested.
9. `foreign_host` fails closed; `is_blocked_domain` is public and imported by name.
10. `CELERY_BEAT_SCHEDULE` still `{}`; the `PROMPT 5` marker untouched.
11. Only `apps/scraping/fetching.py` imports scrapling.
12. `pyproject.toml` and CI both gate at 88%.
13. Zero outbound network in the suite, proven by the socket-guard demonstration.
14. `git status --porcelain` empty; work committed.
15. Step 9 live smoke test done for all five company kinds, with the admin approval shown.

---

## OUTPUT FORMAT

Seven parts, in this order:

1. **BEFORE SNAPSHOT** — Step 1 raw output and the four summary numbers.
2. **CHANGES** — what you changed and why, grouped by step, with `file:line` references.
   For Step 3, show the before/after transaction and lock structure explicitly.
3. **TESTS ADDED** — each new test by name, and what regression it prevents.
4. **AFTER SNAPSHOT** — Step 8 raw output, every exit code visible.
5. **COVERAGE TABLE** — before vs after totals, plus the four required per-file numbers.
6. **DECISIONS & DEVIATIONS** — every judgement call; every remaining `# type: ignore`
   with its code and reason; anything in this prompt that reality contradicted, and what
   you did instead.
7. **LIVE SMOKE RESULTS** — Step 9 in full, plus the admin approval before/after.

If any DoD item is not met, say so plainly at the top of PART 1. A partial pass reported
honestly is far more useful than a full pass reported optimistically.



