/**
 * Runs tab content — S-020.
 *
 * Server component that fetches merged runs for the agent with applied filters.
 * Renders a DataTable with filter controls.
 */

import type { ParsedRunFilters } from "@/lib/run-filters.js";
import type { MergedRun } from "@/server/runs/merge-runs.js";
import type { DataTableState } from "@/components/data-table.js";
import { RunsTableClient } from "./runs-table-client.js";
import { loadRunsForAgent } from "./runs-data.js";

interface RunsTabProps {
  agentName: string;
  filters: ParsedRunFilters;
}

export async function RunsTab({ agentName, filters }: RunsTabProps) {
  let runs: MergedRun[] = [];
  let state: DataTableState = "ready";

  try {
    runs = await loadRunsForAgent(agentName, filters);
    if (runs.length === 0) {
      state = "empty";
    }
  } catch (error: unknown) {
    const errorObj = error as Error & { code?: string };
    if (errorObj.code === "TIMEOUT" || errorObj.message?.includes("timeout")) {
      state = "timeout";
    } else {
      state = "error";
    }
  }

  return <RunsTableClient agentName={agentName} runs={runs} state={state} filters={filters} />;
}
