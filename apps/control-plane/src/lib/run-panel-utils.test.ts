/**
 * Unit tests for run panel utilities — S-021, sub-task 21.9.
 *
 * Tests:
 * - Session ID truncation
 * - Timeline bar geometry computation
 * - Log line parsing (JSON and plain text)
 */

import { describe, it, expect } from "vitest";
import {
  truncateSessionId,
  computeBarGeometry,
  parseStartTime,
  parseLogLine,
  parseLogLines,
  computeTimelineLayout,
} from "./run-panel-utils.js";
import type { TimelineSpan } from "@/server/runs/span-to-run-mapper.js";

describe("truncateSessionId", () => {
  it("truncates a long session ID to first 8 + ... + last 5", () => {
    const input = "dep-updater__myorg-myrepo__20250127T100000Z";
    const result = truncateSessionId(input);
    expect(result).toBe("dep-upda...0000Z");
  });

  it("returns short IDs unchanged (length <= 16)", () => {
    expect(truncateSessionId("short-id")).toBe("short-id");
    expect(truncateSessionId("1234567890123456")).toBe("1234567890123456");
  });

  it("truncates exactly at boundary (length = 17)", () => {
    const input = "12345678901234567";
    expect(truncateSessionId(input)).toBe("12345678...34567");
  });

  it("handles empty string", () => {
    expect(truncateSessionId("")).toBe("");
  });

  it("handles session IDs with special characters", () => {
    const input = "dep-updater__org/repo-name__20250127T100000Z";
    const result = truncateSessionId(input);
    expect(result).toHaveLength(16); // 8 + 3 + 5
    expect(result).toBe("dep-upda...0000Z");
  });
});

describe("computeBarGeometry", () => {
  const makeSpan = (overrides: Partial<TimelineSpan> = {}): TimelineSpan => ({
    spanName: "test-span",
    parentSpanId: "parent-1",
    startTime: "2025-01-27T10:00:00.000Z",
    durationMs: 5000,
    modelId: "",
    tokensIn: 0,
    tokensOut: 0,
    isRoot: false,
    ...overrides,
  });

  it("root span is 100% width at 0% offset", () => {
    const rootStart = Date.parse("2025-01-27T10:00:00.000Z");
    const rootDuration = 10000;
    const span = makeSpan({
      startTime: "2025-01-27T10:00:00.000Z",
      durationMs: 10000,
      isRoot: true,
    });

    const geo = computeBarGeometry(span, rootStart, rootDuration);
    expect(geo.widthPercent).toBe(100);
    expect(geo.leftPercent).toBe(0);
    expect(geo.needsMinWidth).toBe(false);
  });

  it("child span at 50% width and 25% offset", () => {
    const rootStart = Date.parse("2025-01-27T10:00:00.000Z");
    const rootDuration = 10000;
    const span = makeSpan({
      startTime: "2025-01-27T10:00:02.500Z", // 2500ms after root start
      durationMs: 5000, // half of root
    });

    const geo = computeBarGeometry(span, rootStart, rootDuration);
    expect(geo.widthPercent).toBe(50);
    expect(geo.leftPercent).toBe(25);
    expect(geo.needsMinWidth).toBe(false);
  });

  it("very short span gets needsMinWidth flag", () => {
    const rootStart = Date.parse("2025-01-27T10:00:00.000Z");
    const rootDuration = 10000;
    const span = makeSpan({
      startTime: "2025-01-27T10:00:00.000Z",
      durationMs: 50, // 0.5% of root — under 1% threshold
    });

    const geo = computeBarGeometry(span, rootStart, rootDuration);
    expect(geo.widthPercent).toBe(0.5);
    expect(geo.needsMinWidth).toBe(true);
  });

  it("handles zero root duration gracefully", () => {
    const span = makeSpan({ durationMs: 100 });
    const geo = computeBarGeometry(span, 0, 0);
    expect(geo.widthPercent).toBe(100);
    expect(geo.leftPercent).toBe(0);
  });

  it("clamps width to 100% max", () => {
    const rootStart = Date.parse("2025-01-27T10:00:00.000Z");
    const rootDuration = 5000;
    const span = makeSpan({
      startTime: "2025-01-27T10:00:00.000Z",
      durationMs: 10000, // longer than root (data anomaly)
    });

    const geo = computeBarGeometry(span, rootStart, rootDuration);
    expect(geo.widthPercent).toBe(100);
  });

  it("clamps left offset to 0% min", () => {
    const rootStart = Date.parse("2025-01-27T10:00:05.000Z");
    const rootDuration = 10000;
    const span = makeSpan({
      startTime: "2025-01-27T10:00:00.000Z", // before root start
      durationMs: 2000,
    });

    const geo = computeBarGeometry(span, rootStart, rootDuration);
    expect(geo.leftPercent).toBe(0);
  });
});

describe("parseStartTime", () => {
  it("parses ISO date strings", () => {
    const result = parseStartTime("2025-01-27T10:00:00.000Z");
    expect(result).toBe(Date.parse("2025-01-27T10:00:00.000Z"));
  });

  it("parses nanosecond timestamps", () => {
    // 1737972000000000000 ns = 1737972000000 ms
    const result = parseStartTime("1737972000000000000");
    expect(result).toBe(1737972000000);
  });

  it("returns 0 for empty string", () => {
    expect(parseStartTime("")).toBe(0);
  });

  it("returns 0 for unparseable input", () => {
    expect(parseStartTime("not-a-time")).toBe(0);
  });
});

describe("parseLogLine", () => {
  it("parses JSON structured log with timestamp and message", () => {
    const raw =
      '{"timestamp":"2025-01-27T10:00:00.000Z","message":"Starting pipeline","level":"info"}';
    const result = parseLogLine(raw);
    expect(result.timestamp).toBe("2025-01-27T10:00:00.000Z");
    expect(result.message).toBe("Starting pipeline");
    expect(result.raw).toBe(raw);
  });

  it("handles JSON with 'msg' field instead of 'message'", () => {
    const raw = '{"ts":"2025-01-27T10:00:00Z","msg":"Hello world"}';
    const result = parseLogLine(raw);
    expect(result.timestamp).toBe("2025-01-27T10:00:00Z");
    expect(result.message).toBe("Hello world");
  });

  it("handles JSON with 'time' field", () => {
    const raw = '{"time":"2025-01-27T10:00:00Z","message":"test msg"}';
    const result = parseLogLine(raw);
    expect(result.timestamp).toBe("2025-01-27T10:00:00Z");
    expect(result.message).toBe("test msg");
  });

  it("parses plain text with ISO timestamp prefix", () => {
    const raw = "2025-01-27T10:00:00.000Z Processing repository myorg/repo";
    const result = parseLogLine(raw);
    expect(result.timestamp).toBe("2025-01-27T10:00:00.000Z");
    expect(result.message).toBe("Processing repository myorg/repo");
  });

  it("handles plain text without timestamp", () => {
    const raw = "Some log output without a timestamp";
    const result = parseLogLine(raw);
    expect(result.timestamp).toBe("");
    expect(result.message).toBe("Some log output without a timestamp");
  });

  it("handles empty string", () => {
    const result = parseLogLine("");
    expect(result.timestamp).toBe("");
    expect(result.message).toBe("");
  });

  it("handles invalid JSON gracefully", () => {
    const raw = '{"broken json';
    const result = parseLogLine(raw);
    expect(result.message).toBe('{"broken json');
  });

  it("preserves raw field in all cases", () => {
    const raw = "any content here";
    const result = parseLogLine(raw);
    expect(result.raw).toBe(raw);
  });
});

describe("parseLogLines", () => {
  it("parses multiple lines", () => {
    const lines = [
      '{"timestamp":"2025-01-27T10:00:00Z","message":"line 1"}',
      '{"timestamp":"2025-01-27T10:00:01Z","message":"line 2"}',
    ];
    const results = parseLogLines(lines);
    expect(results).toHaveLength(2);
    expect(results[0]?.message).toBe("line 1");
    expect(results[1]?.message).toBe("line 2");
  });

  it("handles empty array", () => {
    expect(parseLogLines([])).toEqual([]);
  });
});

describe("computeTimelineLayout", () => {
  const makeSpan = (overrides: Partial<TimelineSpan> = {}): TimelineSpan => ({
    spanName: "test-span",
    parentSpanId: "parent-1",
    startTime: "2025-01-27T10:00:01.000Z",
    durationMs: 5000,
    modelId: "",
    tokensIn: 0,
    tokensOut: 0,
    isRoot: false,
    ...overrides,
  });

  it("returns empty array for empty input", () => {
    expect(computeTimelineLayout([])).toEqual([]);
  });

  it("root span gets 100% width", () => {
    const spans = [
      makeSpan({ isRoot: true, startTime: "2025-01-27T10:00:00.000Z", durationMs: 10000 }),
    ];
    const layout = computeTimelineLayout(spans);
    expect(layout).toHaveLength(1);
    expect(layout[0]?.geometry.widthPercent).toBe(100);
    expect(layout[0]?.geometry.leftPercent).toBe(0);
    expect(layout[0]?.depth).toBe(0);
  });

  it("child spans positioned relative to root", () => {
    const spans = [
      makeSpan({
        spanName: "root",
        isRoot: true,
        parentSpanId: "",
        startTime: "2025-01-27T10:00:00.000Z",
        durationMs: 10000,
      }),
      makeSpan({
        spanName: "child-1",
        startTime: "2025-01-27T10:00:02.000Z",
        durationMs: 3000,
      }),
    ];
    const layout = computeTimelineLayout(spans);
    expect(layout).toHaveLength(2);

    const child = layout[1];
    expect(child?.geometry.widthPercent).toBe(30);
    expect(child?.geometry.leftPercent).toBe(20);
    expect(child?.depth).toBe(1);
  });

  it("handles spans without explicit root (uses first as reference)", () => {
    const spans = [
      makeSpan({ spanName: "span-a", isRoot: false }),
      makeSpan({ spanName: "span-b", isRoot: false }),
    ];
    const layout = computeTimelineLayout(spans);
    expect(layout).toHaveLength(2);
    // All get 100% width when no root
    expect(layout[0]?.geometry.widthPercent).toBe(100);
    expect(layout[1]?.geometry.widthPercent).toBe(100);
  });
});
