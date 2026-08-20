# Domain Model — PROMPT 2 (Companies & Jobs)

Phase 1 data spine: two domain apps (`companies`, `jobs`), a full Django admin
front-door for internal ops, and a services layer whose signatures are frozen
contracts for Prompts 3/4/5/6.

## 1. Entities and relations

```
Company 1 ──< CompanySource          (append-only career-URL history)
     1 ──< CareerCandidateUrl        (detection candidates, Prompt 3 writes)
     1 ──< DetectionRun              (detection executions, Prompt 3 writes)
     1 ──< Job                       (scraped postings)
     1 ──< JobStatusEvent            (per-job status timeline)

Job 1 ──< SavedJob                   (per-user bookmarks)
Job 1 ──< JobReport                  (user reports, resolved by admins)
Job 0..1 ── Job                      (duplicate_of self-FK, cycle-guarded)
```

All models extend `UUIDModel` + `TimeStampedModel`; `Company` and `Job` also
extend `SoftDeleteModel` (soft delete only — a job is NEVER hard-deleted).

### Company
- **Identity:** `name`, `slug` (auto, collision-suffixed), `domain`
  (normalized registrable host), optional branding fields.
- **How it was added:** `input_type` (`main_website` = Case A,
  `direct_career` = Case B), `input_url` (exactly what the admin pasted),
  `added_by`.
- **Resolved career source (the thing we scrape):** `career_url`,
  `career_source_type`, `ats_identifier`, `career_url_set_by`/`set_at`.
- **Verification:** `detection_status`, `is_verified`, `verified_by`/`at`,
  `detection_attempts`, `last_detection_at`.
- **Scheduling:** `is_active`, `scrape_interval_minutes` (floor 30),
  `next_scrape_at`, `last_scraped_at`, `last_successful_scrape_at`.
- **Health:** `scrape_health`, `consecutive_failures`, `total_scrapes`,
  `total_failures`, `last_failure_reason`, `last_jobs_seen`, `notes`.
- Key constraints: one active `domain` per company; one active `career_url`;
  `scrape_interval >= 30`; verified companies must have a `career_url`.

Properties: `is_scrapable`, `is_ats`, `needs_attention`, `is_due(now)`,
`compute_next_scrape_at(now, backoff_factor=1)` (per-company jitter).

### CompanySource (append-only)
`company`, `url`, `normalized_url`, `source_type`, `ats_identifier`,
`is_current`, `set_by`, `reason`, `retired_at`. At most one `is_current`
row per company; URLs unique per company.

### CareerCandidateUrl (detection candidates)
`company`, `detection_run`, `url`, `normalized_url`, `origin`, `guessed_type`,
`ats_identifier`, `score` (0..100), `score_reasons`, `page_title`,
`http_status`, `sample_job_titles`, `status`, `decided_by`/`at`,
`reject_reason`. At most one `approved` candidate per company.

### DetectionRun
`company`, `triggered_by`, `status`, `started_at`, `finished_at`,
`duration_ms`, `urls_checked`, `candidates_found`, `strategies_used`,
`error_message`, `log`. Written by Prompt 3; read-only admin exists now.

### Job
- **Dedupe identity:** `company`, `source_job_id`, `source_url`,
  `normalized_source_url`, `apply_url`, `content_hash`
  (`sha256_of(title, location_raw, description)`).
- **Content:** `title`, `title_normalized`, `description`,
  `description_html`, `location_raw`, `city`, `state`, `country`,
  `work_mode`, `job_type`, `experience_level`, `min/max_experience_years`,
  `salary_min/max`, `salary_currency`, `salary_period`, `department`,
  `skills`, `education_required`, `posted_at`, `deadline_at`.
- **Lifecycle:** `status`, `missing_count` (≤ 3), `first_seen_at`,
  `last_seen_at`, `closed_at`, `reopened_count`.
- **Publishing/review:** `is_published`, `published_at`, `needs_review`,
  `review_reason`, `reviewed_by`/`at`.
- **Human-edit protection:** `manually_edited_fields` (scraper never
  overwrites), `is_manual_status` (ladder never auto-moves).
- **Quality/ops:** `duplicate_of`, `extraction_confidence`, `trust_label`,
  `report_count`, `view_count`, `save_count`, `search_vector` (GIN),
  `raw_payload`.

Key constraints: one `(company, source_job_id)`; one
`(company, title_normalized, normalized_source_url)`; `missing_count <= 3`;
CLOSED requires `closed_at`; `salary_max >= salary_min`; confidence ≤ 100.

### SavedJob
`user`, `job`, `note`; one bookmark per `(user, job)`.

### JobReport
`job`, `user`, `reason`, `comment`, `status`, `resolved_by`/`at`,
`resolution_note`; at most one OPEN report per `(job, user)`.

### JobStatusEvent (append-only timeline)
`job`, `from_status`, `to_status`, `missing_count`, `trigger` (scrape /
ladder / admin / report / reopen), `actor`, `scrape_run_id`, `note`.

## 2. Two ways to add a company (front door flows)

**Case A — main website (`add_company_from_main_website`):**
1. Admin pastes the homepage.
2. Service normalizes the URL, extracts the domain, rejects blocked domains
   and duplicates, then stores the company with `detection_status=PENDING`,
   `is_verified=False`, `career_url=""`, and NO `next_scrape_at`.
3. Prompt 3 runs career-URL detection and stores candidates.
4. A human approves exactly one candidate → the company becomes scrapable.

**Case B — direct career URL (`add_company_from_direct_career_url`):**
1. Admin pastes the known career page.
2. Service sniffs the source type (Greenhouse / Lever / Ashby /
   SmartRecruiters / Workday / own page), stores the company with
   `detection_status=SKIPPED`, `is_verified=True`, `career_url` set, and
   an initial `CompanySource(is_current=True, reason="direct career url")`.
3. `next_scrape_at` is computed immediately — the company is scrapable.

**Invariant (ground rule 3):** no company becomes scrapable
(`is_verified=True`) without a human action — Case A via the approval queue,
Case B by the admin pasting the URL directly.

## 3. The 3-strike ladder (`apply_missing_strikes`)

Called once per successful scrape with the set of seen job IDs. Jobs of the
company not seen are punished; `MISSING_STATUS_LADDER = {1: possibly_closed,
2: likely_closed, 3: closed}`, cap `MAX_MISSING_COUNT = 3`.

| missing_count after strike | status | side effects |
| --- | --- | --- |
| 1 | POSSIBLY_CLOSED | `JobStatusEvent(from=open, to=possibly_closed, trigger="ladder")` |
| 2 | LIKELY_CLOSED | `JobStatusEvent(from=possibly_closed, to=likely_closed, trigger="ladder")` |
| 3 | CLOSED | `closed_at = now` + event; stays visible with a Closed label |
| 3 again (cap) | CLOSED | no change, no event |

- **Never delete, never unpublish.** Closed jobs remain in the DB forever
  (history + trust). The suite asserts the row still exists after the 4th
  cycle.
- Skipped: `is_manual_status=True` jobs (the ladder must never override an
  admin's decision) and jobs in `seen_job_ids` (they were seen).
- **Safety guard:** if the scrape returned zero jobs (`seen_job_ids` empty)
  and the company has open jobs, strikes are NOT applied — that is a broken
  selector, not 40 simultaneous closures. Returns
  `{"skipped": True, "reason": "empty_result_guard"}`.
- Batch efficiency: `bulk_update` in chunks of 500 + `bulk_create` the events.

## 4. Health state machine (`record_scrape_outcome`)

Every successful scrape happy-paths; every failure walks the ladder:

| consecutive failures | health | backoff |
| --- | --- | --- |
| 0 (success) | HEALTHY | `interval * 1` (+ jitter) |
| 1–2 | DEGRADED | `interval * 2^(n-1)` — 300m, 600m |
| 3–4 | FAILING | 1200m, 2400m → capped at `MAX_BACKOFF_MINUTES` (1440m) |
| ≥ 5 | PAUSED | `is_active=False`, `next_scrape_at=None` (needs a human) |

Audit rows (`company.scrape_outcome`) are written ONLY on transitions or
auto-pause — never one per successful scrape.

## 5. Frozen service signatures — DO NOT CHANGE (consumed by Prompts 3/4/5/6)

`apps/companies/services.py`:

```python
sniff_source_type_from_url(url: str) -> tuple[CareerSourceType, str]
add_company_from_main_website(*, name, website_url, actor, **optional_meta) -> Company
add_company_from_direct_career_url(*, name, career_url, actor, website_url="", **optional_meta) -> Company
approve_career_candidate(*, candidate, actor, interval_minutes=None) -> Company
reject_career_candidate(*, candidate, actor, reason="") -> CareerCandidateUrl
set_manual_career_url(*, company, career_url, actor, verify=True) -> Company
request_redetection(*, company, actor) -> Company
pause_company(*, company, actor, reason="") -> Company
resume_company(*, company, actor) -> Company
archive_company(*, company, actor, reason="") -> Company
unarchive_company(*, company, actor) -> Company
update_scrape_interval(*, company, minutes, actor) -> Company
record_scrape_outcome(*, company, success, failure_reason="", jobs_seen=0, now=None) -> Company
```

`apps/jobs/services.py`:

```python
upsert_job(*, company, payload, scrape_run_id=None, actor=None) -> tuple[Job, str]
apply_missing_strikes(*, company, seen_job_ids, scrape_run_id=None) -> dict
publish_job(*, job, actor, reason="") -> Job
unpublish_job(*, job, actor, reason="") -> Job
mark_job_closed(*, job, actor, reason="") -> Job
reopen_job(*, job, actor, reason="") -> Job
mark_duplicate(*, job, canonical, actor) -> Job
edit_job_fields(*, job, changes, actor) -> Job
approve_job_review(*, job, actor) -> Job
reject_job_review(*, job, actor, reason) -> Job
submit_job_report(*, job, user, reason, comment="") -> JobReport
resolve_report(*, report, actor, accept, note="") -> JobReport
save_job(*, user, job) -> SavedJob
unsave_job(*, user, job) -> None
refresh_search_vector(*, job=None, company=None) -> None
compute_trust_label(job) -> str
```

## 6. Runbook — onboard 10 companies as an admin

1. `python manage.py seed_demo` (or add each by hand via the admin).
2. Add a company with a known ATS: copy the career URL (e.g. Greenhouse
   board) → **Add career URL** (Case B) → it is verified and scheduled.
3. Add a company with an unknown career page: paste the homepage →
   **Add main website** (Case A) → it enters the detection queue
   (Prompt 3 fills it; until then `companies_due` won't list it).
4. In the **Career candidate URLs** changelist, approve the top-scoring
   candidate — the company flips to verified + scheduled in one click.
5. Watch companies hit health issues: FAILING after 3–4 failed scrapes,
   PAUSED after 5 (auto-paused, needs a human to resume).
6. Jobs arriving via `upsert_job` auto-publish only for verified ATS
   companies with confidence ≥ 70; everything else queues in **Review queue
   (needs review)**.
7. Edit a review-queued job: the edited field lands in
   `manually_edited_fields` and the scraper will never overwrite it.
8. Sanity-check the scheduler with `python manage.py companies_due --json`
   before Prompt 5 wires real scraping.