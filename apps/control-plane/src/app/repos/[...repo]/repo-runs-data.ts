/**
 * Per-repo runs data layer — S-023.
 *
 * Fetches runs for a specific repo across all managed agents.
 * Reuses merge logic from S-018 and query service from S-017.
 *
 * Strategy:
 * 1. List managed agents
 * 2. For each agent, query span runs + config runs for this repo
 * 3. Merge all runs, filter by subjectId, apply status/date filters
 * 4. Attach cost estimates
 */

import type { ParsedRunFilters } from "@/lib/run-filters.js";
import { mergeRuns, type MergedRun } from "@/server/runs/merge-runs.js";
import { queryRuns } from "@/server/runs/run-query-service.js";
import { listAgentSubjects } from "@/server/repository/scope-repository.js";
import { projectConfigRun } from "@/server/runs/config-projection.js";
import { getAgentLifecycle } from "@/server/aws/agentcore-adapter.js";
import { estimateRunCost, loadPricingTable } from "@/lib/cost.js";
import { listManagedAgents } from "@/server/aws/tagging-adapter.js";
import type { DiscoveredAgent } from "@/server/aws/tagging-adapter.js";
import type { SubjectAgent } from "@/server/repository/scope-repository.js";
import type { ReadOutcome } from "@/server/repository/types.js";
import type { AgentLifecycle } from "@/server/aws/agentcore-adapter.js";
import type { RunCostEstimate, PricingTable } from "@/lib/cost.js";
import type { Run, ModelUsage } from "@/server/runs/span-to-run-mapper.js";

/**
 * Dependency injection interface for testability.
 */
export interface RepoRunsDataDeps {
  listManagedAgents: () => Promise<DiscoveredAgent[]>;
  listAgentSubjects: (agentName: string) => Promise<ReadOutcome<SubjectAgent[]>>;
  queryRuns: (input: { agentName: string; from: Date; to: Date }) => Promise<ReadOutcome<Run[]>>;
  getAgentLifecycle: (agentName: string) => Promise<AgentLifecycle>;
  loadPricingTable: () => PricingTable;
  estimateRunCost: (perModel: ModelUsage[], table: PricingTable) => RunCostEstimate;
}

/** Default production dependencies */
const productionDeps: RepoRunsDataDeps = {
  listManagedAgents,
  listAgentSubjects,
  queryRuns,
  getAgentLifecycle,
  loadPricingTable,
  estimateRunCost,
};

/**
 * Load merged runs for a specific repo across all agents.
 *
 * 1. List managed agents
 * 2. For each agent, query span and config runs
 * 3. Filter to only this repo's runs
 * 4. Merge and apply filters
 * 5. Attach cost estimates
 */
export async function loadRunsForRepo(
  repoId: string,
  filters: ParsedRunFilters,
  deps: RepoRunsDataDeps = productionDeps,
): Promise<MergedRun[]> {
  const agents = await deps.listManagedAgents();

  // Gather runs from all agents in parallel
  const allSpanRuns: Run[] = [];
  const allConfigRuns: ReturnType<typeof projectConfigRun>[] = [];

  await Promise.all(
    agents.map(async (agent) => {
      // Fetch span runs for this agent (will later filter by repo)
      const spanOutcome = await deps.queryRuns({
        agentName: agent.name,
        from: filters.from,
        to: filters.to,
      });

      if (spanOutcome.status === "ok") {
        // Filter to only runs for this repo
        const repoSpanRuns = spanOutcome.data.filter((run) => run.subjectId === repoId);
        allSpanRuns.push(...repoSpanRuns);
      }

      // Fetch config runs from DynamoDB for this agent
      const subjectsOutcome = await deps.listAgentSubjects(agent.name);
      if (subjectsOutcome.status === "ok") {
        const lifecycle = await deps.getAgentLifecycle(agent.name);
        // Filter to only the target repo and project
        const repoSubjects = subjectsOutcome.data.filter((s) => s.subjectId === repoId);
        for (const subject of repoSubjects) {
          const configRun = projectConfigRun(subject, lifecycle.maxLifetime);
          if (configRun) {
            allConfigRuns.push(configRun);
          }
        }
      }
    }),
  );

  // Filter out nulls from config runs
  const validConfigRuns = allConfigRuns.filter((r): r is Exclude<typeof r, null> => r !== null);

  // Merge with filters
  const merged = mergeRuns(allSpanRuns, validConfigRuns, {
    statusFilter: filters.status,
    from: filters.from,
    to: filters.to,
  });

  // Attach cost estimates
  const table = deps.loadPricingTable();
  return merged.map((run) => {
    if (run.perModel.length > 0) {
      const cost = deps.estimateRunCost(run.perModel, table);
      return {
        ...run,
        cost: { usd: cost.usd, complete: cost.complete, unpricedModels: cost.unpricedModels },
      };
    }
    return run;
  });
}
