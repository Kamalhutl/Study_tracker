# PROMPT 16 — Job list page + crawl control

GOAL
Ship /jobs/ — search and browse — from the endpoints you already have,
with crawl control that keeps faceted URLs out of the index.

NON-GOALS:
- No new API endpoints, no partial indexes, no Redis (all Prompt 17)
- No home, company, or exam pages; no landing pages
- No component library, no client-side state library

SCOPE

0. Carried over: paste the raw output of `make web-smoke` — the five
   assertion lines verbatim, not the summary. Item 5 of 15.2 exists so
   the run is auditable rather than merely green.

1. web/src/app/jobs/page.tsx — server component, reads searchParams.

2. Filter allowlist. One const mapping permitted UI params to API filter
   names (job_type, work_mode, experience_level, city, q, page). Anything
   outside it is dropped, never forwarded. Clamp page_size server-side to
   a maximum. searchParams is attacker-controlled input and this page is
   a proxy to your API — without an allowlist anyone can request an
   unbounded page size.

3. Two fetches: job list and facets.
   - facets: next: { revalidate: 600 }
   - unfiltered list: next: { revalidate: 300 }
   - filtered lists: uncached
   Reading searchParams makes the whole route dynamic, so the caching has
   to live on the individual fetches or every visitor pays full price.

4. generateMetadata, exactly these four cases:
   - no filters, no page  -> robots index,follow; canonical = /jobs/
   - page present, no filters -> index,follow; canonical = that page's
     own URL including its page param
   - any allowlisted filter present -> robots noindex,follow
   - unknown params -> ignored, and absent from the canonical

5. Pagination links built only from allowlisted params, preserving the
   trailing slash on the path segment.

6. Body: filter controls driven by the facets response, result cards
   linking to /jobs/[slug]/, a result count, and an empty state.

7. Extend web/scripts/smoke.sh with three assertions:
   - /jobs/ returns 200, carries a self-canonical, and has no noindex
   - /jobs/?job_type=internship returns 200 and contains noindex
   - /jobs/?nonsense=1 has no "nonsense" anywhere in its canonical

TESTS (vitest)
- allowlist drops unknown keys and clamps page_size
- unfiltered -> index; any filter -> noindex
- page 2 self-canonicalizes to a URL containing its own page param
- canonical never contains a param outside the allowlist
- pagination link builder keeps the trailing slash on /jobs/

DONE WHEN
make web-gates exits 0, and make web-smoke exits 0 with all eight
assertion lines pasted.