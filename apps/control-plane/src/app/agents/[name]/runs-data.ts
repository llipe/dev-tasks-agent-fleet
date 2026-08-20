/**
 * Runs data layer — S-020.
 *
 * Fetches and merges runs for a specific agent with applied filters.
 * Uses mergeRuns from S-018 combining span runs and config runs.
 */

import type { ParsedRunFilters } from "@/lib/run-filters.js";
import { mergeRuns, type MergedRun } from "@/server/runs/merge-runs.js";
import { queryRuns } from "@/server/runs/run-query-service.js";
import { listAgentSubjects } from "@/server/repository/scope-repository.js";
import { projectConfigRun } from "@/server/runs/config-projection.js";
import { getAgentLifecycle } from "@/server/aws/agentcore-adapter.js";
import { estimateRunCost, loadPricingTable } from "@/lib/cost.js";

/**
 * Dependency injection interface for testability.
 */
export interface RunsDataDeps {
  queryRuns: typeof queryRuns;
  listAgentSubjects: typeof listAgentSubjects;
  getAgentLifecycle: typeof getAgentLifecycle;
  loadPricingTable: typeof loadPricingTable;
  estimateRunCost: typeof estimateRunCost;
}

/** Default production dependencies */
const productionDeps: RunsDataDeps = {
  queryRuns,
  listAgentSubjects,
  getAgentLifecycle,
  loadPricingTable,
  estimateRunCost,
};

/**
 * Load merged runs for an agent with filters applied.
 *
 * 1. Query span runs from Logs Insights (filtered by date range)
 * 2. Query config runs from DynamoDB (latest state per subject)
 * 3. Merge and filter
 * 4. Attach cost estimates
 */
export async function loadRunsForAgent(
  agentName: string,
  filters: ParsedRunFilters,
  deps: RunsDataDeps = productionDeps,
): Promise<MergedRun[]> {
  // Fetch span runs from Logs Insights
  const spanOutcome = await deps.queryRuns({
    agentName,
    from: filters.from,
    to: filters.to,
  });

  const spanRuns = spanOutcome.status === "ok" ? spanOutcome.data : [];

  // Fetch config runs from DynamoDB
  const subjectsOutcome = await deps.listAgentSubjects(agentName);
  const subjects = subjectsOutcome.status === "ok" ? subjectsOutcome.data : [];

  // Get agent maxLifetime for status derivation
  const lifecycle = await deps.getAgentLifecycle(agentName);

  // Project config rows into ConfigRun objects
  const configRuns = subjects
    .map((subject) => projectConfigRun(subject, lifecycle.maxLifetime))
    .filter((run) => run !== null);

  // Merge with filters
  const merged = mergeRuns(spanRuns, configRuns, {
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
