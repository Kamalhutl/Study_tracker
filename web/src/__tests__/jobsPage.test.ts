import { describe, it, expect, vi, beforeEach } from "vitest";

const mockFetch = vi.fn();
vi.stubGlobal("fetch", mockFetch);

vi.mock("@/lib/env", () => ({
  SITE_URL: "http://localhost:3000",
  API_BASE_URL: "http://127.0.0.1:8000",
  SSR_SERVICE_TOKEN: "test-token-123",
}));

beforeEach(() => {
  mockFetch.mockReset();
});

function mockJobsResponse(results: unknown[] = [], count = 0) {
  mockFetch.mockResolvedValueOnce({
    ok: true,
    json: () => Promise.resolve({ results, count }),
  });
}

describe("JobsPage", () => {
  it("renders without crashing when API returns empty results", async () => {
    mockJobsResponse();
    const { default: JobsPage } = await import("@/app/jobs/page");
    const result = await JobsPage({
      searchParams: Promise.resolve({}),
    });
    expect(result).toBeDefined();
  });

  it("passes only allowlisted params to the API", async () => {
    mockJobsResponse();
    const { default: JobsPage } = await import("@/app/jobs/page");
    await JobsPage({
      searchParams: Promise.resolve({ job_type: "internship", nonsense: "1" }),
    });
    const callArgs = mockFetch.mock.calls[0];
    const url = callArgs?.[0] as string;
    expect(url).toContain("job_type=internship");
    expect(url).not.toContain("nonsense");
  });
});

describe("generateMetadata", () => {
  it("returns self-referencing canonical for unfiltered /jobs/", async () => {
    mockJobsResponse();
    const { generateMetadata } = await import("@/app/jobs/page");
    const metadata = await generateMetadata({
      searchParams: Promise.resolve({}),
    });
    expect(metadata.alternates?.canonical).toBe("http://localhost:3000/jobs/");
  });

  it("includes noindex robots when active filters are present", async () => {
    mockJobsResponse();
    const { generateMetadata } = await import("@/app/jobs/page");
    const metadata = await generateMetadata({
      searchParams: Promise.resolve({ job_type: "internship" }),
    });
    expect(metadata.robots).toEqual({ index: false });
  });

  it("does not include noindex when no active filters", async () => {
    mockJobsResponse();
    const { generateMetadata } = await import("@/app/jobs/page");
    const metadata = await generateMetadata({
      searchParams: Promise.resolve({}),
    });
    expect(metadata.robots).toBeUndefined();
  });

  it("strips unknown params from canonical URL", async () => {
    mockJobsResponse();
    const { generateMetadata } = await import("@/app/jobs/page");
    const metadata = await generateMetadata({
      searchParams: Promise.resolve({ nonsense: "1" }),
    });
    const canonical = metadata.alternates?.canonical as string;
    expect(canonical).not.toContain("nonsense");
    expect(canonical).toBe("http://localhost:3000/jobs/");
  });

  it("preserves page param in canonical when page > 1", async () => {
    mockJobsResponse();
    const { generateMetadata } = await import("@/app/jobs/page");
    const metadata = await generateMetadata({
      searchParams: Promise.resolve({ page: "3" }),
    });
    const canonical = metadata.alternates?.canonical as string;
    expect(canonical).toContain("page=3");
  });
});
