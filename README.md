# Study Tracker — Job Portal (Phase 1)

Django job portal focused on fresh graduates. Phase 1 = internal ops: the
`companies` + `jobs` domains and the admin portal that operators use to add
companies, approve career sources, review scraped jobs, and watch scraping
health.

## Stack

- Django 5.2 + Postgres (SearchVector/GIN), DRF, celery + redis, docker compose.
- Tooling: ruff, black, mypy (django-stubs), pytest + pytest-django + factory_boy.
- Every run must pass with **no outbound network** (tests block sockets).

## Apps

| App | Purpose |
| --- | --- |
| `accounts` | Email-login user model (Step 1) |
| `audit_logs` | Append-only audit trail written by every mutating service |
| `companies` | Companies, career sources, detection candidates, scraping health |
| `jobs` | Scraped jobs, 3-strike closed ladder, review queue, reports |

## Commands

```bash
python manage.py add_company --name "X" --website https://x.com --actor-email admin@example.com
python manage.py add_company --name "X" --career-url https://boards.greenhouse.io/x --actor-email admin@example.com
python manage.py companies_due [--limit N] [--json]
python manage.py seed_demo [--companies 10] [--jobs-per 8]   # idempotent, DEBUG-only
python manage.py rebuild_search_vectors [--company SLUG]
```

## Quick start

```bash
docker compose up -d
make migrate
python manage.py seed_demo
python manage.py runserver        # /admin/ — companies, candidate approval queue, job review queue
make test                         # coverage >= 88%, 4 critical services at 100%
```

## Docs

- [Domain model, flows, state machines, frozen contracts](docs/domain-model.md)
- Prompt specs: `docs/prompts/`

## Prompts

- Prompt 1 (Step 1): scaffold, settings, core utils, accounts, audit logs, Docker/CI — shipped.
- Prompt 2 (this): companies + jobs domains, services, admin portal, tests.
- Prompt 3: career-URL detection (`# PROMPT 3` markers left in code).
- Prompt 4: Scrapling fetchers (`# scrapling[fetchers]` comment in `requirements/base.txt`).
- Prompt 5: scheduler + `scrape_company` task (`# PROMPT 5` markers left in code).