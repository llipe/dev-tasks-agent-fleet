"use client";

import { useRouter } from "next/navigation";
import { DataTable, createColumnHelper } from "@/components/data-table";
import { StatusBadge, type Status } from "@/components/status-badge";
import { RelativeTime } from "@/components/relative-time";
import { CostEstimate } from "@/components/cost-estimate";
import type { AgentRow } from "./agents-data.js";
import type { DataTableState } from "@/components/data-table";

const columnHelper = createColumnHelper<AgentRow>();

const columns = [
  columnHelper.accessor("name", {
    header: "Agent",
    cell: (info) => (
      <div>
        <span className="font-medium text-text-primary">{info.getValue()}</span>
        <span className="ml-2 text-xs text-text-muted">{info.row.original.domain}</span>
      </div>
    ),
  }),
  columnHelper.accessor("lastRunAt", {
    header: "Last Run",
    cell: (info) => {
      const value = info.getValue();
      if (!value) return <span className="text-text-muted">—</span>;
      return <RelativeTime dateTime={value} />;
    },
  }),
  columnHelper.accessor("status", {
    header: "Status",
    cell: (info) => {
      const value = info.getValue();
      if (!value) return <span className="text-text-muted">—</span>;
      return <StatusBadge status={value as Status} />;
    },
  }),
  columnHelper.accessor("activeRepos", {
    header: "Active Repos",
    cell: (info) => info.getValue(),
    meta: { numeric: true },
  }),
  columnHelper.accessor("cost30d", {
    header: "30d Cost",
    cell: (info) => {
      const cost = info.getValue();
      if (!cost) return <CostEstimate usd={null} complete={false} />;
      return <CostEstimate usd={cost.usd} complete={cost.complete} />;
    },
    meta: { numeric: true },
  }),
];

interface AgentsTableProps {
  data: AgentRow[];
  state: DataTableState;
}

/**
 * Client component wrapping DataTable for the agents list.
 * Handles row click navigation to /agents/[name].
 */
export function AgentsTable({ data, state }: AgentsTableProps) {
  const router = useRouter();

  const handleRowClick = (row: AgentRow) => {
    router.push(`/agents/${encodeURIComponent(row.name)}`);
  };

  return (
    <DataTable
      columns={columns}
      data={data}
      state={state}
      onRowClick={handleRowClick}
      emptyMessage="No agents found"
      errorMessage="Failed to load agents. Please try again later."
      timeoutMessage="Request timed out. Try refreshing the page."
    />
  );
}
