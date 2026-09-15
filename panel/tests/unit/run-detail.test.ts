import { describe, expect, it } from "vitest";

import {
  selectBanner,
  buildLogLines,
  buildSummary,
  buildStepsPanel,
  type SummaryInput,
  type LogEventInput,
  type RunStepInput,
} from "@/lib/domain/run-detail";
import type { RunStatus } from "@/lib/domain/status";

/**
 * Layer 1 (unit) — run-detail presentation logic (test-plan SC-2/6/7/10/11/12, RT-4).
 *
 * `lib/domain/run-detail.ts` is the pure layer under the run-detail screen:
 *  - `selectBanner(status)` — a TOTAL function of status: a §8.3 banner for
 *    `timed_out` / `failed_to_start`, and null for every other status (RT-4).
 *  - `buildLogLines(events, steps, tz)` — projects `run_events` into the
 *    LogLine grid, labeling each line with its step title/key via `step_id`,
 *    and formatting the clock. Never truncates the message.
 *  - `buildSummary(run)` — derives the summary status through `effectiveStatus`
 *    (never the raw column), the short run id, and the metadata fields.
 */

const T0 = Date.UTC(2026, 0, 1, 14, 2, 13);

describe("selectBanner — total function of status (RT-4)", () => {
  it("returns a banner for timed_out", () => {
    const b = selectBanner("timed_out");
    expect(b).not.toBeNull();
    expect(b!.status).toBe("timed_out");
  });

  it("returns a banner for failed_to_start", () => {
    const b = selectBanner("failed_to_start");
    expect(b).not.toBeNull();
    expect(b!.status).toBe("failed_to_start");
  });

  it("returns null for every non-terminal-reaper status", () => {
    const noBanner: (RunStatus | string)[] = [
      "queued",
      "running",
      "succeeded",
      "failed",
      "canceled",
    ];
    for (const s of noBanner) {
      expect(selectBanner(s)).toBeNull();
    }
  });

  it("returns null for an unknown future status (never throws)", () => {
    expect(selectBanner("paused")).toBeNull();
  });
});

describe("buildLogLines — projection + step labeling", () => {
  const steps = [
    { id: "step-1", key: "checkout", title: "Checkout" },
    { id: "step-2", key: "npm_audit", title: null },
  ];

  function event(overrides: Partial<LogEventInput> = {}): LogEventInput {
    return {
      id: 1,
      seq: 1,
      ts: new Date(T0).toISOString(),
      level: "info",
      message: "hello",
      stepId: "step-1",
      ...overrides,
    };
  }

  it("labels a line with the step title when present", () => {
    const [line] = buildLogLines([event({ stepId: "step-1" })], steps, "UTC");
    expect(line.step).toBe("Checkout");
  });

  it("falls back to the step key when the title is null", () => {
    const [line] = buildLogLines([event({ stepId: "step-2" })], steps, "UTC");
    expect(line.step).toBe("npm_audit");
  });

  it("leaves the step blank for a null step_id (SC-7, no 'undefined')", () => {
    const [line] = buildLogLines([event({ stepId: null })], steps, "UTC");
    expect(line.step).toBe("");
  });

  it("leaves the step blank for an unresolvable step_id", () => {
    const [line] = buildLogLines([event({ stepId: "ghost" })], steps, "UTC");
    expect(line.step).toBe("");
  });

  it("formats the clock as HH:MM:SS (UTC)", () => {
    const [line] = buildLogLines([event()], steps, "UTC");
    expect(line.timestamp).toBe("14:02:13");
  });

  it("carries the level and the full message verbatim (never truncated)", () => {
    const big = "x".repeat(8 * 1024);
    const [line] = buildLogLines([event({ level: "error", message: big })], steps, "UTC");
    expect(line.level).toBe("error");
    expect(line.message).toBe(big);
    expect(line.message.length).toBe(8 * 1024);
  });

  it("keeps a message with HTML as a raw string (rendering renders it inert; SC-13)", () => {
    const payload = "<script>alert(1)</script>";
    const [line] = buildLogLines([event({ message: payload })], steps, "UTC");
    // The domain layer does not escape — it carries the raw string; the React
    // component renders it as a text node (inert). The property here is only
    // that the string is not mangled.
    expect(line.message).toBe(payload);
  });

  it("preserves the given order (events arrive pre-sorted by the caller)", () => {
    const lines = buildLogLines(
      [event({ id: 1, seq: 1, message: "a" }), event({ id: 2, seq: 2, message: "b" })],
      steps,
      "UTC",
    );
    expect(lines.map((l) => l.message)).toEqual(["a", "b"]);
  });

  it("returns [] for zero events", () => {
    expect(buildLogLines([], steps, "UTC")).toEqual([]);
  });
});

describe("buildSummary — derived status + metadata", () => {
  function summaryInput(overrides: Partial<SummaryInput> = {}): SummaryInput {
    return {
      id: "01J8XQ2F-3K4M-5N6P-7Q8R-9S0T1U2V3W4X",
      status: "succeeded",
      startedAtMs: T0 - 300_000,
      queuedAtMs: T0 - 360_000,
      finishedAtMs: T0 - 60_000,
      durationMs: 184_000,
      maxRuntimeSeconds: 900,
      graceSeconds: 60,
      startTimeoutSeconds: 300,
      outcome: "fixed",
      repositoryFullName: "llipe/ripley-ingest",
      branch: "main",
      errorMessage: null,
      ...overrides,
    };
  }

  it("derives status through effectiveStatus (SC-2: stale running → timed_out)", () => {
    const s = buildSummary(
      summaryInput({
        status: "running",
        startedAtMs: T0 - 20 * 60_000,
        finishedAtMs: null,
        durationMs: null,
        outcome: null,
      }),
      T0,
    );
    expect(s.effectiveStatus).toBe("timed_out");
  });

  it("passes a terminal status through unchanged", () => {
    expect(buildSummary(summaryInput({ status: "failed" }), T0).effectiveStatus).toBe("failed");
  });

  it("renders the short uppercase run id", () => {
    expect(buildSummary(summaryInput(), T0).shortId).toBe("01J8XQ2F");
  });

  it("formats a finished duration and shows a dash when there is none (SC-3)", () => {
    expect(buildSummary(summaryInput({ durationMs: 184_000 }), T0).duration).toBe("3m 04s");
    const noDur = buildSummary(
      summaryInput({
        status: "failed_to_start",
        startedAtMs: null,
        finishedAtMs: null,
        durationMs: null,
        outcome: null,
      }),
      T0,
    );
    expect(noDur.duration).toBe("—");
  });

  it("carries the repository, branch, and outcome label; reports absence cleanly", () => {
    const s = buildSummary(summaryInput({ repositoryFullName: null, branch: null }), T0);
    expect(s.hasRepository).toBe(false);
    expect(s.repositoryFullName).toBeNull();

    const withRepo = buildSummary(summaryInput({ outcome: "no_vulnerabilities" }), T0);
    expect(withRepo.outcomeLabel).toBe("NO VULNS");
    expect(withRepo.repositoryFullName).toBe("llipe/ripley-ingest");
  });

  it("formats queued/started/finished clocks, with a dash for null timestamps", () => {
    const s = buildSummary(summaryInput({ finishedAtMs: null }), T0, "UTC");
    expect(s.finishedClock).toBe("—");
    // T0 = 14:02:13; queued_at = T0 - 360_000 ms (6 min) = 13:56:13.
    expect(s.queuedClock).toBe("13:56:13");
    // started_at = T0 - 300_000 ms (5 min) = 13:57:13.
    expect(s.startedClock).toBe("13:57:13");
  });
});

// ---------------------------------------------------------------------------
// buildStepsPanel (Story S-145, FR9)
// ---------------------------------------------------------------------------

describe("buildStepsPanel — steps panel projection (FR9)", () => {
  function stepInput(overrides: Partial<RunStepInput> = {}): RunStepInput {
    return {
      id: "step-1",
      key: "checkout",
      title: "Checkout",
      status: "succeeded",
      startedAtMs: T0 - 10_000,
      finishedAtMs: T0 - 4_000,
      ...overrides,
    };
  }

  it("maps each run_steps row to a panel row (dot status, name, duration, event count)", () => {
    const [row] = buildStepsPanel([stepInput()], { "step-1": 12 });
    expect(row.id).toBe("step-1");
    expect(row.title).toBe("Checkout");
    expect(row.status).toBe("succeeded");
    expect(row.duration).toBe("6s");
    expect(row.eventCount).toBe(12);
  });

  it("falls back to the step key when the title is null (reuses buildLogLines' label rule)", () => {
    const [row] = buildStepsPanel([stepInput({ title: null, key: "npm_audit" })], {});
    expect(row.title).toBe("npm_audit");
  });

  it("reuses lib/format.ts duration formatting (Xm XXs for >= 60s)", () => {
    const [row] = buildStepsPanel([stepInput({ startedAtMs: T0 - 184_000, finishedAtMs: T0 })], {});
    expect(row.duration).toBe("3m 04s");
  });

  it("a zero-event step reports event count 0, not undefined/NaN (edge case)", () => {
    const [row] = buildStepsPanel([stepInput({ id: "step-2" })], {});
    expect(row.eventCount).toBe(0);
  });

  it("an in-progress step with no finished_at shows a dash duration, not a crash", () => {
    const [row] = buildStepsPanel(
      [stepInput({ status: "running", startedAtMs: T0 - 5_000, finishedAtMs: null })],
      { "step-1": 3 },
    );
    expect(row.duration).toBe("—");
    expect(row.status).toBe("running");
  });

  it("a step never started (no started_at) also shows a dash duration", () => {
    const [row] = buildStepsPanel(
      [stepInput({ status: "pending", startedAtMs: null, finishedAtMs: null })],
      {},
    );
    expect(row.duration).toBe("—");
  });

  it("returns [] for a zero-step run — an empty panel, not an error (edge case)", () => {
    expect(buildStepsPanel([], {})).toEqual([]);
  });

  it("preserves the given step order (caller provides seq-ordered steps)", () => {
    const rows = buildStepsPanel(
      [stepInput({ id: "s1", key: "a" }), stepInput({ id: "s2", key: "b" })],
      {},
    );
    expect(rows.map((r) => r.id)).toEqual(["s1", "s2"]);
  });

  it("CT-5: the sum of per-step counts never exceeds the total window (a partition, not an independent count)", () => {
    const windowTotal = 10;
    const rows = buildStepsPanel([stepInput({ id: "s1" }), stepInput({ id: "s2" })], {
      s1: 6,
      s2: 4,
    });
    const sum = rows.reduce((acc, r) => acc + r.eventCount, 0);
    expect(sum).toBeLessThanOrEqual(windowTotal);
  });
});
