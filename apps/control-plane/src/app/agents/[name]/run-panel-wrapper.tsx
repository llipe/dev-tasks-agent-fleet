/**
 * Run panel wrapper — S-021.
 *
 * Server component that conditionally renders the RunPanel
 * when a `run` search param is present and matches a run from the list.
 *
 * Initiates data fetching (trace + logs) as promises passed to the client panel.
 */

import { RunPanel } from "@/components/run-panel/index.js";
import { fetchTraceData, fetchLogData } from "./run-panel-data.js";
import type { MergedRun } from "@/server/runs/merge-runs.js";
import type { ParsedRunFilters } from "@/lib/run-filters.js";

interface RunPanelWrapperProps {
  agentName: string;
  runs: MergedRun[];
  filters: ParsedRunFilters;
}

export function RunPanelWrapper({ agentName, runs, filters }: RunPanelWrapperProps) {
  if (!filters.run) {
    return null;
  }

  // Find the matching run from the list for immediate metadata rendering
  const selectedRun = runs.find((r) => r.sessionId === filters.run);
  if (!selectedRun) {
    return null;
  }

  // Start async fetches — these promises are passed to the client component
  // and consumed via React `use()` inside Suspense boundaries
  const tracePromise = fetchTraceData(selectedRun.sessionId, filters.from, filters.to);
  const logsPromise = fetchLogData(selectedRun.sessionId, filters.from, filters.to);

  return (
    <RunPanel
      run={selectedRun}
      agentName={agentName}
      tracePromise={tracePromise}
      logsPromise={logsPromise}
    />
  );
}
