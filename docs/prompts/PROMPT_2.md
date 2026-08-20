# PROMPT 3 — Build Order Steps 5 + 6
​
**Career URL Detection Engine + Scrapling Fetch Layer**
​
- **Project:** `/Users/apple/Study_tracker`
- **Depends on:** Prompt 1 ✅ (scaffold/auth/audit) · Prompt 2 ✅ (companies + jobs domain — 316 tests, 90.70%)
- **Next:** Prompt 4 (Scrapling spiders + ATS connectors + ScrapeRun)
- **Note:** the Scrapling source repo is already present at `Scrapling-main/` in the project root. Section 0 tells you how to use it.
​
---
​
## ROLE
​
You are a senior Django backend engineer. Steps 1, 2 and 4 are COMPLETE and GREEN (316 tests, 90.70% coverage, ruff/black/mypy clean, `makemigrations --check` clean, `check --deploy` zero issues against prod settings, ops admin portal click-through verified).
​
Your job in this prompt: build the **career URL detection engine** — the system that takes a company's homepage and figures out where its job listings live, then hands ranked candidates to a human for approval.
​
**This is the first prompt that touches the internet.** You will introduce Scrapling as the single fetch layer for the entire project. Get this layer right — Prompt 4 (spiders / ATS connectors) and Prompt 5 (scheduler) are both built on top of it.
​
---
​
## 0. FIRST TASK — READ THE LOCAL SCRAPLING SOURCE
​
The Scrapling repository has been cloned to `Scrapling-main/` in the project root. **Before writing a single line of fetch code, read these files.** You must not guess a single Scrapling API signature — the source is right there.
​
| Path | Why you need it |
| --- | --- |
| `Scrapling-main/agent-skill/` | **Read this entire directory first.** It is Scrapling's own skill/instruction bundle written for AI agents. It is the authoritative usage guide. |
| `Scrapling-main/pyproject.toml` | Exact package version, the real extras names (confirm `fetchers` is correct), Python floor, dependency list |
| `Scrapling-main/scrapling/fetchers/` | Real constructor and method signatures for `Fetcher`, `DynamicFetcher`, `StealthyFetcher` and their session classes |
| `Scrapling-main/scrapling/parser.py` | `Selector` API — `.css()`, `.xpath()`, `find_all()`, `adaptive=True`, `auto_save`, `TextHandler` |
| `Scrapling-main/scrapling/spiders/` | `Spider` / `SitemapSpider` — needed for the sitemap strategy now, and heavily in Prompt 4 |
| `Scrapling-main/scrapling/core/` | Shared primitives, custom types, storage/adaptive-selector persistence |
| `Scrapling-main/scrapling/engines/` | How the browser engine is driven — informs the timeout/`network_idle`/`capture_xhr` options |
| `Scrapling-main/docs/` | Prose docs, options reference, caching / `crawldir` behavior |
| `Scrapling-main/AI_POLICY.md` | The project's own policy on AI usage — read and respect it |
| `Scrapling-main/LICENSE` | Copy verbatim into `THIRD_PARTY_LICENSES.md` |
| `Scrapling-main/tests/` | Shows the intended calling conventions; also a source of realistic HTML fixture ideas |
​
**In PART 6 of your report, list the exact API signatures you confirmed from the source** (constructor kwargs for each fetcher, the adaptive-selector options, the robots option name). If any instruction later in this prompt contradicts the actual source, **the source wins** — implement what the library really does and record the discrepancy in PART 6.
​
### 0.1 How the repo is used — a hard rule
​
`Scrapling-main/` is a **reference checkout, not project source code.**
​
1. **Never import from `Scrapling-main/`.** No `sys.path` hacks, no relative imports into it. Import the installed package (`import scrapling`) only.
2. **Never commit it.** Add to `.gitignore`:
   ```
   /Scrapling-main/
   ```
3. **Never ship it to Docker.** Add to `.dockerignore`:
   ```
   Scrapling-main/
   ```
   It would bloat the build context and let a stale local copy diverge from the pinned image.
4. **Install as a normal pinned dependency.** Read the version from `Scrapling-main/pyproject.toml` and pin that exact version in `requirements/base.txt`:
   ```
   scrapling[fetchers]==<version from pyproject.toml>
   ```
   Docker and CI install from the index — reproducible, small, no local state.
5. **Local dev install is your choice of either:**
   ```bash
   pip install "scrapling[fetchers]==<pinned>"     # preferred — matches CI/Docker exactly
   pip install -e "./Scrapling-main[fetchers]"     # only if you need to step through library code
   ```
   If you use the editable install locally, the pinned requirement must still be the PyPI one. State in PART 6 which you used.
6. After install, run once (needed for browser fetchers):
   ```bash
   scrapling install
   ```
7. If the index is unreachable and you must install from the local path in Docker, say so explicitly in PART 6 — do not silently switch the build to a local-path install.
​
---
​
## 1. GROUND RULES — READ BEFORE WRITING ANY CODE
​
1. **NO auto-approve, ever.** Detection produces `CareerCandidateUrl` rows with scores. A human approves one via the admin. Even a perfect-score Greenhouse board requires a click. Product rule, not a preference.
2. **NO machine learning, no LLM calls, no embeddings.** Detection is deterministic rules + scoring. Same HTML in → same score out, every time.
3. **NO live network in the test suite.** The Step 1 socket-blocking fixture stays ON for the whole suite. Every detection test runs against recorded HTML fixtures. The only permitted exception is a loopback-only allowlist for the fetch-wrapper integration tests (§8.1) — document it.
4. **Respect robots.txt** on every request. If robots disallows a path, skip it and record the skip in `DetectionRun.log`.
5. **Rate limit hard:** ≤10 requests/minute per domain, ≤25 total URL checks per detection run, 10s per-request timeout, 120s total run budget. A run that hits a budget stops cleanly and reports what it found — it does not raise.
6. **Blocked domains are absolute.** `BLOCKED_DOMAINS` from `apps/companies/enums.py`. Never fetch them, never create a candidate pointing at them, never follow a redirect into them.
7. **All Scrapling imports live in exactly ONE module** — `apps/scraping/fetching.py`. Detection code, strategies, tasks and admin must never `import scrapling`. Hard architectural rule so the library can be upgraded or swapped without touching business logic. There is a DoD check that greps for this.
8. Every mutating service writes an AuditLog row. Every service is `transaction.atomic()`. Type hints on 100% of functions. mypy stays clean.
9. **Do not change any frozen signature** from Prompt 2 (`docs/domain-model.md` §5). If you believe one must change, stop and report it in PART 6.
10. Do not modify Prompt 1 / Prompt 2 files except: `INSTALLED_APPS`, settings additions, `requirements/*`, `Dockerfile`, `docker-compose.yml`, `.gitignore`, `.dockerignore`, and filling in the existing `# PROMPT 3:` markers. Additive admin actions are allowed. Anything else — flag it in PART 6, do not change it.
11. `config/celery.py` `beat_schedule` stays **EMPTY** with its `# STEP 12` marker. Detection is triggered on demand (company creation, admin action, management command) — never on a schedule. Prompt 5 owns the schedule.
12. **Pre-flight:** before starting, run `make lint`, `make typecheck`, `make test` and paste the results at the top of PART 5. If anything is red from the previous session, fix that first and say so. Do not build on a red tree.
​
---
​
## 2. WHAT ALREADY EXISTS — REUSE, DO NOT REBUILD
​
### From Prompt 2 — `apps/companies`
- Models: `Company`, `CompanySource`, `CareerCandidateUrl`, `DetectionRun`
- Enums: `SourceInputType`, `CareerSourceType`, `DetectionStatus`, `ScrapeHealth`, `CandidateOrigin`, `CandidateStatus`
- Constants: `BLOCKED_DOMAINS`, `MIN_SCRAPE_INTERVAL_MINUTES`, `DEFAULT_SCRAPE_INTERVAL_MINUTES`, `MAX_CONSECUTIVE_FAILURES`, `MAX_BACKOFF_MINUTES`
- **`sniff_source_type_from_url(url) -> tuple[CareerSourceType, str]`** — FROZEN. Detection calls this on every candidate to fill `guessed_type` and `ats_identifier`. **Do not reimplement ATS pattern matching anywhere.**
- `approve_career_candidate`, `reject_career_candidate`, `set_manual_career_url`, `request_redetection` — FROZEN, already wired to the admin approval queue
- Exceptions: `CompanyError`, `DuplicateCompany`, `BlockedDomain`, `InvalidCompanyTransition`, `CandidateAlreadyDecided`, `DetectionNotApplicable`
- `CompanyQuerySet.pending_detection()`
​
### From Prompt 1 — `core/`
- `normalize_url(url)` — use for ALL candidate dedupe. Two strategies finding the same page must produce exactly one candidate row.
- `sha256_of(*parts)`, `client_ip(request)`
- `redis_lock(key, timeout, blocking_timeout)`, `LockNotAcquired`
- `TimeStampedModel`, `UUIDModel`, `SoftDeleteModel`
- `apps.audit_logs.services.record()` / `snapshot()`
​
### The markers you must fill in
```
apps/companies/services.py:187   # PROMPT 3: enqueue detect_career_url.delay(str(company.id)) here
apps/companies/services.py:467   # PROMPT 3: same (request_redetection)
apps/companies/admin.py:448      # PROMPT 3: "Run detection now" action goes here
```
Leave `apps/companies/admin.py:449` (`# PROMPT 5: "Scrape now"`) untouched.
​
---
​
## 3. SCOPE
​
### IN SCOPE
- **A.** Scrapling dependency, pinning, browser install, license notice, ignore files
- **B.** `apps/scraping/` — the fetch wrapper ONLY (`fetching.py`, `throttle.py`, `robots.py`, `exceptions.py`). No spiders, no ATS connectors, **no models, no migrations.**
- **C.** `apps/career_detection/` — 8 detection strategies, deterministic scoring, orchestrator, Celery tasks
- **D.** Admin: "Run detection now", candidate evidence display, DetectionRun log viewer, dashboard panel
- **E.** Management commands: `detect_career_url`, `detect_pending`
- **F.** Offline fixture harness + 11 end-to-end scenarios + full test suite
​
### OUT OF SCOPE — leave a `# PROMPT N:` marker only
​
| Feature | Prompt |
| --- | --- |
| Job spiders, ATS connectors (Greenhouse/Lever/Ashby/SmartRecruiters), `ScrapeRun` / `ScrapeError` models, XHR capture for job lists | PROMPT 4 |
| Celery Beat 5-hour cycle, `refresh_all_companies`, `scrape_company`, per-company locks, "Scrape now" | PROMPT 5 |
| Public REST APIs, search, filters | PROMPT 6 |
| Exams, eligibility, opportunities, reminders, FCM | PROMPT 7 |
​
**Do NOT extract jobs in this prompt.** Detection may read up to 5 job *titles* from a candidate page purely as evidence for the reviewer (`CareerCandidateUrl.sample_job_titles`). It must never create a `Job` row. `upsert_job` is not called anywhere in this prompt.
​
---
​
## 4. DEPENDENCY & INFRASTRUCTURE
​
### 4.1 Requirements
​
Replace the placeholder in `requirements/base.txt`:
```
# was: # scrapling[fetchers] — added in PROMPT 4 (apps/scraping)
scrapling[fetchers]==<exact version from Scrapling-main/pyproject.toml>
```
​
- Confirm the extras name against `Scrapling-main/pyproject.toml` before writing it.
- Do **NOT** add `scrapy`, `beautifulsoup4`, `requests`, `httpx`, `playwright`, or `selenium`. Scrapling covers fetching, parsing and the browser engine. If you believe another dependency is genuinely unavoidable, justify it in PART 6.
- Check Scrapling's own dependency list for conflicts with the existing pins (especially `lxml`, `orjson`, `pydantic`). Report any resolution in PART 6.
​
### 4.2 Browser install (worker only)
​
Browser fetchers need Chromium. The `web` image must NOT carry browsers; only `worker` (and `beat`, if it ever fetches) need them.
​
In `Dockerfile`, after pip install, in a worker-targeted stage or its own cached layer:
```dockerfile
RUN scrapling install
```
Accepted alternative: base the worker image on `pyd4vinci/scrapling` (browsers preinstalled). Pick one and document which in PART 6.
​
In `docker-compose.yml`:
- `worker`: `mem_limit: 2g` (browsers leak)
- add a named volume for Scrapling's adaptive-selector storage, mounted into `worker`, so learned selectors survive restarts
- `web` stays browser-free
​
### 4.3 License notice
​
Create `THIRD_PARTY_LICENSES.md` with Scrapling's BSD-3-Clause text and copyright line copied verbatim from `Scrapling-main/LICENSE`. Link it from `README.md`.
​
### 4.4 Ignore files
​
`.gitignore` → `/Scrapling-main/`  ·  `.dockerignore` → `Scrapling-main/`
​
Verify with `git status --porcelain` that nothing under `Scrapling-main/` is staged.
​
### 4.5 Settings — new block in `config/settings/base.py`
​
```python
# ---- Fetching (Scrapling wrapper) ----
FETCH_USER_AGENT = env("FETCH_USER_AGENT", default="StudyTrackerBot/1.0 (+https://<your-domain>/bot)")
FETCH_TIMEOUT_SECONDS = 10
FETCH_MAX_REDIRECTS = 5
FETCH_MAX_RESPONSE_BYTES = 3 * 1024 * 1024
FETCH_ROBOTS_OBEY = True
FETCH_ROBOTS_CACHE_SECONDS = 3600
FETCH_PER_DOMAIN_RATE = 10                   # requests per minute per domain
FETCH_PER_DOMAIN_JITTER_MS = (200, 900)
FETCH_ADAPTIVE_STORAGE_DIR = env("FETCH_ADAPTIVE_STORAGE_DIR", default="/data/scrapling")
FETCH_ALLOW_DYNAMIC = True
FETCH_ALLOW_STEALTHY = False                 # not used in detection; Prompt 4 flips this
​
# ---- Career detection ----
DETECTION_MAX_URL_CHECKS = 25
DETECTION_TOTAL_BUDGET_SECONDS = 120
DETECTION_MAX_CANDIDATES = 10
DETECTION_MIN_CANDIDATE_SCORE = 20
DETECTION_SAMPLE_TITLE_LIMIT = 5
DETECTION_COMMON_PATHS = [
    "/careers", "/career", "/jobs", "/job", "/join-us", "/join",
    "/work-with-us", "/open-positions", "/job-openings", "/openings",
    "/vacancies", "/hiring", "/we-are-hiring", "/company/careers",
    "/about/careers", "/en/careers",
]
DETECTION_COMMON_SUBDOMAINS = ["careers", "career", "jobs", "job", "work", "hiring"]
```
​
In `config/settings/test.py`: `FETCH_ALLOW_DYNAMIC = False` by default (tests opt in via fixture), and point `FETCH_ADAPTIVE_STORAGE_DIR` at a tmp path.
​
---
​
## 5. `apps/scraping/` — THE FETCH WRAPPER (the only Scrapling boundary)
​
No models, no migrations in this prompt.
​
### 5.1 `apps/scraping/exceptions.py`
​
Our own hierarchy. Scrapling exceptions must NEVER escape `fetching.py`.
​
```python
FetchError(Exception)          # base; carries .url and .code
FetchTimeout(FetchError)
FetchBlocked(FetchError)       # 403 / 429 / anti-bot wall
FetchNotFound(FetchError)      # 404 / 410
FetchServerError(FetchError)   # 5xx
FetchTooLarge(FetchError)
FetchRobotsDisallowed(FetchError)
FetchDomainBlocked(FetchError) # our BLOCKED_DOMAINS denylist
FetchBudgetExceeded(FetchError)
```
​
### 5.2 `apps/scraping/robots.py`
​
```python
def is_allowed(url: str, *, user_agent: str | None = None) -> bool
def sitemaps_for(domain: str) -> list[str]     # from robots.txt Sitemap: lines
```
​
- Fetch and parse `robots.txt` once per domain; cache in Redis for `FETCH_ROBOTS_CACHE_SECONDS`.
- Use Scrapling's bundled robots support (check the source for the exact option/helper name — it uses Protego). Do not add a new robots dependency.
- Missing or unparseable `robots.txt` ⇒ **allowed** (standard). 5xx on `robots.txt` ⇒ allowed, but log it.
- The `robots.txt` fetch does not count against `DETECTION_MAX_URL_CHECKS`, but DOES count against the rate limiter.
​
### 5.3 `apps/scraping/throttle.py`
​
```python
def acquire_slot(domain: str, *, rate_per_minute: int, timeout: float = 30.0) -> None
```
​
- Redis-backed token bucket keyed `throttle:{domain}`. Must work **across Celery workers** — per-process limiting is useless at 1000 companies.
- Sleeps until a slot frees; raises `FetchBudgetExceeded` if it would wait past `timeout`.
- Adds random jitter from `FETCH_PER_DOMAIN_JITTER_MS` after acquiring, so we never look like a metronome.
- Reuse the `core.locks` Redis connection handling. Do not open a second client pool.
​
### 5.4 `apps/scraping/fetching.py` — **THE ONLY FILE THAT IMPORTS SCRAPLING**
​
```python
class FetchMode(StrEnum):
    HTTP     = "http"        # Scrapling Fetcher, impersonate="chrome"
    DYNAMIC  = "dynamic"     # DynamicFetcher — real browser, JS executed
    STEALTHY = "stealthy"    # StealthyFetcher — anti-bot; disabled in this prompt
​
@dataclass(frozen=True)
class FetchResult:
    url: str                 # requested
    final_url: str           # after redirects
    status_code: int
    html: str
    selector: Any            # Scrapling Selector — the ONLY leaked library object
    fetcher_used: FetchMode
    elapsed_ms: int
    from_cache: bool
    escalation_reason: str    # "" when no escalation happened
    xhr_payloads: list[dict]  # empty in HTTP mode; populated in DYNAMIC when capture_xhr
​
    # helpers so callers never touch the Selector for common needs
    def links(self) -> list[tuple[str, str]]   # [(absolute_href, anchor_text)], deduped
    def title(self) -> str
    def text(self) -> str
    def json_ld(self) -> list[dict]            # parsed ld+json; must not raise on malformed
    def region_links(self, region: str) -> list[tuple[str, str]]  # "header"|"nav"|"footer"
```
​
#### Public functions
​
```python
def fetch(
    url: str, *,
    mode: FetchMode = FetchMode.HTTP,
    timeout: int | None = None,
    company: Company | None = None,
    obey_robots: bool | None = None,
    capture_xhr: bool = False,
) -> FetchResult
```
​
Order of operations — all mandatory:
1. `normalize_url()` the input.
2. Reject if the host or any parent domain is in `BLOCKED_DOMAINS` → `FetchDomainBlocked` (before any request).
3. If robots enabled and `not robots.is_allowed(url)` → `FetchRobotsDisallowed`.
4. `throttle.acquire_slot(domain)`.
5. Dispatch to the Scrapling fetcher for `mode`. `STEALTHY` raises unless `FETCH_ALLOW_STEALTHY`; `DYNAMIC` raises unless `FETCH_ALLOW_DYNAMIC`.
6. Abort if the response exceeds `FETCH_MAX_RESPONSE_BYTES` → `FetchTooLarge`.
7. **Re-check the final URL against `BLOCKED_DOMAINS`** — a redirect must not smuggle us into LinkedIn → `FetchDomainBlocked`.
8. Map status: 404/410 → `FetchNotFound`; 403/429 → `FetchBlocked`; 5xx → `FetchServerError`; 2xx/3xx → `FetchResult`.
9. Wrap every Scrapling/transport exception into ours. Nothing from the library leaks.
​
```python
def fetch_with_escalation(
    url: str, *, company: Company | None = None, timeout: int | None = None,
) -> FetchResult
```
Try `HTTP` first. Escalate to `DYNAMIC` **only** if the result looks JS-rendered:
- fewer than 5 anchors on the page, **or**
- visible text under 500 characters, **or**
- body contains an SPA root marker (`<div id="root">`, `<div id="app">`, `<app-root`) with no anchors
​
Set `escalation_reason` on the result. **Never escalate twice.** If `FETCH_ALLOW_DYNAMIC` is false, return the HTTP result unchanged.
​
```python
def head_ok(url: str, *, company: Company | None = None) -> tuple[bool, int]
```
Cheap existence probe for common-path / subdomain guessing. Prefer HEAD; fall back to a ranged GET on 405. Returns `(ok, status_code)`; never raises for ordinary HTTP failures.
​
```python
def session_for(domain: str) -> AbstractContextManager
```
A reusable session/connection pool for one domain within a single detection run — one pool per run, not per request. Use the real session class you found in `Scrapling-main/scrapling/fetchers/`.
​
#### Scrapling features you MUST use
- `Fetcher` with `impersonate="chrome"` for HTTP mode
- Session reuse per domain per run (see `session_for`)
- `adaptive=True` selectors with `auto_save` pointed at `FETCH_ADAPTIVE_STORAGE_DIR`, so a site redesign degrades instead of breaking
- `DynamicFetcher` with `network_idle=True` for escalation; `capture_xhr` plumbed through but unused here (Prompt 4 needs it)
- Scrapling's own response caching / `crawldir` checkpoint support, wired so tests can replay recorded fixtures (§8.1)
​
Use the **real** kwarg names from the source. If any name above differs, follow the source and note it in PART 6.
​
---
​
## 6. `apps/career_detection/` — THE DETECTION ENGINE
​
### 6.1 Strategy interface — `apps/career_detection/strategies/`
​
```python
class Strategy(Protocol):
    name: str          # matches a CandidateOrigin value
    cost: int          # rough request count, used for ordering
    def run(self, ctx: DetectionContext) -> list[RawCandidate]: ...
​
@dataclass
class RawCandidate:
    url: str
    origin: CandidateOrigin
    evidence: dict                 # strategy-specific proof; feeds scoring + reviewer UI
    http_status: int | None = None
    page_title: str = ""
    sample_job_titles: list[str] = field(default_factory=list)
```
​
`DetectionContext` carries: the `Company`, the `DetectionRun`, the shared fetch session, a URL-check budget counter, a deadline timestamp, the set of already-seen normalized URLs, the homepage `FetchResult`, and `log(step, **fields)` which appends structured entries to `DetectionRun.log`.
​
### 6.2 The 8 strategies, in execution order (cheapest first)
​
| # | Module | `CandidateOrigin` | What it does |
| --- | --- | --- | --- |
| 1 | `ats_links.py` | `ATS_PATTERN` | Scan the already-fetched homepage's outbound links for ATS hosts via `sniff_source_type_from_url`. **Zero extra requests.** Highest-value strategy — most companies just link out to their board. |
| 2 | `nav_links.py` | `HEADER_LINK` / `FOOTER_LINK` | Scan `<header>`/`<nav>`/`<footer>` regions for anchors whose text or href matches career keywords. Zero extra requests. Record which region matched (header scores higher than footer). |
| 3 | `robots_txt.py` | `ROBOTS_TXT` | Read `robots.txt`: collect `Sitemap:` URLs, plus any `Allow`/`Disallow` path containing a career keyword (a *disallowed* `/careers/` still proves the path exists). |
| 4 | `sitemap.py` | `SITEMAP` | Fetch sitemaps from step 3 plus `/sitemap.xml`, `/sitemap_index.xml`. Follow at most 2 index levels, cap 5000 URLs parsed. Filter for career keywords. Prefer *list* pages over individual postings. Use Scrapling's `SitemapSpider` where it fits. |
| 5 | `common_paths.py` | `COMMON_PATH` | `head_ok()` against `DETECTION_COMMON_PATHS`. Stop early once 3 paths resolve. |
| 6 | `subdomains.py` | `SUBDOMAIN_GUESS` | `head_ok()` against `DETECTION_COMMON_SUBDOMAINS` on the registrable domain. |
| 7 | `json_ld.py` | `JSON_LD` | For the top few candidates so far, fetch and look for `JobPosting` / `ItemList` JSON-LD. Strong positive signal; also harvests `sample_job_titles`. |
| 8 | `verify.py` | — | Not discovery: fetches top candidates that were only *guessed* (common path / subdomain), confirms 200, grabs `page_title` + up to `DETECTION_SAMPLE_TITLE_LIMIT` job-like link texts as evidence. |
​
**Short-circuit:** if strategy 1 finds a valid ATS board, **skip strategies 3–6** (still run 7–8 to verify). An ATS link is definitive; spending 20 requests guessing paths is waste.
​
### 6.3 `apps/career_detection/scoring.py`
​
```python
def score_candidate(*, url: str, evidence: dict) -> tuple[int, list[dict]]
```
​
**Pure function. No network, no DB, no clock.** Returns `(score_0_to_100, reasons)`, each reason `{"rule": str, "points": int, "detail": str}`. Must be **100% line+branch covered.**
​
**Positive rules**
​
| Rule | Points | Fires when |
| --- | --- | --- |
| `ats_host` | +40 | `sniff_source_type_from_url` returns a supported ATS with non-empty identifier |
| `json_ld_jobposting` | +30 | JSON-LD `JobPosting` or `ItemList` of postings found |
| `career_path_keyword` | +25 | path contains careers/jobs/openings/vacancies/hiring/join-us |
| `multiple_job_links` | +20 | ≥3 links that look like individual job postings |
| `career_subdomain` | +18 | host starts with `careers.` / `jobs.` / `work.` |
| `nav_header` | +15 | found in `<header>` / `<nav>` |
| `title_keyword` | +15 | `<title>` contains a career keyword |
| `nav_footer` | +10 | found in `<footer>` |
| `in_sitemap` | +10 | appeared in the sitemap |
| `http_200` | +5 | verified 200 |
| `explicit_no_openings` | +5 | page says "no open positions" / "no current openings" — still a real career page, just empty today |
​
**Negative rules**
​
| Rule | Points | Fires when |
| --- | --- | --- |
| `pdf_or_asset` | −40 | ends in .pdf/.doc/.docx/.jpg/.png |
| `noise_path` | −30 | contains blog/news/press/investors/privacy/terms/login/support |
| `workday` | −20 | Workday host (recognized, unsupported in Phase 1) |
| `single_posting` | −15 | looks like ONE job, not a list (job id/slug segment after a job keyword) |
| `deep_path` | −10 | path depth > 3 |
| `query_heavy` | −5 | more than 2 query params |
​
**Hard disqualifiers** — return score `0` with a single reason; the orchestrator discards these:
- host in `BLOCKED_DOMAINS`
- verified non-2xx status
- scheme not http/https
- host is not the company domain, a subdomain of it, or a recognized ATS host (blocks random third-party links)
​
Clamp final score to `0..100`. `score_reasons` is stored verbatim on the candidate row — the admin already renders this table, so a human can see exactly why something scored 87.
​
### 6.4 `apps/career_detection/services.py` — FROZEN SIGNATURES
​
```python
def run_detection(
    *, company: Company, actor: User | None = None,
    max_checks: int | None = None, dry_run: bool = False,
) -> DetectionRun
```
​
**Guards — raise before doing any work:**
- `company.input_type == DIRECT_CAREER` and already verified → `DetectionNotApplicable`
- `company.is_deleted` → `DetectionNotApplicable`
- a `DetectionRun` for this company is `RUNNING` and started < 10 min ago → `DetectionNotApplicable`. Use `core.locks.redis_lock(f"detect:{company.id}")`; on `LockNotAcquired` raise `DetectionNotApplicable`.
​
**Flow:**
1. Create `DetectionRun(status=RUNNING, started_at=now, triggered_by=actor)`. Set `company.detection_status = RUNNING`, `detection_attempts += 1`, `last_detection_at = now`.
2. Fetch the homepage via `fetch_with_escalation()`. On failure → run `status=FAILED`, `error_message` set, `company.detection_status = FAILED`, return. **Never raise out of the orchestrator for network failures.**
3. Run strategies in order, respecting the check budget and the 120s deadline. Log every step as `{"step", "url", "status", "elapsed_ms", "found", "note"}`. Append each strategy name to `strategies_used`.
4. Dedupe all `RawCandidate`s by `normalize_url()`, **merging** their `evidence` dicts — a URL found by both sitemap AND footer keeps both signals and scores higher.
5. Score every candidate. Discard below `DETECTION_MIN_CANDIDATE_SCORE`. Keep top `DETECTION_MAX_CANDIDATES`.
6. Persist `CareerCandidateUrl` rows (`bulk_create`, `status=PENDING`, linked to this run, `guessed_type`/`ats_identifier` from `sniff_source_type_from_url`). Respect `uniq_candidate_per_company`: if a URL already exists from a previous run, update score/evidence **only if the new score is higher**, and **never touch an already-decided row**.
7. Finalize: candidates found → `DetectionRun.status = NEEDS_REVIEW` and `company.detection_status = NEEDS_REVIEW`; none found → both `NOT_FOUND`. Set `finished_at`, `duration_ms`, `urls_checked`, `candidates_found`.
8. Audit-log `company.detection_completed` with outcome and candidate count.
​
`dry_run=True` runs everything but persists nothing — returns an unsaved `DetectionRun` with a populated `log`.
​
```python
def detection_summary(*, company: Company) -> dict
```
Read-only: latest run status, candidate count by status, top candidate + score, last error. Feeds the admin dashboard.
​
### 6.5 `apps/career_detection/tasks.py`
​
```python
@shared_task(
    bind=True, queue="scraping", max_retries=2,
    autoretry_for=(FetchServerError, FetchBlocked),
    retry_backoff=60, retry_jitter=True, acks_late=True,
)
def detect_career_url(self, company_id: str) -> dict
```
- Missing or deleted company → return `{"skipped": "gone"}`. Never crash.
- Catch `DetectionNotApplicable` → `{"skipped": <reason>}`.
- Return JSON-safe: `{"company": slug, "status": ..., "candidates": n, "urls_checked": n, "duration_ms": n}`.
- **Idempotent:** two concurrent invocations for one company must not both run — the Redis lock handles it; assert it in a test.
​
```python
@shared_task(queue="scraping")
def detect_pending_companies(limit: int = 50) -> dict
```
Fan out `detect_career_url` for `Company.objects.pending_detection()[:limit]`. **Do NOT add to `beat_schedule`.**
​
### 6.6 Fill in the Prompt 2 markers
​
- `apps/companies/services.py:187` (`add_company_from_main_website`) → enqueue `detect_career_url.delay(str(company.id))` via **`transaction.on_commit(...)`**. Enqueueing inside the transaction is a real bug — the worker can start before the row is visible.
- `apps/companies/services.py:467` (`request_redetection`) → same, also `on_commit`.
- Tests assert the task was *enqueued* (mock `.delay`), and assert it is **not** enqueued when the transaction rolls back.
​
### 6.7 Admin additions (additive only)
​
- `apps/companies/admin.py:448` → **"Run detection now"** action on `CompanyAdmin`. Enqueues per selected company; skips already-verified `DIRECT_CAREER` ones with a clear per-row message; reports counts via `message_user`.
- `CareerCandidateUrlAdmin`: render `evidence` / `score_reasons` as a readable table (rule · points · detail) and `sample_job_titles` as a bulleted list. **A reviewer must be able to decide in ~5 seconds without opening the URL.**
- `DetectionRunAdmin`: pretty-print the structured `log` as a step table (step / url / status / elapsed / found / note); `strategies_used` as chips.
- Admin dashboard: add a **"Detection"** panel — pending / running / needs_review / not_found / failed counts, each linking to a filtered changelist, plus the 10 most recent runs with durations. One aggregate query each; no N+1.
​
### 6.8 Management commands
​
```bash
python manage.py detect_career_url --company <slug> [--dry-run] [--max-checks N] [--json]
```
Runs detection **synchronously** (no Celery). Prints the step log as a table plus ranked candidates with scores and reasons. This is the primary debugging tool — make the output genuinely readable.
​
```bash
python manage.py detect_pending [--limit N] [--sync]
```
Queues (or with `--sync`, runs inline) detection for all `pending_detection()` companies. Prints a summary table.
​
---
​
## 7. WHAT "GOOD" LOOKS LIKE — worked examples
​
These become the fixture scenarios in §8.
​
| Scenario | Expected outcome |
| --- | --- |
| Homepage footer links to `boards.greenhouse.io/acme` | 1 candidate, origin `ATS_PATTERN`, `guessed_type=GREENHOUSE`, `ats_identifier="acme"`, score ≥ 85, strategies 3–6 skipped, ≤3 total requests |
| Homepage nav → `/careers` listing 8 job links | candidate `/careers`, origin `HEADER_LINK`, `multiple_job_links` + `career_path_keyword` fire, 5 sample titles captured |
| `robots.txt` has `Sitemap:`; sitemap has a `/jobs/` list page + 40 postings | list page ranks above every individual posting (`single_posting` penalty applied) |
| SPA homepage: `<div id="root">`, no anchors | escalates to `DYNAMIC` exactly once, `escalation_reason` recorded, candidates found from the rendered DOM |
| No careers page anywhere | run `NOT_FOUND`, company `NOT_FOUND`, 0 candidates, budget not exceeded, no exception |
| Only jobs link points at LinkedIn | LinkedIn candidate never created, skip recorded in the log, outcome `NOT_FOUND` |
| `careers.acme.com` resolves 200, homepage has no career link | candidate via `SUBDOMAIN_GUESS`, `career_subdomain` +18, verified 200 |
| `/jobs` page with JSON-LD `JobPosting` | `json_ld_jobposting` +30, sample titles harvested from the JSON-LD |
| 4 plausible candidates, different signals | all 4 persisted, ordered by score desc, ranked in admin, `uniq_approved_candidate_per_company` still enforced on approval |
| Homepage 500s | run `FAILED`, `error_message` set, company `FAILED`, task retried per `autoretry_for` |
| Same company detected twice | no duplicate candidate rows; higher score wins; already-decided rows untouched |
​
---
​
## 8. TESTS — offline, fixture-driven, ~90 new tests
​
### 8.1 The fixture harness (build this first)
​
`tests/fetch_fixtures.py`:
- `FakeFetchRegistry` mapping normalized URL → `(status_code, body, content_type)`, loaded from `tests/fixtures/detection/<scenario>/`.
- Each scenario dir has a `manifest.json` (`url → file, status`) plus raw `.html` / `.xml` / `.txt` files. **Real captured HTML**, hand-trimmed to a few KB — not synthetic soup. Realistic markup is the entire point; you can lift shapes from `Scrapling-main/tests/`.
- A pytest fixture `fetch_scenario(name)` that monkeypatches `apps.scraping.fetching.fetch`, `fetch_with_escalation` and `head_ok` to serve from the registry, records the exact call sequence, and **asserts no unregistered URL was requested**.
- A separate module exercises the **real** `fetching.py` against a loopback WSGI/`pytest-httpserver` on `127.0.0.1`, so status mapping, redirect re-check, size cap, robots and throttle are genuinely tested rather than mocked away. Extend the socket guard's allowlist to loopback only and document it in PART 6.
​
### 8.2 Scenario directories
​
```
tests/fixtures/detection/
  greenhouse_footer/     homepage.html, robots.txt
  own_careers_page/      homepage.html, careers.html
  sitemap_jobs/          robots.txt, sitemap.xml, jobs_list.html, posting_1..3.html
  spa_homepage/          homepage_shell.html, homepage_rendered.html
  no_careers/            homepage.html, robots.txt
  linkedin_only/         homepage.html
  careers_subdomain/     homepage.html, careers_subdomain.html
  jsonld_jobs/           homepage.html, jobs.html
  multi_candidate/       homepage.html, careers.html, jobs.html, sitemap.xml, work_with_us.html
  homepage_500/          manifest only, status 500
  robots_disallow/       robots.txt (disallows /careers), homepage.html
```
​
### 8.3 Required coverage
​
**`scoring.py` — 100% line+branch**
- every positive rule fires in isolation with exact expected points
- every negative rule fires in isolation
- every hard disqualifier returns 0 with the right reason
- clamping at both ends (stacked positives cap at 100, stacked negatives floor at 0)
- **determinism:** same input twice → identical score AND identical `reasons` list order
- parametrized ranking: list page beats individual posting; ATS beats own page; header beats footer
​
**`run_detection` — 100% line+branch**
- all 11 scenarios from §7, asserting run status, company `detection_status`, candidate count, top candidate URL/origin/score band, `strategies_used`, `urls_checked`
- ATS short-circuit: assert strategies 3–6 never ran (check `strategies_used` **and** the recorded fetch call list)
- budget: a scenario with 60 discoverable URLs stops at `DETECTION_MAX_URL_CHECKS`, run still completes with candidates
- deadline: monkeypatch the clock so the deadline passes mid-run → clean stop, partial results kept, no exception
- guards: verified `DIRECT_CAREER` company → `DetectionNotApplicable`; deleted company → same
- concurrency: with the lock held, second call raises `DetectionNotApplicable`; assert only one `DetectionRun` row
- re-run idempotence: same scenario twice → no duplicate candidates, higher score wins, `APPROVED`/`REJECTED` rows untouched
- `dry_run=True` → zero DB writes (row-count snapshot or `django_assert_num_queries`), log still populated
- exactly one AuditLog row per run
​
**`fetching.py`** (loopback server)
- status mapping: 404→`FetchNotFound`, 403→`FetchBlocked`, 429→`FetchBlocked`, 500→`FetchServerError`, 200→`FetchResult`
- **redirect into a blocked domain → `FetchDomainBlocked`** (the critical security test)
- response over `FETCH_MAX_RESPONSE_BYTES` → `FetchTooLarge`
- robots disallow → `FetchRobotsDisallowed`; missing robots → allowed; robots 500 → allowed
- blocked-domain input → `FetchDomainBlocked` with **zero requests made**
- timeout → `FetchTimeout`
- **no Scrapling exception ever escapes** — parametrized test raising each Scrapling error class from a patched fetcher, asserting our type comes out
- `links()` returns absolute deduped URLs; `json_ld()` parses valid and survives malformed JSON without raising; `region_links()` distinguishes header/nav/footer
- `fetch_with_escalation`: escalates on each of the 3 SPA triggers, does NOT escalate on a normal page, never escalates twice, honors `FETCH_ALLOW_DYNAMIC=False`
- `STEALTHY` raises while `FETCH_ALLOW_STEALTHY=False`
​
**`throttle.py`**
- 11 requests to one domain in a minute: the 11th waits (fake clock — **no real `sleep`**)
- two domains do not block each other
- `timeout` exceeded → `FetchBudgetExceeded`
​
**`robots.py`**
- parses `Sitemap:` lines; caches per domain (second call issues no request); survives malformed content
​
**tasks**
- missing/deleted company → `{"skipped": "gone"}`, no exception
- `DetectionNotApplicable` → skipped dict, task does not fail
- `FetchServerError` → retry attempted (assert `self.retry` called)
- `add_company_from_main_website` enqueues **on commit** (assert `.delay` called once with the right id; assert NOT called when the transaction rolls back)
- `request_redetection` enqueues too
​
**admin**
- "Run detection now" enqueues per selected company, skips ineligible with a message
- candidate change view renders `score_reasons` + `sample_job_titles`
- DetectionRun change view renders the step log without error
- dashboard detection panel shows correct counts
- changelist query budgets hold (no N+1 from the new panel)
​
**commands**
- `detect_career_url --company X --dry-run` prints the log, writes nothing
- `--json` output parses
- unknown slug → non-zero exit
- `detect_pending --sync` processes only pending companies
​
### 8.4 Non-negotiable test rules
- Socket guard stays ON for the whole suite; only loopback is allowlisted, and only for §8.1's integration module.
- No test may reach a real external host. A test that would need one is a design failure — record the fixture instead.
- No `time.sleep()` anywhere in tests. Fake the clock.
​
---
​
## 9. DOCS
​
### `docs/career-detection.md` (new)
- the 8 strategies in order, with cost and what each proves
- the full scoring rubric as a table — **must match `scoring.py` exactly**
- the hard disqualifiers
- a worked example: real company → step log → 3 candidates → scores → why the winner won
- runbook: "how to debug a company that failed detection" using `manage.py detect_career_url --dry-run`
- politeness policy: robots, rate limits, budgets, user agent, blocked-source list and the reason
​
### `docs/fetching.md` (new)
- the `FetchMode` ladder and the exact escalation triggers
- **why all Scrapling imports are confined to one module**, and the rule for keeping it that way
- our exception hierarchy and what each means operationally
- how to add a recorded fixture for a new site
- the `Scrapling-main/` reference-checkout policy (not committed, not imported, not shipped to Docker) and the pinned version
​
### Updates
- `docs/domain-model.md` — add `run_detection`, `fetch`, `score_candidate` to the frozen-signature section. Add the note: **never put `description` in `manually_edited_fields`** — it permanently blinds the scraper to real changes on that job.
- `README.md` — new apps, the two new commands, browser install requirement for workers, links to both new docs and `THIRD_PARTY_LICENSES.md`.
​
---
​
## 10. DEFINITION OF DONE — all must be literally verified
​
1. Pre-flight lint/typecheck/test results pasted at the top of PART 5, green.
2. `makemigrations --check --dry-run` → **no changes** (`apps/scraping` and `apps/career_detection` have no models).
3. Full suite green. Total coverage **≥ 88%**.
4. **100% line+branch** on `career_detection/scoring.py::score_candidate` and `career_detection/services.py::run_detection`.
5. `apps/scraping/fetching.py` coverage ≥ 95%.
6. `grep -rn "import scrapling\|from scrapling" apps/ core/ config/ tests/` returns **exactly one file**: `apps/scraping/fetching.py`. Paste the output.
7. `git status --porcelain | grep Scrapling-main` returns **nothing** (reference checkout not committed).
8. ruff, `black --check`, mypy: all clean, no new blanket ignores.
9. `check --deploy --settings config.settings.prod` → 0 issues.
10. Zero outbound network in the suite except the documented loopback allowlist.
11. `docker compose build` succeeds; `worker` has Chromium (prove it: `docker compose exec worker scrapling --version` or equivalent); `web` image does **not** ship browsers.
12. `beat_schedule` still EMPTY with its `# STEP 12` marker.
13. All Prompt 2 frozen signatures unchanged — diff against `docs/domain-model.md` §5 and show it.
14. **LIVE SMOKE TEST** — outside CI, network on, run `manage.py detect_career_url` against **5 real companies**: at least one Greenhouse, one Lever, one own-careers-page, one JS-heavy site, one with no careers page. Paste the real step logs and candidate scores in PART 5. Then approve one candidate through the admin and confirm the company flips to `VERIFIED` with `next_scrape_at` set. **This is the gate that actually proves the prompt worked** — fixtures can lie, the real web cannot.
​
---
​
## 11. SCOPE FENCE — DO NOT BUILD YET
​
Do NOT write: job spiders, ATS API clients, `ScrapeRun` / `ScrapeError` models, job extraction or parsing, `upsert_job` calls, Celery Beat schedule entries, `scrape_company`, per-company scrape locks, "Scrape now", DRF serializers/viewsets for public APIs, Meilisearch, FCM, exams, eligibility, reminders, opportunities.
​
Where those hook in, leave exactly one comment line, e.g.
```python
# PROMPT 4: hand the verified career_url to the spider registry here
# PROMPT 5: scrape_company.delay(str(company.id)) here
```
​
---
​
## 12. REQUIRED OUTPUT FORMAT — answer in exactly these 7 parts
​
1. **PART 1 — PLAN:** numbered file-by-file build order, one line each. Start with what you read from `Scrapling-main/` and what you learned.
2. **PART 2 — CODE:** every new/changed file in full, each in its own fenced block with the exact path as the header. No `...` elisions, no TODOs.
3. **PART 3 — DEPENDENCY & INFRA:** the pinned Scrapling version and where you got it, the confirmed extras name, dependency-conflict resolution, Dockerfile/compose diffs, `.gitignore`/`.dockerignore` diffs, `THIRD_PARTY_LICENSES.md`.
4. **PART 4 — TESTS:** the full test files and fixture manifests, plus final `pytest` output with pass count and the coverage table (highlight `score_candidate`, `run_detection`, `fetching.py`).
5. **PART 5 — VERIFICATION LOG:** pre-flight results; then literal terminal output for `makemigrations --check`, ruff, black, mypy, `check --deploy`, the two greps from DoD 6 and 7, `docker compose build` + the worker Chromium proof; **then the 5-company live smoke test with real step logs and scores**, and the admin approval click-through.
6. **PART 6 — DECISIONS & DEVIATIONS:** the exact Scrapling API signatures you confirmed from source; anywhere the source contradicted this prompt and what you did; local dev install method used; the socket-guard loopback allowlist; anything you designed differently and why; any Prompt 1/2 file you believe must change (list it, do not change it).
7. **PART 7 — HANDOFF:** frozen signature list as implemented (copy-paste ready), what Prompt 4 can now assume exists (especially the `FetchResult` / `session_for` / `capture_xhr` surface), and every `# PROMPT N:` marker with its `file:line`.
​
> Work autonomously through the entire prompt. Do not ask questions mid-way — make the most reasonable senior-engineer decision, implement it, and record it in PART 6. Stop only when every Definition of Done item is literally verified.
​
---
​
## APPENDIX — post-completion checklist (for the human)
​
- [ ] `grep -rn "from scrapling" apps/ core/ config/` → only `apps/scraping/fetching.py`
- [ ] `git status` → `Scrapling-main/` not tracked
- [ ] Coverage ≥88%; `score_candidate` and `run_detection` at 100%
- [ ] Live: `python manage.py detect_career_url --company <real-slug>` on 5 real companies — logs look sane, scores make sense
- [ ] Admin: approve one real candidate → company becomes VERIFIED with `next_scrape_at` set
- [ ] `docker compose exec worker scrapling --version` works; `web` has no browsers
- [ ] `beat_schedule` still empty
- [ ] Then → **Prompt 4** (Scrapling spiders + ATS connectors + ScrapeRun/ScrapeError)
​