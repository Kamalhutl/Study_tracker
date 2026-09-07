import type { components } from "./schema";

type JobDetail = components["schemas"]["JobDetail"];

export type AssertCanonicalUrl = "canonical_url" extends keyof JobDetail ? true : never;
export type AssertStructuredData = "structured_data" extends keyof JobDetail ? true : never;

const _checkCanonicalUrl: AssertCanonicalUrl = true as AssertCanonicalUrl;
const _checkStructuredData: AssertStructuredData = true as AssertStructuredData;

void _checkCanonicalUrl;
void _checkStructuredData;
