/**
 * Agents list data layer — S-019.
 *
 * Fetches agent inventory, config counts, and 30d cost aggregate.
 * Pure data logic — no UI imports. Accepts dependencies for testability.
 */

import type { DiscoveredAgent } from "@/server/aws/tagging-adapter.js";
import type { SubjectAgent } from "@/server/repository/scope-repository.js";
import type { ReadOutcome } from "@/server/repository/types.js";
import type { RunCostEstimate } from "@/lib/cost.js";
import type { AgentLifecycle } from "@/server/aws/agentcore-adapter.js";
import { deriveStatus } from "@fleet/shared";

/**
 * Row view-model for the agents list table.
 */
export interface AgentRow {
  name: string;
  domain: string;
  lastRunAt: string | null;
  status: string | null;
  activeRepos: number;
  cost30d: { usd: number; complete: boolean } | null;
}

/**
 * Dependency injection interface for testability.
 */
export interface AgentDataDeps {
  listManagedAgents: () => Promise<DiscoveredAgent[]>;
  listAgentSubjects: (agentName: string) => Promise<ReadOutcome<SubjectAgent[]>>;
  getAgentCostAggregate: (agentName: string) => Promise<RunCostEstimate>;
  getAgentLifecycle: (agentName: string) => Promise<AgentLifecycle>;
}

/**
 * Build agent rows from adapters.
 *
 * For each discovered agent:
 * 1. Query subjects → count enabled, find most recent run
 * 2. Derive status of most recent run
 * 3. Get 30d cost aggregate (graceful null on failure)
 */
export async function buildAgentRows(deps: AgentDataDeps): Promise<AgentRow[]> {
  const agents = await deps.listManagedAgents();

  if (agents.length === 0) {
    return [];
  }

  const rows = await Promise.all(agents.map((agent) => buildSingleAgentRow(agent, deps)));

  return rows;
}

async function buildSingleAgentRow(agent: DiscoveredAgent, deps: AgentDataDeps): Promise<AgentRow> {
  // Fetch subjects for this agent
  const subjectsOutcome = await deps.listAgentSubjects(agent.name);

  let subjects: SubjectAgent[] = [];
  if (subjectsOutcome.status === "ok") {
    subjects = subjectsOutcome.data;
  }

  // Count enabled repos
  const activeRepos = subjects.filter((s) => s.enabled).length;

  // Find most recent run across all subjects
  const { lastRunAt, status } = findMostRecentRun(subjects, deps, agent.name);

  // Get 30d cost (graceful failure → null)
  let cost30d: { usd: number; complete: boolean } | null = null;
  try {
    const costEstimate = await deps.getAgentCostAggregate(agent.name);
    cost30d = { usd: costEstimate.usd, complete: costEstimate.complete };
  } catch {
    // Cost unavailable — already null, nothing to do
  }

  return {
    name: agent.name,
    domain: agent.domain,
    lastRunAt,
    status,
    activeRepos,
    cost30d,
  };
}

/**
 * Find the most recent lastRunAt across all subjects and derive its status.
 */
function findMostRecentRun(
  subjects: SubjectAgent[],
  _deps: AgentDataDeps,
  _agentName: string,
): { lastRunAt: string | null; status: string | null } {
  let mostRecentRunAt: string | null = null;
  let mostRecentStatus: string | null = null;
  let mostRecentTimestamp = 0;

  for (const subject of subjects) {
    if (subject.lastRunAt) {
      const ts = new Date(subject.lastRunAt).getTime();
      if (!isNaN(ts) && ts > mostRecentTimestamp) {
        mostRecentTimestamp = ts;
        mostRecentRunAt = subject.lastRunAt;
        mostRecentStatus = subject.lastStatus ?? null;
      }
    }
  }

  if (!mostRecentRunAt) {
    return { lastRunAt: null, status: null };
  }

  // Derive status using shared deriveStatus (applies incomplete logic)
  // Use default maxLifetime since we don't async-fetch per agent here
  // The status derivation uses the raw last_status from the most recent run
  const derivedStatus = mostRecentStatus
    ? deriveStatus(mostRecentStatus, mostRecentRunAt, undefined, Date.now())
    : null;

  return { lastRunAt: mostRecentRunAt, status: derivedStatus };
}
