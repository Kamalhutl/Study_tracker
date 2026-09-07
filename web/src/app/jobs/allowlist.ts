export const ALLOWED_PARAMS = [
  "job_type",
  "work_mode",
  "experience_level",
  "city",
  "q",
  "page",
] as const;

export type AllowedParam = (typeof ALLOWED_PARAMS)[number];

export const API_FILTER_MAP: Record<AllowedParam, string> = {
  job_type: "job_type",
  work_mode: "work_mode",
  experience_level: "experience_level",
  city: "city",
  q: "q",
  page: "page",
};

export const MAX_PAGE_SIZE = 100;

export function filterSearchParams(
  searchParams: URLSearchParams
): { filtered: URLSearchParams; hasUnknown: boolean } {
  const filtered = new URLSearchParams();
  let hasUnknown = false;

  for (const [key, value] of searchParams.entries()) {
    if ((ALLOWED_PARAMS as readonly string[]).includes(key)) {
      if (key === "page") {
        const num = parseInt(value, 10);
        if (!isNaN(num) && num >= 1) {
          filtered.set(key, String(num));
        }
      } else {
        filtered.set(key, value);
      }
    } else {
      hasUnknown = true;
    }
  }

  return { filtered, hasUnknown };
}

export function buildApiQueryString(
  filtered: URLSearchParams,
  pageSize?: number
): string {
  const apiParams = new URLSearchParams();

  for (const [key, value] of filtered.entries()) {
    if (key === "page") {
      apiParams.set("page", value);
    } else {
      apiParams.set(API_FILTER_MAP[key as AllowedParam], value);
    }
  }

  if (pageSize !== undefined) {
    const clamped = Math.min(Math.max(1, pageSize), MAX_PAGE_SIZE);
    apiParams.set("page_size", String(clamped));
  }

  return apiParams.toString();
}

export function hasActiveFilters(filtered: URLSearchParams): boolean {
  for (const key of filtered.keys()) {
    if (key !== "page") return true;
  }
  return false;
}

export function buildPaginationUrl(
  baseUrl: string,
  filtered: URLSearchParams,
  page: number
): string {
  const params = new URLSearchParams(filtered);
  if (page <= 1) {
    params.delete("page");
  } else {
    params.set("page", String(page));
  }
  const qs = params.toString();
  return qs ? `${baseUrl}?${qs}` : baseUrl;
}
