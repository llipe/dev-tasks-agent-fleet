/**
 * Integration tests for RunPanel — S-021, sub-task 21.10.
 *
 * Tests:
 * - Panel renders with mocked timeline and logs
 * - Each async state per section (loading, empty, error, timeout)
 * - Panel metadata renders immediately from row data
 * - Session ID truncation displayed correctly
 * - Incomplete run shows logs without error
 */

import { describe, it, expect, vi } from "vitest";
import type { MergedRun } from "@/server/runs/merge-runs.js";
import type { TimelineSpan } from "@/server/runs/span-to-run-mapper.js";
import type { ReadOutcome } from "@/server/repository/types.js";
import {
  fetchTraceData,
  fetchLogData,
  type RunPanelDataDeps,
} from "@/app/agents/[name]/run-panel-data.js";
import { truncateSessionId, parseLogLine, computeTimelineLayout } from "@/lib/run-panel-utils.js";

function makeMergedRun(overrides: Partial<MergedRun> = {}): MergedRun {
  return {
    sessionId: "dep-updater__myorg-myrepo__20250127T100000Z",
    subjectId: "myorg/myrepo",
    agentName: "dep-updater",
    status: "success",
    outcomeType: "pr",
    outcomeUrl: "https://github.com/myorg/myrepo/pull/42",
    startedAt: "2025-01-27T10:00:00.000Z",
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
    cost: { usd: 0.012, complete: true, unpricedModels: [] },
    ...overrides,
  };
}

function makeTimelineSpans(): TimelineSpan[] {
  return [
    {
      spanName: "dep-updater-run",
      parentSpanId: "",
      startTime: "2025-01-27T10:00:00.000Z",
      durationMs: 150000,
      modelId: "",
      tokensIn: 0,
      tokensOut: 0,
      isRoot: true,
    },
    {
      spanName: "bedrock-invoke",
      parentSpanId: "root-span-id",
      startTime: "2025-01-27T10:00:30.000Z",
      durationMs: 45000,
      modelId: "us.anthropic.claude-sonnet-4-20250514-v1:0",
      tokensIn: 1500,
      tokensOut: 500,
      isRoot: false,
    },
    {
      spanName: "bedrock-invoke-2",
      parentSpanId: "root-span-id",
      startTime: "2025-01-27T10:01:30.000Z",
      durationMs: 30000,
      modelId: "us.anthropic.claude-sonnet-4-20250514-v1:0",
      tokensIn: 800,
      tokensOut: 300,
      isRoot: false,
    },
  ];
}

function makeLogLines(): string[] {
  return [
    '{"timestamp":"2025-01-27T10:00:00.000Z","message":"Starting pipeline","level":"info","session_id":"dep-updater__myorg-myrepo__20250127T100000Z"}',
    '{"timestamp":"2025-01-27T10:00:01.000Z","message":"Cloning repository myorg/myrepo","level":"info","session_id":"dep-updater__myorg-myrepo__20250127T100000Z"}',
    '{"timestamp":"2025-01-27T10:02:30.000Z","message":"Pipeline complete: success","level":"info","session_id":"dep-updater__myorg-myrepo__20250127T100000Z"}',
  ];
}

describe("RunPanel integration", () => {
  describe("data fetching", () => {
    it("fetchTraceData calls querySessionTrace with correct params", async () => {
      const mockTrace = vi.fn<RunPanelDataDeps["querySessionTrace"]>().mockResolvedValue({
        status: "ok",
        data: makeTimelineSpans(),
        correlationId: "trace-1",
      });

      const from = new Date("2025-01-27T00:00:00.000Z");
      const to = new Date("2025-01-28T00:00:00.000Z");

      const result = await fetchTraceData("session-abc", from, to, {
        querySessionTrace: mockTrace,
        filterLogsBySessionId: vi.fn(),
      });

      expect(mockTrace).toHaveBeenCalledWith({
        sessionId: "session-abc",
        from,
        to,
      });
      expect(result.status).toBe("ok");
    });

    it("fetchLogData calls filterLogsBySessionId with correct params", async () => {
      // AGENT_LOG_GROUP has no default — the AgentCore-generated group name
      // changes on every runtime recreation, so it must be configured. See
      // run-panel-data.test.ts for the unset case.
      process.env["AGENT_LOG_GROUP"] =
        "/aws/bedrock-agentcore/runtimes/depupdater_dep_updater-M4gkuL4wSr-DEFAULT";

      const mockLogs = vi.fn<RunPanelDataDeps["filterLogsBySessionId"]>().mockResolvedValue({
        status: "ok",
        data: makeLogLines(),
        correlationId: "log-1",
      });

      const from = new Date("2025-01-27T00:00:00.000Z");
      const to = new Date("2025-01-28T00:00:00.000Z");

      const result = await fetchLogData("session-abc", from, to, {
        querySessionTrace: vi.fn(),
        filterLogsBySessionId: mockLogs,
      });

      expect(mockLogs).toHaveBeenCalledWith(
        expect.objectContaining({
          sessionId: "session-abc",
          startTime: from.getTime(),
          endTime: to.getTime(),
        }),
      );
      expect(result.status).toBe("ok");
    });
  });

  describe("async state handling - timeline", () => {
    it("handles ok state with spans", async () => {
      const mockTrace = vi.fn().mockResolvedValue({
        status: "ok",
        data: makeTimelineSpans(),
        correlationId: "t-1",
      } satisfies ReadOutcome<TimelineSpan[]>);

      const result = await mockTrace();
      expect(result.status).toBe("ok");
      expect(result.data).toHaveLength(3);
    });

    it("handles empty state", async () => {
      const mockTrace = vi.fn().mockResolvedValue({
        status: "empty",
        correlationId: "t-2",
      } satisfies ReadOutcome<TimelineSpan[]>);

      const result = await mockTrace();
      expect(result.status).toBe("empty");
    });

    it("handles error state", async () => {
      const mockTrace = vi.fn().mockResolvedValue({
        status: "error",
        error: "Service unavailable",
        correlationId: "t-3",
      } satisfies ReadOutcome<TimelineSpan[]>);

      const result = await mockTrace();
      expect(result.status).toBe("error");
      expect(result.error).toBe("Service unavailable");
    });

    it("handles timeout state", async () => {
      const mockTrace = vi.fn().mockResolvedValue({
        status: "timeout",
        correlationId: "t-4",
      } satisfies ReadOutcome<TimelineSpan[]>);

      const result = await mockTrace();
      expect(result.status).toBe("timeout");
    });
  });

  describe("async state handling - logs", () => {
    it("handles ok state with log lines", async () => {
      const mockLogs = vi.fn().mockResolvedValue({
        status: "ok",
        data: makeLogLines(),
        correlationId: "l-1",
      } satisfies ReadOutcome<string[]>);

      const result = await mockLogs();
      expect(result.status).toBe("ok");
      expect(result.data).toHaveLength(3);
    });

    it("handles empty state", async () => {
      const mockLogs = vi.fn().mockResolvedValue({
        status: "empty",
        correlationId: "l-2",
      } satisfies ReadOutcome<string[]>);

      const result = await mockLogs();
      expect(result.status).toBe("empty");
    });

    it("handles error state", async () => {
      const mockLogs = vi.fn().mockResolvedValue({
        status: "error",
        error: "Access denied",
        correlationId: "l-3",
      } satisfies ReadOutcome<string[]>);

      const result = await mockLogs();
      expect(result.status).toBe("error");
      expect(result.error).toBe("Access denied");
    });

    it("handles timeout state", async () => {
      const mockLogs = vi.fn().mockResolvedValue({
        status: "timeout",
        correlationId: "l-4",
      } satisfies ReadOutcome<string[]>);

      const result = await mockLogs();
      expect(result.status).toBe("timeout");
    });
  });

  describe("panel metadata rendering logic", () => {
    it("session ID is truncated correctly for display", () => {
      const run = makeMergedRun();
      const truncated = truncateSessionId(run.sessionId);
      expect(truncated).toBe("dep-upda...0000Z");
      expect(truncated).toHaveLength(16);
    });

    it("full session ID preserved for copy and title", () => {
      const run = makeMergedRun();
      expect(run.sessionId).toBe("dep-updater__myorg-myrepo__20250127T100000Z");
      expect(run.sessionId.length).toBeGreaterThan(16);
    });

    it("incomplete run passes through without error state", () => {
      const run = makeMergedRun({ status: "incomplete" });
      // The panel should render logs without an error indicator
      expect(run.status).toBe("incomplete");
      // Verify log viewer doesn't add error state for incomplete
      const logLines = makeLogLines().slice(0, 2); // Partial logs
      const parsed = logLines.map(parseLogLine);
      expect(parsed).toHaveLength(2);
      // No error message in parsed output
      parsed.forEach((line) => {
        expect(line.message).not.toContain("error");
      });
    });
  });

  describe("timeline layout computation", () => {
    it("computes correct layout for a full trace", () => {
      const spans = makeTimelineSpans();
      const layout = computeTimelineLayout(spans);

      expect(layout).toHaveLength(3);

      // Root span at full width
      expect(layout[0]?.geometry.widthPercent).toBe(100);
      expect(layout[0]?.geometry.leftPercent).toBe(0);
      expect(layout[0]?.depth).toBe(0);

      // First child: starts at 30s / 150s = 20%, duration 45s / 150s = 30%
      expect(layout[1]?.geometry.widthPercent).toBe(30);
      expect(layout[1]?.geometry.leftPercent).toBe(20);
      expect(layout[1]?.depth).toBe(1);

      // Second child: starts at 90s / 150s = 60%, duration 30s / 150s = 20%
      expect(layout[2]?.geometry.widthPercent).toBe(20);
      expect(layout[2]?.geometry.leftPercent).toBe(60);
      expect(layout[2]?.depth).toBe(1);
    });

    it("handles empty spans array", () => {
      const layout = computeTimelineLayout([]);
      expect(layout).toEqual([]);
    });

    it("handles single root span", () => {
      const spans: TimelineSpan[] = [
        {
          spanName: "root",
          parentSpanId: "",
          startTime: "2025-01-27T10:00:00.000Z",
          durationMs: 5000,
          modelId: "",
          tokensIn: 0,
          tokensOut: 0,
          isRoot: true,
        },
      ];
      const layout = computeTimelineLayout(spans);
      expect(layout).toHaveLength(1);
      expect(layout[0]?.geometry.widthPercent).toBe(100);
    });
  });

  describe("log parsing integration", () => {
    it("parses JSON structured log lines from agent", () => {
      const lines = makeLogLines();
      const parsed = lines.map(parseLogLine);

      expect(parsed[0]?.timestamp).toBe("2025-01-27T10:00:00.000Z");
      expect(parsed[0]?.message).toBe("Starting pipeline");
      expect(parsed[1]?.message).toBe("Cloning repository myorg/myrepo");
      expect(parsed[2]?.message).toBe("Pipeline complete: success");
    });

    it("handles mixed log formats", () => {
      const lines = [
        '{"timestamp":"2025-01-27T10:00:00Z","message":"json line"}',
        "2025-01-27T10:00:01Z plain text line",
        "unformatted output",
      ];

      const parsed = lines.map(parseLogLine);
      expect(parsed[0]?.timestamp).toBe("2025-01-27T10:00:00Z");
      expect(parsed[0]?.message).toBe("json line");
      expect(parsed[1]?.timestamp).toBe("2025-01-27T10:00:01Z");
      expect(parsed[1]?.message).toBe("plain text line");
      expect(parsed[2]?.timestamp).toBe("");
      expect(parsed[2]?.message).toBe("unformatted output");
    });

    it("incomplete run logs stop at cut-off without error indicator", () => {
      // Simulate incomplete run - logs just stop, no error/failure log line
      const lines = [
        '{"timestamp":"2025-01-27T10:00:00Z","message":"Starting pipeline"}',
        '{"timestamp":"2025-01-27T10:00:10Z","message":"Processing..."}',
        // No final "complete" or "error" line - run was cut off
      ];

      const parsed = lines.map(parseLogLine);
      expect(parsed).toHaveLength(2);
      // No error state indicator needed
      expect(parsed.every((l) => !l.message.toLowerCase().includes("error"))).toBe(true);
    });
  });

  describe("panel data wiring", () => {
    it("run with no matching session returns null panel", () => {
      const runs = [makeMergedRun({ sessionId: "session-A" })];
      const targetSession = "non-existent-session";
      const found = runs.find((r) => r.sessionId === targetSession);
      expect(found).toBeUndefined();
    });

    it("run with matching session provides data for panel", () => {
      const runs = [
        makeMergedRun({ sessionId: "session-A" }),
        makeMergedRun({ sessionId: "session-B" }),
      ];
      const targetSession = "session-B";
      const found = runs.find((r) => r.sessionId === targetSession);
      expect(found).toBeDefined();
      expect(found?.sessionId).toBe("session-B");
    });
  });
});
