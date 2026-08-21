/**
 * Run panel data layer — S-021.
 *
 * Provides async data fetching for the run panel's timeline and logs sections.
 * These return promises that are passed to client components for Suspense-based rendering.
 */

import { querySessionTrace } from "@/server/runs/trace-query.js";
import { filterLogsBySessionId } from "@/server/aws/filter-logs-adapter.js";
import type { TimelineSpan } from "@/server/runs/span-to-run-mapper.js";
import type { ReadOutcome } from "@/server/repository/types.js";

const AGENT_LOG_GROUP = process.env["AGENT_LOG_GROUP"] ?? "/aws/agentcore/dep-updater";

export interface RunPanelDataDeps {
  querySessionTrace: typeof querySessionTrace;
  filterLogsBySessionId: typeof filterLogsBySessionId;
}

const productionDeps: RunPanelDataDeps = {
  querySessionTrace,
  filterLogsBySessionId,
};

/**
 * Fetch span trace data for the timeline.
 * Returns a promise suitable for React Suspense via `use()`.
 */
export function fetchTraceData(
  sessionId: string,
  from: Date,
  to: Date,
  deps: RunPanelDataDeps = productionDeps,
): Promise<ReadOutcome<TimelineSpan[]>> {
  return deps.querySessionTrace({ sessionId, from, to });
}

/**
 * Fetch log lines for the log viewer.
 * Returns a promise suitable for React Suspense via `use()`.
 */
export function fetchLogData(
  sessionId: string,
  from: Date,
  to: Date,
  deps: RunPanelDataDeps = productionDeps,
): Promise<ReadOutcome<string[]>> {
  return deps.filterLogsBySessionId({
    logGroupName: AGENT_LOG_GROUP,
    sessionId,
    startTime: from.getTime(),
    endTime: to.getTime(),
  });
}
