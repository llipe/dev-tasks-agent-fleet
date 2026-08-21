/**
 * Repos data layer — S-022, sub-task 22.1.
 *
 * Fetches the agent's subjects (repos) for the Repos tab DataTable.
 * Uses DI for testability.
 */

import { listAgentSubjects, type SubjectAgent } from "@/server/repository/scope-repository.js";
import type { DataTableState } from "@/components/data-table.js";

export interface ReposDataDeps {
  listAgentSubjects: typeof listAgentSubjects;
}

const productionDeps: ReposDataDeps = {
  listAgentSubjects,
};

export interface RepoRow {
  subjectId: string;
  enabled: boolean;
  lastRunAt?: string;
  lastStatus?: string;
  lastOutcomeUrl?: string;
}

export interface ReposDataResult {
  repos: RepoRow[];
  state: DataTableState;
}

/**
 * Load repos for an agent.
 */
export async function loadReposForAgent(
  agentName: string,
  deps: ReposDataDeps = productionDeps,
): Promise<ReposDataResult> {
  const outcome = await deps.listAgentSubjects(agentName);

  if (outcome.status === "ok") {
    const repos: RepoRow[] = outcome.data.map((item: SubjectAgent) => ({
      subjectId: item.subjectId,
      enabled: item.enabled,
      lastRunAt: item.lastRunAt,
      lastStatus: item.lastStatus,
      lastOutcomeUrl: item.lastOutcomeUrl,
    }));
    return { repos, state: repos.length === 0 ? "empty" : "ready" };
  }

  if (outcome.status === "empty") {
    return { repos: [], state: "empty" };
  }

  if (outcome.status === "timeout") {
    return { repos: [], state: "timeout" };
  }

  return { repos: [], state: "error" };
}
