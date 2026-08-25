/**
 * Repos list page — S-023.
 *
 * Server component that fetches all subjects and their coverage data.
 * Renders a DataTable with repo, agents covering it, last activity, and status.
 * Row click navigates to /repos/[repo] for per-repo run detail.
 */

import type { DataTableState } from "@/components/data-table.js";
import { buildRepoRows, type RepoRow, type ReposDataDeps } from "./repos-data.js";
import { ReposTableClient } from "./repos-table-client.js";
import { listSubjects, listAgentSubjects } from "@/server/repository/scope-repository.js";
import { listManagedAgents } from "@/server/aws/tagging-adapter.js";
import { getAgentLifecycle } from "@/server/aws/agentcore-adapter.js";

export const dynamic = "force-dynamic";

/** Production dependencies */
const productionDeps: ReposDataDeps = {
  listSubjects,
  listManagedAgents,
  listAgentSubjects,
  getAgentLifecycle,
};

export default async function ReposPage() {
  let repos: RepoRow[] = [];
  let state: DataTableState = "ready";

  try {
    repos = await buildRepoRows(productionDeps);
    if (repos.length === 0) {
      state = "empty";
    }
  } catch (error: unknown) {
    const errorObj = error as Error & { code?: string; name?: string };
    console.error("[repos-page] Failed to load repos", {
      name: errorObj.name,
      code: errorObj.code,
      message: errorObj.message,
      stack: errorObj.stack,
    });
    if (errorObj.code === "TIMEOUT" || errorObj.message?.includes("timeout")) {
      state = "timeout";
    } else {
      state = "error";
    }
  }

  return (
    <div className="p-6">
      <h1 className="text-2xl font-bold text-text-primary">Repos</h1>
      <p className="mt-1 text-sm text-text-secondary">Repository inventory with agent coverage.</p>

      <div className="mt-6">
        <ReposTableClient repos={repos} state={state} />
      </div>
    </div>
  );
}
