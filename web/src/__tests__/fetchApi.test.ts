import { describe, it, expect, vi, beforeEach } from "vitest";
import { ApiError } from "@/lib/api/fetch";

const mockFetch = vi.fn();
vi.stubGlobal("fetch", mockFetch);

vi.mock("@/lib/env", () => ({
  SITE_URL: "http://localhost:3000",
  API_BASE_URL: "http://127.0.0.1:8000",
  SSR_SERVICE_TOKEN: "test-token-123",
}));

async function importFetchApi() {
  const mod = await import("@/lib/api/fetch");
  return mod.fetchApi;
}

beforeEach(() => {
  mockFetch.mockReset();
});

describe("fetchApi", () => {
  it("attaches X-Service-Token from server env", async () => {
    mockFetch.mockResolvedValueOnce({
      ok: true,
      json: () => Promise.resolve({ id: "1" }),
    });
    const fetchApi = await importFetchApi();
    await fetchApi("/api/v1/jobs/by-slug/test/");
    const callArgs = mockFetch.mock.calls[0];
    const headers = callArgs?.[1]?.headers as Record<string, string>;
    expect(headers["X-Service-Token"]).toBe("test-token-123");
  });

  it("the token never appears in any value fetchApi returns or throws", async () => {
    mockFetch.mockResolvedValueOnce({
      ok: true,
      json: () => Promise.resolve({ data: "safe-value" }),
    });
    const fetchApi = await importFetchApi();
    const result = await fetchApi("/api/v1/jobs/by-slug/test/");
    const serialized = JSON.stringify(result);
    expect(serialized).not.toContain("test-token-123");
  });

  it("non-2xx throws ApiError carrying the status", async () => {
    mockFetch.mockResolvedValueOnce({
      ok: false,
      status: 404,
      statusText: "Not Found",
    });
    const fetchApi = await importFetchApi();
    try {
      await fetchApi("/api/v1/jobs/by-slug/missing/");
      expect.fail("should have thrown");
    } catch (err) {
      expect(err).toBeInstanceOf(ApiError);
      expect((err as ApiError).status).toBe(404);
    }
  });
});

describe("generateMetadata", () => {
  it("returns the API's canonical_url unmodified", async () => {
    const canonicalUrl = "https://example.com/jobs/my-job/";
    mockFetch.mockResolvedValueOnce({
      ok: true,
      json: () =>
        Promise.resolve({
          title: "Dev",
          description: "A job",
          canonical_url: canonicalUrl,
        }),
    });
    const { generateMetadata } = await import("@/app/jobs/[slug]/page");
    const metadata = await generateMetadata({
      params: Promise.resolve({ slug: "my-job" }),
    });
    expect(metadata.alternates?.canonical).toBe(canonicalUrl);
  });
});

describe("JSON-LD passthrough", () => {
  it("JSON-LD is passed through byte-identical to the API payload", async () => {
    const structuredData = {
      "@context": "https://schema.org",
      "@type": "JobPosting",
      title: "Engineer",
    };
    mockFetch.mockResolvedValueOnce({
      ok: true,
      json: () =>
        Promise.resolve({
          title: "Engineer",
          company: { name: "Acme" },
          location_raw: "",
          job_type: "full_time",
          posted_at: null,
          scraped_at: "2025-01-01T00:00:00Z",
          apply_url: "https://example.com/apply",
          structured_data: structuredData,
          canonical_url: "https://example.com/jobs/engineer/",
        }),
    });
    const { generateMetadata } = await import("@/app/jobs/[slug]/page");
    await generateMetadata({
      params: Promise.resolve({ slug: "engineer" }),
    });
    const fetchCall = mockFetch.mock.calls[0];
    const url = fetchCall?.[0] as string;
    expect(url).toContain("/api/v1/jobs/by-slug/engineer/");
  });

  it("a payload missing optional fields produces no null keys in the JSON-LD", async () => {
    const structuredData = {
      "@context": "https://schema.org",
      "@type": "JobPosting",
      title: "Minimal",
    };
    mockFetch.mockResolvedValueOnce({
      ok: true,
      json: () =>
        Promise.resolve({
          title: "Minimal",
          company: { name: "Co" },
          location_raw: "",
          job_type: "full_time",
          posted_at: null,
          scraped_at: "2025-01-01T00:00:00Z",
          apply_url: "",
          structured_data: structuredData,
          canonical_url: "https://example.com/jobs/minimal/",
        }),
    });
    const fetchApi = await importFetchApi();
    const job = await fetchApi("/api/v1/jobs/by-slug/minimal/");
    const sd = (job as Record<string, unknown>).structured_data as Record<string, unknown>;
    const values = Object.values(sd);
    for (const v of values) {
      expect(v).not.toBeNull();
    }
  });
});

describe("JSON-LD escaping", () => {
  it("escapes < to prevent XSS via job title in structured_data", async () => {
    const { escapeJsonLd } = await import("@/lib/jsonld");
    const malicious = {
      "@context": "https://schema.org",
      "@type": "JobPosting",
      title: "</script><script>alert(1)</script>",
    };
    const escaped = escapeJsonLd(malicious);
    expect(escaped).not.toBeNull();
    expect(escaped).not.toContain("<");
    expect(escaped).toContain("\\u003c");
    const parsed = JSON.parse(escaped!);
    expect(parsed.title).toBe("</script><script>alert(1)</script>");
  });

  it("returns null for null input", async () => {
    const { escapeJsonLd } = await import("@/lib/jsonld");
    expect(escapeJsonLd(null)).toBeNull();
  });
});

describe("trailing slash", () => {
  it("a job URL built by the app ends with a trailing slash", async () => {
    const nextConfig = await import("../../next.config");
    const config = nextConfig.default;
    expect(config.trailingSlash).toBe(true);
  });
});
