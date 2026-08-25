/**
 * Repos tab content — S-022, sub-task 22.1.
 *
 * Server component that fetches the agent's subjects and renders a DataTable
 * with: repo, enabled toggle, last run, last status, output.
 * Includes AddRepoForm for adding new repos.
 */

import { loadReposForAgent, type RepoRow } from "./repos-data.js";
import type { DataTableState } from "@/components/data-table.js";
import { ReposTableClient } from "./repos-table-client.js";
import { AddRepoForm } from "./add-repo-form.js";

interface ReposTabProps {
  agentName: string;
}

export async function ReposTab({ agentName }: ReposTabProps) {
  let repos: RepoRow[] = [];
  let state: DataTableState;

  try {
    const result = await loadReposForAgent(agentName);
    repos = result.repos;
    state = result.state;
  } catch (error: unknown) {
    const errorObj = error as Error & { code?: string };
    if (errorObj.code === "TIMEOUT" || errorObj.message?.includes("timeout")) {
      state = "timeout";
    } else {
      state = "error";
    }
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h2 className="text-lg font-semibold text-text-primary">Repositories</h2>
        <AddRepoForm agentName={agentName} />
      </div>
      <ReposTableClient agentName={agentName} repos={repos} state={state} />
    </div>
  );
}
