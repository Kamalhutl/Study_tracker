# Exams API v1

## Base URL
`/api/v1/exams/`

## Authentication
Public endpoints allow anonymous access. Protected endpoints (save/unsave) require JWT authentication.

## Publication Rule
Only cycles with `is_published=True` and `verified_by_human=True` are exposed to non-staff users. All list and detail views apply `public()` queryset methods.

## Endpoints

### 1. List Exams
`GET /api/v1/exams/`

**Filters:**
- `q` — trigram search on exam name, short name, and conducting body name. For queries <3 characters, falls back to `icontains`. Does **not** search description.
- `body` — comma-separated conducting body slugs
- `category` — comma-separated enum values: `civil_services`, `banking`, `railway`, `ssc`, `teaching`, `defence`, `engineering`, `medical`, `law`, `state_psc`, `other`
- `level` — `national` or `state`
- `status` — filters by latest cycle status (e.g., `announced`, `applications_open`)
- `applications_open` — boolean; cycles where today falls between `application_start` and `application_end`
- `upcoming_within_days` — integer; any stage or application date inside the window
- `allow_final_year` — boolean; from eligibility
- `ordering` — allowlist: `name`, `created_at` (prefix `-` for descending)

**Response:** Paginated list of exams with latest cycle status.

### 2. Exam Detail
`GET /api/v1/exams/<slug>/`

Returns full exam detail with nested cycles, stages, eligibility, and date-change history.

### 3. List Cycles
`GET /api/v1/exams/cycles/`

Filters: `exam`, `status`, `year`. Returns published cycles only.

### 4. Cycle Detail
`GET /api/v1/exams/cycles/<uuid>/`

Returns cycle with stages and date-change history.

### 5. Calendar
`GET /api/v1/exams/calendar/`

Returns flat list of events for a date range. Parameters: `from` (YYYY-MM-DD), `to` (YYYY-MM-DD). Defaults to today + 90 days.

**Event types:** `notification`, `application_start`, `application_end`, `fee_last_date`, `correction_start`, `correction_end`, `admit_card`, `stage_exam`, `stage_result`, `result`.

Each event: `date`, `event_type`, `exam_name`, `exam_slug`, `cycle_label`, `stage_name` (nullable), `is_tentative`, `official_url`.

### 6. Save/Unsave Exam
`POST /api/v1/exams/<slug>/save/` — authenticates, idempotent.
`DELETE /api/v1/exams/<slug>/save/` — removes save.

### 7. Saved Exams
`GET /api/v1/exams/saved/` — returns the authenticated user's saved exams.