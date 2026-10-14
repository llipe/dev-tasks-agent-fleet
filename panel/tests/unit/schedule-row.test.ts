import { describe, expect, it } from "vitest";
import {
  buildScheduleCellModel,
  formatRelativeFuture,
  reasonChipFor,
  type ScheduleRowInput,
} from "@/lib/domain/schedule-row";

// Layer 1 — S-161 (#273): the /schedules table row shaper (pure, clock-injected).

const NOW = Date.UTC(2026, 9, 13, 10, 0, 0); // 2026-10-13 10:00Z

function base(overrides: Partial<ScheduleRowInput> = {}): ScheduleRowInput {
  return {
    id: "s1",
    state: "active",
    agentName: "Dependency Update",
    agentSlug: "dependency-update",
    repositoryFullName: "llipe/thinkfirst-web",
    repositoryBranch: "main",
    cadence: { kind: "daily", minute: 0, hour: 7 },
    timezone: "America/Santiago",
    nextRunAtMs: NOW + 3 * 3600_000 + 40 * 60_000,
    blockReason: null,
    lastSkippedReason: null,
    prBlockRunId: null,
    lastRunStatus: "succeeded",
    lastRunOutcome: "fixed",
    lastRunFinishedAtMs: NOW - 3600_000,
    lastRunId: "r1",
    ...overrides,
  };
}

describe("formatRelativeFuture", () => {
  it("renders minutes, hours+minutes, tomorrow, and days", () => {
    expect(formatRelativeFuture(NOW + 40 * 60_000, NOW)).toBe("in 40m");
    expect(formatRelativeFuture(NOW + 3 * 3600_000 + 40 * 60_000, NOW)).toBe("in 3h 40m");
    expect(formatRelativeFuture(NOW + 3 * 3600_000, NOW)).toBe("in 3h");
    expect(formatRelativeFuture(NOW + 24 * 3600_000, NOW)).toBe("tomorrow");
    expect(formatRelativeFuture(NOW + 3 * 24 * 3600_000, NOW)).toBe("in 3d");
  });
  it("clamps a past instant to 'due now'", () => {
    expect(formatRelativeFuture(NOW - 1000, NOW)).toBe("due now");
  });
});

describe("buildScheduleCellModel", () => {
  it("active: renders the cadence label, next-run relative+absolute, last-run", () => {
    const m = buildScheduleCellModel(base(), NOW);
    expect(m.statePill).toBe("active");
    expect(m.cadenceText).toBe("Daily · 07:00");
    expect(m.nextRun?.relative).toBe("in 3h 40m");
    expect(m.nextRun?.absolute).toMatch(/10:40/); // 13:40Z = 10:40 Santiago (UTC-3, Oct)
    expect(m.nextRunPlaceholder).toBeNull();
    expect(m.lastRun?.label).toBe("success");
  });

  it("paused: next-run shows the paused placeholder, no next-run block", () => {
    const m = buildScheduleCellModel(base({ state: "paused", blockReason: "manual_pause" }), NOW);
    expect(m.statePill).toBe("paused");
    expect(m.nextRun).toBeNull();
    expect(m.nextRunPlaceholder).toBe("paused");
    expect(m.reason?.glyph).toBe("manual_pause");
  });

  it("blocked by open_pr: held placeholder + a clearable reason chip (G5-c)", () => {
    const m = buildScheduleCellModel(
      base({ state: "blocked", blockReason: "open_pr", prBlockRunId: "r9" }),
      NOW,
    );
    expect(m.statePill).toBe("blocked");
    expect(m.nextRunPlaceholder).toBe("held");
    expect(m.reason?.glyph).toBe("open_pr");
    expect(m.reason?.clearable).toBe(true);
  });

  it("renders no last-run block when the schedule never fired", () => {
    const m = buildScheduleCellModel(base({ lastRunId: null, lastRunStatus: null }), NOW);
    expect(m.lastRun).toBeNull();
  });

  it("maps a reaper timed_out last run to 'timed out'", () => {
    const m = buildScheduleCellModel(
      base({ lastRunStatus: "timed_out", lastRunOutcome: null }),
      NOW,
    );
    expect(m.lastRun?.label).toBe("timed out");
  });

  it("tolerates an invalid timezone without throwing", () => {
    const m = buildScheduleCellModel(base({ timezone: "Not/AZone" }), NOW);
    expect(typeof m.nextRun?.absolute).toBe("string");
  });
});

describe("reasonChipFor", () => {
  it("auto_paused → timeout tone, not clearable", () => {
    const c = reasonChipFor(base({ blockReason: "auto_paused:consecutive_failures" }));
    expect(c?.glyph).toBe("auto_paused");
    expect(c?.clearable).toBe(false);
  });
  it("overlap/concurrency_cap → faint skip chip", () => {
    expect(reasonChipFor(base({ lastSkippedReason: "overlap" }))?.glyph).toBe("skip");
    expect(reasonChipFor(base({ lastSkippedReason: "concurrency_cap" }))?.tone).toBe("faint");
  });
  it("no reason → null", () => {
    expect(reasonChipFor(base())).toBeNull();
  });
});
