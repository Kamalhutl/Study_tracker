import { notFound } from "next/navigation";
import type { Metadata } from "next";
import { fetchApi, ApiError } from "@/lib/api/fetch";
import type { components } from "@/lib/api/schema";
import { escapeJsonLd } from "@/lib/jsonld";

export const revalidate = 3600;

type JobDetail = components["schemas"]["JobDetail"];

interface PageProps {
  params: Promise<{ slug: string }>;
}

export async function generateMetadata({ params }: PageProps): Promise<Metadata> {
  const { slug } = await params;
  try {
    const job = await fetchApi<JobDetail>(`/api/v1/jobs/by-slug/${slug}/`, {
      revalidate,
    });
    return {
      title: `${job.title} | Study Tracker`,
      description: job.description?.slice(0, 160) ?? "",
      alternates: {
        canonical: job.canonical_url,
      },
    };
  } catch {
    return {};
  }
}

function formatDate(value: string | null | undefined): string {
  if (!value) return "Unknown";
  return new Date(value).toLocaleDateString("en-US", {
    year: "numeric",
    month: "long",
    day: "numeric",
  });
}

export default async function JobPage({ params }: PageProps) {
  const { slug } = await params;
  let job: JobDetail;
  try {
    job = await fetchApi<JobDetail>(`/api/v1/jobs/by-slug/${slug}/`, {
      revalidate,
    });
  } catch (err) {
    if (err instanceof ApiError && err.status === 404) {
      notFound();
    }
    throw err;
  }

  const jsonLd = escapeJsonLd(job.structured_data);

  return (
    <main className="max-w-3xl mx-auto p-6">
      {jsonLd && (
        <script
          type="application/ld+json"
          dangerouslySetInnerHTML={{ __html: jsonLd }}
        />
      )}
      <h1 className="text-2xl font-bold mb-2">{job.title}</h1>
      <p className="text-lg text-gray-700 mb-1">{job.company.name}</p>
      <p className="mb-1">{job.location_raw || "Location not specified"}</p>
      <p className="mb-1">{job.job_type}</p>
      <p className="mb-1">Posted: {formatDate(job.posted_at)}</p>
      <p className="mb-4">Last checked: {formatDate(job.scraped_at)}</p>
      {job.apply_url && (
        <a
          href={job.apply_url}
          target="_blank"
          rel="noopener noreferrer"
          className="inline-block bg-blue-600 text-white px-6 py-2 rounded hover:bg-blue-700"
        >
          Apply
        </a>
      )}
    </main>
  );
}
