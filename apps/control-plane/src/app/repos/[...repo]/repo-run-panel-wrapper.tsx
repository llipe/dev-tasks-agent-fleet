/**
 * Repo run panel wrapper — S-023.
 *
 * Server component that conditionally renders the RunPanel
 * when a `run` search param is present. Identical to S-021 pattern.
 */

import { RunPanel } from "@/components/run-panel/index.js";
import { fetchTraceData, fetchLogData } from "@/app/agents/[name]/run-panel-data.js";
import type { MergedRun } from "@/server/runs/merge-runs.js";
import type { ParsedRunFilters } from "@/lib/run-filters.js";

interface RepoRunPanelWrapperProps {
  repoId: string;
  runs: MergedRun[];
  filters: ParsedRunFilters;
}

export function RepoRunPanelWrapper({ repoId: _repoId, runs, filters }: RepoRunPanelWrapperProps) {
  if (!filters.run) {
    return null;
  }

  // Find the matching run from the list for immediate metadata rendering
  const selectedRun = runs.find((r) => r.sessionId === filters.run);
  if (!selectedRun) {
    return null;
  }

  // Start async fetches — these promises are passed to the client component
  const tracePromise = fetchTraceData(selectedRun.sessionId, filters.from, filters.to);
  const logsPromise = fetchLogData(selectedRun.sessionId, filters.from, filters.to);

  return (
    <RunPanel
      run={selectedRun}
      agentName={selectedRun.agentName}
      tracePromise={tracePromise}
      logsPromise={logsPromise}
    />
  );
}
