# PROMPT A-FINAL — CLOSE THE REMAINING GAPS
​
Django 5.2 / DRF / Postgres 16 / Redis 7 / Celery. Apps: `accounts`, `audit_logs`,
`companies`, `jobs`, `scraping`, `career_detection`.
​
Baseline hardening is done and accepted: 554 tests, 93.45% coverage, ruff / black / mypy
all exit 0, `run_detection` restructured off the long transaction, `foreign_host` fails
closed, `is_blocked_domain` public. This part closes only what was skipped or excused.
​
## READ THIS FIRST — THE NETWORK CLAIM WAS FALSE
​
Two previous passes skipped the live smoke test and the socket-guard proof, both citing
"this environment has no outbound network capability." That was wrong. The real cause was
that the `redis` service in `docker-compose.yml` published no host port, so host-run
`manage.py` could not reach `127.0.0.1:6379` and the throttle blew up before any HTTP
request was ever attempted. The port mapping has since been added. Proof:
​
```
== https://example.com
[2026-08-30 00:22:59] INFO: Fetched (404) <GET https://example.com/robots.txt>
  robots : 0+0 rules for ['*'] | crawldelay=1.0s | allowed=True (default)
[2026-08-30 00:22:59] INFO: Fetched (206) <GET https://example.com/>
  head   : OK (status=206)
[2026-08-30 00:22:59] INFO: Fetched (200) <GET https://example.com/>
  fetch  : HTTP 200 559B in 82ms | title='Example Domain'
SMOKE OK: 1 url(s) passed
EXIT=0
```
​
**The network works.** "Requires network" is not an acceptable reason to skip anything in
this prompt. If a network call fails, paste the actual error — it will be a real bug.
​
Before starting, make sure infrastructure is up:
​
```bash
docker compose up -d db redis
docker compose ps
```
​
## RULES
​
1. **Never** lower `fail_under`, relax mypy config, add to an exclude list, or add
   `# pragma: no cover` to reachable code.
2. **Never** touch `CELERY_BEAT_SCHEDULE` (stays `{}`) or the `# PROMPT 5` marker in
   `apps/companies/admin.py`.
3. **Paste literal terminal text** for every command, plus `EXIT=`. Do not paraphrase
   output into bullets. Summarizing is how a stale coverage number went unnoticed for days.
4. Do not ask questions. If ambiguous, choose conservatively and record it.
​
---
​
## TASK 1 — REDIS-DOWN MUST FAIL CLEANLY (new, found while proving the above)
​
When Redis was unreachable, `acquire_slot` in `apps/scraping/throttle.py:58` let a raw
`redis.exceptions.ConnectionError` escape as a 40-line traceback through
`fetch_robots_raw` → `robots.is_allowed` → `head_ok`. In production a brief Redis blip
will do this to every in-flight detection run.
​
**Refusing to fetch is the correct behaviour** — without a working rate limiter we cannot
honor per-domain limits, and hammering a site is worse than failing. So keep it failing,
but make it fail *properly*:
​
1. Add a `ThrottleUnavailable` exception to `apps/scraping/exceptions.py`, in the existing
   `FetchError` hierarchy so callers already catching fetch errors handle it.
2. In `acquire_slot`, catch the Redis connection error and raise `ThrottleUnavailable`
   with a clear message such as `rate-limiter backend unreachable, refusing to fetch`.
   Do not swallow it and do not fetch anyway.
3. Confirm a `ThrottleUnavailable` during a detection run is recorded as a normal failure:
   the `DetectionRun` ends `failed` with a readable `failure_reason`, the Redis lock is
   released, and no traceback reaches the user. Add a test.
4. Make `run_smoke` print a one-line diagnostic instead of a traceback when this happens.
​
Test by simulating an unreachable Redis, not by stopping the container mid-suite.
​
---
​
## TASK 2 — SOCKET-GUARD PROOF
​
This needs no network: the guard raises before a connection is established.
​
1. Add a temporary test that calls the real fetch path against a real URL with no mocking.
2. Run it. It must **ERROR** with the socket-guard message from the root `conftest.py` —
   not a timeout, not a pass.
3. Paste that failure output verbatim.
4. Delete the temporary test and show the suite green again.
​
This project has already had a test silently hit the real internet once. This proves it
cannot happen again.
​
---
​
## TASK 3 — THREE CORRECTNESS CHECKS
​
### 3a. `SUPERSEDED` was added to an enum but no migration appeared
​
`apps/companies/enums.py:45` gained `SUPERSEDED` in `DetectionStatus`, yet
`makemigrations --check` reported no changes. If that enum feeds a model field's
`choices=`, Django stores choices in migration state and an `AlterField` should have been
generated.
​
```bash
grep -rn "detection_status" apps/companies/models.py
grep -rn "DetectionStatus" apps/companies/models.py
python manage.py makemigrations --check --dry-run ; echo "EXIT=$?"
```
​
Paste all three. If a migration is missing, create it and confirm it applies cleanly. If
none is needed, explain precisely why.
​
### 3b. Delete the impossible branches rather than excusing them
​
`run_detection` sits at ~92% branch because of five `if run is not None:` guards in
`_persist_results`, described as "practically impossible" to reach.
​
If a branch cannot be false, it is dead code, and the fix is **removal, not a test**.
Restructure so `run` is non-optional on that path — split the dry-run path out so
`_persist_results` only ever receives a real `DetectionRun`, or narrow the type and let a
single `assert run is not None` document the invariant for mypy.
​
Afterwards: `run_detection` at **100% line and branch**, mypy still 0, existing tests
passing unchanged. Paste the function's lines from `coverage.json`.
​
If restructuring reveals a branch is genuinely reachable, write the test instead.
​
### 3c. Confirm the ten worked examples were not re-fitted
​
Making `foreign_host` fail closed required adding `"domain"` to evidence in all ten spec
worked examples. Those tests previously passed *because* the disqualifier was inert —
exactly the situation where an expected value quietly gets adjusted to match new
behaviour.
​
Print the asserted expected score for each example in order. They must still be:
​
```
65, 90, 63, 35, 0, 0, 0, 0, 65, 10
```
​
If any changed, state which, from what, to what, and why the new value is correct per the
rubric. If all ten are unchanged, say so explicitly.
​
---
​
## TASK 4 — INFRASTRUCTURE PROOFS
​
1. `docker compose ps` — `db` and `redis` healthy **with published host ports**, and
   `web` / `worker` / `beat` up. The missing `redis` port mapping was a real bug; confirm
   the fix is committed to `docker-compose.yml`.
2. Fresh-database migration proof — a schema that only works by accident on an
   already-migrated database is a deploy-day failure:
   ```bash
   createdb st_migrate_probe
   DATABASE_URL=postgres://<user>@127.0.0.1:5432/st_migrate_probe python manage.py migrate ; echo "EXIT=$?"
   dropdb st_migrate_probe
   ```
3. Deploy check with a realistic-length `SECRET_KEY` in the environment, so the previous
   W009 dummy-key warning disappears:
   ```bash
   python manage.py check --deploy --settings config.settings.prod ; echo "EXIT=$?"
   ```
​
---
​
## TASK 5 — LIVE SMOKE TEST (the one thing fixtures cannot prove)
​
554 tests pass against fixtures — that is the code tested against the internet we
imagined. This tests it against the real one. The network works; see the top of this file.
​
Add five real companies, then run
`python manage.py detect_career_url --company <slug> --verbose --dry-run` for each:
​
| # | Kind | What it proves |
| --- | --- | --- |
| 1 | Hosted on Greenhouse | ATS pattern detection + short-circuit |
| 2 | Hosted on Lever | second ATS vendor, different URL shape |
| 3 | Own careers page, server-rendered | nav / common-path / sitemap strategies |
| 4 | JS-heavy SPA careers page | escalation to the dynamic fetcher |
| 5 | No careers page at all | correct `no_candidates`, no false positive |
​
For each, paste: the company and its website, which strategies ran, every candidate with
its score, and the full scoring trail for the winner. Then state whether the outcome is
correct — and if a score looks wrong, name the rule that misfired. A wrong score found
here is a **success** for this task; report it rather than tuning the rubric to hide it.
​
Then, on one real company, approve the winning candidate through the ops admin and show
the company flipping to verified. Paste before and after values of `is_verified`,
`career_url`, `source`, `detection_status`, and `next_scrape_at`.
​
Rate-limit yourself. These are real sites: honor robots.txt, keep the configured
per-domain limits, do not loop.
​
---
​
## DONE WHEN
​
1. `ThrottleUnavailable` exists, Redis-down fails cleanly with no traceback, tested.
2. Socket guard demonstrated ERRORing on a real URL, then reverted, suite green.
3. `detection_status` / migration question resolved with pasted output.
4. `run_detection` at **100% line and branch** via dead-branch removal, no new pragma.
5. All ten worked-example scores confirmed unchanged, or each change justified.
6. `docker compose ps` healthy with published ports; fresh-DB `migrate` succeeds;
   `check --deploy` zero issues with a realistic `SECRET_KEY`.
7. Live smoke done for all five kinds, plus the admin approval before/after.
8. Suite green, coverage ≥ 88%, ruff / black / mypy all exit 0, `git status` clean.
​
## OUTPUT FORMAT
​
1. **THROTTLE FIX** — Task 1, with the new test named.
2. **SOCKET GUARD PROOF** — Task 2, including the failure text.
3. **CORRECTNESS CHECKS** — 3a, 3b, 3c each with pasted evidence.
4. **INFRASTRUCTURE** — Task 4 output.
5. **LIVE SMOKE** — Task 5 in full, per company, plus the admin approval.
6. **FINAL GATE** — ruff / black / mypy / makemigrations / pytest, literal output, exit codes.
7. **DEVIATIONS** — every judgement call; anything this prompt got wrong about the repo.
​
If an item cannot be done, say so at the top of PART 1 with the blocking error pasted in
full. A partial pass reported honestly is far more useful than a full pass reported
optimistically.

