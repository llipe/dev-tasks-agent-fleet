/**
 * Unit tests for span-to-run mapper.
 *
 * Tests:
 * - Mapper against S-012's committed fixture
 * - Per-model folding (single and multi-model)
 * - Zero-token run
 * - Missing optional attribute
 * - Malformed row skipped with warn
 */

/* eslint-disable @typescript-eslint/no-non-null-assertion */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { mapRowsToRuns, mapRowsToTimeline } from "./span-to-run-mapper.js";
import type { LogsInsightsRow } from "../aws/logs-insights-adapter.js";

// Simulate what Logs Insights returns from the committed fixtures
// The query aliases map: session_id, subject_id, run_status, etc.
function makeRootRow(overrides: Partial<LogsInsightsRow> = {}): LogsInsightsRow {
  return {
    session_id: "dep-updater__llipe-dev-tasks-agent-fleet__20250127T120000Z",
    session_id_fallback: "dep-updater__llipe-dev-tasks-agent-fleet__20250127T120000Z",
    subject_id: "llipe/dev-tasks-agent-fleet",
    run_status: "success",
    outcome_type: "pr",
    outcome_url: "https://github.com/llipe/dev-tasks-agent-fleet/pull/42",
    service_name: "dep-updater",
    duration_ns: "60000000000",
    start_time: "1737999000000000000",
    parent_span_id: "",
    ...overrides,
  };
}

function makeGenAiRow(overrides: Partial<LogsInsightsRow> = {}): LogsInsightsRow {
  return {
    session_id: "dep-updater__llipe-dev-tasks-agent-fleet__20250127T120000Z",
    session_id_fallback: "dep-updater__llipe-dev-tasks-agent-fleet__20250127T120000Z",
    subject_id: "llipe/dev-tasks-agent-fleet",
    model_id: "us.anthropic.claude-sonnet-4-6",
    tokens_in: "1500",
    tokens_out: "500",
    duration_ns: "15000000000",
    start_time: "1737999010000000000",
    parent_span_id: "1234567890abcdef",
    span_name: "gen_ai.chat",
    ...overrides,
  };
}

describe("mapRowsToRuns", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  describe("mapper against S-012 fixture", () => {
    it("maps a root span + gen_ai child into a complete Run", () => {
      const rows = [makeRootRow(), makeGenAiRow()];
      const runs = mapRowsToRuns(rows);

      expect(runs).toHaveLength(1);
      const run = runs[0]!;

      expect(run.sessionId).toBe("dep-updater__llipe-dev-tasks-agent-fleet__20250127T120000Z");
      expect(run.subjectId).toBe("llipe/dev-tasks-agent-fleet");
      expect(run.agentName).toBe("dep-updater");
      expect(run.status).toBe("success");
      expect(run.outcomeType).toBe("pr");
      expect(run.outcomeUrl).toBe("https://github.com/llipe/dev-tasks-agent-fleet/pull/42");
      expect(run.source).toBe("spans");
      expect(run.durationMs).toBe(60000); // 60s in ms
      expect(run.startedAt).toBe("2025-01-27T17:30:00.000Z"); // from nanos
      expect(run.perModel).toHaveLength(1);
      expect(run.perModel[0]).toEqual({
        modelId: "us.anthropic.claude-sonnet-4-6",
        tokensIn: 1500,
        tokensOut: 500,
        calls: 1,
      });
    });
  });

  describe("per-model folding", () => {
    it("folds multiple spans for same model into one ModelUsage entry", () => {
      const rows = [
        makeRootRow(),
        makeGenAiRow({ tokens_in: "1000", tokens_out: "200" }),
        makeGenAiRow({ tokens_in: "500", tokens_out: "300" }),
      ];
      const runs = mapRowsToRuns(rows);

      expect(runs).toHaveLength(1);
      expect(runs[0]!.perModel).toHaveLength(1);
      expect(runs[0]!.perModel[0]).toEqual({
        modelId: "us.anthropic.claude-sonnet-4-6",
        tokensIn: 1500,
        tokensOut: 500,
        calls: 2,
      });
    });

    it("keeps separate entries for different models", () => {
      const rows = [
        makeRootRow(),
        makeGenAiRow({ model_id: "anthropic.claude-3-haiku", tokens_in: "100", tokens_out: "50" }),
        makeGenAiRow({ model_id: "anthropic.claude-3-opus", tokens_in: "2000", tokens_out: "800" }),
      ];
      const runs = mapRowsToRuns(rows);

      expect(runs).toHaveLength(1);
      expect(runs[0]!.perModel).toHaveLength(2);

      const haiku = runs[0]!.perModel.find((m) => m.modelId === "anthropic.claude-3-haiku");
      const opus = runs[0]!.perModel.find((m) => m.modelId === "anthropic.claude-3-opus");

      expect(haiku).toEqual({
        modelId: "anthropic.claude-3-haiku",
        tokensIn: 100,
        tokensOut: 50,
        calls: 1,
      });
      expect(opus).toEqual({
        modelId: "anthropic.claude-3-opus",
        tokensIn: 2000,
        tokensOut: 800,
        calls: 1,
      });
    });
  });

  describe("zero-token run", () => {
    it("produces a valid Run with empty perModel when no gen_ai spans", () => {
      const rows = [makeRootRow()];
      const runs = mapRowsToRuns(rows);

      expect(runs).toHaveLength(1);
      expect(runs[0]!.perModel).toEqual([]);
      expect(runs[0]!.durationMs).toBe(60000);
    });

    it("handles gen_ai span with zero tokens", () => {
      const rows = [makeRootRow(), makeGenAiRow({ tokens_in: "0", tokens_out: "0" })];
      const runs = mapRowsToRuns(rows);

      expect(runs).toHaveLength(1);
      expect(runs[0]!.perModel[0]).toEqual({
        modelId: "us.anthropic.claude-sonnet-4-6",
        tokensIn: 0,
        tokensOut: 0,
        calls: 1,
      });
    });
  });

  describe("missing optional attributes", () => {
    it("handles missing outcome_type gracefully", () => {
      const rows = [makeRootRow({ outcome_type: undefined })];
      const runs = mapRowsToRuns(rows);

      expect(runs).toHaveLength(1);
      expect(runs[0]!.outcomeType).toBe("");
    });

    it("handles missing outcome_url gracefully", () => {
      const rows = [makeRootRow({ outcome_url: undefined })];
      const runs = mapRowsToRuns(rows);

      expect(runs).toHaveLength(1);
      expect(runs[0]!.outcomeUrl).toBe("");
    });

    it("handles missing duration_ns gracefully", () => {
      const rows = [makeRootRow({ duration_ns: undefined })];
      const runs = mapRowsToRuns(rows);

      expect(runs).toHaveLength(1);
      expect(runs[0]!.durationMs).toBe(0);
    });

    it("uses session_id_fallback when session_id is missing", () => {
      const rows = [makeRootRow({ session_id: "", session_id_fallback: "fallback-session-123" })];
      const runs = mapRowsToRuns(rows);

      expect(runs).toHaveLength(1);
      expect(runs[0]!.sessionId).toBe("fallback-session-123");
    });
  });

  describe("malformed row skipped with warn", () => {
    it("skips rows with missing session_id and warns", () => {
      const warnSpy = vi.spyOn(console, "warn").mockImplementation(() => {});

      const rows = [
        { run_status: "success", subject_id: "foo/bar" } as LogsInsightsRow, // no session_id
        makeRootRow(),
      ];
      const runs = mapRowsToRuns(rows);

      expect(runs).toHaveLength(1);
      expect(warnSpy).toHaveBeenCalledWith(
        expect.stringContaining("missing session_id"),
        expect.any(Object),
      );
    });

    it("skips sessions with no root span and warns", () => {
      const warnSpy = vi.spyOn(console, "warn").mockImplementation(() => {});

      // Only a child span, no root
      const rows = [makeGenAiRow()];
      const runs = mapRowsToRuns(rows);

      expect(runs).toHaveLength(0);
      expect(warnSpy).toHaveBeenCalledWith(
        expect.stringContaining("no root span"),
        expect.any(Object),
      );
    });

    it("skips root span with missing subject_id and warns", () => {
      const warnSpy = vi.spyOn(console, "warn").mockImplementation(() => {});

      const rows = [makeRootRow({ subject_id: undefined })];
      const runs = mapRowsToRuns(rows);

      expect(runs).toHaveLength(0);
      expect(warnSpy).toHaveBeenCalledWith(
        expect.stringContaining("missing subject_id"),
        expect.any(Object),
      );
    });
  });

  describe("multiple sessions", () => {
    it("maps rows from different sessions into separate Runs", () => {
      const rows = [
        makeRootRow({ session_id: "session-a", subject_id: "org/repo-a" }),
        makeGenAiRow({ session_id: "session-a", tokens_in: "100", tokens_out: "50" }),
        makeRootRow({ session_id: "session-b", subject_id: "org/repo-b" }),
        makeGenAiRow({ session_id: "session-b", tokens_in: "200", tokens_out: "100" }),
      ];
      const runs = mapRowsToRuns(rows);

      expect(runs).toHaveLength(2);
      expect(runs.map((r) => r.sessionId).sort()).toEqual(["session-a", "session-b"]);
    });
  });
});

describe("mapRowsToTimeline", () => {
  it("maps rows to timeline spans with correct fields", () => {
    const rows: LogsInsightsRow[] = [
      {
        span_name: "dep-updater-run",
        parent_span_id: "",
        start_time: "1737999000000000000",
        duration_ns: "60000000000",
        model_id: "",
        tokens_in: "0",
        tokens_out: "0",
      },
      {
        span_name: "gen_ai.chat",
        parent_span_id: "1234567890abcdef",
        start_time: "1737999010000000000",
        duration_ns: "15000000000",
        model_id: "us.anthropic.claude-sonnet-4-6",
        tokens_in: "1500",
        tokens_out: "500",
      },
    ];

    const timeline = mapRowsToTimeline(rows);

    expect(timeline).toHaveLength(2);
    expect(timeline[0]).toEqual({
      spanName: "dep-updater-run",
      parentSpanId: "",
      startTime: "1737999000000000000",
      durationMs: 60000,
      modelId: "",
      tokensIn: 0,
      tokensOut: 0,
      isRoot: true,
    });
    expect(timeline[1]).toEqual({
      spanName: "gen_ai.chat",
      parentSpanId: "1234567890abcdef",
      startTime: "1737999010000000000",
      durationMs: 15000,
      modelId: "us.anthropic.claude-sonnet-4-6",
      tokensIn: 1500,
      tokensOut: 500,
      isRoot: false,
    });
  });
});
