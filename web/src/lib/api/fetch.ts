import type { paths } from "./schema";

export class ApiError extends Error {
  status: number;

  constructor(status: number, message: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

interface FetchApiOptions {
  revalidate?: number;
}

type PathKey = keyof paths;

export async function fetchApi<P extends PathKey>(
  path: P,
  options?: FetchApiOptions
): Promise<
  paths[P] extends { get: { responses: { 200: { content: { "application/json": infer T } } } } }
    ? T
    : never
>;
export async function fetchApi<T>(
  path: string,
  options?: FetchApiOptions
): Promise<T>;
export async function fetchApi(
  path: string,
  options?: FetchApiOptions
): Promise<unknown> {
  const { API_BASE_URL, SSR_SERVICE_TOKEN } = await import("@/lib/env");
  const url = `${API_BASE_URL}${path}`;
  const headers: Record<string, string> = {
    Accept: "application/json",
  };
  if (SSR_SERVICE_TOKEN) {
    headers["X-Service-Token"] = SSR_SERVICE_TOKEN;
  }
  const init: RequestInit & { next?: { revalidate?: number } } = {
    headers,
  };
  if (options?.revalidate !== undefined) {
    init.next = { revalidate: options.revalidate };
  }
  const res = await fetch(url, init);
  if (!res.ok) {
    throw new ApiError(res.status, `API error: ${res.status} ${res.statusText}`);
  }
  return res.json();
}
