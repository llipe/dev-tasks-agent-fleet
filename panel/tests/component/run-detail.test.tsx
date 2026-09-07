import { render, screen, within, fireEvent, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { RunSummary } from "@/components/run-detail/RunSummary";
import { StateBanner } from "@/components/run-detail/StateBanner";
import { LogViewer } from "@/components/run-detail/LogViewer";
import { ArtifactLinks, type ArtifactView } from "@/components/run-detail/ArtifactLinks";
import {
  buildSummary,
  buildLogLines,
  selectBanner,
  type SummaryInput,
  type LogEventInput,
  type LogLineView,
} from "@/lib/domain/run-detail";

/**
 * Layer 2 component tests for the run-detail screen (S-109 / issue #122).
 *
 * The two mandatory security-negative categories are exercised here:
 *  - **#6 (SC-13):** a message containing `<script>` renders as literal inert
 *    text — no script node is created.
 *  - **#5 (SC-14) is unit-tested** in tests/unit/artifact-url.test.ts; here we
 *    assert the RENDER consequence: an unsafe URL is not turned into an anchor.
 *
 * Plus: AC14 (artifact link on a `failed` run), the summary status/outcome
 * pairs, the terminal-state banner, `aria-live` on the log region, and the
 * "load earlier" interaction.
 */

const NOW = Date.UTC(2026, 0, 1, 14, 2, 13);

function summaryInput(overrides: Partial<SummaryInput> = {}): SummaryInput {
  return {
    id: "01J8XQ2F-3K4M-5N6P-7Q8R-9S0T1U2V3W4X",
    status: "succeeded",
    startedAtMs: NOW - 300_000,
    queuedAtMs: NOW - 360_000,
    finishedAtMs: NOW - 60_000,
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

function renderSummary(input: SummaryInput, artifacts: ArtifactView[] = []) {
  return render(<RunSummary summary={buildSummary(input, NOW)} artifacts={artifacts} />);
}

// ---------------------------------------------------------------------------
// AC2 — summary status/outcome pairs
// ---------------------------------------------------------------------------

describe("RunSummary — status + outcome (AC2)", () => {
  it("renders the status pill from the derived effective status", () => {
    renderSummary(summaryInput({ status: "succeeded" }));
    expect(screen.getByText("succeeded")).toBeInTheDocument();
  });

  it("derives a stale running run to timed_out (SC-2)", () => {
    renderSummary(
      summaryInput({
        status: "running",
        startedAtMs: NOW - 20 * 60_000,
        finishedAtMs: null,
        durationMs: null,
        outcome: null,
      }),
    );
    expect(screen.getByText("timed out")).toBeInTheDocument();
    expect(screen.queryByText(/^running$/)).toBeNull();
  });

  it("renders the outcome tag and the short run id", () => {
    renderSummary(summaryInput({ outcome: "no_vulnerabilities" }));
    expect(screen.getByText("NO VULNS")).toBeInTheDocument();
    expect(screen.getByText("01J8XQ2F")).toBeInTheDocument();
  });

  it("renders a run with no repository and null finished cleanly (no null/NaN, SC-3)", () => {
    renderSummary(
      summaryInput({
        status: "failed_to_start",
        repositoryFullName: null,
        branch: null,
        startedAtMs: null,
        finishedAtMs: null,
        durationMs: null,
        outcome: null,
      }),
    );
    const region = screen.getByRole("region", { name: /run summary/i });
    expect(region.textContent).not.toMatch(/null/);
    expect(region.textContent).not.toMatch(/NaN/);
    // Duration and finished both dash out.
    expect(within(region).getAllByText("—").length).toBeGreaterThanOrEqual(2);
  });
});

// ---------------------------------------------------------------------------
// AC3 / AC14 — artifacts, including on a failed run
// ---------------------------------------------------------------------------

describe("ArtifactLinks + RunSummary — AC14 (artifact on a failed run)", () => {
  const pr: ArtifactView = {
    id: "a1",
    type: "pull_request",
    title: "Bump lodash to 4.17.21",
    url: "https://github.com/llipe/x/pull/42",
  };

  it("renders the PR pill link ALONGSIDE the red failed pill (AC14)", () => {
    renderSummary(summaryInput({ status: "failed", outcome: "needs_review", durationMs: 90_000 }), [
      pr,
    ]);
    // The failed pill is present...
    expect(screen.getByText("failed")).toBeInTheDocument();
    // ...and so is the artifact link, not hidden behind the failure.
    const link = screen.getByRole("link", { name: /bump lodash/i });
    expect(link).toHaveAttribute("href", "https://github.com/llipe/x/pull/42");
  });

  it("hardens the artifact anchor with rel=noopener noreferrer (SC-4)", () => {
    render(<ArtifactLinks artifacts={[pr]} />);
    const link = screen.getByRole("link", { name: /bump lodash/i });
    expect(link).toHaveAttribute("rel", expect.stringContaining("noopener"));
    expect(link).toHaveAttribute("rel", expect.stringContaining("noreferrer"));
  });

  it("renders an UNSAFE-scheme artifact as inert text, never an anchor (security #5 render)", () => {
    const evil: ArtifactView = {
      id: "a2",
      type: "file",
      title: "click me",
      url: "javascript:alert(1)",
    };
    render(<ArtifactLinks artifacts={[evil]} />);
    // No link is rendered for the javascript: URL.
    expect(screen.queryByRole("link", { name: /click me/i })).toBeNull();
    // The label is still shown, as inert text.
    expect(screen.getByText("click me")).toBeInTheDocument();
  });

  it("renders an http: artifact as inert text (no downgrade link)", () => {
    const insecure: ArtifactView = {
      id: "a3",
      type: "audit_report",
      title: "report",
      url: "http://example.com/report",
    };
    render(<ArtifactLinks artifacts={[insecure]} />);
    expect(screen.queryByRole("link", { name: /report/i })).toBeNull();
    expect(screen.getByText("report")).toBeInTheDocument();
  });

  it("renders nothing for an empty artifact list", () => {
    const { container } = render(<ArtifactLinks artifacts={[]} />);
    expect(container).toBeEmptyDOMElement();
  });
});

// ---------------------------------------------------------------------------
// AC7 / security #6 — inert message rendering
// ---------------------------------------------------------------------------

describe("LogViewer — inert message rendering (AC7 / security #6, SC-13)", () => {
  function lines(messages: string[]): LogLineView[] {
    const events: LogEventInput[] = messages.map((m, i) => ({
      id: i + 1,
      seq: i + 1,
      ts: new Date(NOW).toISOString(),
      level: "info",
      message: m,
      stepId: null,
    }));
    return buildLogLines(events, [], "UTC");
  }

  const noop = async () => [];

  it("renders <script> content as literal text, injecting no script node", () => {
    render(
      <LogViewer
        initialLines={lines(["<script>alert(1)</script>"])}
        hasEarlier={false}
        oldestSeq={1}
        loadEarlier={noop}
      />,
    );
    // The literal text is present...
    expect(screen.getByText("<script>alert(1)</script>")).toBeInTheDocument();
    // ...and NO real <script> element was created inside the log region.
    const region = screen.getByRole("log", { name: /run log/i });
    expect(region.querySelector("script")).toBeNull();
  });

  it("renders an img/onerror payload as literal text, creating no img element", () => {
    render(
      <LogViewer
        initialLines={lines(['<img src=x onerror="alert(1)">'])}
        hasEarlier={false}
        oldestSeq={1}
        loadEarlier={noop}
      />,
    );
    expect(screen.getByText('<img src=x onerror="alert(1)">')).toBeInTheDocument();
    const region = screen.getByRole("log", { name: /run log/i });
    expect(region.querySelector("img")).toBeNull();
  });

  it("renders a full 8 KB message without truncating it (SC-16)", () => {
    const big = "y".repeat(8 * 1024);
    render(
      <LogViewer initialLines={lines([big])} hasEarlier={false} oldestSeq={1} loadEarlier={noop} />,
    );
    expect(screen.getByText(big)).toBeInTheDocument();
  });
});

// ---------------------------------------------------------------------------
// AC8 — aria-live
// ---------------------------------------------------------------------------

describe("LogViewer — accessibility + empty (AC8)", () => {
  const noop = async () => [];

  it("marks the log region aria-live=polite (AC8) and role=log", () => {
    render(<LogViewer initialLines={[]} hasEarlier={false} oldestSeq={null} loadEarlier={noop} />);
    const region = screen.getByRole("log", { name: /run log/i });
    expect(region).toHaveAttribute("aria-live", "polite");
  });

  it("keeps a stable SSE mount point for S-110", () => {
    render(<LogViewer initialLines={[]} hasEarlier={false} oldestSeq={null} loadEarlier={noop} />);
    const region = screen.getByRole("log", { name: /run log/i });
    expect(region).toHaveAttribute("data-sse-mount", "run-log");
  });

  it("renders an empty-log message when there are no events (SC-11)", () => {
    render(<LogViewer initialLines={[]} hasEarlier={false} oldestSeq={null} loadEarlier={noop} />);
    expect(screen.getByText(/no log events/i)).toBeInTheDocument();
  });
});

// ---------------------------------------------------------------------------
// AC5 — load earlier
// ---------------------------------------------------------------------------

describe("LogViewer — load earlier (AC5, SC-9)", () => {
  function line(seq: number): LogLineView {
    return {
      id: seq,
      seq,
      timestamp: "14:02:13",
      level: "info",
      step: "",
      message: `event ${seq}`,
    };
  }

  it("shows a Load earlier control only when earlier events exist", () => {
    const { unmount } = render(
      <LogViewer
        initialLines={[line(2001)]}
        hasEarlier={true}
        oldestSeq={2001}
        loadEarlier={async () => []}
      />,
    );
    expect(screen.getByRole("button", { name: /load earlier/i })).toBeInTheDocument();
    unmount();

    // Fresh mount for a run with no earlier events — the control is absent.
    render(
      <LogViewer
        initialLines={[line(1)]}
        hasEarlier={false}
        oldestSeq={1}
        loadEarlier={async () => []}
      />,
    );
    expect(screen.queryByRole("button", { name: /load earlier/i })).toBeNull();
  });

  it("fetches and prepends the prior window when clicked, without duplicating seqs", async () => {
    const loadEarlier = vi.fn(async () => [line(1), line(2)]);
    render(
      <LogViewer
        initialLines={[line(2001)]}
        hasEarlier={true}
        oldestSeq={2001}
        loadEarlier={loadEarlier}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: /load earlier/i }));

    await waitFor(() => {
      expect(loadEarlier).toHaveBeenCalledWith(1, 2000);
    });
    // The earlier lines are prepended (event 1 appears before event 2001).
    await waitFor(() => {
      expect(screen.getByText("event 1")).toBeInTheDocument();
    });
    const region = screen.getByRole("log", { name: /run log/i });
    const text = region.textContent ?? "";
    expect(text.indexOf("event 1")).toBeLessThan(text.indexOf("event 2001"));
    // Reached seq 1 → no more "load earlier".
    await waitFor(() => {
      expect(screen.queryByRole("button", { name: /load earlier/i })).toBeNull();
    });
  });
});

// ---------------------------------------------------------------------------
// AC6 — terminal-state banners
// ---------------------------------------------------------------------------

describe("StateBanner — terminal-state banners (AC6, SC-10/11/12)", () => {
  it("renders a timed_out banner with the reaper explanatory text", () => {
    const banner = selectBanner("timed_out")!;
    render(<StateBanner banner={banner} message="No terminal status after 3720s; reaped." />);
    const region = screen.getByRole("status");
    expect(within(region).getByText(/timed out/i)).toBeInTheDocument();
    expect(within(region).getByText(/reaped/i)).toBeInTheDocument();
  });

  it("renders a failed_to_start banner", () => {
    const banner = selectBanner("failed_to_start")!;
    render(<StateBanner banner={banner} message={null} />);
    expect(screen.getByText(/failed to start/i)).toBeInTheDocument();
  });

  it("selects NO banner for non-terminal-reaper statuses (SC-12)", () => {
    for (const s of ["running", "succeeded", "failed", "queued", "canceled"]) {
      expect(selectBanner(s)).toBeNull();
    }
  });

  it("renders the banner explanatory text as inert (no markup execution)", () => {
    const banner = selectBanner("timed_out")!;
    render(<StateBanner banner={banner} message="<script>alert(1)</script>" />);
    expect(screen.getByText("<script>alert(1)</script>")).toBeInTheDocument();
    expect(screen.getByRole("status").querySelector("script")).toBeNull();
  });
});
