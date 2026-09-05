import { describe, expect, it } from "vitest";

import {
  buildRunRow,
  buildRunRows,
  buildAgentHeader,
  shouldRunHistory404,
  type RunRowInput,
  type AgentHeaderInput,
} from "@/lib/domain/run-row";

/**
 * Layer 1 (unit) tests for the run-history row shaper (task 3.2).
 *
 * `lib/domain/run-row.ts` turns the flat `v_runs`-shaped rows into the per-row
 * projection the run-history table renders, and derives the three agent-header
 * metrics (p50 duration, success rate, params count is read off the schema).
 *
 * Load-bearing properties:
 *  - Every displayed status is `effectiveStatus`, never `runs.status` (FR11a).
 *    A stale `running` row must present `timed_out` (AC10 seen from the shaper).
 *  - Duration presents `Xm XXs` for a finished run, `running · Xm` for a live
 *    one, and `—` when there is no duration to show — never `NaN` or `0m 00s`
 *    for a run that never produced a duration.
 *  - `now` is always injected, so a stale row is stale at an instant the test
 *    controls (EC-8).
 */

const T0 = Date.UTC(2026, 0, 1, 12, 0, 0);

// A 900s max_runtime + 60s grace = 960s (16 min) running window.
function run(overrides: Partial<RunRowInput> = {}): RunRowInput {
  return {
    id: "01J8XQ2F3K4M5N6P7Q8R9S0T1U",
    status: "succeeded",
    effectiveStatusFallback: undefined,
    startedAtMs: T0 - 300_000,
    queuedAtMs: T0 - 360_000,
    finishedAtMs: T0 - 60_000,
    createdAtMs: T0 - 360_000,
    durationMs: 184_000, // 3m 04s
    maxRuntimeSeconds: 900,
    graceSeconds: 60,
    startTimeoutSeconds: 300,
    outcome: "fixed",
    repositoryFullName: "llipe/ripley-ingest",
    repositoryBranch: "main",
    stepsDone: 4,
    stepsTotal: 4,
    ...overrides,
  };
}

describe("buildRunRow — status derivation (FR11a)", () => {
  it("passes a terminal status through unchanged", () => {
    const rowSucceeded = buildRunRow(run({ status: "succeeded" }), T0);
    expect(rowSucceeded.effectiveStatus).toBe("succeeded");

    const rowFailed = buildRunRow(run({ status: "failed", outcome: "needs_review" }), T0);
    expect(rowFailed.effectiveStatus).toBe("failed");
  });

  it("derives a stale running row into timed_out (AC10 from the shaper)", () => {
    const stale = run({
      status: "running",
      startedAtMs: T0 - 20 * 60_000, // 20 min ago, 16 min window
      finishedAtMs: null,
      durationMs: null,
      outcome: null,
    });
    expect(buildRunRow(stale, T0).effectiveStatus).toBe("timed_out");
  });

  it("keeps a genuinely fresh running row as running", () => {
    const fresh = run({
      status: "running",
      startedAtMs: T0 - 60_000, // 1 min ago
      finishedAtMs: null,
      durationMs: null,
      outcome: null,
    });
    expect(buildRunRow(fresh, T0).effectiveStatus).toBe("running");
  });

  it("derives a stale queued row into failed_to_start", () => {
    const staleQueued = run({
      status: "queued",
      startedAtMs: null,
      queuedAtMs: T0 - 10 * 60_000, // 10 min ago, 300s window
      finishedAtMs: null,
      durationMs: null,
      outcome: null,
    });
    expect(buildRunRow(staleQueued, T0).effectiveStatus).toBe("failed_to_start");
  });

  it("passes an unknown future status through as a neutral fallback (never throws)", () => {
    const weird = run({ status: "paused" as unknown as RunRowInput["status"] });
    expect(buildRunRow(weird, T0).effectiveStatus).toBe("paused");
  });
});

describe("buildRunRow — duration presentation", () => {
  it("formats a finished run as Xm XXs", () => {
    const row = buildRunRow(run({ durationMs: 184_000 }), T0);
    expect(row.duration).toBe("3m 04s");
  });

  it("formats a live running run as running · Xm from started_at", () => {
    const row = buildRunRow(
      run({
        status: "running",
        startedAtMs: T0 - 2 * 60_000 - 5_000, // 2 min 5 s ago
        finishedAtMs: null,
        durationMs: null,
        outcome: null,
      }),
      T0,
    );
    expect(row.duration).toBe("running · 2m");
  });

  it("shows — when a terminal run carries no duration and no finished_at (never NaN)", () => {
    const row = buildRunRow(
      run({
        status: "failed_to_start",
        startedAtMs: null,
        finishedAtMs: null,
        durationMs: null,
        outcome: null,
      }),
      T0,
    );
    expect(row.duration).toBe("—");
  });

  it("derives duration from finished−started when duration_ms is null but both timestamps exist", () => {
    const row = buildRunRow(
      run({
        durationMs: null,
        startedAtMs: T0 - 184_000 - 60_000,
        finishedAtMs: T0 - 60_000,
      }),
      T0,
    );
    expect(row.duration).toBe("3m 04s");
  });

  it("formats a sub-second finished run as 0m 00s, not empty or NaN", () => {
    const row = buildRunRow(run({ durationMs: 400 }), T0);
    expect(row.duration).toBe("0m 00s");
  });
});

describe("buildRunRow — outcome, steps, repository, time", () => {
  it("maps an outcome to its uppercase label", () => {
    expect(buildRunRow(run({ outcome: "fixed" }), T0).outcomeLabel).toBe("FIXED");
    expect(buildRunRow(run({ outcome: "no_vulnerabilities" }), T0).outcomeLabel).toBe("NO VULNS");
    expect(buildRunRow(run({ outcome: "needs_review" }), T0).outcomeLabel).toBe("NEEDS REVIEW");
    expect(buildRunRow(run({ outcome: "partial" }), T0).outcomeLabel).toBe("PARTIAL");
  });

  it("presents a null outcome as the — fallback (rendered at reduced opacity by the row)", () => {
    const row = buildRunRow(run({ outcome: null }), T0);
    expect(row.outcomeLabel).toBe("—");
    expect(row.hasOutcome).toBe(false);
  });

  it("formats step progress as n/m", () => {
    expect(buildRunRow(run({ stepsDone: 2, stepsTotal: 4 }), T0).steps).toBe("2/4");
    expect(buildRunRow(run({ stepsDone: 0, stepsTotal: 0 }), T0).steps).toBe("0/0");
  });

  it("carries the repository name and branch, and reports absence cleanly (no null/null)", () => {
    const withRepo = buildRunRow(
      run({ repositoryFullName: "llipe/x", repositoryBranch: "main" }),
      T0,
    );
    expect(withRepo.repositoryFullName).toBe("llipe/x");
    expect(withRepo.repositoryBranch).toBe("main");
    expect(withRepo.hasRepository).toBe(true);

    const noRepo = buildRunRow(run({ repositoryFullName: null, repositoryBranch: null }), T0);
    expect(noRepo.hasRepository).toBe(false);
    expect(noRepo.repositoryFullName).toBeNull();
  });

  it("formats the relative start time from started_at, falling back to created_at", () => {
    const started = buildRunRow(run({ startedAtMs: T0 - 14 * 60_000 }), T0);
    expect(started.startedRelative).toBe("14 min ago");

    const neverStarted = buildRunRow(
      run({ status: "failed_to_start", startedAtMs: null, createdAtMs: T0 - 6 * 60 * 60_000 }),
      T0,
    );
    expect(neverStarted.startedRelative).toBe("6h ago");
  });

  it("exposes a short run id for the row link target", () => {
    const row = buildRunRow(run({ id: "01J8XQ2F-3K4M-5N6P" }), T0);
    expect(row.id).toBe("01J8XQ2F-3K4M-5N6P");
    expect(row.shortId).toBe("01J8XQ2F");
  });
});

describe("buildRunRows — ordering", () => {
  it("preserves the newest-first order the query returns (does not re-sort)", () => {
    const rows = buildRunRows(
      [
        run({ id: "newest", createdAtMs: T0 - 60_000 }),
        run({ id: "middle", createdAtMs: T0 - 120_000 }),
        run({ id: "oldest", createdAtMs: T0 - 180_000 }),
      ],
      T0,
    );
    expect(rows.map((r) => r.id)).toEqual(["newest", "middle", "oldest"]);
  });

  it("returns an empty array for zero runs", () => {
    expect(buildRunRows([], T0)).toEqual([]);
  });
});

describe("buildAgentHeader — metrics", () => {
  function header(overrides: Partial<AgentHeaderInput> = {}): AgentHeaderInput {
    return {
      name: "Dependency Update",
      slug: "dependency-update",
      description: "Runs npm audit and opens a PR.",
      paramsCount: 4,
      isEnabled: true,
      runs: [],
      ...overrides,
    };
  }

  it("counts params from the provided count", () => {
    expect(buildAgentHeader(header({ paramsCount: 4 }), T0).paramsCount).toBe(4);
    expect(buildAgentHeader(header({ paramsCount: 0 }), T0).paramsCount).toBe(0);
  });

  it("computes p50 duration with an odd count (the middle element)", () => {
    // durations: 1m, 2m, 3m → median 2m 00s
    const h = header({
      runs: [
        run({ durationMs: 60_000, status: "succeeded" }),
        run({ durationMs: 120_000, status: "succeeded" }),
        run({ durationMs: 180_000, status: "succeeded" }),
      ],
    });
    expect(buildAgentHeader(h, T0).p50Duration).toBe("2m 00s");
  });

  it("computes p50 duration with an even count (lower-mid, deterministic)", () => {
    // durations: 1m, 2m, 3m, 4m → even count; use the lower-mid (2m) deterministically
    const h = header({
      runs: [
        run({ durationMs: 60_000 }),
        run({ durationMs: 120_000 }),
        run({ durationMs: 180_000 }),
        run({ durationMs: 240_000 }),
      ],
    });
    expect(buildAgentHeader(h, T0).p50Duration).toBe("2m 00s");
  });

  it("reports no duration data when no run has a duration", () => {
    const h = header({
      runs: [
        run({
          status: "failed_to_start",
          durationMs: null,
          startedAtMs: null,
          finishedAtMs: null,
          outcome: null,
        }),
      ],
    });
    expect(buildAgentHeader(h, T0).p50Duration).toBeNull();
  });

  it("computes success rate as succeeded / total, rounded to a whole percent", () => {
    // 3 succeeded of 4 total = 75%
    const h = header({
      runs: [
        run({ status: "succeeded" }),
        run({ status: "succeeded" }),
        run({ status: "succeeded" }),
        run({ status: "failed", outcome: "needs_review" }),
      ],
    });
    expect(buildAgentHeader(h, T0).successRate).toBe(75);
  });

  it("counts a stale running run as timed_out (not success) in the success rate (FR11a)", () => {
    // 1 succeeded, 1 stale running (→ timed_out) → 50%
    const h = header({
      runs: [
        run({ status: "succeeded" }),
        run({
          status: "running",
          startedAtMs: T0 - 20 * 60_000,
          finishedAtMs: null,
          durationMs: null,
          outcome: null,
        }),
      ],
    });
    expect(buildAgentHeader(h, T0).successRate).toBe(50);
  });

  it("returns a null success rate for zero runs (never NaN)", () => {
    const h = buildAgentHeader(header({ runs: [] }), T0);
    expect(h.successRate).toBeNull();
    expect(h.p50Duration).toBeNull();
    expect(h.runCount).toBe(0);
  });
});

describe("shouldRunHistory404 — route guard (task 3.9)", () => {
  it("404s for an unknown slug (null agent)", () => {
    expect(shouldRunHistory404(null)).toBe(true);
  });

  it("404s for a disabled agent — not an empty list", () => {
    expect(shouldRunHistory404({ is_enabled: false })).toBe(true);
  });

  it("does NOT 404 for an enabled agent", () => {
    expect(shouldRunHistory404({ is_enabled: true })).toBe(false);
  });
});
