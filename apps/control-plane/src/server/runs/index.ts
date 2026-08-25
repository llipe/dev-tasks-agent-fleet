/**
 * Runs module — public API for querying run data from CloudWatch spans and DynamoDB config.
 */

export { queryRuns, clearRunListCache } from "./run-query-service.js";
export { querySessionTrace } from "./trace-query.js";
export { mapRowsToRuns, mapRowsToTimeline } from "./span-to-run-mapper.js";
export type { Run, ModelUsage, TimelineSpan } from "./span-to-run-mapper.js";
export type { QueryOutcome } from "./query-executor.js";
export type { RunListQueryInput, SessionQueryInput } from "./query-builder.js";

// S-018: Run merge, config projection
export { mergeRuns } from "./merge-runs.js";
export type { MergedRun, MergeFilters } from "./merge-runs.js";
export { projectConfigRun } from "./config-projection.js";
export type { ConfigRun } from "./config-projection.js";
