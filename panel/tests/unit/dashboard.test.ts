import { describe, expect, it } from "vitest";

import {
  buildAgentSummaries,
  filterAgentSummaries,
  matchesQuery,
  type AgentSummaryInput,
  type DashboardRun,
} from "@/lib/domain/dashboard";

/**
 * Layer 1 (unit) tests for the dashboard aggregation shaper (task 2.2 / 2.12a).
 *
 * The shaper turns the flat `v_runs`-shaped rows the query returns into one
 * per-agent summary each variant renders. The load-bearing property is CT-1:
 * every displayed status — INCLUDING the aggregate breakdown — is the
 * `effectiveStatus` derivation, never the raw `runs.status`. A stale `running`
 * row must land in the `timed_out` bucket, not the `running` one, or a row
 * reads `timed_out` while the count above it reads `running` (the invisible
 * FR11a violation this shaper exists to prevent).
 *
 * `now` is always injected so a stale row is stale at an instant the test
 * controls (EC-8 / EC-4).
 */

const T0 = Date.UTC(2026, 0, 1, 12, 0, 0);

// A 900s max_runtime + 60s grace = 960s running window; a 300s queue window.
function run(overrides: Partial<DashboardRun> = {}): DashboardRun {
  return {
    status: "succeeded",
    startedAtMs: T0 - 300_000,
    queuedAtMs: T0 - 360_000,
    finishedAtMs: T0 - 60_000,
    createdAtMs: T0 - 360_000,
    maxRuntimeSeconds: 900,
    graceSeconds: 60,
    startTimeoutSeconds: 300,
    outcome: "no_vulnerabilities",
    ...overrides,
  };
}

function agent(overrides: Partial<AgentSummaryInput> = {}): AgentSummaryInput {
  return {
    id: "a1",
    slug: "dependency-update",
    name: "Dependency Update",
    description: "Runs npm audit and opens a PR.",
    requiresRepository: true,
    runs: [],
    ...overrides,
  };
}

describe("buildAgentSummaries — run count and shape", () => {
  it("returns one summary per agent, preserving identity fields", () => {
    const summaries = buildAgentSummaries(
      [agent({ id: "a1", slug: "dependency-update", name: "Dependency Update" })],
      T0,
    );
    expect(summaries).toHaveLength(1);
    const s = summaries[0];
    expect(s.id).toBe("a1");
    expect(s.slug).toBe("dependency-update");
    expect(s.name).toBe("Dependency Update");
    expect(s.description).toBe("Runs npm audit and opens a PR.");
    expect(s.runCount).toBe(0);
  });

  it("counts every run", () => {
    const summaries = buildAgentSummaries(
      [agent({ runs: [run(), run(), run({ status: "failed", outcome: null })] })],
      T0,
    );
    expect(summaries[0].runCount).toBe(3);
  });
});

describe("buildAgentSummaries — status breakdown counts effective_status (CT-1)", () => {
  it("buckets a mix of terminal statuses", () => {
    const summaries = buildAgentSummaries(
      [
        agent({
          runs: [
            run({ status: "succeeded" }),
            run({ status: "succeeded" }),
            run({ status: "failed", outcome: null }),
          ],
        }),
      ],
      T0,
    );
    const b = summaries[0].breakdown;
    expect(b.succeeded).toBe(2);
    expect(b.failed).toBe(1);
    expect(b.timed_out).toBe(0);
    expect(b.running).toBe(0);
  });

  it("derives a stale running row into the timed_out bucket, NOT running (CT-1)", () => {
    // started_at 20 min before now, window is 16 min → past threshold.
    const stale = run({
      status: "running",
      startedAtMs: T0 - 20 * 60_000,
      finishedAtMs: null,
      outcome: null,
    });
    // a genuinely fresh running run (started 1 min ago) stays running.
    const fresh = run({
      status: "running",
      startedAtMs: T0 - 60_000,
      finishedAtMs: null,
      outcome: null,
    });
    const summaries = buildAgentSummaries(
      [
        agent({
          runs: [
            run({ status: "succeeded" }),
            run({ status: "succeeded" }),
            run({ status: "failed", outcome: null }),
            fresh,
            stale,
          ],
        }),
      ],
      T0,
    );
    const b = summaries[0].breakdown;
    // The exact assertion CT-1 names: running is exactly 1, timed_out exactly 1.
    expect(b.running).toBe(1);
    expect(b.timed_out).toBe(1);
    expect(b.succeeded).toBe(2);
    expect(b.failed).toBe(1);
  });

  it("never re-derives a terminal succeeded run even with an ancient started_at (EC-4)", () => {
    const ancient = run({
      status: "succeeded",
      startedAtMs: T0 - 365 * 24 * 60 * 60_000, // a year ago
      finishedAtMs: T0 - 365 * 24 * 60 * 60_000 + 60_000,
    });
    const summaries = buildAgentSummaries([agent({ runs: [ancient] })], T0);
    expect(summaries[0].breakdown.succeeded).toBe(1);
    expect(summaries[0].breakdown.timed_out).toBe(0);
  });

  it("derives a stale queued row into failed_to_start", () => {
    const staleQueued = run({
      status: "queued",
      startedAtMs: null,
      queuedAtMs: T0 - 10 * 60_000, // 10 min ago, 300s window
      finishedAtMs: null,
      outcome: null,
    });
    const summaries = buildAgentSummaries([agent({ runs: [staleQueued] })], T0);
    expect(summaries[0].breakdown.failed_to_start).toBe(1);
    expect(summaries[0].breakdown.queued).toBe(0);
  });

  it("provides ok/fail/timeout legend buckets aligned with formatStatusLegend", () => {
    const summaries = buildAgentSummaries(
      [
        agent({
          runs: [
            run({ status: "succeeded" }),
            run({ status: "succeeded" }),
            run({ status: "failed", outcome: null }),
            run({
              status: "running",
              startedAtMs: T0 - 20 * 60_000,
              finishedAtMs: null,
              outcome: null,
            }),
          ],
        }),
      ],
      T0,
    );
    const legend = summaries[0].legend;
    expect(legend.ok).toBe(2);
    expect(legend.fail).toBe(1);
    expect(legend.timeout).toBe(1);
  });
});

describe("buildAgentSummaries — last run", () => {
  it("selects the newest run by createdAt as the last run", () => {
    const older = run({ createdAtMs: T0 - 10 * 60_000, status: "failed", outcome: null });
    const newer = run({
      createdAtMs: T0 - 60_000,
      status: "succeeded",
      outcome: "fixed",
      finishedAtMs: T0 - 30_000,
    });
    const summaries = buildAgentSummaries([agent({ runs: [older, newer] })], T0);
    const last = summaries[0].lastRun;
    expect(last).not.toBeNull();
    expect(last?.effectiveStatus).toBe("succeeded");
    expect(last?.outcome).toBe("fixed");
    // last-run timestamp is the newest run's finished (fallback started/created)
    expect(last?.atMs).toBe(T0 - 30_000);
  });

  it("last run derives effective_status too (a stale running last run reads timed_out)", () => {
    const stale = run({
      createdAtMs: T0 - 60_000,
      status: "running",
      startedAtMs: T0 - 20 * 60_000,
      finishedAtMs: null,
      outcome: null,
    });
    const summaries = buildAgentSummaries([agent({ runs: [stale] })], T0);
    expect(summaries[0].lastRun?.effectiveStatus).toBe("timed_out");
  });

  it("uses started_at, then created_at, when finished_at is null", () => {
    const running = run({
      createdAtMs: T0 - 5 * 60_000,
      status: "running",
      startedAtMs: T0 - 2 * 60_000,
      finishedAtMs: null,
      outcome: null,
    });
    const summaries = buildAgentSummaries([agent({ runs: [running] })], T0);
    expect(summaries[0].lastRun?.atMs).toBe(T0 - 2 * 60_000);
  });

  it("last run is null for an agent with zero runs (empty-state safety, EC-19)", () => {
    const summaries = buildAgentSummaries([agent({ runs: [] })], T0);
    expect(summaries[0].lastRun).toBeNull();
    expect(summaries[0].runCount).toBe(0);
    // breakdown is all-zero, never NaN
    expect(Object.values(summaries[0].breakdown).every((n) => n === 0)).toBe(true);
  });
});

describe("buildAgentSummaries — recent runs for the RunStrip", () => {
  it("exposes recent runs newest-last, capped, each carrying its effective status", () => {
    const runs = Array.from({ length: 30 }, (_, i) =>
      run({ createdAtMs: T0 - (30 - i) * 60_000, status: "succeeded" }),
    );
    const summaries = buildAgentSummaries([agent({ runs })], T0, { recentLimit: 24 });
    const recent = summaries[0].recentRuns;
    expect(recent).toHaveLength(24);
    // newest-last: the last element is the most-recently created
    expect(recent[recent.length - 1].createdAtMs).toBe(T0 - 60_000);
    expect(recent[0].effectiveStatus).toBe("succeeded");
  });
});

describe("matchesQuery / filterAgentSummaries (AC-107.8, EC-25)", () => {
  const summaries = buildAgentSummaries(
    [
      agent({ id: "a1", slug: "dependency-update", name: "Dependency Update" }),
      agent({ id: "a2", slug: "secret-scan", name: "Secret Scanner" }),
    ],
    T0,
  );

  it("matches on name, case-insensitively", () => {
    expect(matchesQuery(summaries[0], "dependency")).toBe(true);
    expect(matchesQuery(summaries[0], "DEPENDENCY")).toBe(true);
    expect(matchesQuery(summaries[1], "scanner")).toBe(true);
  });

  it("matches on slug, case-insensitively", () => {
    expect(matchesQuery(summaries[1], "secret-scan")).toBe(true);
    expect(matchesQuery(summaries[1], "SECRET")).toBe(true);
  });

  it("treats a whitespace-only query as empty (matches everything)", () => {
    expect(matchesQuery(summaries[0], "   ")).toBe(true);
    expect(filterAgentSummaries(summaries, "   ")).toHaveLength(2);
    expect(filterAgentSummaries(summaries, "")).toHaveLength(2);
  });

  it("treats regex metacharacters literally, never constructing a RegExp", () => {
    expect(matchesQuery(summaries[0], ".*")).toBe(false);
    expect(matchesQuery(summaries[0], "[")).toBe(false);
    expect(matchesQuery(summaries[0], "\\")).toBe(false);
    // a literal substring that happens to exist still matches
    expect(matchesQuery(summaries[0], "-update")).toBe(true);
  });

  it("returns no matches for a non-existent query and for a very long string", () => {
    expect(filterAgentSummaries(summaries, "zzz")).toHaveLength(0);
    expect(filterAgentSummaries(summaries, "x".repeat(500))).toHaveLength(0);
  });

  it("trims surrounding whitespace before matching", () => {
    expect(matchesQuery(summaries[0], "  dependency  ")).toBe(true);
  });
});
