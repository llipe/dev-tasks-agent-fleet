"use client";

/**
 * Repos table client component — S-023.
 *
 * Renders the DataTable with repo columns and row click navigation to /repos/[repo].
 */

import { useRouter } from "next/navigation";
import { useCallback } from "react";
import { DataTable, createColumnHelper } from "@/components/data-table";
import { StatusBadge, type Status } from "@/components/status-badge";
import { RelativeTime } from "@/components/relative-time";
import type { RepoRow } from "./repos-data.js";
import type { DataTableState } from "@/components/data-table.js";

const columnHelper = createColumnHelper<RepoRow>();

const columns = [
  columnHelper.accessor("subjectId", {
    header: "Repo",
    cell: (info) => <span className="font-medium text-text-primary">{info.getValue()}</span>,
  }),
  columnHelper.accessor("agentCount", {
    header: "Agents",
    cell: (info) => {
      const count = info.getValue();
      return (
        <span className="tabular-nums text-text-primary">
          {count} {count === 1 ? "agent" : "agents"}
        </span>
      );
    },
  }),
  columnHelper.accessor("lastRunAt", {
    header: "Last Activity",
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
];

interface ReposTableClientProps {
  repos: RepoRow[];
  state: DataTableState;
}

export function ReposTableClient({ repos, state }: ReposTableClientProps) {
  const router = useRouter();

  const handleRowClick = useCallback(
    (row: RepoRow) => {
      router.push(`/repos/${encodeURIComponent(row.subjectId)}`);
    },
    [router],
  );

  return (
    <DataTable
      columns={columns}
      data={repos}
      state={state}
      onRowClick={handleRowClick}
      emptyMessage="No repositories found."
      errorMessage="Failed to load repositories. Please try again later."
      timeoutMessage="Request timed out. Please try again."
    />
  );
}
