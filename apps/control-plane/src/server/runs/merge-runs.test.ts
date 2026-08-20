/**
 * Unit tests for mergeRuns — S-018 sub-tasks 18.1, 18.3, 18.9.
 *
 * Covers:
 * - In-both: span wins on conflict
 * - Spans-only: included as-is
 * - Config-only: included regardless of last_status
 * - Sort order: startedAt descending
 * - Status filter application
 * - Date-range filter application
 */

import { describe, it, expect } from "vitest";
import { mergeRuns } from "./merge-runs.js";
import type { Run } from "./span-to-run-mapper.js";
import type { ConfigRun } from "./config-projection.js";

function makeSpanRun(overrides: Partial<Run> = {}): Run {
  return {
    sessionId: "session-1",
    subjectId: "myorg/repo-a",
    agentName: "dep-updater",
    status: "success",
    outcomeType: "pr",
    outcomeUrl: "https://github.com/myorg/repo-a/pull/1",
    startedAt: "2026-08-20T06:00:00.000Z",
    durationMs: 120_000,
    perModel: [
      { modelId: "us.anthropic.claude-sonnet-4-6", tokensIn: 5000, tokensOut: 2000, calls: 3 },
    ],
    source: "spans",
    ...overrides,
  };
}

function makeConfigRun(overrides: Partial<ConfigRun> = {}): ConfigRun {
  return {
    sessionId: "session-2",
    subjectId: "myorg/repo-b",
    agentName: "dep-updater",
    status: "running",
    outcomeType: "",
    outcomeUrl: "",
    startedAt: "2026-08-20T05:00:00.000Z",
    durationMs: 0,
    perModel: [],
    source: "config",
    ...overrides,
  };
}

describe("mergeRuns", () => {
  it("includes span-only runs", () => {
    const spanRuns = [makeSpanRun({ sessionId: "span-only-1" })];
    const configRuns: ConfigRun[] = [];

    const result = mergeRuns(spanRuns, configRuns);

    expect(result).toHaveLength(1);
    expect(result[0]?.sessionId).toBe("span-only-1");
    expect(result[0]?.source).toBe("spans");
  });

  it("includes config-only runs regardless of last_status", () => {
    const spanRuns: Run[] = [];
    const configRuns = [
      makeConfigRun({ sessionId: "config-running", status: "running" }),
      makeConfigRun({ sessionId: "config-success", status: "success" }),
      makeConfigRun({ sessionId: "config-failed", status: "failed" }),
      makeConfigRun({ sessionId: "config-incomplete", status: "incomplete" }),
    ];

    const result = mergeRuns(spanRuns, configRuns);

    expect(result).toHaveLength(4);
    const sessionIds = result.map((r) => r.sessionId);
    expect(sessionIds).toContain("config-running");
    expect(sessionIds).toContain("config-success");
    expect(sessionIds).toContain("config-failed");
    expect(sessionIds).toContain("config-incomplete");
  });

  it("span wins on conflict (same session_id in both sources)", () => {
    const spanRuns = [
      makeSpanRun({
        sessionId: "shared-session",
        status: "success",
        outcomeUrl: "https://github.com/myorg/repo/pull/5",
        durationMs: 180_000,
      }),
    ];
    const configRuns = [
      makeConfigRun({
        sessionId: "shared-session",
        status: "running",
        outcomeUrl: "",
        durationMs: 0,
      }),
    ];

    const result = mergeRuns(spanRuns, configRuns);

    expect(result).toHaveLength(1);
    const merged = result[0];
    expect(merged?.sessionId).toBe("shared-session");
    expect(merged?.source).toBe("spans");
    expect(merged?.status).toBe("success");
    expect(merged?.outcomeUrl).toBe("https://github.com/myorg/repo/pull/5");
    expect(merged?.durationMs).toBe(180_000);
  });

  it("sorts by startedAt descending (most recent first)", () => {
    const spanRuns = [
      makeSpanRun({ sessionId: "old", startedAt: "2026-08-18T06:00:00.000Z" }),
      makeSpanRun({ sessionId: "new", startedAt: "2026-08-20T06:00:00.000Z" }),
    ];
    const configRuns = [makeConfigRun({ sessionId: "mid", startedAt: "2026-08-19T06:00:00.000Z" })];

    const result = mergeRuns(spanRuns, configRuns);

    expect(result.map((r) => r.sessionId)).toEqual(["new", "mid", "old"]);
  });

  it("applies status filter", () => {
    const spanRuns = [
      makeSpanRun({ sessionId: "s1", status: "success" }),
      makeSpanRun({ sessionId: "s2", status: "failed" }),
    ];
    const configRuns = [makeConfigRun({ sessionId: "c1", status: "running" })];

    const result = mergeRuns(spanRuns, configRuns, { statusFilter: "failed" });

    expect(result).toHaveLength(1);
    expect(result[0]?.sessionId).toBe("s2");
  });

  it("applies date-range filter (from/to)", () => {
    const spanRuns = [
      makeSpanRun({ sessionId: "before", startedAt: "2026-08-01T00:00:00.000Z" }),
      makeSpanRun({ sessionId: "in-range", startedAt: "2026-08-15T12:00:00.000Z" }),
      makeSpanRun({ sessionId: "after", startedAt: "2026-08-25T00:00:00.000Z" }),
    ];

    const result = mergeRuns(spanRuns, [], {
      from: new Date("2026-08-10T00:00:00.000Z"),
      to: new Date("2026-08-20T00:00:00.000Z"),
    });

    expect(result).toHaveLength(1);
    expect(result[0]?.sessionId).toBe("in-range");
  });

  it("applies both filters simultaneously", () => {
    const spanRuns = [
      makeSpanRun({ sessionId: "match", status: "success", startedAt: "2026-08-15T12:00:00.000Z" }),
      makeSpanRun({
        sessionId: "wrong-status",
        status: "failed",
        startedAt: "2026-08-15T12:00:00.000Z",
      }),
      makeSpanRun({
        sessionId: "wrong-date",
        status: "success",
        startedAt: "2026-08-01T12:00:00.000Z",
      }),
    ];

    const result = mergeRuns(spanRuns, [], {
      statusFilter: "success",
      from: new Date("2026-08-10T00:00:00.000Z"),
      to: new Date("2026-08-20T00:00:00.000Z"),
    });

    expect(result).toHaveLength(1);
    expect(result[0]?.sessionId).toBe("match");
  });

  it("returns empty array when no runs match filters", () => {
    const spanRuns = [makeSpanRun({ status: "success" })];

    const result = mergeRuns(spanRuns, [], { statusFilter: "failed" });

    expect(result).toEqual([]);
  });

  it("handles empty inputs gracefully", () => {
    const result = mergeRuns([], []);
    expect(result).toEqual([]);
  });

  it("merged result has MergedRun shape", () => {
    const spanRuns = [makeSpanRun({ sessionId: "s1" })];
    const configRuns = [makeConfigRun({ sessionId: "c1" })];

    const result = mergeRuns(spanRuns, configRuns);

    for (const run of result) {
      expect(run).toHaveProperty("sessionId");
      expect(run).toHaveProperty("subjectId");
      expect(run).toHaveProperty("agentName");
      expect(run).toHaveProperty("status");
      expect(run).toHaveProperty("outcomeType");
      expect(run).toHaveProperty("outcomeUrl");
      expect(run).toHaveProperty("startedAt");
      expect(run).toHaveProperty("durationMs");
      expect(run).toHaveProperty("perModel");
      expect(run).toHaveProperty("source");
    }
  });
});
