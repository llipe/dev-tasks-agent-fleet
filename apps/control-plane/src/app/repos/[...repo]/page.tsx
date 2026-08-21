/**
 * Per-repo run detail page — S-023.
 *
 * Dynamic route: /repos/[...repo] (catch-all since repo is owner/repo with a slash).
 * Reuses RunsTable pattern from S-020 with an additional Agent column.
 * Renders filters, run table, and run panel identically to S-020/S-021.
 */

import { parseRunFilters, type ParsedRunFilters } from "@/lib/run-filters.js";
import type { MergedRun } from "@/server/runs/merge-runs.js";
import type { DataTableState } from "@/components/data-table.js";
import { RepoRunsTableClient } from "./repo-runs-table-client.js";
import { RepoRunPanelWrapper } from "./repo-run-panel-wrapper.js";
import { loadRunsForRepo } from "./repo-runs-data.js";

export const dynamic = "force-dynamic";

interface RepoDetailPageProps {
  params: Promise<{ repo: string[] }>;
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}

export default async function RepoDetailPage({ params, searchParams }: RepoDetailPageProps) {
  const { repo } = await params;
  const rawParams = await searchParams;

  // Parse catch-all route segments into owner/repo
  const repoId = repo.join("/");

  // Normalize searchParams to simple string values
  const normalizedParams: Record<string, string> = {};
  for (const [key, value] of Object.entries(rawParams)) {
    if (typeof value === "string") {
      normalizedParams[key] = value;
    } else if (Array.isArray(value) && value.length > 0 && value[0] !== undefined) {
      normalizedParams[key] = value[0];
    }
  }

  const filters: ParsedRunFilters = parseRunFilters(normalizedParams);

  // Load runs for this repo
  let runs: MergedRun[] = [];
  let state: DataTableState = "ready";

  try {
    runs = await loadRunsForRepo(repoId, filters);
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

  return (
    <div className="p-6">
      <h1 className="text-2xl font-bold text-text-primary">{repoId}</h1>
      <p className="mt-1 text-sm text-text-secondary">
        Runs across all agents for this repository.
      </p>

      <div className="mt-6">
        <RepoRunsTableClient repoId={repoId} runs={runs} state={state} filters={filters} />
      </div>

      {/* Run side panel — same as S-021 */}
      <RepoRunPanelWrapper repoId={repoId} runs={runs} filters={filters} />
    </div>
  );
}
