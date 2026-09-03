# PROMPT A6 v3 — Exams domain (target: 70%)
​
> Paste this **entire file** as `prompt.md`.
> Read §0.1 before writing any code. It governs everything else.
> Scope: one new Django app. No frontend. No changes to the jobs domain except §0.2.
​
---
​
## 0. Context
​
**Repo:** `/Users/apple/Study_tracker` · Django 5.2.17 · DRF · Python 3.12.13 · Postgres 16 · Celery + Redis · macOS/zsh
**Always `source .venv/bin/activate` first.**
​
The jobs domain is complete and committed: ATS scraping (Greenhouse, Lever, Ashby, SmartRecruiters), HTML sanitization via `nh3`, trigram search, audit logging, admin review queue. Coverage gate is `fail_under = 88`.
​
**Decided in A5 and binding here:** trigram similarity (`pg_trgm`) is this project's **single** search mechanism. There is no full-text search. Exam search must use trigram too. **Do not introduce a second search mechanism** — no `SearchVectorField`, no `SearchVector`, no separate stored search column. This project already paid for having two mechanisms where one was silently unused and unmaintained.
​
Reuse this existing infrastructure rather than rebuilding it:
​
| Module | What to reuse |
|---|---|
| `core/locks.py` | `redis_lock`, raises `LockNotAcquired` |
| `apps/scraping/fetching.py` | `fetch`, `fetch_with_escalation`, `FetchResult`, `FetchError`, honours `FETCH_MAX_RESPONSE_BYTES` |
| `apps/scraping/robots.py` | robots.txt checking with a body cap |
| `apps/audit_logs` | `record(action, actor, instance, before, after, source)` |
| `apps/jobs/filters.py` | the trigram `filter_q` pattern — copy this shape exactly |
| `core/pagination.py`, `core/permissions.py`, `core/throttling.py`, `core/exceptions.py` | as-is |
| `core/models.py` | base model with `id` UUID, `created_at`, `updated_at`, soft delete |
​
---
​
## 0.1 🔴 Evidence rules — read this first
​
Every rule below exists because it was violated in this project and cost real time.
​
**Report only what the terminal printed.** Never state a number you did not read from output. This prompt deliberately contains **no expected test counts, no expected coverage figures, and no expected row counts** — because three times in this project a reported number turned out to be derived from the instructions rather than measured. If you are about to write a number you did not just read, stop.
​
**A command with no output is not a passing command.** Never chain a check with `&& echo $?` — with `&&` the `echo` only runs on success, so a failure looks like silence. This exact mistake hid a failing `migrate --check`. Put every command and its `echo` on separate lines.
​
**Paste verbatim tails, not summaries.** "Gates pass" is not a result. Paste the actual last lines of the actual output.
​
**Stop and report when a result contradicts the plan.** Do not pick the interpretation that lets work continue. If a value does not match your expectation, question the expectation — **never edit production code to make a number match.** That has happened here twice.
​
**Never delete a test to make a suite green.** A failing test after a change is that change's cost becoming visible. Delete one only alongside a written record of what was removed and why.
​
**Delete code; do not comment it out.** Git stores history. Tombstone comments left inside import blocks caused ruff failures last round.
​
**Never use `write` on a file that already exists.** Use `edit`. A `write` destroyed an API doc last round, and because that file was untracked it was unrecoverable.
​
**`git add` every new file as you create it.** An untracked file is invisible to `git diff` and unrecoverable if overwritten.
​
**Before every assertion, ask: would this still pass if the code under test did nothing?** If yes, it is not a test. This project has shipped `assert script_tags == 0` against empty strings, and a search test whose author wrote "the test would pass anyway."
​
**If your plan contains two steps that contradict each other, resolve it before editing files.** Last round's plan added a database trigger to maintain a column that the same plan dropped.
​
**Implement one section at a time.** Run the relevant tests after each before moving on.
​
---
​
## 0.2 A5 carry-over — three small items first
​
Do these before starting the exams app. Minutes each.
​
**a) Strengthen `test_search_contract` in `tests/test_jobs_services.py`.**
It currently creates a single job, so its three positive assertions (`Rust`, `Acme`, `Engineering`) would pass even if `filter_q` returned every row. Add a second decoy job whose title, company name, and department are all trigram-distant from the first, and assert the decoy is **excluded** from each positive query. The similarity threshold is 0.1, which is low — choose values empirically. If a decoy matches unexpectedly, print the computed similarity and pick more distant values rather than weakening the assertion.
​
**b) Confirm `docs/api_v1_jobs.md` is tracked.**
​
```bash
git ls-files docs/
```
​
If it is absent from that list, `git add` it and say so. It was reported as "recovered from git" last round while actually being untracked.
​
**c) Investigate the Figma `work_mode` anomaly.**
A live Greenhouse scrape of Figma returned 160 jobs with `work_mode` empty for **every single one**: `Counter({'': 160})`. Ashby and Lever both populate it. Either Greenhouse's `location.name` for this board carries no remote/hybrid signal (in which case empty is correct and should be recorded as expected), or `work_mode_from_text` is not receiving what it should. Determine which, with output:
​
```bash
curl -s "https://boards-api.greenhouse.io/v1/boards/figma/jobs?content=true" | python -c "import sys, json; from collections import Counter; d = json.load(sys.stdin); jobs = d.get('jobs') or list(); print('count:', len(jobs)); print(Counter(str((j.get('location') or dict()).get('name')) for j in jobs).most_common(12))"
```
​
Report the finding. Only change parser code if the data shows a signal is being dropped.
​
---
​
## 1. Reality check before you write a scraper
​
The jobs domain works because ATS providers publish clean JSON at stable URLs. **Indian government exam sources are nothing like that.** Do not assume the jobs architecture transfers.
​
What these sources actually are:
- HTML pages with table layouts that change without notice
- Notifications published as **PDFs**, sometimes scanned images with no text layer
- Dates given as "tentative", revised repeatedly, sometimes contradicting the PDF that announced them
- Corrigendum PDFs that amend earlier PDFs
- No API, no stable IDs, no pagination contract
​
**Therefore A6 is a data-model and API milestone, not a scraping milestone.** Build the schema, the seed data, the API, and a defensive PDF text extractor. Automated end-to-end scraping of live government sites is explicitly **out of scope** — it belongs to a later milestone with human review in the loop.
​
The seed data in §3 is the real data source for this milestone. Treat it as authoritative and hand-curated.
​
---
​
## 2. Models — `apps/exams/models.py`
​
Create a new app: `python manage.py startapp exams apps/exams`. Register it in `INSTALLED_APPS`. Inherit from the existing base model in `core/models.py` so UUID primary keys, timestamps, and soft delete come for free.
​
### 2.1 `ConductingBody`
​
The organisation that runs exams.
​
- `name` — e.g. "Union Public Service Commission"
- `short_name` — e.g. "UPSC"
- `slug` — unique
- `body_type` — TextChoices: `central`, `state`, `banking`, `railway`, `defence`, `testing_agency`
- `state` — blank for central bodies
- `website` — URL
- `is_active`
​
### 2.2 `Exam`
​
The recurring exam itself, independent of any year.
​
- `name`, `short_name`, `slug` (unique)
- `conducting_body` — FK, `on_delete=PROTECT`
- `category` — TextChoices: `civil_services`, `banking`, `railway`, `ssc`, `teaching`, `defence`, `engineering`, `medical`, `law`, `state_psc`, `other`
- `level` — TextChoices: `national`, `state`
- `description` — text
- `official_url`
- `typical_month` — small int, nullable; the month the notification usually appears, for "expected soon" UI
- `is_active`
- Index on `(category, level)` and a trigram index on `name` mirroring `job_title_trgm`
​
### 2.3 `ExamCycle`
​
One year's run of an exam. This is where nearly all volatile data lives.
​
- `exam` — FK, `related_name="cycles"`
- `year` — int
- `cycle_label` — e.g. "2027", "2027 Tier-I", "CGL 2027"
- `status` — TextChoices: `announced`, `notification_out`, `applications_open`, `applications_closed`, `admit_card_out`, `exam_conducted`, `result_out`, `cancelled`, `postponed`
- Dates, all nullable: `notification_date`, `application_start`, `application_end`, `fee_last_date`, `correction_window_start`, `correction_window_end`, `result_date`
- `vacancy_count` — nullable int
- `official_notification_url`, `notification_pdf_url`
- `source_url` — where this record's data came from
- `extraction_confidence` — 0–100, with a check constraint, matching the jobs domain
- `verified_by_human` — boolean, default `False`
- `is_published` — boolean, default `False`
- `notes` — text, for corrigendum context
- Unique constraint on `(exam, year, cycle_label)`
- Index on `(status, -application_end)` and `(is_published, -notification_date)`
​
**Publication rule, and it is not optional:** a cycle may only have `is_published=True` when `verified_by_human=True`. Enforce this at the service layer and cover it with a test. Wrong exam dates are worse than missing exam dates — a student who misses an application window because of a scraped date has been actively harmed. Never auto-publish machine-extracted dates.
​
### 2.4 `ExamStage`
​
Exams have multiple stages with their own dates. Do not flatten these into `ExamCycle`.
​
- `cycle` — FK, `related_name="stages"`
- `name` — e.g. "Prelims", "Mains", "Interview", "Tier-I", "Skill Test", "PET", "PST", "Document Verification"
- `stage_order` — int
- `mode` — TextChoices: `online_cbt`, `offline_omr`, `descriptive`, `interview`, `physical`, `document`
- `date_start`, `date_end` — nullable; a range because many stages span multiple days across shifts
- `is_date_tentative` — boolean, default `True`
- `admit_card_date`, `city_intimation_date`, `result_date` — nullable
- `duration_minutes` — nullable int
- `total_marks` — nullable int
- `negative_marking` — text, blank allowed, e.g. "1/3 per wrong answer"
- `is_qualifying_only` — boolean; true for stages whose marks do not count toward the final merit
- Unique constraint on `(cycle, stage_order)`
​
### 2.5 `ExamEligibility`
​
Attach to `Exam`, not `ExamCycle`, with an optional `cycle` FK for the year a rule changed. Most rules are statutory and stable.
​
- `exam` — FK, `related_name="eligibility"`
- `cycle` — FK, nullable; set only when a rule is cycle-specific
- `min_age`, `max_age` — nullable ints
- `age_as_on_date` — the reference date for age computation. **This matters and is commonly got wrong:** UPSC uses **1 August** of the exam year; SSC uses **1 January**. Store it, do not hardcode it.
- `age_relaxation` — JSON. Statutory values in years:
​
| Category | Relaxation |
|---|---|
| SC / ST | +5 |
| OBC (non-creamy layer) | +3 |
| PwBD — General | +10 |
| PwBD — OBC | +13 |
| PwBD — SC/ST | +15 |
| Ex-servicemen | +3 (after deducting service rendered) |
| J&K domicile (specified period) | +5 |
​
- `attempts_general`, `attempts_obc`, `attempts_sc_st`, `attempts_pwbd` — nullable ints. **`null` means unlimited, not zero.** For UPSC CSE: General 6, OBC 9, SC/ST `null`, PwBD (Gen/OBC) 9. Document this convention in a docstring and cover it with a test, because a `null`-means-unlimited field read as zero would tell a student they cannot apply.
- `min_qualification` — text
- `allow_final_year_appearing` — boolean; true for UPSC CSE and SSC CGL, and students filter heavily on it
- `nationality_note` — text
- `physical_standards` — JSON, nullable; height, chest, vision, running, for defence and police exams
- `verified_by_human` — boolean, default `False`
- `source_url`
​
Provide a **pure function** `compute_effective_max_age(eligibility, category, is_pwbd, is_ex_serviceman, service_years=0)` in `apps/exams/services.py`. No database writes. It must be a pure function so it is cheap to test exhaustively, and its tests must cover each relaxation row above, the combined PwBD tiers, and the ex-servicemen deduction.
​
### 2.6 `ExamDateChange`
​
An append-only record of every date that moves. Government exam dates shift constantly, and "what changed and when" is the single most valuable thing this app can offer.
​
- `cycle` — FK, `related_name="date_changes"`
- `stage` — FK, nullable
- `field_name` — the field that changed
- `old_value`, `new_value` — both text, so any field type can be recorded
- `changed_at` — datetime
- `source_url`
- `detected_by` — TextChoices: `scrape`, `human`, `corrigendum`
- `note` — text
​
Write an `ExamCycle` update service that records one `ExamDateChange` row per changed date field, plus an `apps.audit_logs` entry. **Never mutate a date silently.**
​
### 2.7 `SavedExam`
​
- `user` — FK to `settings.AUTH_USER_MODEL`
- `exam` — FK
- `notify` — boolean, default `True`; the hook for the email notifications in a later milestone
- Unique constraint on `(user, exam)`
​
---
​
## 3. Seed data — `apps/exams/management/commands/seed_exams.py`
​
Seed roughly **45 exams** with their conducting bodies, at least one cycle each for the current or upcoming year, stages, and eligibility. This is hand-curated reference data, not scraped, so mark it `verified_by_human=True` and `is_published=True`.
​
Cover this spread:
​
- **UPSC** — Civil Services (Prelims / Mains / Interview), CDS, NDA, CAPF AC, Engineering Services, Combined Medical Services, IFS
- **SSC** — CGL (Tier-I / Tier-II), CHSL, MTS, GD Constable, JE, Stenographer, CPO
- **Banking** — IBPS PO, IBPS Clerk, IBPS SO, IBPS RRB (Officer Scale I, Office Assistant), SBI PO, SBI Clerk, RBI Grade B, RBI Assistant, NABARD Grade A
- **Railway** — RRB NTPC, RRB Group D, RRB ALP, RRB JE, RPF Constable
- **Teaching** — CTET, UGC NET, CSIR NET, KVS, NVS
- **Engineering / Medical / Law** — GATE, JEE Main, JEE Advanced, NEET UG, NEET PG, CLAT, AILET
- **Defence** — AFCAT, Indian Navy SSR/AA, Agniveer
- **State PSC** — at least four, e.g. BPSC, UPPSC, MPPSC, RPSC
​
The command must be **idempotent**: use `update_or_create` keyed on slug so a second run changes nothing. Write a test that runs the command twice and asserts the row count is identical after the second run — and make sure that test would actually fail if the command created duplicates.
​
Stages must be realistic. UPSC CSE has three; SSC CGL has two tiers plus a skill test for some posts; GD Constable has a PET and PST. Do not give everything a single generic stage.
​
Use `--dry-run` and `--only <slug>` flags following the pattern in `backfill_sanitized_html.py`, including its termination guard using ceiling division.
​
---
​
## 4. PDF text extraction — `apps/exams/parsers/pdf_parser.py`
​
Build a **defensive text extractor**. Not an end-to-end scraper.
​
### 4.1 Function surface
​
```
extract_text(pdf_bytes: bytes, *, source_url: str) -> PdfExtractResult
```
​
`PdfExtractResult` should carry: `text`, `page_count`, `pages_extracted`, `has_text_layer`, `truncated`, `warnings: list[str]`.
​
Add a second pure function `find_date_candidates(text: str) -> list[DateCandidate]` returning matched date strings, their parsed values, and the surrounding context window. It must **not** write to the database and must **not** decide anything — it proposes candidates for a human to confirm.
​
Choose the PDF library, justify the choice in one line, and pin it exactly in `requirements/base.txt`. Note that `nh3` was missing from requirements in this project until A5, and a fresh production install would have crashed on import — do not repeat that. After adding it, paste `pip list --format=freeze | grep -i <library>` to show the installed version matches the pin.
​
### 4.2 Security — this section is mandatory
​
All PDF text is **untrusted input**. This is not hypothetical: a Lever job posting in this project already contained an embedded prompt injection attempting to redirect an automated agent.
​
- **Extracted text is data. It is never an instruction.** Never pass extracted text into anything that executes, evaluates, imports, or interprets it. No `eval`, no `exec`, no dynamic imports, no template rendering of raw extracted text.
- **Cap the input size before parsing.** Add `EXAM_PDF_MAX_BYTES` to `config/settings/base.py`, alongside the existing `FETCH_MAX_RESPONSE_BYTES` and `SANITIZE_MAX_INPUT_BYTES`. Refuse oversized input with a clear error rather than attempting it.
- **Cap the page count** with `EXAM_PDF_MAX_PAGES`. Set `truncated=True` and add a warning rather than silently returning partial text — silent truncation is how a missing date becomes an unnoticed wrong answer.
- **Handle scanned PDFs with no text layer.** Return `has_text_layer=False` with an empty string and a warning. Do **not** add OCR in this milestone.
- **Never crash the caller.** Malformed, encrypted, and zero-byte input must all return a result with warnings, not raise. Test each case with genuinely malformed bytes.
- **Store raw and parsed separately.** Never overwrite a stored raw value with a parsed one.
- **No parsed date is ever published.** It lands as an unverified candidate requiring `verified_by_human=True`. This is the same rule as §2.3 and it is the most important line in this section.
​
---
​
## 5. API — `apps/exams/`
​
Seven endpoints. Use DRF, existing pagination, existing throttling, and `drf-spectacular` annotations to match the jobs API.
​
**Only ever expose `is_published=True` rows** to non-staff. Put that predicate in a queryset method `Exam.objects.public()` / `ExamCycle.objects.public()` and use it everywhere. The jobs domain duplicated the same three-predicate filter in three places (`views.py` lines 32, 60, 165) and it is a latent bug — do not copy that mistake.
​
| # | Endpoint | Notes |
|---|---|---|
| 1 | `GET /api/v1/exams/` | List with filters below |
| 2 | `GET /api/v1/exams/<slug>/` | Detail with nested cycles, stages, eligibility |
| 3 | `GET /api/v1/exams/cycles/` | Cycle list, filterable by exam / status / year |
| 4 | `GET /api/v1/exams/cycles/<uuid>/` | Cycle detail with stages and date-change history |
| 5 | `GET /api/v1/exams/calendar/` | **Flat event stream** — see below |
| 6 | `POST` / `DELETE /api/v1/exams/<slug>/save/` | Authenticated; idempotent both ways |
| 7 | `GET /api/v1/exams/saved/` | The requesting user's saved exams |
​
### 5.1 Filters on the list endpoint
​
- `q` — **trigram only**, copying `apps/jobs/filters.py`. Searches exam name, short name, and conducting body name. It does **not** search `description`. Use the same threshold as the jobs domain and the same sub-3-character `icontains` fallback on the same fields. Document this contract in `docs/api_v1_exams.md` and enforce it with a contract test built like the strengthened `test_search_contract` from §0.2a — including a decoy row that must be excluded.
- `body` — conducting body slug, comma-separated
- `category`, `level` — comma-separated enum values
- `status` — filters on the latest cycle's status
- `applications_open` — boolean; cycles where today falls between `application_start` and `application_end`
- `upcoming_within_days` — int; any stage or application date inside the window
- `allow_final_year` — boolean, from eligibility
- `ordering` — allowlist only, rejecting anything else with **400**, matching the jobs API behaviour
​
### 5.2 The calendar endpoint
​
Return a **flat list of events**, not nested exams. The frontend renders a calendar and must not have to walk a tree to find dates.
​
Each event: `date`, `event_type`, `exam_name`, `exam_slug`, `cycle_label`, `stage_name` (nullable), `is_tentative`, `official_url`.
​
`event_type` values: `notification`, `application_start`, `application_end`, `fee_last_date`, `correction_start`, `correction_end`, `admit_card`, `stage_exam`, `stage_result`, `result`.
​
Accept `from` and `to` date parameters, defaulting to a sensible window. Sort by date ascending. Skip null dates entirely rather than emitting placeholder events. Carry `is_tentative` through from `ExamStage.is_date_tentative` — a tentative date shown as firm is a real harm to a student planning around it.
​
---
​
## 6. Celery — `apps/exams/tasks.py`
​
Use `queue="exams"` so exam work cannot starve the scraping queue.
​
- `refresh_exam_cycle(cycle_id)` — fetch the source, extract candidates, record `ExamDateChange` rows, **never publish**
- `refresh_all_active_exams()` — fan out over published cycles with open or upcoming dates
​
Requirements:
- Wrap each task in `redis_lock` from `core/locks.py` and handle `LockNotAcquired` by returning cleanly, following `apps/scraping/tasks.py`
- `max_retries=0`, matching `scrape_company`
- Register a beat schedule entry in `config/celery.py`
- Every task must log its outcome and write an `apps.audit_logs` record
​
Test these with the mock pattern the jobs suite already requires: patch `fetch`, the parser, and the service layer at their **import site in the tasks module**, not at their definition. Tests must not make network calls.
​
---
​
## 7. Tests
​
Add `apps/exams/tests/`. The coverage gate is `fail_under = 88` and applies to the whole project, so the new app must carry real tests, not filler.
​
Required coverage:
​
1. **Model constraints** — unique `(exam, year, cycle_label)`; unique `(cycle, stage_order)`; unique `(user, exam)`; the `extraction_confidence` range constraint. Each must assert the database actually rejects the bad row.
2. **The publication rule** — `is_published=True` with `verified_by_human=False` must be refused. This is the single most important test in A6.
3. **`compute_effective_max_age`** — one case per relaxation row in §2.5, plus PwBD tiers and the ex-servicemen service deduction.
4. **Attempts `null` semantics** — assert `null` reads as unlimited and is never presented as zero.
5. **`age_as_on_date`** — assert UPSC (1 Aug) and SSC (1 Jan) produce different eligibility for the same date of birth. If they produce the same answer, the field is not being used.
6. **Search contract** — `q` matches name, short name, and conducting body; does **not** match description; decoy row excluded; short-query fallback covered on the same fields.
7. **Calendar flattening** — a cycle with stages and multiple dates produces the expected event count and types; null dates produce no events; `is_tentative` propagates.
8. **`ExamDateChange`** — changing a date writes exactly one row with correct old and new values; changing nothing writes none.
9. **Seed idempotency** — run twice, assert identical counts, and confirm the test would fail on duplicate creation.
10. **PDF parser** — oversize input refused; page cap sets `truncated=True`; no text layer returns `has_text_layer=False`; malformed, encrypted, and zero-byte input return warnings rather than raising.
11. **Permissions** — unpublished cycles invisible to anonymous and non-staff users; save endpoints reject anonymous requests.
12. **Ordering allowlist** — an invalid `ordering` value returns 400.
​
For each test, apply the §0.1 check: *would this pass if the code did nothing?* Report your own count of assertions that survive that question.
​
Run `grep -c "assert True" ` over the new test files and paste the result.
​
---
​
## 8. Gates
​
Run exactly this, each command on its own line:
​
```bash
source .venv/bin/activate
black apps/ core/ config/ tests/
ruff check apps/ core/ config/ tests/
mypy apps/ core/ config/
python manage.py makemigrations --check --dry-run
echo "makemigrations exit: $?"
python manage.py migrate --check
echo "migrate exit: $?"
python manage.py showmigrations exams
pytest -q --cov=apps --cov=core --cov=config --cov-branch --cov-report=term-missing --durations=10
```
​
Required: ruff clean **without** `--fix` · mypy no errors · both migration exit codes `0` · every `exams` migration `[X]` · every test passing · coverage at or above the gate.
​
Paste the final `TOTAL` line, the `Total coverage:` line, and the `N passed` line **verbatim**. Report the test count your run produces and the delta from the previous run. Do not state a number before you have run it.
​
`pyproject.toml` `addopts` contains no `--cov`, so always pass the `--cov` flags explicitly or `coverage report` reads a stale `.coverage` file. That stale file cost a full round of debugging in A4.
​
If `black` or `ruff --fix` modifies a file, paste the diff. Three times in this project a gate silently rewrote source with no diff shown.
​
---
​
## 9. Commit at the end
​
Before A6, this repo went 34 files and several rounds without a commit, so `git diff` became useless for reviewing any single change and there was no rollback point.
​
When the gates are green:
​
```bash
git status --short
git add -A
git status --short
```
​
Check the staged list before committing. These must **not** be in it: `db.sqlite3`, `.coverage`, `celerybeat-schedule`, `htmlcov/`, `var/`, `.tmp/`. If any appear, add them to `.gitignore` first.
​
Then commit with a message naming the exams app, the migration, and the PDF library added.
​
---
​
## 10. Deliverables
​
1. §0.2 carry-over: strengthened jobs search contract test, `docs/` tracking confirmed, Figma `work_mode` finding reported
2. `apps/exams/` with all seven models and migrations applied
3. The publication rule enforced in services and covered by a test
4. `compute_effective_max_age` as a pure function with exhaustive relaxation tests
5. `seed_exams` command, idempotent, roughly 45 exams with realistic stages
6. `pdf_parser.py` with every §4.2 security control, and the PDF library pinned with `pip list` proof
7. Seven API endpoints with `public()` queryset methods used everywhere
8. `docs/api_v1_exams.md` — created with `write` (new file), then `git add`ed, documenting the search contract, the calendar event types, all filters, and the publication rule
9. Full test suite per §7, with your own count of non-vacuous assertions
10. Gates with verbatim output and an accounted-for test count
11. Commit per §9, with the staged file list pasted
12. Project completion percentage
​
---
​
## 11. Handing code to the user
​
The user pastes into zsh, and their paste path mangles text. When you give a command to run:
​
- Strips leading `# ` and indentation
- **Eats `}` before `]`**
- Collapses whitespace
- Mangles `\|` inside `grep` — use `grep -E "a|b"`
- Autolinks bare URLs
​
So: prefer `printf '%s\n' 'line' > file` over heredocs; use heredocs only as `<<'PYEOF'` starting at column 0; avoid `{ } [ ]` entirely in generated one-liners by using `dict()`, `list()`, and `chr(123)`; never use the `─` character, which has already caused `SyntaxError: invalid character '─' (U+2500)` here.
​
After writing any Python file, verify it parses:
​
```bash
python -c "import ast;ast.parse(open('PATH').read());print('SYNTAX OK')"
```
​
Keep runnable commands and quoted source in separate blocks.
​
---
​
## 12. Bug scorecard
​
Eight production bugs so far. **None was caught by the unit suite alone.**
​
| # | Bug | Caught by |
|---|---|---|
| 1 | Lever URL template pointed at the HTML page, not the API | live smoke |
| 2 | `FETCH_MAX_RESPONSE_BYTES` 3 MiB too small | live smoke |
| 3 | `ats_lever.py` `work_mode` hardcoded `""` | live smoke |
| 4 | `ats_lever.py` `job_type` hardcoded `""` | live smoke |
| 5 | `ats_ashby.py` + `ats_greenhouse.py` `work_mode` hardcoded `""` | live smoke |
| 6 | Migration `0003` never applied — 170 rows unsanitized | live smoke |
| 7 | `backfill_sanitized_html` infinite loop | hanging test + reading source |
| 8 | `nh3` missing from requirements — fresh prod install would fail at import | reading requirements |
​
The lesson is specific: **running real code against real data finds bugs; a green unit suite does not.** For A6 that means actually running `seed_exams`, actually calling the calendar endpoint, and actually feeding a real government notification PDF through the parser — then pasting what happened.
​
---
​
## 13. Roadmap
​
A6 targets **70%**. Remaining after this:
​
| Milestone | Scope | Target |
|---|---|---|
| A7 | Govt source ingestion with human review in the loop | 75% |
| A8 | Accounts, saved items, email notifications (SendGrid or SES) | 80% |
| A9 | Search, filters, performance, indexes | 86% |
| A10 | CI, deployment, monitoring | 90% |
| W1–W4 | Next.js website | 100% |
​
The stack is website-first: Django + DRF backend, **Next.js** frontend (no Flutter), email notifications (no FCM). Mobile apps are out of scope for the launch.
​