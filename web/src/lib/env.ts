import "server-only";

export const SITE_URL = process.env.NEXT_PUBLIC_SITE_URL || "http://localhost:3000";
export const API_BASE_URL = process.env.API_BASE_URL || "http://127.0.0.1:8000";
export const SSR_SERVICE_TOKEN = process.env.SSR_SERVICE_TOKEN || "";
