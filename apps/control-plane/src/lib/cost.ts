/**
 * Cost estimation module — S-018.
 *
 * - Loads pricing table from pricing-v1.json (once at startup)
 * - Estimates run cost from per-model token usage
 * - Aggregates 30-day per-agent cost with 5-min cache
 * - Logs warn on any unpriced model_id
 */

import { readFileSync } from "node:fs";
import { resolve, dirname } from "node:path";
import { fileURLToPath } from "node:url";
import type { ModelUsage } from "../server/runs/span-to-run-mapper.js";
import { TtlCache } from "../server/cache/ttl-cache.js";

/** Pricing entry for a single model */
export interface PricingEntry {
  inputPer1k: number;
  outputPer1k: number;
}

/** Pricing table: model_id → pricing entry */
export type PricingTable = Record<string, PricingEntry>;

/** Result of cost estimation for a single run */
export interface RunCostEstimate {
  /** Estimated USD cost */
  usd: number;
  /** True only if ALL models in the run have pricing entries */
  complete: boolean;
  /** Model IDs that had no pricing entry */
  unpricedModels: string[];
}

// --- Pricing table loader ---

let cachedTable: PricingTable | null = null;

/**
 * Load the pricing table from pricing-v1.json.
 * Loaded once and cached in-process.
 */
export function loadPricingTable(): PricingTable {
  if (cachedTable) return cachedTable;

  const __dirname = dirname(fileURLToPath(import.meta.url));
  const pricingPath = resolve(__dirname, "../../pricing/pricing-v1.json");

  const content = readFileSync(pricingPath, "utf-8");
  cachedTable = JSON.parse(content) as PricingTable;
  return cachedTable;
}

/**
 * Reset the cached pricing table (for testing).
 */
export function resetPricingTableCache(): void {
  cachedTable = null;
}

// --- Run cost estimation ---

/**
 * Estimate the cost of a single run based on per-model token usage.
 *
 * Rules:
 * - For each model: cost = (tokensIn / 1000) * inputPer1k + (tokensOut / 1000) * outputPer1k
 * - Sum all model costs
 * - If any model is unpriced: complete=false, model added to unpricedModels
 * - Log warn for each unpriced model
 * - Genuinely free run (all priced, total=0): { usd: 0, complete: true, unpricedModels: [] }
 * - Empty perModel (no model invocations): { usd: 0, complete: true, unpricedModels: [] }
 */
export function estimateRunCost(perModel: ModelUsage[], table: PricingTable): RunCostEstimate {
  if (perModel.length === 0) {
    return { usd: 0, complete: true, unpricedModels: [] };
  }

  let totalUsd = 0;
  const unpricedModels: string[] = [];

  for (const usage of perModel) {
    const entry = table[usage.modelId];
    if (!entry) {
      unpricedModels.push(usage.modelId);
      console.warn(`[cost] Unpriced model_id: ${usage.modelId}`);
      continue;
    }

    const inputCost = (usage.tokensIn / 1000) * entry.inputPer1k;
    const outputCost = (usage.tokensOut / 1000) * entry.outputPer1k;
    totalUsd += inputCost + outputCost;
  }

  return {
    usd: totalUsd,
    complete: unpricedModels.length === 0,
    unpricedModels,
  };
}

// --- 30-day per-agent cost aggregate ---

/** Cache TTL for 30-day cost aggregate: 5 minutes */
const COST_CACHE_TTL_MS = 5 * 60 * 1000;

/** Cache for per-agent 30-day cost aggregates */
const agentCostCache = new TtlCache<string, RunCostEstimate>({
  ttlMs: COST_CACHE_TTL_MS,
  maxEntries: 100,
});

export interface AgentCostInput {
  agentName: string;
  runs: Array<{ perModel: ModelUsage[] }>;
}

/**
 * Calculate 30-day per-agent cost aggregate with 5-min cache.
 *
 * Sums estimateRunCost across all runs for the agent.
 */
export async function getAgentCostAggregate(
  agentName: string,
  fetchRuns: () => Promise<Array<{ perModel: ModelUsage[] }>>,
): Promise<RunCostEstimate> {
  const table = loadPricingTable();

  return agentCostCache.get(`cost:30d:${agentName}`, async () => {
    const runs = await fetchRuns();
    let totalUsd = 0;
    let allComplete = true;
    const allUnpriced = new Set<string>();

    for (const run of runs) {
      const estimate = estimateRunCost(run.perModel, table);
      totalUsd += estimate.usd;
      if (!estimate.complete) allComplete = false;
      for (const model of estimate.unpricedModels) {
        allUnpriced.add(model);
      }
    }

    return {
      usd: totalUsd,
      complete: allComplete,
      unpricedModels: Array.from(allUnpriced),
    };
  });
}

/**
 * Clear the agent cost cache (for testing).
 */
export function clearAgentCostCache(): void {
  agentCostCache.clear();
}
