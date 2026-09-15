import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { RunHistoryRow } from "@/components/runs/RunHistoryRow";
import { buildRunRow, type RunRowInput } from "@/lib/domain/run-row";

/**
 * Component tests for the run-history row's inline PR link (Story S-144,
 * issue #204).
 *
 * Branch display is unchanged (already covered by
 * `panel/tests/component/run-history.test.tsx`); these tests cover only the
 * new PR-link half of the repository cell:
 *
 *  - AC1: a run with a `pull_request` artifact renders a clickable inline
 *    link to that PR.
 *  - AC2: a run with no `pull_request` artifact renders the existing
 *    branch-only markup, unchanged — no link, no inert placeholder either.
 *  - AC4 (edge case): an unsafe URL (`javascript:`/relative) renders inert
 *    text, never an `<a href>` — reusing `isSafeArtifactUrl` (S-109), matching
 *    Run Detail's existing `ArtifactLinks` behavior. No new URL-safety test
 *    is added here; `artifact-url.test.ts` already covers the guard itself.
 *
 * `RunHistoryRow` renders a `<tr>`, so it needs a `<table><tbody>` wrapper for
 * valid markup / correct ARIA table-row semantics (same pattern as the
 * existing `RunHistoryTable` tests).
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

function renderRow(overrides: Partial<RunRowInput> = {}, showAgentColumn = false) {
  const row = buildRunRow(run(overrides), NOW);
  return render(
    <table>
      <tbody>
        <RunHistoryRow row={row} showAgentColumn={showAgentColumn} />
      </tbody>
    </table>,
  );
}

describe("RunHistoryRow — inline PR link (AC1)", () => {
  it("renders a clickable link to the PR when a safe https URL is present", () => {
    renderRow({ pullRequestUrl: "https://github.com/llipe/ripley-ingest/pull/42" });
    const link = screen.getByRole("link", { name: /pr/i });
    expect(link).toHaveAttribute("href", "https://github.com/llipe/ripley-ingest/pull/42");
    // Opens in a new tab, safely (matches Run Detail's ArtifactLinks pattern).
    expect(link).toHaveAttribute("target", "_blank");
    expect(link).toHaveAttribute("rel", expect.stringContaining("noopener"));
  });

  it("still renders the repository name and branch alongside the PR link", () => {
    renderRow({ pullRequestUrl: "https://github.com/llipe/ripley-ingest/pull/42" });
    expect(screen.getByText("llipe/ripley-ingest")).toBeInTheDocument();
    expect(screen.getByText("main")).toBeInTheDocument();
  });

  it("carries no onClick handler — regression guard for the RunHistoryRow/RunHistoryTable/AgentRunHistoryPage Server Component chain, which cannot serialize an event-handler prop (a native click must bubble past the link, not be stopped)", () => {
    renderRow({ pullRequestUrl: "https://github.com/llipe/ripley-ingest/pull/42" });
    const link = screen.getByRole("link", { name: /pr/i });
    const outerHandler = vi.fn();
    const row = link.closest("tr");
    row?.addEventListener("click", outerHandler);
    fireEvent.click(link);
    expect(outerHandler).toHaveBeenCalledTimes(1);
  });
});

describe("RunHistoryRow — no pull_request artifact (AC2, unchanged)", () => {
  it("renders the existing branch-only markup with no link and no inert placeholder", () => {
    renderRow({ pullRequestUrl: null });
    expect(screen.getByText("llipe/ripley-ingest")).toBeInTheDocument();
    expect(screen.getByText("main")).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: /pr/i })).toBeNull();
    expect(screen.queryByTitle(/no linkable url/i)).toBeNull();
  });
});

describe("RunHistoryRow — unsafe PR URL renders inert (edge case, reuses isSafeArtifactUrl)", () => {
  it("renders inert text, never a link, for a javascript: URL", () => {
    renderRow({ pullRequestUrl: "javascript:alert(1)" });
    expect(screen.queryByRole("link", { name: /pr/i })).toBeNull();
    expect(screen.getByTitle(/no linkable url/i)).toBeInTheDocument();
  });

  it("renders inert text, never a link, for a relative URL", () => {
    renderRow({ pullRequestUrl: "/runs/123" });
    expect(screen.queryByRole("link", { name: /pr/i })).toBeNull();
    expect(screen.getByTitle(/no linkable url/i)).toBeInTheDocument();
  });
});

describe("RunHistoryRow — no repository (EC, no crash)", () => {
  it("renders cleanly with a PR url but no repository (defensive — should not occur in practice)", () => {
    renderRow({
      repositoryFullName: null,
      repositoryBranch: null,
      pullRequestUrl: "https://github.com/llipe/x/pull/1",
    });
    expect(screen.getByRole("table").textContent).not.toMatch(/null/);
  });
});

describe("RunHistoryRow — showAgentColumn (S-146, /runs cross-agent feed)", () => {
  it("renders no agent cell when showAgentColumn is false (default, /agents/[slug] unaffected)", () => {
    renderRow({ agentName: "Dependency Update", agentSlug: "dependency-update" }, false);
    expect(screen.queryByText("Dependency Update")).toBeNull();
    expect(screen.queryByText("dependency-update")).toBeNull();
  });

  it("renders the agent name and slug when showAgentColumn is true", () => {
    renderRow({ agentName: "Dependency Update", agentSlug: "dependency-update" }, true);
    expect(screen.getByText("Dependency Update")).toBeInTheDocument();
    expect(screen.getByText("dependency-update")).toBeInTheDocument();
  });

  it("renders a clean — for a missing agent identity, never null/undefined text (EC)", () => {
    renderRow({ agentName: undefined, agentSlug: undefined }, true);
    expect(screen.getByRole("table").textContent).not.toMatch(/null|undefined/);
  });

  it("renders just the name when the slug is missing but the name is present (EC)", () => {
    renderRow({ agentName: "Dependency Update", agentSlug: undefined }, true);
    expect(screen.getByText("Dependency Update")).toBeInTheDocument();
  });
});
