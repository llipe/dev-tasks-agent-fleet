"use client";

/**
 * Repos DataTable client wrapper — S-022, sub-task 22.1.
 *
 * Columns: Repo, Enabled (toggle), Last Run (RelativeTime), Status (StatusBadge), Output.
 */

import { useMemo } from "react";
import { DataTable, createColumnHelper, type DataTableState } from "@/components/data-table.js";
import { StatusBadge, type Status } from "@/components/status-badge.js";
import { RelativeTime } from "@/components/relative-time.js";
import { EnabledToggle } from "./enabled-toggle.js";
import { ParamsEditor } from "./params-editor.js";
import type { RepoRow } from "./repos-data.js";

interface ReposTableClientProps {
  agentName: string;
  repos: RepoRow[];
  state: DataTableState;
}

const columnHelper = createColumnHelper<RepoRow>();

export function ReposTableClient({ agentName, repos, state }: ReposTableClientProps) {
  const columns = useMemo(
    () => [
      columnHelper.accessor("subjectId", {
        header: "Repo",
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        cell: (info: any) => <span className="font-mono text-xs">{info.getValue()}</span>,
      }),
      columnHelper.display({
        id: "enabled",
        header: "Enabled",
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        cell: (info: any) => (
          <EnabledToggle
            subjectId={info.row.original.subjectId}
            agentName={agentName}
            initialEnabled={info.row.original.enabled}
          />
        ),
      }),
      columnHelper.accessor("lastRunAt", {
        header: "Last Run",
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        cell: (info: any) => {
          const value = info.getValue();
          return value ? (
            <RelativeTime dateTime={value} />
          ) : (
            <span className="text-text-muted">—</span>
          );
        },
      }),
      columnHelper.accessor("lastStatus", {
        header: "Status",
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        cell: (info: any) => {
          const status = info.getValue();
          if (!status) return <span className="text-text-muted">—</span>;
          return <StatusBadge status={status as Status} />;
        },
      }),
      columnHelper.accessor("lastOutcomeUrl", {
        header: "Output",
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        cell: (info: any) => {
          const url = info.getValue();
          if (!url) return <span className="text-text-muted">—</span>;
          return (
            <a
              href={url}
              target="_blank"
              rel="noopener noreferrer"
              className="text-brand-secondary underline hover:text-brand-primary"
              onClick={(e) => e.stopPropagation()}
            >
              View
            </a>
          );
        },
      }),
      columnHelper.display({
        id: "params",
        header: "Params",
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        cell: (info: any) => (
          <ParamsEditor subjectId={info.row.original.subjectId} agentName={agentName} />
        ),
      }),
    ],
    [agentName],
  );

  return (
    <DataTable<RepoRow>
      columns={columns}
      data={repos}
      state={state}
      emptyMessage="No repositories configured for this agent."
      errorMessage="Failed to load repositories."
      timeoutMessage="Request timed out. Try again later."
    />
  );
}
