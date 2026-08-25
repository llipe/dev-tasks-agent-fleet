/**
 * Run panel data layer — S-021.
 *
 * Provides async data fetching for the run panel's timeline and logs sections.
 * These return promises that are passed to client components for Suspense-based rendering.
 */

import { querySessionTrace } from "@/server/runs/trace-query.js";
import { filterLogsBySessionId } from "@/server/aws/filter-logs-adapter.js";
import { errorOutcome } from "@/server/repository/types.js";
import type { TimelineSpan } from "@/server/runs/span-to-run-mapper.js";
import type { ReadOutcome } from "@/server/repository/types.js";

/**
 * Resolve the agent's CloudWatch application log group from the environment.
 *
 * There is deliberately no compile-time default. AgentCore names this group
 * `/aws/bedrock-agentcore/runtimes/depupdater_dep_updater-<generated>-DEFAULT`,
 * and the suffix is regenerated whenever the runtime is recreated, so any
 * hardcoded value is wrong the moment the runtime changes. Querying a
 * nonexistent group returns no events rather than an error, which would make a
 * misconfigured deployment look like a run that produced no logs.
 *
 * Obtain the value with:
 *
 *   aws logs describe-log-groups \
 *     --log-group-name-prefix /aws/bedrock-agentcore/runtimes/depupdater_dep_updater \
 *     --query 'logGroups[0].logGroupName' --output text
 *
 * Read per call rather than captured at module load so a redeploy that changes
 * the group only needs the process environment updated.
 */
export function resolveAgentLogGroup(): string | null {
  const configured = process.env["AGENT_LOG_GROUP"]?.trim();
  return configured ? configured : null;
}

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
  const logGroupName = resolveAgentLogGroup();
  if (!logGroupName) {
    return Promise.resolve(
      errorOutcome<string[]>(
        "AGENT_LOG_GROUP is not configured. Set it to the agent's CloudWatch " +
          "application log group; discover the name with `aws logs describe-log-groups " +
          "--log-group-name-prefix /aws/bedrock-agentcore/runtimes/depupdater_dep_updater`.",
      ),
    );
  }

  return deps.filterLogsBySessionId({
    logGroupName,
    sessionId,
    startTime: from.getTime(),
    endTime: to.getTime(),
  });
}
