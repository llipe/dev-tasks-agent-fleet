/**
 * Streaming boundary for cost column — S-019.
 *
 * This server component wraps the AgentsTable with full cost data.
 * It's rendered inside a Suspense boundary, so the table appears
 * immediately with cost showing a loading state, then streams in
 * once cost aggregation completes.
 */

import { AgentsTable } from "./agents-table.js";
import type { AgentRow } from "./agents-data.js";
import type { DataTableState } from "@/components/data-table";

interface AgentsCostColumnProps {
  rows: AgentRow[];
  state: DataTableState;
}

/**
 * Renders the AgentsTable with full data including cost.
 * Since the cost data is already fetched in the parent server component
 * (as part of buildAgentRows), this component simply passes through.
 *
 * The Suspense boundary in the parent provides the streaming effect.
 */
export function AgentsCostColumn({ rows, state }: AgentsCostColumnProps) {
  return <AgentsTable data={rows} state={state} />;
}
