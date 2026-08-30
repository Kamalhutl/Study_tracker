# PROMPT A2 — FINISH THE GAPS
​
Django 5.2 / DRF / Postgres 16 / Redis 7 / Celery. Apps: `accounts`, `audit_logs`,
`companies`, `jobs`, `scraping`, `career_detection`.
​
## CURRENT STATE — MEASURED, NOT CLAIMED
​
The previous pass did real work but reported things it had not done. These are the actual
numbers from a full local run:
​
```
554 passed in 30.57s     EXIT=0
TOTAL  5737  277  1056  129  93%    Total coverage: 93.17%
mypy: Success: no issues found in 116 source files    EXIT=0
```
​
Already landed and accepted — **do not redo these**:
​
- `ThrottleUnavailable` added to `apps/scraping/exceptions.py`, raised by `throttle.py`,
  handled in `run_smoke`.
- Dead `elif run is None and not dry_run:` branch removed from `services.py`.
- `conftest.py` now blocks `scrapling.engines.static.CurlSession` / `AsyncCurlSession`.
- `docker-compose.yml` publishes the Redis host port.
- Migration `0004_alter_company_detection_status_and_more.py` exists (this answers the
  earlier `SUPERSEDED` question — an `AlterField` was indeed required).
​
## RULES
​
1. **Never** lower `fail_under`, relax mypy config, add to an exclude list, or add
   `# pragma: no cover` to reachable code. Never delete a test to raise a percentage.
2. **Never** touch `CELERY_BEAT_SCHEDULE` (stays `{}`) or the `# PROMPT 5` marker in
   `apps/companies/admin.py`.
3. **Paste literal terminal output with `EXIT=` for every claim.** Do not write a
   narrative summary of what a command "would" show. The previous pass invented an entire
   report — including a FastAPI container, Python 3.8, and ten fake tests — while the real
   suite had 554 tests on Python 3.12. Every number below is checkable, and will be checked.
4. The network works. `run_smoke https://example.com` returns `EXIT=0` with HTTP 200 and
   `title='Example Domain'`. "Requires network" is not a valid reason to skip anything.
   Run `docker compose up -d db redis` first.
5. Do not ask questions. If ambiguous, choose conservatively and record it.
​
---
​
## TASK 1 — COVER THE THROTTLE HANDLER YOU WROTE
​
`apps/career_detection/services.py` reports **91%**, with `191-207` missing. That range is
the `except ThrottleUnavailable` handler added last pass. Sixteen statements of
brand-new error-handling code have never been executed. The previous report claimed a test
was added for it; no such test exists.
​
Also missing: `apps/scraping/throttle.py` is at **80%**, missing `63-69` and `96-98` —
the raise path itself is untested.
​
Write tests that actually execute these paths, by simulating an unreachable Redis (not by
stopping the container):
​
1. `throttle.py` — `acquire_slot` raises `ThrottleUnavailable` when the cache backend
   raises a connection error, with the expected message. Cover `63-69` and `96-98`.
2. `services.py` — a detection run whose fetch raises `ThrottleUnavailable` ends with the
   `DetectionRun` at `failed`, a readable `error_message`, `company.detection_status`
   set to `failed`, the Redis lock released, and **no traceback escaping**.
3. The `dry_run=True` variant, which re-raises.
​
### Then get `run_detection` to 100% line and branch
​
After the tests above, the remaining partial branches are `216->220`, `253->258`,
`263->268`, `273->278`. For each one, decide and state which it is:
​
- **reachable** → write the test, or
- **unreachable** → delete the branch.
​
Note that the new throttle handler re-introduced the exact `if run is not None` guard
pattern that was just deleted as dead code last pass. If `run` cannot be `None` there,
remove the guard rather than testing it.
​
Target: `apps/career_detection/services.py` **100% line and branch**. Paste the line from
the coverage table proving it.
​
---
​
## TASK 2 — HARDEN THE NETWORK GUARD
​
The new `conftest.py` guard closed a real hole: `socket.socket` monkeypatching never
blocked Scrapling, because `curl_cffi` calls libcurl in C and bypasses Python sockets.
Every earlier claim of "zero outbound network in the suite, proven" was false.
​
Two weaknesses remain:
​
1. `patch("scrapling.engines.static.CurlSession", ...)` targets an internal path. If
   Scrapling renames it, the patch fails silently and the guard quietly stops working.
   Assert the attribute exists before patching, so an upgrade fails loudly instead.
2. `DynamicFetcher` / `StealthyFetcher` use Playwright, which launches a **subprocess** —
   caught by neither the socket patch nor the curl patch. State plainly whether a browser
   fetch can currently reach the internet during tests. If it can, block it too.
​
### Then prove the guard works
​
Add a temporary test that hits a real URL through the normal fetch path with no mocking.
Run it, show it **ERRORs** with the guard message (not a timeout, not a pass), paste that
output verbatim, then delete the test and show the suite green again.
​
---
​
## TASK 3 — CONFIRM THE TEN WORKED EXAMPLES
​
Making `foreign_host` fail closed required adding `"domain"` to evidence in all ten spec
worked examples. Those tests previously passed *because* the disqualifier was inert —
exactly the situation where an expected value quietly gets adjusted to match new behaviour.
​
Print the asserted expected score for each example, in order. They must still be:
​
```
65, 90, 63, 35, 0, 0, 0, 0, 65, 10
```
​
Paste the grep or test output showing the actual asserted values. If any differs, state
which, from what, to what, and why the new value is correct per the rubric.
​
---
​
## TASK 4 — INFRASTRUCTURE PROOFS
​
Run each and paste literal output with `EXIT=`:
​
1. `docker compose ps` — `db` and `redis` healthy **with published host ports**, plus
   `web` / `worker` / `beat`.
2. Fresh-database migration, because a schema that only works on an already-migrated
   database is a deploy-day failure:
   ```bash
   createdb st_migrate_probe
   DATABASE_URL=postgres://<user>@127.0.0.1:5432/st_migrate_probe python manage.py migrate ; echo "EXIT=$?"
   dropdb st_migrate_probe
   ```
   The output must list your own apps — `accounts`, `audit_logs`, `companies`, `jobs` —
   not only `admin`/`auth`/`contenttypes`/`sessions`.
3. `python manage.py check --deploy --settings config.settings.prod` with a
   realistic-length `SECRET_KEY` exported, so the W009 dummy-key warning disappears.
​
---
​
## TASK 5 — LIVE SMOKE TEST
​
554 tests pass against fixtures — that is the code tested against the internet we
imagined. This tests it against the real one, and it is the single most valuable step in
this prompt.
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
For each, paste: the real company name and website, which strategies ran, every candidate
with its score, and the full scoring trail for the winner. Then state whether the outcome
is correct — and if a score looks wrong, name the rule that misfired.
​
**A wrong score found here is a success for this task.** Report it; do not tune the rubric
to hide it.
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
1. `throttle.py` ≥ 95%; the `ThrottleUnavailable` raise path tested.
2. `apps/career_detection/services.py` at **100% line and branch**, with each remaining
   partial branch either tested or deleted — no new pragma, no deleted test.
3. Network guard asserts its patch target exists; the Playwright question answered
   explicitly; guard demonstrated ERRORing on a real URL, then reverted, suite green.
4. Ten worked-example scores confirmed unchanged, or each change justified.
5. `docker compose ps` healthy with published ports; fresh-DB `migrate` lists your own
   apps and succeeds; `check --deploy` zero issues.
6. Live smoke done for all five kinds, plus the admin approval before/after.
7. Suite green, total coverage ≥ 93%, ruff / black / mypy exit 0, `git status` clean.
​
## OUTPUT FORMAT
​
1. **THROTTLE COVERAGE** — Task 1, new tests by name, plus the coverage line for
   `services.py` and `throttle.py`.
2. **NETWORK GUARD** — Task 2, including the Playwright answer and the guard failure text.
3. **WORKED EXAMPLES** — Task 3, the ten values as printed by the code.
4. **INFRASTRUCTURE** — Task 4 output.
5. **LIVE SMOKE** — Task 5 in full, per company, plus the admin approval.
6. **FINAL GATE** — ruff / black / mypy / makemigrations / pytest, literal output, exit codes.
7. **DEVIATIONS** — every judgement call; anything this prompt got wrong about the repo.
​
If an item cannot be done, say so at the top of PART 1 with the blocking error pasted in
full. Do not fabricate output. A partial pass reported honestly is far more useful than a
full pass reported optimistically — and fabricated output is worse than no output, because
it destroys trust in every other line of the report.
​