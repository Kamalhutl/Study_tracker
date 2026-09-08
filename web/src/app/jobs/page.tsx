import React from "react";
import type { Metadata } from "next";
import { fetchApi } from "@/lib/api/fetch";
import { SITE_URL } from "@/lib/env";
import {
  filterSearchParams,
  buildApiQueryString,
  hasActiveFilters,
  buildPaginationUrl,
} from "./allowlist";

export const revalidate = 3600;

interface JobsPageProps {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}

function toURLSearchParams(
  raw: Record<string, string | string[] | undefined>
): URLSearchParams {
  const sp = new URLSearchParams();
  for (const [key, value] of Object.entries(raw)) {
    if (value === undefined) continue;
    if (Array.isArray(value)) {
      for (const v of value) sp.append(key, v);
    } else {
      sp.set(key, value);
    }
  }
  return sp;
}

export async function generateMetadata({
  searchParams,
}: JobsPageProps): Promise<Metadata> {
  const raw = await searchParams;
  const sp = toURLSearchParams(raw);
  const { filtered } = filterSearchParams(sp);
  const active = hasActiveFilters(filtered);
  const currentPage = parseInt(filtered.get("page") || "1", 10);
  const canonical = buildPaginationUrl(`${SITE_URL}/jobs/`, filtered, currentPage);

  return {
    title: "Jobs | Study Tracker",
    alternates: {
      canonical,
    },
    ...(active ? { robots: { index: false } } : {}),
  };
}

export default async function JobsPage({ searchParams }: JobsPageProps) {
  const raw = await searchParams;
  const sp = toURLSearchParams(raw);
  const { filtered } = filterSearchParams(sp);
  const active = hasActiveFilters(filtered);
  const currentPage = parseInt(filtered.get("page") || "1", 10);
  const apiQs = buildApiQueryString(filtered, 20);
  const apiPath = `/api/v1/jobs/${apiQs ? `?${apiQs}` : ""}`;

  let jobs: unknown[] = [];
  let totalCount = 0;
  try {
    const data = await fetchApi<{ results: unknown[]; count: number }>(
      apiPath as string,
      { revalidate }
    );
    jobs = data.results ?? [];
    totalCount = data.count ?? 0;
  } catch {
    jobs = [];
    totalCount = 0;
  }

  const totalPages = Math.max(1, Math.ceil(totalCount / 20));
  const canonical = buildPaginationUrl(`${SITE_URL}/jobs/`, filtered, 1);

  return (
    <main className="max-w-4xl mx-auto p-6">
      {active && <meta name="robots" content="noindex" />}
      <link rel="canonical" href={canonical} />
      <h1 className="text-2xl font-bold mb-4">Jobs</h1>
      {jobs.length === 0 ? (
        <p>No jobs found.</p>
      ) : (
        <ul className="space-y-4">
          {jobs.map((job: unknown) => {
            const j = job as Record<string, unknown>;
            return (
              <li key={String(j.slug ?? j.id)} className="border p-4 rounded">
                <h2 className="text-lg font-semibold">{String(j.title ?? "")}</h2>
                <p className="text-sm text-gray-600">
                  {String((j.company as Record<string, unknown>)?.name ?? "")}
                </p>
                <p className="text-sm">{String(j.job_type ?? "")}</p>
              </li>
            );
          })}
        </ul>
      )}
      {totalPages > 1 && (
        <nav className="mt-6 flex gap-2">
          {Array.from({ length: totalPages }, (_, i) => i + 1).map((page) => (
            <a
              key={page}
              href={buildPaginationUrl("/jobs/", filtered, page)}
              className={
                page === currentPage
                  ? "px-3 py-1 bg-blue-600 text-white rounded"
                  : "px-3 py-1 border rounded"
              }
            >
              {page}
            </a>
          ))}
        </nav>
      )}
    </main>
  );
}
