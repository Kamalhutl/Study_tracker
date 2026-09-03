# API v1: Jobs Endpoint

## `/api/v1/jobs/`

### Search Mechanism

**Trigram similarity** (`pg_trgm`) is the **single authoritative** search mechanism. There is no full-text search in this project.

- `q` searches exactly: **title**, **company name** (`company__name`), and **department**.
- **`q` does NOT search job description text.** This is deliberate — description search is not supported.
- For queries with **< 3 characters**, a fallback `icontains` match is applied on the same three fields.
- For queries with **≥ 3 characters**, trigram similarity is used with a **threshold of 0.1**.

**Removed components** (migration `0004_remove_job_idx_job_search_vector_and_more`):
- `search_vector` column and its GIN index
- `refresh_search_vector()` function
- `rebuild_search_vectors` management command
- Admin refresh action
- `Job.objects.search()` queryset method
- Tests: `test_search_vector_finds_job`, `test_company_bulk_refresh`, and the three `TestRebuildSearchVectors` tests

**Known follow-up**: The trigram index exists only on `title` (`job_title_trgm`). `company__name` and `department` lack trigram indexes, which may become a scaling concern as the dataset grows. Indexes such as `CREATE INDEX ... ON companies_company USING gin (name gin_trgm_ops)` and on `department` would be needed.

### Endpoint

- `GET /api/v1/jobs/` - List jobs with filtering and search.

### Filtering

- `q`: Search string (trigram-based)
- `work_mode`: comma-separated list of WorkMode values
- `job_type`: comma-separated list of JobType values
- `company`: comma-separated list of company slugs
- `department`: case-insensitive containment
- `location`: case-insensitive containment on `location_raw`
- `posted_after`: ISO datetime
- `posted_within_days`: number of days
- `has_apply_url`: boolean
- `ordering`: comma-separated list of fields (allowed: `posted_at`, `-posted_at`, `created_at`, `-created_at`, `title`)

### Example

```
GET /api/v1/jobs/?q=python&work_mode=remote,hybrid&ordering=-posted_at
```