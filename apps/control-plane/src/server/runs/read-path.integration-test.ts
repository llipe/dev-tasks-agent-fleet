/**
 * Integration test: full read path producing merged list — S-018 sub-task 18.12.
 *
 * Tests the full pipeline:
 * - Span runs from Logs Insights mapper
 * - Config runs from DynamoDB projection
 * - Merged list with one completed, one running, one incomplete
 * - Cost estimation applied to merged results
 */

import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { mergeRuns } from "./merge-runs.js";
import { projectConfigRun, type ConfigRun } from "./config-projection.js";
import type { Run, ModelUsage } from "./span-to-run-mapper.js";
import { estimateRunCost, loadPricingTable } from "../../lib/cost.js";
import { TERMINATION_GRACE_MS } from "@fleet/shared";
import type { SubjectAgent } from "../repository/scope-repository.js";

describe("read-path integration: merged run list", () => {
  let warnSpy: ReturnType<typeof vi.spyOn>;

  beforeEach(() => {
    warnSpy = vi.spyOn(console, "warn").mockImplementation(() => {});
  });

  afterEach(() => {
    warnSpy.mockRestore();
  });

  it("produces merged list with one completed, one running, one incomplete", () => {
    const now = new Date("2026-08-20T12:00:00.000Z").getTime();
    const maxLifetimeSeconds = 3600; // 1 hour
    const thresholdMs = maxLifetimeSeconds * 1000 + TERMINATION_GRACE_MS;

    // --- Span runs (from Logs Insights) ---
    const completedSpanRun: Run = {
      sessionId: "session-completed",
      subjectId: "myorg/repo-alpha",
      agentName: "dep-updater",
      status: "success",
      outcomeType: "pr",
      outcomeUrl: "https://github.com/myorg/repo-alpha/pull/42",
      startedAt: "2026-08-20T10:00:00.000Z",
      durationMs: 180_000,
      perModel: [
        { modelId: "us.anthropic.claude-sonnet-4-6", tokensIn: 5000, tokensOut: 2000, calls: 3 },
      ],
      source: "spans",
    };

    // --- Config runs (from DynamoDB SubjectAgentItem) ---
    const runningAgent: SubjectAgent = {
      subjectId: "myorg/repo-beta",
      agentName: "dep-updater",
      enabled: true,
      params: {},
      lastSessionId: "session-running",
      lastRunAt: new Date(now - 60_000).toISOString(), // started 1 min ago
      lastStatus: "running",
      lastOutcomeUrl: "",
    };

    const incompleteAgent: SubjectAgent = {
      subjectId: "myorg/repo-gamma",
      agentName: "dep-updater",
      enabled: true,
      params: {},
      lastSessionId: "session-incomplete",
      lastRunAt: new Date(now - thresholdMs - 1000).toISOString(), // well past threshold
      lastStatus: "running",
      lastOutcomeUrl: "",
    };

    // Project config runs
    const runningConfigRun = projectConfigRun(runningAgent, maxLifetimeSeconds, now);
    const incompleteConfigRun = projectConfigRun(incompleteAgent, maxLifetimeSeconds, now);

    expect(runningConfigRun).not.toBeNull();
    expect(incompleteConfigRun).not.toBeNull();
    expect(runningConfigRun?.status).toBe("running");
    expect(incompleteConfigRun?.status).toBe("incomplete");

    // Merge all runs
    const spanRuns: Run[] = [completedSpanRun];
    const configRuns: ConfigRun[] = [];
    if (runningConfigRun) configRuns.push(runningConfigRun);
    if (incompleteConfigRun) configRuns.push(incompleteConfigRun);

    const merged = mergeRuns(spanRuns, configRuns);

    // Verify: 3 runs total
    expect(merged).toHaveLength(3);

    // Verify: sorted by startedAt descending
    const timestamps = merged.map((r) => new Date(r.startedAt).getTime());
    for (let i = 0; i < timestamps.length - 1; i++) {
      const current = timestamps[i] ?? 0;
      const next = timestamps[i + 1] ?? 0;
      expect(current).toBeGreaterThanOrEqual(next);
    }

    // Verify: each status present
    const statuses = merged.map((r) => r.status);
    expect(statuses).toContain("success");
    expect(statuses).toContain("running");
    expect(statuses).toContain("incomplete");

    // Verify: completed run has span data
    const completed = merged.find((r) => r.sessionId === "session-completed");
    expect(completed?.source).toBe("spans");
    expect(completed?.durationMs).toBe(180_000);
    expect(completed?.perModel).toHaveLength(1);

    // Verify: config runs have empty perModel
    const running = merged.find((r) => r.sessionId === "session-running");
    expect(running?.source).toBe("config");
    expect(running?.perModel).toEqual([]);

    const incomplete = merged.find((r) => r.sessionId === "session-incomplete");
    expect(incomplete?.source).toBe("config");
    expect(incomplete?.status).toBe("incomplete");
  });

  it("cost estimation integrates with merged results", () => {
    const table = loadPricingTable();

    const perModel: ModelUsage[] = [
      { modelId: "us.anthropic.claude-sonnet-4-6", tokensIn: 10_000, tokensOut: 5_000, calls: 5 },
    ];

    const cost = estimateRunCost(perModel, table);

    expect(cost.complete).toBe(true);
    expect(cost.usd).toBeGreaterThan(0);
    expect(cost.unpricedModels).toEqual([]);
  });

  it("unpriced model triggers warn and marks cost incomplete", () => {
    const table = loadPricingTable();

    const perModel: ModelUsage[] = [
      { modelId: "us.anthropic.claude-sonnet-4-6", tokensIn: 1000, tokensOut: 500, calls: 1 },
      { modelId: "totally-unknown-model", tokensIn: 2000, tokensOut: 1000, calls: 2 },
    ];

    const cost = estimateRunCost(perModel, table);

    expect(cost.complete).toBe(false);
    expect(cost.unpricedModels).toContain("totally-unknown-model");
    expect(cost.usd).toBeGreaterThan(0);
    expect(warnSpy).toHaveBeenCalledWith(expect.stringContaining("totally-unknown-model"));
  });

  it("status filter after merge selects only matching runs", () => {
    const spanRuns: Run[] = [
      {
        sessionId: "s-success",
        subjectId: "myorg/repo",
        agentName: "dep-updater",
        status: "success",
        outcomeType: "pr",
        outcomeUrl: "",
        startedAt: "2026-08-20T10:00:00.000Z",
        durationMs: 60_000,
        perModel: [],
        source: "spans",
      },
      {
        sessionId: "s-failed",
        subjectId: "myorg/repo",
        agentName: "dep-updater",
        status: "failed",
        outcomeType: "",
        outcomeUrl: "",
        startedAt: "2026-08-20T09:00:00.000Z",
        durationMs: 30_000,
        perModel: [],
        source: "spans",
      },
    ];

    const result = mergeRuns(spanRuns, [], { statusFilter: "failed" });

    expect(result).toHaveLength(1);
    expect(result[0]?.status).toBe("failed");
  });
});
