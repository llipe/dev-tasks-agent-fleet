/**
 * Integration tests for agents list view (S-019).
 *
 * Tests:
 * - Renders agents from tagging adapter with correct row data
 * - Untagged agent is excluded
 * - Zero agents → empty state
 * - Agent with zero repos → shows 0
 * - Agent never run → shows dash/null for last run
 * - Cost unknown → shows null cost
 * - Timeout from adapter → timeout state
 */

import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import type { DiscoveredAgent } from "@/server/aws/tagging-adapter.js";
import type { SubjectAgent } from "@/server/repository/scope-repository.js";
import { buildAgentRows, type AgentDataDeps } from "./agents-data.js";

describe("agents-list integration", () => {
  let warnSpy: ReturnType<typeof vi.spyOn>;

  beforeEach(() => {
    warnSpy = vi.spyOn(console, "warn").mockImplementation(() => {});
  });

  afterEach(() => {
    warnSpy.mockRestore();
  });

  function createMockDeps(overrides: Partial<AgentDataDeps> = {}): AgentDataDeps {
    return {
      listManagedAgents: overrides.listManagedAgents ?? (async () => []),
      listAgentSubjects:
        overrides.listAgentSubjects ??
        (async () => ({ status: "empty" as const, correlationId: "test" })),
      getAgentCostAggregate:
        overrides.getAgentCostAggregate ??
        (async () => ({ usd: 0, complete: true, unpricedModels: [] })),
      getAgentLifecycle: overrides.getAgentLifecycle ?? (async () => ({ maxLifetime: 28800 })),
    };
  }

  describe("renders with mocked adapters", () => {
    it("renders agents from tagging with correct rows", async () => {
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

      const subjectsForDepUpdater: SubjectAgent[] = [
        {
          subjectId: "myorg/repo-alpha",
          agentName: "dep-updater",
          enabled: true,
          params: {},
          lastSessionId: "session-1",
          lastRunAt: "2026-08-20T10:00:00.000Z",
          lastStatus: "success",
        },
        {
          subjectId: "myorg/repo-beta",
          agentName: "dep-updater",
          enabled: true,
          params: {},
          lastSessionId: "session-2",
          lastRunAt: "2026-08-20T09:00:00.000Z",
          lastStatus: "failed",
        },
        {
          subjectId: "myorg/repo-gamma",
          agentName: "dep-updater",
          enabled: false,
          params: {},
        },
      ];

      const subjectsForCodeReviewer: SubjectAgent[] = [
        {
          subjectId: "myorg/repo-alpha",
          agentName: "code-reviewer",
          enabled: true,
          params: {},
          lastSessionId: "session-3",
          lastRunAt: "2026-08-19T15:00:00.000Z",
          lastStatus: "success",
        },
      ];

      const deps = createMockDeps({
        listManagedAgents: async () => agents,
        listAgentSubjects: async (agentName: string) => {
          if (agentName === "dep-updater") {
            return {
              status: "ok" as const,
              data: subjectsForDepUpdater,
              correlationId: "test-1",
            };
          }
          if (agentName === "code-reviewer") {
            return {
              status: "ok" as const,
              data: subjectsForCodeReviewer,
              correlationId: "test-2",
            };
          }
          return { status: "empty" as const, correlationId: "test" };
        },
        getAgentCostAggregate: async (_name: string) => ({
          usd: 1.5,
          complete: true,
          unpricedModels: [],
        }),
      });

      const rows = await buildAgentRows(deps);
      expect(rows).toHaveLength(2);

      const depUpdater = rows.find((r) => r.name === "dep-updater");
      expect(depUpdater).toBeDefined();
      expect(depUpdater?.domain).toBe("security");
      expect(depUpdater?.activeRepos).toBe(2); // only enabled ones
      expect(depUpdater?.lastRunAt).toBe("2026-08-20T10:00:00.000Z"); // most recent
      expect(depUpdater?.status).toBe("success");
      expect(depUpdater?.cost30d).toEqual({ usd: 1.5, complete: true });

      const codeReviewer = rows.find((r) => r.name === "code-reviewer");
      expect(codeReviewer).toBeDefined();
      expect(codeReviewer?.domain).toBe("quality");
      expect(codeReviewer?.activeRepos).toBe(1);
    });

    it("untagged agent excluded (only tagged agents returned by listManagedAgents)", async () => {
      // The tagging adapter already filters by agent:managed=true
      // An untagged agent simply won't appear in the list
      const agents: DiscoveredAgent[] = [
        {
          name: "dep-updater",
          domain: "security",
          arn: "arn:aws:agentcore:us-east-1:123:agent/dep-updater",
        },
      ];

      const deps = createMockDeps({
        listManagedAgents: async () => agents,
        listAgentSubjects: async () => ({
          status: "empty" as const,
          correlationId: "test",
        }),
      });

      const rows = await buildAgentRows(deps);
      expect(rows).toHaveLength(1);
      expect(rows[0]?.name).toBe("dep-updater");
      // "untagged-agent" not present in results
    });
  });

  describe("edge cases", () => {
    it("zero agents returns empty array", async () => {
      const deps = createMockDeps({
        listManagedAgents: async () => [],
      });

      const rows = await buildAgentRows(deps);
      expect(rows).toHaveLength(0);
    });

    it("agent with zero repos shows 0 active repos", async () => {
      const agents: DiscoveredAgent[] = [
        {
          name: "dep-updater",
          domain: "security",
          arn: "arn:aws:agentcore:us-east-1:123:agent/dep-updater",
        },
      ];

      const deps = createMockDeps({
        listManagedAgents: async () => agents,
        listAgentSubjects: async () => ({
          status: "empty" as const,
          correlationId: "test",
        }),
      });

      const rows = await buildAgentRows(deps);
      expect(rows).toHaveLength(1);
      expect(rows[0]?.activeRepos).toBe(0);
    });

    it("agent never run shows null lastRunAt and no status", async () => {
      const agents: DiscoveredAgent[] = [
        {
          name: "dep-updater",
          domain: "security",
          arn: "arn:aws:agentcore:us-east-1:123:agent/dep-updater",
        },
      ];

      // All subjects have no lastRunAt
      const subjects: SubjectAgent[] = [
        {
          subjectId: "myorg/repo-alpha",
          agentName: "dep-updater",
          enabled: true,
          params: {},
          // No lastRunAt, no lastStatus
        },
      ];

      const deps = createMockDeps({
        listManagedAgents: async () => agents,
        listAgentSubjects: async () => ({
          status: "ok" as const,
          data: subjects,
          correlationId: "test",
        }),
      });

      const rows = await buildAgentRows(deps);
      expect(rows).toHaveLength(1);
      expect(rows[0]?.lastRunAt).toBeNull();
      expect(rows[0]?.status).toBeNull();
    });

    it("cost unknown shows null cost", async () => {
      const agents: DiscoveredAgent[] = [
        {
          name: "dep-updater",
          domain: "security",
          arn: "arn:aws:agentcore:us-east-1:123:agent/dep-updater",
        },
      ];

      const deps = createMockDeps({
        listManagedAgents: async () => agents,
        listAgentSubjects: async () => ({
          status: "empty" as const,
          correlationId: "test",
        }),
        getAgentCostAggregate: async () => {
          throw new Error("Cost unavailable");
        },
      });

      const rows = await buildAgentRows(deps);
      expect(rows).toHaveLength(1);
      expect(rows[0]?.cost30d).toBeNull();
    });

    it("timeout from adapter throws with timeout signal", async () => {
      const deps = createMockDeps({
        listManagedAgents: async () => {
          const error = new Error("timeout");
          (error as Error & { code?: string }).code = "TIMEOUT";
          throw error;
        },
      });

      await expect(buildAgentRows(deps)).rejects.toThrow("timeout");
    });
  });
});
