/**
 * Repos list data layer — S-023.
 *
 * Builds the repo list by:
 * 1. Querying all subjects via GSI1 pk = "META" (no Scan)
 * 2. For each managed agent, querying their subjects to build coverage map
 * 3. Aggregating: per-repo agent count, last activity, status
 *
 * Hard invariant: NO Scan anywhere.
 */

import type { Subject, SubjectAgent } from "@/server/repository/scope-repository.js";
import type { ReadOutcome } from "@/server/repository/types.js";
import type { DiscoveredAgent } from "@/server/aws/tagging-adapter.js";
import type { AgentLifecycle } from "@/server/aws/agentcore-adapter.js";
import { deriveStatus } from "@fleet/shared";

/**
 * Row view-model for the repos list table.
 */
export interface RepoRow {
  subjectId: string;
  agentCount: number;
  lastRunAt: string | null;
  status: string | null;
}

/**
 * Dependency injection interface for testability.
 * Note: no Scan dependency exists — only GSI1 Query operations.
 */
export interface ReposDataDeps {
  listSubjects: () => Promise<ReadOutcome<Subject[]>>;
  listManagedAgents: () => Promise<DiscoveredAgent[]>;
  listAgentSubjects: (agentName: string) => Promise<ReadOutcome<SubjectAgent[]>>;
  getAgentLifecycle: (agentName: string) => Promise<AgentLifecycle>;
}

/**
 * Build repo rows from adapters.
 *
 * Strategy:
 * 1. List all subjects (GSI1 pk = "META") → set of known repos
 * 2. List managed agents (tagging adapter) → discover all agents
 * 3. For each agent, query their subjects → build coverage map
 * 4. Aggregate: for each subject, count covering agents + find most recent activity
 */
export async function buildRepoRows(deps: ReposDataDeps): Promise<RepoRow[]> {
  // Step 1: Get all subjects
  const subjectsOutcome = await deps.listSubjects();

  if (subjectsOutcome.status === "empty") {
    return [];
  }

  if (subjectsOutcome.status !== "ok") {
    // Propagate error for the page to handle
    throw new Error(`Failed to list subjects: ${subjectsOutcome.status}`);
  }

  const subjects = subjectsOutcome.data;

  // Step 2: Get all managed agents
  const agents = await deps.listManagedAgents();

  // Step 3: For each agent, query their subjects and build a coverage map
  // Map: subjectId → { agentCount, lastRunAt, lastStatus }
  const coverageMap = new Map<
    string,
    { agentCount: number; lastRunAt: string | null; lastStatus: string | null }
  >();

  // Initialize all subjects with zero coverage
  for (const subject of subjects) {
    coverageMap.set(subject.subjectId, {
      agentCount: 0,
      lastRunAt: null,
      lastStatus: null,
    });
  }

  // Query each agent's subjects and aggregate
  await Promise.all(
    agents.map(async (agent) => {
      const agentSubjectsOutcome = await deps.listAgentSubjects(agent.name);
      if (agentSubjectsOutcome.status !== "ok") return;

      for (const agentSubject of agentSubjectsOutcome.data) {
        const existing = coverageMap.get(agentSubject.subjectId);
        if (!existing) {
          // Subject exists in agent scope but not in META list — skip
          continue;
        }

        // Increment agent count
        existing.agentCount += 1;

        // Track most recent activity across all agents
        if (agentSubject.lastRunAt) {
          const ts = new Date(agentSubject.lastRunAt).getTime();
          const existingTs = existing.lastRunAt ? new Date(existing.lastRunAt).getTime() : 0;

          if (!isNaN(ts) && ts > existingTs) {
            existing.lastRunAt = agentSubject.lastRunAt;
            existing.lastStatus = agentSubject.lastStatus ?? null;
          }
        }
      }
    }),
  );

  // Step 4: Build rows from the coverage map
  const rows: RepoRow[] = [];

  for (const subject of subjects) {
    const coverage = coverageMap.get(subject.subjectId);
    if (!coverage) continue;

    // Derive status using shared deriveStatus (applies incomplete logic)
    let status: string | null = null;
    if (coverage.lastRunAt && coverage.lastStatus) {
      status = deriveStatus(coverage.lastStatus, coverage.lastRunAt, undefined, Date.now());
    }

    rows.push({
      subjectId: subject.subjectId,
      agentCount: coverage.agentCount,
      lastRunAt: coverage.lastRunAt,
      status,
    });
  }

  return rows;
}
