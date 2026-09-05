import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { RunHistoryTable } from "@/components/runs/RunHistoryTable";
import { buildRunRows, buildRunRow, type RunRowInput } from "@/lib/domain/run-row";

/**
 * Edge-case coverage for the run-history screen (S-108 / issue #121, task 3.16).
 *
 * Cases: zero runs; single run; `finished_at` null with a terminal status;
 * zero steps (`0/0`); sub-second duration; a `canceled` status (never written
 * in v1) rendering as a neutral fallback rather than crashing.
 *
 * The unknown-slug / disabled-agent → 404 cases live at the page level (a
 * server component calling `notFound()`); they are exercised by the Layer 2.5
 * read path (an unknown slug returns no agent) and asserted directly in
 * `run-history-page.test.ts` against the extracted guard. Here we cover the
 * presentational edges the shaper + table own.
 */

const NOW = Date.UTC(2026, 0, 1, 12, 0, 0);

function run(overrides: Partial<RunRowInput> = {}): RunRowInput {
  return {
    id: "01J8XQ2F3K4M5N6P7Q8R9S0T1U",
    status: "succeeded",
    startedAtMs: NOW - 300_000,
    queuedAtMs: NOW - 360_000,
    finishedAtMs: NOW - 60_000,
    createdAtMs: NOW - 360_000,
    durationMs: 184_000,
    maxRuntimeSeconds: 900,
    graceSeconds: 60,
    startTimeoutSeconds: 300,
    outcome: "fixed",
    repositoryFullName: "llipe/x",
    repositoryBranch: "main",
    stepsDone: 4,
    stepsTotal: 4,
    ...overrides,
  };
}

describe("run-history edge cases — table sizes", () => {
  it("renders the empty state for zero runs (no table)", () => {
    render(<RunHistoryTable rows={[]} invokeHref={null} />);
    expect(screen.queryByRole("table")).toBeNull();
    expect(screen.getByText(/no runs yet/i)).toBeInTheDocument();
  });

  it("renders a single run as one body row", () => {
    render(<RunHistoryTable rows={buildRunRows([run({ id: "only" })], NOW)} invokeHref={null} />);
    expect(screen.getByRole("table")).toBeInTheDocument();
    expect(screen.getByText("succeeded")).toBeInTheDocument();
  });
});

describe("run-history edge cases — duration / steps", () => {
  it("shows — when a terminal run has finished_at null and no duration (never NaN)", () => {
    const row = buildRunRow(
      run({
        status: "failed_to_start",
        startedAtMs: null,
        finishedAtMs: null,
        durationMs: null,
        outcome: null,
      }),
      NOW,
    );
    expect(row.duration).toBe("—");
  });

  it("renders 0/0 for a run with zero steps", () => {
    render(
      <RunHistoryTable rows={buildRunRows([run({ stepsDone: 0, stepsTotal: 0 })], NOW)} invokeHref={null} />,
    );
    expect(screen.getByText("0/0")).toBeInTheDocument();
  });

  it("renders a sub-second finished run as 0m 00s, not empty or NaN", () => {
    render(<RunHistoryTable rows={buildRunRows([run({ durationMs: 400 })], NOW)} invokeHref={null} />);
    expect(screen.getByText("0m 00s")).toBeInTheDocument();
  });
});

describe("run-history edge cases — unusual status", () => {
  it("renders a canceled run with a neutral fallback (never written in v1, must not crash)", () => {
    render(
      <RunHistoryTable
        rows={buildRunRows(
          [run({ id: "c", status: "canceled", outcome: null, durationMs: 120_000 })],
          NOW,
        )}
        invokeHref={null}
      />,
    );
    // status-meta maps canceled to a neutral label; it renders as "canceled".
    expect(screen.getByText("canceled")).toBeInTheDocument();
    expect(document.body.textContent).not.toMatch(/NaN|undefined/);
  });

  it("passes an unknown future status through as its own label (EC-20)", () => {
    const row = buildRunRow(run({ status: "paused" as unknown as RunRowInput["status"] }), NOW);
    expect(row.effectiveStatus).toBe("paused");
  });
});
