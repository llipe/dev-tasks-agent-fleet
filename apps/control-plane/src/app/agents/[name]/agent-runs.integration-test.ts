/**
 * Integration tests for agent detail Runs tab — S-020, sub-task 20.9.
 *
 * Tests:
 * - Page data layer renders with filters applied
 * - Invalid params fall back to defaults
 * - Merged runs include cost estimates
 * - Status filter applies correctly
 * - Date range filter applies correctly
 * - Empty result set → empty state
 * - Timeout from query → timeout state
 */

import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import type { SubjectAgent } from "@/server/repository/scope-repository.js";
import type { Run } from "@/server/runs/span-to-run-mapper.js";
import type { AgentLifecycle } from "@/server/aws/agentcore-adapter.js";
import type { PricingTable } from "@/lib/cost.js";
import { parseRunFilters } from "@/lib/run-filters.js";
import { loadRunsForAgent, type RunsDataDeps } from "./runs-data.js";

const NOW = new Date("2026-08-25T12:00:00.000Z").getTime();

function createMockDeps(overrides: Partial<RunsDataDeps> = {}): RunsDataDeps {
  const defaultPricingTable: PricingTable = {
    "us.anthropic.claude-sonnet-4-20250514-v1:0": { inputPer1k: 0.003, outputPer1k: 0.015 },
    "us.amazon.nova-micro-v1:0": { inputPer1k: 0.000035, outputPer1k: 0.00014 },
  };

  return {
    queryRuns:
      overrides.queryRuns ?? (async () => ({ status: "empty" as const, correlationId: "test" })),
    listAgentSubjects:
      overrides.listAgentSubjects ??
      (async () => ({ status: "empty" as const, correlationId: "test" })),
    getAgentLifecycle:
      overrides.getAgentLifecycle ?? (async () => ({ maxLifetime: 28800 }) as AgentLifecycle),
    loadPricingTable: overrides.loadPricingTable ?? (() => defaultPricingTable),
    estimateRunCost:
      overrides.estimateRunCost ??
      ((perModel, table) => {
        // Use the real implementation logic
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

function makeSpanRun(overrides: Partial<Run> = {}): Run {
  return {
    sessionId: "session-001",
    subjectId: "myorg/repo-alpha",
    agentName: "dep-updater",
    status: "success",
    outcomeType: "pr",
    outcomeUrl: "https://github.com/myorg/repo-alpha/pull/42",
    startedAt: "2026-08-24T10:00:00.000Z",
    durationMs: 150000,
    perModel: [
      {
        modelId: "us.anthropic.claude-sonnet-4-20250514-v1:0",
        tokensIn: 1500,
        tokensOut: 500,
        calls: 2,
      },
    ],
    source: "spans",
    ...overrides,
  };
}

function makeSubjectAgent(overrides: Partial<SubjectAgent> = {}): SubjectAgent {
  return {
    subjectId: "myorg/repo-beta",
    agentName: "dep-updater",
    enabled: true,
    params: {},
    lastSessionId: "session-002",
    lastRunAt: "2026-08-24T08:00:00.000Z",
    lastStatus: "success",
    ...overrides,
  };
}

describe("agent-runs integration", () => {
  let warnSpy: ReturnType<typeof vi.spyOn>;

  beforeEach(() => {
    warnSpy = vi.spyOn(console, "warn").mockImplementation(() => {});
  });

  afterEach(() => {
    warnSpy.mockRestore();
  });

  describe("loadRunsForAgent", () => {
    it("returns merged runs with cost from span and config sources", async () => {
      const spanRun = makeSpanRun();
      const configSubject = makeSubjectAgent();

      const deps = createMockDeps({
        queryRuns: async () => ({
          status: "ok" as const,
          data: [spanRun],
          correlationId: "test-1",
        }),
        listAgentSubjects: async () => ({
          status: "ok" as const,
          data: [configSubject],
          correlationId: "test-2",
        }),
      });

      const filters = parseRunFilters({}, NOW);
      const runs = await loadRunsForAgent("dep-updater", filters, deps);

      expect(runs.length).toBeGreaterThanOrEqual(1);

      // Span run should be present with cost
      const spanResult = runs.find((r) => r.sessionId === "session-001");
      expect(spanResult).toBeDefined();
      expect(spanResult?.cost).toBeDefined();
      expect(spanResult?.cost?.usd).toBeGreaterThan(0);
      expect(spanResult?.cost?.complete).toBe(true);
    });

    it("applies status filter correctly", async () => {
      const successRun = makeSpanRun({ sessionId: "s-1", status: "success" });
      const failedRun = makeSpanRun({ sessionId: "s-2", status: "failed" });

      const deps = createMockDeps({
        queryRuns: async () => ({
          status: "ok" as const,
          data: [successRun, failedRun],
          correlationId: "test",
        }),
      });

      const filters = parseRunFilters({ status: "failed" }, NOW);
      const runs = await loadRunsForAgent("dep-updater", filters, deps);

      expect(runs).toHaveLength(1);
      expect(runs[0]?.status).toBe("failed");
    });

    it("applies date range filter correctly", async () => {
      const recentRun = makeSpanRun({
        sessionId: "s-recent",
        startedAt: "2026-08-24T10:00:00.000Z",
      });
      const oldRun = makeSpanRun({
        sessionId: "s-old",
        startedAt: "2026-07-01T10:00:00.000Z",
      });

      const deps = createMockDeps({
        queryRuns: async () => ({
          status: "ok" as const,
          data: [recentRun, oldRun],
          correlationId: "test",
        }),
      });

      // Default 7-day range from NOW
      const filters = parseRunFilters({}, NOW);
      const runs = await loadRunsForAgent("dep-updater", filters, deps);

      // Only the recent run should be within the 7-day window
      expect(runs).toHaveLength(1);
      expect(runs[0]?.sessionId).toBe("s-recent");
    });

    it("returns empty array when no runs match filters", async () => {
      const deps = createMockDeps({
        queryRuns: async () => ({
          status: "empty" as const,
          correlationId: "test",
        }),
        listAgentSubjects: async () => ({
          status: "empty" as const,
          correlationId: "test",
        }),
      });

      const filters = parseRunFilters({}, NOW);
      const runs = await loadRunsForAgent("dep-updater", filters, deps);

      expect(runs).toHaveLength(0);
    });

    it("throws timeout error from query service", async () => {
      const deps = createMockDeps({
        queryRuns: async () => {
          const error = new Error("Query timed out");
          (error as Error & { code?: string }).code = "TIMEOUT";
          throw error;
        },
      });

      const filters = parseRunFilters({}, NOW);
      await expect(loadRunsForAgent("dep-updater", filters, deps)).rejects.toThrow(
        "Query timed out",
      );
    });

    it("invalid params fall back to defaults and still return results", async () => {
      const spanRun = makeSpanRun({
        startedAt: "2026-08-24T10:00:00.000Z",
      });

      const deps = createMockDeps({
        queryRuns: async () => ({
          status: "ok" as const,
          data: [spanRun],
          correlationId: "test",
        }),
      });

      // Invalid params should fall back to defaults (7d range, all statuses)
      const filters = parseRunFilters(
        {
          tab: "invalid",
          status: "bogus",
          from: "not-a-date",
          to: "also-bad",
        },
        NOW,
      );

      expect(filters.tab).toBe("runs");
      expect(filters.status).toBeUndefined();

      const runs = await loadRunsForAgent("dep-updater", filters, deps);
      expect(runs.length).toBeGreaterThanOrEqual(1);
    });

    it("config-only runs included when within date range", async () => {
      const configSubject = makeSubjectAgent({
        lastSessionId: "config-only-session",
        lastRunAt: "2026-08-24T08:00:00.000Z",
        lastStatus: "running",
      });

      const deps = createMockDeps({
        queryRuns: async () => ({
          status: "empty" as const,
          correlationId: "test",
        }),
        listAgentSubjects: async () => ({
          status: "ok" as const,
          data: [configSubject],
          correlationId: "test",
        }),
      });

      const filters = parseRunFilters({}, NOW);
      const runs = await loadRunsForAgent("dep-updater", filters, deps);

      expect(runs).toHaveLength(1);
      expect(runs[0]?.sessionId).toBe("config-only-session");
      expect(runs[0]?.source).toBe("config");
    });

    it("runs without model usage have no cost attached", async () => {
      const runNoTokens = makeSpanRun({
        sessionId: "s-no-tokens",
        perModel: [],
      });

      const deps = createMockDeps({
        queryRuns: async () => ({
          status: "ok" as const,
          data: [runNoTokens],
          correlationId: "test",
        }),
      });

      const filters = parseRunFilters({}, NOW);
      const runs = await loadRunsForAgent("dep-updater", filters, deps);

      expect(runs).toHaveLength(1);
      expect(runs[0]?.cost).toBeUndefined();
    });

    it("runs with unpriced models show incomplete cost", async () => {
      const runUnpriced = makeSpanRun({
        sessionId: "s-unpriced",
        perModel: [{ modelId: "unknown-model-xyz", tokensIn: 100, tokensOut: 50, calls: 1 }],
      });

      const deps = createMockDeps({
        queryRuns: async () => ({
          status: "ok" as const,
          data: [runUnpriced],
          correlationId: "test",
        }),
      });

      const filters = parseRunFilters({}, NOW);
      const runs = await loadRunsForAgent("dep-updater", filters, deps);

      expect(runs).toHaveLength(1);
      expect(runs[0]?.cost?.complete).toBe(false);
      expect(runs[0]?.cost?.unpricedModels).toContain("unknown-model-xyz");
    });
  });
});
