#!/usr/bin/env bash
set -euo pipefail

export SSR_SERVICE_TOKEN="${SSR_SERVICE_TOKEN:-dev-ssr-token}"
export SITE_BASE_URL="${SITE_BASE_URL:-http://localhost:3000}"
DJANGO_PORT=8000
NEXT_PORT=3000
DJANGO_LOG=$(mktemp)
NEXT_LOG=$(mktemp)
PAGE_TMP=$(mktemp)
API_TMP=$(mktemp)
DJANGO_PID=""
NEXT_PID=""

cleanup() {
  [ -n "$NEXT_PID" ] && kill "$NEXT_PID" 2>/dev/null || true
  [ -n "$DJANGO_PID" ] && kill "$DJANGO_PID" 2>/dev/null || true
  lsof -ti :${DJANGO_PORT} 2>/dev/null | xargs kill 2>/dev/null || true
  lsof -ti :${NEXT_PORT} 2>/dev/null | xargs kill 2>/dev/null || true
  rm -f "$PAGE_TMP" "$API_TMP" "$DJANGO_LOG" "$NEXT_LOG"
}
trap cleanup EXIT

lsof -ti :${DJANGO_PORT} 2>/dev/null | xargs kill 2>/dev/null || true
lsof -ti :${NEXT_PORT} 2>/dev/null | xargs kill 2>/dev/null || true
sleep 1

python manage.py runserver "127.0.0.1:${DJANGO_PORT}" --noreload >"$DJANGO_LOG" 2>&1 &
DJANGO_PID=$!

rm -rf web/.next
pnpm --dir web build >"$NEXT_LOG" 2>&1
pnpm --dir web start -p "$NEXT_PORT" >>"$NEXT_LOG" 2>&1 &
NEXT_PID=$!

for i in $(seq 1 60); do
  if curl -sf "http://127.0.0.1:${DJANGO_PORT}/healthz" >/dev/null 2>&1; then
    echo "Django ready after ${i}s"
    break
  fi
  if [ "$i" -eq 60 ]; then
    echo "FAIL: Django /healthz did not respond within 60s"
    tail -30 "$DJANGO_LOG"
    exit 1
  fi
  sleep 1
done

for i in $(seq 1 60); do
  if nc -z 127.0.0.1 "${NEXT_PORT}" 2>/dev/null; then
    echo "Next ready after ${i}s"
    break
  fi
  if [ "$i" -eq 60 ]; then
    echo "FAIL: Next port ${NEXT_PORT} did not respond within 60s"
    tail -30 "$NEXT_LOG"
    exit 1
  fi
  sleep 1
done

SLUG=$(python manage.py shell -c "
import sys
from apps.jobs.models import Job
job = Job.objects.filter(status='open', is_published=True).exclude(slug__isnull=True).exclude(slug='').first()
if not job:
    from apps.companies.models import Company
    c = Company.objects.first()
    if not c:
        c = Company(name='Smoke Corp', slug='smoke-corp', domain='smoke.test')
        c.save()
    import hashlib
    job = Job(
        company=c,
        source_url='https://smoke.test/job',
        normalized_source_url='https://smoke.test/job',
        content_hash=hashlib.sha256(b'smoke').hexdigest(),
        title='Smoke Test Engineer',
        title_normalized='smoke test engineer',
        slug='smoke-test-engineer',
        status='open',
        is_published=True,
    )
    job.save()
sys.stdout.write(job.slug + '\n')
" | tail -1)

echo "Using slug: ${SLUG}"

curl -s "http://localhost:${NEXT_PORT}/jobs/${SLUG}/" >"$PAGE_TMP"
curl -s "http://127.0.0.1:${DJANGO_PORT}/api/v1/jobs/by-slug/${SLUG}/" -H "X-Service-Token: ${SSR_SERVICE_TOKEN}" >"$API_TMP"



FAILED=0

LD_COUNT=$(grep -c 'application/ld+json' "$PAGE_TMP" || true)
echo "[assertion a] application/ld+json count: ${LD_COUNT}"
if [ "$LD_COUNT" -ne 1 ]; then
  echo "FAIL: expected exactly 1 application/ld+json, got ${LD_COUNT}"
  FAILED=1
else
  echo "OK: exactly 1 application/ld+json"
fi

JSON_LD_CONTENT=$(python3 -c "
import re, sys
html = open('$PAGE_TMP').read()
m = re.search(r'<script type=\"application/ld\+json\">(.*?)</script>', html, re.DOTALL)
if m:
    print(m.group(1))
else:
    sys.exit(1)
" || true)
echo "[assertion b] JSON-LD @type check:"
echo "$JSON_LD_CONTENT"
if [ -z "$JSON_LD_CONTENT" ]; then
  echo "FAIL: no JSON-LD script tag found"
  FAILED=1
else
  AT_TYPE=$(echo "$JSON_LD_CONTENT" | python3 -c "import json,sys; print(json.load(sys.stdin).get('@type',''))" || true)
  if [ "$AT_TYPE" != "JobPosting" ]; then
    echo "FAIL: expected @type JobPosting, got '${AT_TYPE}'"
    FAILED=1
  else
    echo "OK: @type == JobPosting"
  fi
fi

STATUS_SLASH=$(curl -sI -o /dev/null -w '%{http_code}' "http://localhost:${NEXT_PORT}/jobs/${SLUG}/")
echo "[assertion c] GET /jobs/${SLUG}/ HTTP status: ${STATUS_SLASH}"
if [ "$STATUS_SLASH" -ne 200 ]; then
  echo "FAIL: expected 200, got ${STATUS_SLASH}"
  FAILED=1
else
  echo "OK: 200"
fi

HEADERS_NO_SLASH=$(curl -sI "http://localhost:${NEXT_PORT}/jobs/${SLUG}")
STATUS_NO_SLASH=$(echo "$HEADERS_NO_SLASH" | head -1 | awk '{print $2}')
LOCATION=$(echo "$HEADERS_NO_SLASH" | grep -i '^location:' | tr -d '\r' | awk '{print $2}')
echo "[assertion d] GET /jobs/${SLUG} (no slash) HTTP status: ${STATUS_NO_SLASH}, Location: ${LOCATION}"
if [ "$STATUS_NO_SLASH" -ne 308 ]; then
  echo "FAIL: expected 308, got ${STATUS_NO_SLASH}"
  FAILED=1
elif ! echo "$LOCATION" | grep -q '/$'; then
  echo "FAIL: Location does not end with /: ${LOCATION}"
  FAILED=1
else
  echo "OK: 308 redirect with trailing slash"
fi

CANONICAL_API=$(python3 -c "import json; print(json.load(open('$API_TMP'))['canonical_url'])" 2>/dev/null || echo "")
CANONICAL_PAGE=$(python3 -c "
import re
html = open('$PAGE_TMP').read()
m = re.search(r'<link rel=\"canonical\" href=\"([^\"]+)\"', html)
print(m.group(1) if m else '')
" 2>/dev/null || echo "")
echo "[assertion e] canonical comparison:"
echo "  API canonical_url:   ${CANONICAL_API}"
echo "  page <link> href:    ${CANONICAL_PAGE}"
CANONICAL_API_SLASH="${CANONICAL_API%/}/"
if [ "$CANONICAL_PAGE" != "$CANONICAL_API" ] && [ "$CANONICAL_PAGE" != "$CANONICAL_API_SLASH" ]; then
  echo "FAIL: canonical mismatch"
  FAILED=1
else
  echo "OK: canonical matches"
fi

JOBS_TMP=$(mktemp)
curl -s "http://localhost:${NEXT_PORT}/jobs/" >"$JOBS_TMP"
STATUS_JOBS=$(curl -sI -o /dev/null -w '%{http_code}' "http://localhost:${NEXT_PORT}/jobs/")
JOBS_CANONICAL=$(python3 -c "
import re
html = open('$JOBS_TMP').read()
m = re.search(r'<link rel=\"canonical\" href=\"([^\"]+)\"', html)
print(m.group(1) if m else '')
" 2>/dev/null || echo "")
JOBS_NOINDEX=$(grep -ci 'noindex' "$JOBS_TMP" || true)
echo "[assertion f] GET /jobs/ HTTP status: ${STATUS_JOBS}, canonical: ${JOBS_CANONICAL}, noindex count: ${JOBS_NOINDEX}"
if [ "$STATUS_JOBS" -ne 200 ]; then
  echo "FAIL: expected 200 for /jobs/, got ${STATUS_JOBS}"
  FAILED=1
elif [ -z "$JOBS_CANONICAL" ]; then
  echo "FAIL: /jobs/ missing canonical"
  FAILED=1
elif ! echo "$JOBS_CANONICAL" | grep -q '/jobs/'; then
  echo "FAIL: /jobs/ canonical does not self-reference"
  FAILED=1
elif [ "$JOBS_NOINDEX" -gt 0 ]; then
  echo "FAIL: /jobs/ should not have noindex"
  FAILED=1
else
  echo "OK: /jobs/ returns 200, self-canonical, no noindex"
fi

FILTER_TMP=$(mktemp)
curl -s "http://localhost:${NEXT_PORT}/jobs/?job_type=internship" >"$FILTER_TMP"
STATUS_FILTER=$(curl -sI -o /dev/null -w '%{http_code}' "http://localhost:${NEXT_PORT}/jobs/?job_type=internship")
FILTER_NOINDEX=$(grep -ci 'noindex' "$FILTER_TMP" || true)
echo "[assertion g] GET /jobs/?job_type=internship HTTP status: ${STATUS_FILTER}, noindex count: ${FILTER_NOINDEX}"
if [ "$STATUS_FILTER" -ne 200 ]; then
  echo "FAIL: expected 200, got ${STATUS_FILTER}"
  FAILED=1
elif [ "$FILTER_NOINDEX" -eq 0 ]; then
  echo "FAIL: filtered page should contain noindex"
  FAILED=1
else
  echo "OK: /jobs/?job_type=internship returns 200 with noindex"
fi

NONSENSE_TMP=$(mktemp)
curl -s "http://localhost:${NEXT_PORT}/jobs/?nonsense=1" >"$NONSENSE_TMP"
NONSENSE_CANONICAL=$(python3 -c "
import re
html = open('$NONSENSE_TMP').read()
m = re.search(r'<link rel=\"canonical\" href=\"([^\"]+)\"', html)
print(m.group(1) if m else '')
" 2>/dev/null || echo "")
echo "[assertion h] GET /jobs/?nonsense=1 canonical: ${NONSENSE_CANONICAL}"
if echo "$NONSENSE_CANONICAL" | grep -qi 'nonsense'; then
  echo "FAIL: canonical should not contain unknown param 'nonsense'"
  FAILED=1
else
  echo "OK: canonical does not contain nonsense"
fi

rm -f "$JOBS_TMP" "$FILTER_TMP" "$NONSENSE_TMP"

if [ "$FAILED" -ne 0 ]; then
  exit 1
fi

echo "All 8 assertions passed."
