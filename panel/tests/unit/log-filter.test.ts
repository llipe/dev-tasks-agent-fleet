import { describe, expect, it } from "vitest";

import { applyLogFilter, NO_LOG_FILTER, type LogFilterState } from "@/lib/domain/log-filter";
import type { LogLineView } from "@/lib/domain/run-detail";

/**
 * Layer 1 (unit) — `applyLogFilter` (Story S-145, FR10/FR11).
 *
 * Both the step filter and the log-level filter are pure, client-side
 * reducers over the already-loaded log window (spec §8.2) — no I/O, no new
 * server read. Covers: step-only, level-only, both combined, neither (full
 * tail / identity), "All steps" reset, an unknown `stepId` (empty result, not
 * a crash), and the CT-4 subset/idempotency contract.
 */

function line(overrides: Partial<LogLineView> = {}): LogLineView {
  return {
    id: 1,
    seq: 1,
    timestamp: "14:02:13",
    level: "info",
    step: "",
    stepId: null,
    message: "hello",
    ...overrides,
  };
}

describe("applyLogFilter — step filter (FR10)", () => {
  const lines = [
    line({ id: 1, seq: 1, stepId: "step-1", message: "a" }),
    line({ id: 2, seq: 2, stepId: "step-2", message: "b" }),
    line({ id: 3, seq: 3, stepId: null, message: "c" }),
  ];

  it("keeps only lines matching the selected step id", () => {
    const result = applyLogFilter(lines, { stepId: "step-1", level: "all" });
    expect(result.map((l) => l.message)).toEqual(["a"]);
  });

  it("returns an empty result for an unknown stepId — not a crash (TC-FR10-N1)", () => {
    const result = applyLogFilter(lines, { stepId: "ghost-step", level: "all" });
    expect(result).toEqual([]);
  });

  it("'All steps' (stepId: null) restores the full tail", () => {
    const result = applyLogFilter(lines, { stepId: null, level: "all" });
    expect(result).toEqual(lines);
  });

  it("a line with no step_id never matches a specific step filter", () => {
    const result = applyLogFilter(lines, { stepId: "step-1", level: "all" });
    expect(result.some((l) => l.message === "c")).toBe(false);
  });
});

describe("applyLogFilter — level filter (FR11)", () => {
  const lines = [
    line({ id: 1, seq: 1, level: "debug", message: "d" }),
    line({ id: 2, seq: 2, level: "info", message: "i" }),
    line({ id: 3, seq: 3, level: "warn", message: "w" }),
    line({ id: 4, seq: 4, level: "error", message: "e" }),
  ];

  it("'warn' shows warnings AND errors ('errors and warnings only', AC3 example)", () => {
    const result = applyLogFilter(lines, { stepId: null, level: "warn" });
    expect(result.map((l) => l.message)).toEqual(["w", "e"]);
  });

  it("'error' shows only errors", () => {
    const result = applyLogFilter(lines, { stepId: null, level: "error" });
    expect(result.map((l) => l.message)).toEqual(["e"]);
  });

  it("'all' is the identity filter over level", () => {
    const result = applyLogFilter(lines, { stepId: null, level: "all" });
    expect(result).toEqual(lines);
  });

  it("a line with an unrecognized level string falls back to 'info' severity, not a crash (schema-drift EC)", () => {
    const weird = line({ id: 9, seq: 9, level: "trace", message: "weird" });
    // "trace" is treated as info-severity — kept by "warn"/"error" filters
    // are too strict for it, but "all" and "info"-and-above keep it.
    expect(applyLogFilter([weird], { stepId: null, level: "warn" })).toEqual([]);
    expect(applyLogFilter([weird], { stepId: null, level: "info" })).toEqual([weird]);
  });
});

describe("applyLogFilter — composition (both filters together, AC3)", () => {
  const lines = [
    line({ id: 1, seq: 1, stepId: "step-1", level: "info", message: "step1-info" }),
    line({ id: 2, seq: 2, stepId: "step-1", level: "error", message: "step1-error" }),
    line({ id: 3, seq: 3, stepId: "step-2", level: "error", message: "step2-error" }),
  ];

  it("a step + level combination shows only lines matching BOTH", () => {
    const result = applyLogFilter(lines, { stepId: "step-1", level: "error" });
    expect(result.map((l) => l.message)).toEqual(["step1-error"]);
  });

  it("neither filter active returns the full tail unchanged", () => {
    const result = applyLogFilter(lines, NO_LOG_FILTER);
    expect(result).toEqual(lines);
  });
});

describe("applyLogFilter — CT-4 contract + edge cases", () => {
  it("returns [] for zero input lines, for any filter", () => {
    expect(applyLogFilter([], { stepId: "x", level: "warn" })).toEqual([]);
    expect(applyLogFilter([], NO_LOG_FILTER)).toEqual([]);
  });

  it("output is always a subset of input (length never exceeds input length)", () => {
    const lines = [
      line({ id: 1, seq: 1, stepId: "step-1", level: "warn" }),
      line({ id: 2, seq: 2, stepId: "step-2", level: "error" }),
      line({ id: 3, seq: 3, stepId: null, level: "debug" }),
    ];
    const filters: LogFilterState[] = [
      NO_LOG_FILTER,
      { stepId: "step-1", level: "all" },
      { stepId: null, level: "warn" },
      { stepId: "step-2", level: "error" },
      { stepId: "ghost", level: "debug" },
    ];
    for (const filter of filters) {
      const result = applyLogFilter(lines, filter);
      expect(result.length).toBeLessThanOrEqual(lines.length);
    }
  });

  it("applying the same filter twice is idempotent", () => {
    const lines = [
      line({ id: 1, seq: 1, stepId: "step-1", level: "warn" }),
      line({ id: 2, seq: 2, stepId: "step-2", level: "error" }),
    ];
    const filter: LogFilterState = { stepId: "step-1", level: "all" };
    const once = applyLogFilter(lines, filter);
    const twice = applyLogFilter(once, filter);
    expect(twice).toEqual(once);
  });

  it("the empty filter is always the identity function", () => {
    const lines = [
      line({ id: 1, seq: 1, stepId: "step-1", level: "warn" }),
      line({ id: 2, seq: 2, stepId: null, level: "debug" }),
    ];
    expect(applyLogFilter(lines, NO_LOG_FILTER)).toEqual(lines);
  });
});
