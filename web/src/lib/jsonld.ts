export function escapeJsonLd(data: unknown): string | null {
  if (!data) return null;
  return JSON.stringify(data).replace(/</g, "\\u003c");
}
