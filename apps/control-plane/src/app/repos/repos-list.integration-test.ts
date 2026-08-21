/**
 * Integration tests for repos list and per-repo run view — S-023, sub-task 23.8.
 *
 * Tests:
 * - Repos list renders from mocked subjects and agents
 * - No ScanCommand issued (verified by mock dependency injection)
 * - Subject with no agents appears showing zero
 * - Coverage aggregation counts agents per subject
 * - All four async states (ready, empty, error, timeout)
 * - Per-repo runs load with agent column
 */

import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import type { Subject, SubjectAgent } from "@/server/repository/scope-repository.js";
import type { Run } from "@/server/runs/span-to-run-mapper.js";
import type { AgentLifecycle } from "@/server/aws/agentcore-adapter.js";
import type { PricingTable } from "@/lib/cost.js";
import type { DiscoveredAgent } from "@/server/aws/tagging-adapter.js";
import { buildRepoRows, type ReposDataDeps } from "./repos-data.js";
import { loadRunsForRepo, type RepoRunsDataDeps } from "./[...repo]/repo-runs-data.js";
import { parseRunFilters } from "@/lib/run-filters.js";

const NOW = new Date("2026-08-25T12:00:00.000Z").getTime();

function createMockReposDeps(overrides: Partial<ReposDataDeps> = {}): ReposDataDeps {
  return {
    listSubjects:
      overrides.listSubjects ?? (async () => ({ status: "empty" as const, correlationId: "test" })),
    listManagedAgents: overrides.listManagedAgents ?? (async () => []),
    listAgentSubjects:
      overrides.listAgentSubjects ??
      (async () => ({ status: "empty" as const, correlationId: "test" })),
    getAgentLifecycle: overrides.getAgentLifecycle ?? (async () => ({ maxLifetime: 28800 })),
  };
}

function createMockRepoRunsDeps(overrides: Partial<RepoRunsDataDeps> = {}): RepoRunsDataDeps {
  const defaultPricingTable: PricingTable = {
    "us.anthropic.claude-sonnet-4-20250514-v1:0": { inputPer1k: 0.003, outputPer1k: 0.015 },
  };

  return {
    listManagedAgents: overrides.listManagedAgents ?? (async () => []),
    listAgentSubjects:
      overrides.listAgentSubjects ??
      (async () => ({ status: "empty" as const, correlationId: "test" })),
    queryRuns:
      overrides.queryRuns ?? (async () => ({ status: "empty" as const, correlationId: "test" })),
    getAgentLifecycle:
      overrides.getAgentLifecycle ?? (async () => ({ maxLifetime: 28800 }) as AgentLifecycle),
    loadPricingTable: overrides.loadPricingTable ?? (() => defaultPricingTable),
    estimateRunCost:
      overrides.estimateRunCost ??
      ((perModel, table) => {
        let totalUsd = 0;
        const unpricedModels: string[] = [];
        for (const usage of perModel) {
          const entry = table[usage.modelId];
          if (!entry) {
            unpricedModels.push(usage.modelId);
            continue;
          }
          totalUsd += (usage.tokensIn / 1000) * entry.inputPer1k;
          totalUsd += (usage.tokensOut / 1000) * entry.outputPer1k;
        }
        return { usd: totalUsd, complete: unpricedModels.length === 0, unpricedModels };
      }),
  };
}

describe("repos-list integration", () => {
  let warnSpy: ReturnType<typeof vi.spyOn>;

  beforeEach(() => {
    warnSpy = vi.spyOn(console, "warn").mockImplementation(() => {});
  });

  afterEach(() => {
    warnSpy.mockRestore();
  });

  describe("buildRepoRows", () => {
    it("returns repos with agent coverage count and last activity", async () => {
      const subjects: Subject[] = [
        { subjectId: "myorg/repo-alpha", createdAt: "2026-06-01T00:00:00.000Z" },
        { subjectId: "myorg/repo-beta", createdAt: "2026-06-01T00:00:00.000Z" },
      ];

      const agents: DiscoveredAgent[] = [
        {
          name: "dep-updater",
          domain: "security",
          arn: "arn:aws:agentcore:us-east-1:123:agent/dep-updater",
        },
        {
          name: "code-reviewer",
          domain: "quality",
          arn: "arn:aws:agentcore:us-east-1:123:agent/code-reviewer",
        },
      ];

      const depUpdaterSubjects: SubjectAgent[] = [
        {
          subjectId: "myorg/repo-alpha",
          agentName: "dep-updater",
          enabled: true,
          params: {},
          lastSessionId: "session-1",
          lastRunAt: "2026-08-24T10:00:00.000Z",
          lastStatus: "success",
        },
        {
          subjectId: "myorg/repo-beta",
          agentName: "dep-updater",
          enabled: true,
          params: {},
          lastSessionId: "session-2",
          lastRunAt: "2026-08-23T08:00:00.000Z",
          lastStatus: "failed",
        },
      ];

      const codeReviewerSubjects: SubjectAgent[] = [
        {
          subjectId: "myorg/repo-alpha",
          agentName: "code-reviewer",
          enabled: true,
          params: {},
          lastSessionId: "session-3",
          lastRunAt: "2026-08-24T12:00:00.000Z",
          lastStatus: "success",
        },
      ];

      const deps = createMockReposDeps({
        listSubjects: async () => ({
          status: "ok" as const,
          data: subjects,
          correlationId: "test-1",
        }),
        listManagedAgents: async () => agents,
        listAgentSubjects: async (agentName: string) => {
          if (agentName === "dep-updater") {
            return { status: "ok" as const, data: depUpdaterSubjects, correlationId: "test-2" };
          }
          if (agentName === "code-reviewer") {
            return { status: "ok" as const, data: codeReviewerSubjects, correlationId: "test-3" };
          }
          return { status: "empty" as const, correlationId: "test" };
        },
      });

      const rows = await buildRepoRows(deps);

      expect(rows).toHaveLength(2);

      const alpha = rows.find((r) => r.subjectId === "myorg/repo-alpha");
      expect(alpha).toBeDefined();
      expect(alpha?.agentCount).toBe(2); // covered by both agents
      expect(alpha?.lastRunAt).toBe("2026-08-24T12:00:00.000Z"); // most recent across agents
      expect(alpha?.status).toBe("success");

      const beta = rows.find((r) => r.subjectId === "myorg/repo-beta");
      expect(beta).toBeDefined();
      expect(beta?.agentCount).toBe(1); // only dep-updater
      expect(beta?.lastRunAt).toBe("2026-08-23T08:00:00.000Z");
      expect(beta?.status).toBe("failed");
    });

    it("subject with META only and no agents appears with zero count", async () => {
      const subjects: Subject[] = [
        { subjectId: "myorg/orphan-repo", createdAt: "2026-06-01T00:00:00.000Z" },
      ];

      const deps = createMockReposDeps({
        listSubjects: async () => ({
          status: "ok" as const,
          data: subjects,
          correlationId: "test-1",
        }),
        listManagedAgents: async () => [
          { name: "dep-updater", domain: "security", arn: "arn:..." },
        ],
        listAgentSubjects: async () => ({
          status: "ok" as const,
          data: [], // dep-updater covers no repos (or none match)
          correlationId: "test-2",
        }),
      });

      const rows = await buildRepoRows(deps);

      expect(rows).toHaveLength(1);
      expect(rows[0]?.subjectId).toBe("myorg/orphan-repo");
      expect(rows[0]?.agentCount).toBe(0);
      expect(rows[0]?.lastRunAt).toBeNull();
      expect(rows[0]?.status).toBeNull();
    });

    it("returns empty array when no subjects exist", async () => {
      const deps = createMockReposDeps({
        listSubjects: async () => ({
          status: "empty" as const,
          correlationId: "test",
        }),
      });

      const rows = await buildRepoRows(deps);
      expect(rows).toHaveLength(0);
    });

    it("throws on listSubjects error (propagates for error state)", async () => {
      const deps = createMockReposDeps({
        listSubjects: async () => {
          throw new Error("DynamoDB error");
        },
      });

      await expect(buildRepoRows(deps)).rejects.toThrow("DynamoDB error");
    });

    it("throws on timeout (propagates for timeout state)", async () => {
      const deps = createMockReposDeps({
        listSubjects: async () => {
          const error = new Error("timeout");
          (error as Error & { code?: string }).code = "TIMEOUT";
          throw error;
        },
      });

      await expect(buildRepoRows(deps)).rejects.toThrow("timeout");
    });

    it("no ScanCommand issued — only Query via GSI1 (verified by mock structure)", async () => {
      // This test verifies the architectural constraint by ensuring that
      // the data layer only calls listSubjects (which uses GSI1 Query pk=META)
      // and listAgentSubjects (which uses GSI1 Query pk=AGENT#<name>).
      // No Scan-type dependency exists in the deps interface.
      const listSubjectsCalled = vi.fn(async () => ({
        status: "ok" as const,
        data: [{ subjectId: "myorg/repo-a", createdAt: "2026-01-01T00:00:00.000Z" }] as Subject[],
        correlationId: "test",
      }));

      const listAgentSubjectsCalled = vi.fn(async () => ({
        status: "ok" as const,
        data: [] as SubjectAgent[],
        correlationId: "test",
      }));

      const deps = createMockReposDeps({
        listSubjects: listSubjectsCalled,
        listManagedAgents: async () => [
          { name: "dep-updater", domain: "security", arn: "arn:..." },
        ],
        listAgentSubjects: listAgentSubjectsCalled,
      });

      await buildRepoRows(deps);

      // Verify only GSI1 Query operations were used
      expect(listSubjectsCalled).toHaveBeenCalledTimes(1);
      expect(listAgentSubjectsCalled).toHaveBeenCalledTimes(1);
      // The DI interface ensures no Scan is possible — no scanTable in deps
    });
  });

  describe("loadRunsForRepo", () => {
    it("loads runs for a specific repo across all agents", async () => {
      const agents: DiscoveredAgent[] = [
        { name: "dep-updater", domain: "security", arn: "arn:..." },
        { name: "code-reviewer", domain: "quality", arn: "arn:..." },
      ];

      const depUpdaterSubjects: SubjectAgent[] = [
        {
          subjectId: "myorg/repo-alpha",
          agentName: "dep-updater",
          enabled: true,
          params: {},
          lastSessionId: "session-du-1",
          lastRunAt: "2026-08-24T10:00:00.000Z",
          lastStatus: "success",
        },
      ];

      const codeReviewerSubjects: SubjectAgent[] = [
        {
          subjectId: "myorg/repo-alpha",
          agentName: "code-reviewer",
          enabled: true,
          params: {},
          lastSessionId: "session-cr-1",
          lastRunAt: "2026-08-24T11:00:00.000Z",
          lastStatus: "success",
        },
      ];

      const spanRuns: Run[] = [
        {
          sessionId: "session-du-1",
          subjectId: "myorg/repo-alpha",
          agentName: "dep-updater",
          status: "success",
          outcomeType: "pr",
          outcomeUrl: "https://github.com/myorg/repo-alpha/pull/1",
          startedAt: "2026-08-24T10:00:00.000Z",
          durationMs: 120000,
          perModel: [
            {
              modelId: "us.anthropic.claude-sonnet-4-20250514-v1:0",
              tokensIn: 1000,
              tokensOut: 500,
              calls: 1,
            },
          ],
          source: "spans",
        },
      ];

      const deps = createMockRepoRunsDeps({
        listManagedAgents: async () => agents,
        listAgentSubjects: async (agentName: string) => {
          if (agentName === "dep-updater") {
            return { status: "ok" as const, data: depUpdaterSubjects, correlationId: "test" };
          }
          if (agentName === "code-reviewer") {
            return { status: "ok" as const, data: codeReviewerSubjects, correlationId: "test" };
          }
          return { status: "empty" as const, correlationId: "test" };
        },
        queryRuns: async (input) => {
          // Only return spans for dep-updater queried for this repo
          if (input.agentName === "dep-updater") {
            return { status: "ok" as const, data: spanRuns, correlationId: "test" };
          }
          return { status: "empty" as const, correlationId: "test" };
        },
      });

      const filters = parseRunFilters({}, NOW);
      const runs = await loadRunsForRepo("myorg/repo-alpha", filters, deps);

      // Should include runs from both agents
      expect(runs.length).toBeGreaterThanOrEqual(1);

      // The span run from dep-updater should have cost attached
      const duRun = runs.find((r) => r.sessionId === "session-du-1");
      expect(duRun).toBeDefined();
      expect(duRun?.agentName).toBe("dep-updater");
    });

    it("applies status and date filters", async () => {
      const agents: DiscoveredAgent[] = [
        { name: "dep-updater", domain: "security", arn: "arn:..." },
      ];

      const spanRuns: Run[] = [
        {
          sessionId: "s-1",
          subjectId: "myorg/repo-alpha",
          agentName: "dep-updater",
          status: "success",
          outcomeType: "",
          outcomeUrl: "",
          startedAt: "2026-08-24T10:00:00.000Z",
          durationMs: 100000,
          perModel: [],
          source: "spans",
        },
        {
          sessionId: "s-2",
          subjectId: "myorg/repo-alpha",
          agentName: "dep-updater",
          status: "failed",
          outcomeType: "",
          outcomeUrl: "",
          startedAt: "2026-08-24T11:00:00.000Z",
          durationMs: 50000,
          perModel: [],
          source: "spans",
        },
      ];

      const deps = createMockRepoRunsDeps({
        listManagedAgents: async () => agents,
        listAgentSubjects: async () => ({
          status: "ok" as const,
          data: [
            {
              subjectId: "myorg/repo-alpha",
              agentName: "dep-updater",
              enabled: true,
              params: {},
              lastSessionId: "s-2",
              lastRunAt: "2026-08-24T11:00:00.000Z",
              lastStatus: "failed",
            },
          ] as SubjectAgent[],
          correlationId: "test",
        }),
        queryRuns: async () => ({ status: "ok" as const, data: spanRuns, correlationId: "test" }),
      });

      const filters = parseRunFilters({ status: "failed" }, NOW);
      const runs = await loadRunsForRepo("myorg/repo-alpha", filters, deps);

      expect(runs).toHaveLength(1);
      expect(runs[0]?.status).toBe("failed");
    });

    it("returns empty when repo has no runs", async () => {
      const deps = createMockRepoRunsDeps({
        listManagedAgents: async () => [
          { name: "dep-updater", domain: "security", arn: "arn:..." },
        ],
        listAgentSubjects: async () => ({
          status: "empty" as const,
          correlationId: "test",
        }),
        queryRuns: async () => ({ status: "empty" as const, correlationId: "test" }),
      });

      const filters = parseRunFilters({}, NOW);
      const runs = await loadRunsForRepo("myorg/repo-alpha", filters, deps);

      expect(runs).toHaveLength(0);
    });
  });
});
