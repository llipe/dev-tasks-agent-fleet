"use client";

/**
 * Repo runs table client component — S-023.
 *
 * Same as RunsTableClient from S-020 but with an Agent column added.
 * Renders DataTable with run columns, filter controls, and row click for run panel.
 */

import { useRouter, useSearchParams } from "next/navigation";
import { useCallback } from "react";
import { DataTable, createColumnHelper } from "@/components/data-table";
import { StatusBadge, type Status } from "@/components/status-badge";
import { RelativeTime } from "@/components/relative-time";
import { CostEstimate } from "@/components/cost-estimate";
import { formatDuration, formatTokens } from "@/lib/run-filters.js";
import type { MergedRun } from "@/server/runs/merge-runs.js";
import type { DataTableState } from "@/components/data-table.js";
import type { ParsedRunFilters } from "@/lib/run-filters.js";
import { RepoRunFilters } from "./repo-run-filters.js";

const columnHelper = createColumnHelper<MergedRun>();

const columns = [
  columnHelper.accessor("startedAt", {
    header: "Date",
    cell: (info) => {
      const value = info.getValue();
      if (!value) return <span className="text-text-muted">—</span>;
      return <RelativeTime dateTime={value} />;
    },
  }),
  columnHelper.accessor("agentName", {
    header: "Agent",
    cell: (info) => <span className="font-medium text-text-primary">{info.getValue()}</span>,
  }),
  columnHelper.accessor("status", {
    header: "Status",
    cell: (info) => {
      const value = info.getValue();
      if (!value) return <span className="text-text-muted">—</span>;
      return <StatusBadge status={value as Status} />;
    },
  }),
  columnHelper.accessor("durationMs", {
    header: "Duration",
    cell: (info) => <span className="tabular-nums">{formatDuration(info.getValue())}</span>,
    meta: { numeric: true },
  }),
  columnHelper.display({
    id: "tokens",
    header: "Tokens",
    cell: (info) => {
      const row = info.row.original;
      const totalIn = row.perModel.reduce((sum, m) => sum + m.tokensIn, 0);
      const totalOut = row.perModel.reduce((sum, m) => sum + m.tokensOut, 0);
      return <span className="tabular-nums">{formatTokens(totalIn, totalOut)}</span>;
    },
    meta: { numeric: true },
  }),
  columnHelper.accessor("cost", {
    header: "Cost",
    cell: (info) => {
      const cost = info.getValue();
      if (!cost) return <CostEstimate usd={null} complete={false} />;
      return <CostEstimate usd={cost.usd} complete={cost.complete} />;
    },
    meta: { numeric: true },
  }),
  columnHelper.display({
    id: "output",
    header: "Output",
    cell: (info) => {
      const row = info.row.original;
      if (!row.outcomeType || row.outcomeType === "none" || row.outcomeType === "") {
        return <span className="text-text-muted">—</span>;
      }

      const label = row.outcomeType.charAt(0).toUpperCase() + row.outcomeType.slice(1);

      if (row.outcomeUrl) {
        return (
          <a
            href={row.outcomeUrl}
            target="_blank"
            rel="noopener noreferrer"
            className="text-brand-secondary underline hover:text-brand-primary"
            onClick={(e) => e.stopPropagation()}
          >
            {label}
          </a>
        );
      }

      return <span className="text-text-primary">{label}</span>;
    },
  }),
];

interface RepoRunsTableClientProps {
  repoId: string;
  runs: MergedRun[];
  state: DataTableState;
  filters: ParsedRunFilters;
}

export function RepoRunsTableClient({ repoId, runs, state, filters }: RepoRunsTableClientProps) {
  const router = useRouter();
  const searchParams = useSearchParams();

  const handleRowClick = useCallback(
    (row: MergedRun) => {
      const params = new URLSearchParams(searchParams.toString());
      params.set("run", row.sessionId);
      router.replace(`/repos/${encodeURIComponent(repoId)}?${params.toString()}`);
    },
    [router, repoId, searchParams],
  );

  return (
    <div>
      <RepoRunFilters repoId={repoId} filters={filters} />

      <div className="mt-4">
        <DataTable
          columns={columns}
          data={runs}
          state={state}
          onRowClick={handleRowClick}
          emptyMessage="No runs found for the selected filters."
          errorMessage="Failed to load runs. Please try again later."
          timeoutMessage="Query timed out. Try narrowing the date range."
        />
      </div>
    </div>
  );
}
