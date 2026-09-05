import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { RunHistoryTable } from "@/components/runs/RunHistoryTable";
import { AgentHeader } from "@/components/runs/AgentHeader";
import {
  buildRunRows,
  buildAgentHeader,
  type RunRowInput,
  type AgentHeaderInput,
} from "@/lib/domain/run-row";

/**
 * Layer 2 component tests for the run-history screen (S-108 / issue #121).
 *
 * Covers: the table is semantic `<table>` markup (AC — spec §10), rows render
 * every status through the derived `effective_status` (AC3), a live running
 * run shows `running · Xm` (AC2), a missing repository renders cleanly (no
 * `null/null`, EC), and the empty state renders the invoke CTA (AC6). The
 * header renders the breadcrumb + the three metadata values, and the zero-run
 * header presents legible copy, never `NaN`.
 *
 * next/navigation is not mocked: these components use next/link (rendered
 * anchors), not the router, so there is nothing to intercept.
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
    repositoryFullName: "llipe/ripley-ingest",
    repositoryBranch: "main",
    stepsDone: 4,
    stepsTotal: 4,
    ...overrides,
  };
}

function renderTable(inputs: RunRowInput[], invokeHref: string | null = null) {
  return render(<RunHistoryTable rows={buildRunRows(inputs, NOW)} invokeHref={invokeHref} />);
}

describe("RunHistoryTable — semantic markup (spec §10)", () => {
  it("renders a real <table> with a labeled accessible name", () => {
    renderTable([run()]);
    const table = screen.getByRole("table", { name: /run history/i });
    expect(table.tagName).toBe("TABLE");
  });

  it("renders the six documented column headers", () => {
    renderTable([run()]);
    const table = screen.getByRole("table", { name: /run history/i });
    for (const col of ["Status", "Outcome", "Repository", "Duration", "Steps", "Started"]) {
      expect(within(table).getByRole("columnheader", { name: col })).toBeInTheDocument();
    }
  });

  it("renders one row per run in the order given (newest-first, not re-sorted)", () => {
    renderTable([
      run({ id: "r-new", repositoryFullName: "llipe/aaa", createdAtMs: NOW - 60_000 }),
      run({ id: "r-old", repositoryFullName: "llipe/zzz", createdAtMs: NOW - 600_000 }),
    ]);
    const bodyRows = screen.getAllByRole("row").filter((r) => within(r).queryByText(/llipe\//));
    expect(within(bodyRows[0]).getByText("llipe/aaa")).toBeInTheDocument();
    expect(within(bodyRows[1]).getByText("llipe/zzz")).toBeInTheDocument();
  });
});

describe("RunHistoryTable — status derivation (AC3 / FR11a)", () => {
  it("renders each terminal status as its own pill", () => {
    renderTable([
      run({ id: "s", status: "succeeded" }),
      run({ id: "f", status: "failed", outcome: "needs_review" }),
      run({ id: "t", status: "timed_out", outcome: "partial", durationMs: 900_000 }),
      run({
        id: "x",
        status: "failed_to_start",
        outcome: null,
        startedAtMs: null,
        finishedAtMs: null,
        durationMs: null,
      }),
    ]);
    expect(screen.getByText("succeeded")).toBeInTheDocument();
    expect(screen.getByText("failed")).toBeInTheDocument();
    expect(screen.getByText("timed out")).toBeInTheDocument();
    expect(screen.getByText("failed to start")).toBeInTheDocument();
  });

  it("shows timed_out (not running) for a stale running row — the AC10 property in the UI", () => {
    renderTable([
      run({
        id: "stale",
        status: "running",
        startedAtMs: NOW - 20 * 60_000, // 20 min ago, 16 min window
        finishedAtMs: null,
        durationMs: null,
        outcome: null,
      }),
    ]);
    expect(screen.getByText("timed out")).toBeInTheDocument();
    expect(screen.queryByText(/^running$/)).toBeNull();
  });
});

describe("RunHistoryTable — duration presentation (AC2)", () => {
  it("shows running · Xm for a live running run", () => {
    renderTable([
      run({
        id: "live",
        status: "running",
        startedAtMs: NOW - 2 * 60_000 - 5_000,
        finishedAtMs: null,
        durationMs: null,
        outcome: null,
      }),
    ]);
    expect(screen.getByText("running · 2m")).toBeInTheDocument();
  });

  it("shows Xm XXs for a finished run", () => {
    renderTable([run({ durationMs: 184_000 })]);
    expect(screen.getByText("3m 04s")).toBeInTheDocument();
  });
});

describe("RunHistoryTable — repository + outcome fallbacks (EC)", () => {
  it("renders a missing repository as a clean — (never null/null)", () => {
    renderTable([
      run({
        id: "norepo",
        repositoryFullName: null,
        repositoryBranch: null,
      }),
    ]);
    expect(screen.getByRole("table").textContent).not.toMatch(/null/);
  });

  it("renders a null outcome as the — pending marker, not a tag", () => {
    renderTable([
      run({
        id: "noout",
        status: "running",
        startedAtMs: NOW - 60_000,
        finishedAtMs: null,
        durationMs: null,
        outcome: null,
      }),
    ]);
    expect(screen.getByLabelText(/no outcome yet/i)).toBeInTheDocument();
  });

  it("renders the branch alongside the repository when present", () => {
    renderTable([run({ repositoryFullName: "llipe/x", repositoryBranch: "release/24.8" })]);
    expect(screen.getByText("llipe/x")).toBeInTheDocument();
    expect(screen.getByText("release/24.8")).toBeInTheDocument();
  });

  it("links each row to /runs/[id]", () => {
    renderTable([run({ id: "abc-123" })]);
    const link = screen.getByRole("link", { name: /open run/i });
    expect(link).toHaveAttribute("href", "/runs/abc-123");
  });
});

describe("RunHistoryTable — empty state (AC6)", () => {
  it("renders a no-runs message with a disabled Invoke CTA when the route is unbuilt", () => {
    render(<RunHistoryTable rows={[]} invokeHref={null} />);
    expect(screen.getByText(/no runs yet/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /invoke on one repo/i })).toBeDisabled();
    // No table rendered in the empty state.
    expect(screen.queryByRole("table")).toBeNull();
  });

  it("renders an enabled Invoke link when the route is available", () => {
    render(<RunHistoryTable rows={[]} invokeHref="/agents/dependency-update/invoke" />);
    expect(screen.getByRole("link", { name: /invoke on one repo/i })).toHaveAttribute(
      "href",
      "/agents/dependency-update/invoke",
    );
  });
});

describe("AgentHeader — metadata + breadcrumb (AC5)", () => {
  function header(overrides: Partial<AgentHeaderInput> = {}): AgentHeaderInput {
    return {
      name: "Dependency Update",
      slug: "dependency-update",
      description: "Runs npm audit and opens a PR.",
      paramsCount: 4,
      isEnabled: true,
      runs: [
        run(),
        run({ durationMs: 120_000 }),
        run({ status: "failed", outcome: "needs_review" }),
      ],
      ...overrides,
    };
  }

  it("renders the breadcrumb agents / <slug>", () => {
    render(<AgentHeader header={buildAgentHeader(header(), NOW)} invokeHref={null} />);
    const crumb = screen.getByRole("navigation", { name: /breadcrumb/i });
    expect(within(crumb).getByText("agents")).toBeInTheDocument();
    expect(within(crumb).getByText("dependency-update")).toBeInTheDocument();
  });

  it("renders the three metadata values with real numbers", () => {
    render(<AgentHeader header={buildAgentHeader(header(), NOW)} invokeHref={null} />);
    expect(screen.getByText(/4 params/)).toBeInTheDocument();
    expect(screen.getByText(/p50/)).toBeInTheDocument();
    expect(screen.getByText(/% success/)).toBeInTheDocument();
  });

  it("shows the ENABLED tag for an enabled agent and DISABLED otherwise", () => {
    const { rerender } = render(
      <AgentHeader header={buildAgentHeader(header({ isEnabled: true }), NOW)} invokeHref={null} />,
    );
    expect(screen.getByText("ENABLED")).toBeInTheDocument();
    rerender(
      <AgentHeader
        header={buildAgentHeader(header({ isEnabled: false }), NOW)}
        invokeHref={null}
      />,
    );
    expect(screen.getByText("DISABLED")).toBeInTheDocument();
  });

  it("renders legible copy (no NaN) for a zero-run agent", () => {
    render(<AgentHeader header={buildAgentHeader(header({ runs: [] }), NOW)} invokeHref={null} />);
    expect(screen.getByText(/no duration data/i)).toBeInTheDocument();
    expect(screen.getByText(/no runs yet/i)).toBeInTheDocument();
    // The header block must not contain NaN anywhere.
    expect(document.body.textContent).not.toMatch(/NaN/);
  });
});
