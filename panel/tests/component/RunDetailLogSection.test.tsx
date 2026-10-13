import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";

import { RunDetailLogSection } from "@/components/run-detail/RunDetailLogSection";
import type { StepPanelRow, LogLineView } from "@/lib/domain/run-detail";

/**
 * `next/navigation` is mocked because the live viewer (`LiveLogViewer`) now
 * calls `useRouter()` for the #244 refresh-on-terminal effect.
 */
vi.mock("next/navigation", () => ({
  useRouter: () => ({ refresh: vi.fn() }),
}));

/**
 * Layer 2 (component) — RunDetailLogSection (Story S-145).
 *
 * The `"use client"` filter-state wrapper that owns `{ stepId, level }` and
 * wires the StepsPanel + a level-filter control to whichever log viewer is
 * mounted (terminal `LogViewer` or live `LiveLogViewer`), per spec §8.2.
 */

function stepRow(overrides: Partial<StepPanelRow> = {}): StepPanelRow {
  return {
    id: "step-1",
    title: "Checkout",
    status: "succeeded",
    duration: "3m 04s",
    eventCount: 2,
    ...overrides,
  };
}

function line(
  seq: number,
  stepId: string | null,
  level = "info",
  message = `event-${seq}`,
): LogLineView {
  return { id: seq, seq, timestamp: "00:00:00", level, step: stepId ?? "", stepId, message };
}

afterEach(() => {
  cleanup();
});

describe("RunDetailLogSection — terminal run (LogViewer)", () => {
  const baseLogViewerProps = {
    initialLines: [line(1, "step-1"), line(2, "step-2", "error")],
    hasEarlier: false,
    oldestSeq: 1,
    loadEarlier: vi.fn(async () => []),
  };

  it("renders the steps panel and the terminal LogViewer together", () => {
    render(
      <RunDetailLogSection
        steps={[stepRow({ id: "step-1" }), stepRow({ id: "step-2", title: "npm_audit" })]}
        isLive={false}
        logViewerProps={baseLogViewerProps}
      />,
    );
    expect(screen.getByText("Checkout")).toBeInTheDocument();
    expect(screen.getByRole("log", { name: /run log/i })).toBeInTheDocument();
    expect(screen.getByText("event-1")).toBeInTheDocument();
    expect(screen.getByText("event-2")).toBeInTheDocument();
  });

  it("clicking a step narrows the log to that step's events (AC2)", () => {
    render(
      <RunDetailLogSection
        steps={[stepRow({ id: "step-1" }), stepRow({ id: "step-2", title: "npm_audit" })]}
        isLive={false}
        logViewerProps={baseLogViewerProps}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: /checkout/i }));
    expect(screen.getByText("event-1")).toBeInTheDocument();
    expect(screen.queryByText("event-2")).toBeNull();
  });

  it("'All steps' restores the full tail after a step filter was applied (AC2)", () => {
    render(
      <RunDetailLogSection
        steps={[stepRow({ id: "step-1" }), stepRow({ id: "step-2", title: "npm_audit" })]}
        isLive={false}
        logViewerProps={baseLogViewerProps}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: /checkout/i }));
    expect(screen.queryByText("event-2")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: /all steps/i }));
    expect(screen.getByText("event-1")).toBeInTheDocument();
    expect(screen.getByText("event-2")).toBeInTheDocument();
  });

  it("a level-filter control composes with an active step filter (AC3)", () => {
    render(
      <RunDetailLogSection
        steps={[stepRow({ id: "step-1" }), stepRow({ id: "step-2", title: "npm_audit" })]}
        isLive={false}
        logViewerProps={{
          ...baseLogViewerProps,
          initialLines: [
            line(1, "step-1", "info", "s1-info"),
            line(2, "step-1", "error", "s1-error"),
            line(3, "step-2", "error", "s2-error"),
          ],
        }}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: /checkout/i }));
    fireEvent.change(screen.getByLabelText(/log level/i), { target: { value: "error" } });
    expect(screen.queryByText("s1-info")).toBeNull();
    expect(screen.getByText("s1-error")).toBeInTheDocument();
    expect(screen.queryByText("s2-error")).toBeNull();
  });

  it("renders an empty (but present) steps panel for a zero-step run — not an error", () => {
    render(<RunDetailLogSection steps={[]} isLive={false} logViewerProps={baseLogViewerProps} />);
    expect(screen.queryByRole("button", { name: /all steps/i })).toBeNull();
    expect(screen.getByRole("log", { name: /run log/i })).toBeInTheDocument();
  });
});

describe("RunDetailLogSection — live run (LiveLogViewer)", () => {
  it("renders the live viewer when isLive is true", () => {
    render(
      <RunDetailLogSection
        steps={[stepRow()]}
        isLive={true}
        liveLogViewerProps={{
          runId: "r1",
          initialLines: [line(1, "step-1")],
          initialStatus: "running",
          maxRuntimeSeconds: 900,
          graceSeconds: 60,
          startTimeoutSeconds: 300,
          startedAtMs: Date.now(),
          queuedAtMs: Date.now(),
          eventSourceFactory: () =>
            ({
              addEventListener: () => {},
              close: () => {},
            }) as unknown as EventSource,
        }}
      />,
    );
    expect(screen.getByRole("log", { name: /run log/i })).toHaveAttribute(
      "data-sse-mount",
      "run-log",
    );
    expect(screen.getByText("Checkout")).toBeInTheDocument();
  });
});

describe("RunDetailLogSection — filter persists across the refresh viewer swap (#244 AC5, D-03)", () => {
  const liveFactory = () =>
    ({
      addEventListener: () => {},
      close: () => {},
    }) as unknown as EventSource;

  it("keeps the selected level filter applied after the live viewer swaps to the terminal LogViewer", () => {
    const lines = [
      line(1, "step-1", "info", "swap-info"),
      line(2, "step-1", "error", "swap-error"),
    ];

    // 1) Live render (running run). The user selects "Errors only".
    const { rerender } = render(
      <RunDetailLogSection
        steps={[stepRow({ id: "step-1" })]}
        isLive={true}
        liveLogViewerProps={{
          runId: "r1",
          initialLines: lines,
          initialStatus: "running",
          maxRuntimeSeconds: 900,
          graceSeconds: 60,
          startTimeoutSeconds: 300,
          startedAtMs: Date.now(),
          queuedAtMs: Date.now(),
          eventSourceFactory: liveFactory,
        }}
      />,
    );
    fireEvent.change(screen.getByLabelText(/log level/i), { target: { value: "error" } });
    expect(screen.queryByText("swap-info")).toBeNull();
    expect(screen.getByText("swap-error")).toBeInTheDocument();

    // 2) router.refresh() re-reads the server tree: the run is now terminal, so
    // the page passes isLive=false and the terminal LogViewer replaces the live
    // one. RunDetailLogSection stays mounted at the same position, so its
    // useState filter ({ level: "error" }) is PRESERVED (D-03).
    rerender(
      <RunDetailLogSection
        steps={[stepRow({ id: "step-1" })]}
        isLive={false}
        logViewerProps={{
          initialLines: lines,
          hasEarlier: false,
          oldestSeq: 1,
          loadEarlier: vi.fn(async () => []),
        }}
      />,
    );

    // The filter is still "Errors only" — the info line stays hidden, the error
    // line stays visible, with no re-selection by the user.
    expect(screen.getByLabelText(/log level/i)).toHaveValue("error");
    expect(screen.queryByText("swap-info")).toBeNull();
    expect(screen.getByText("swap-error")).toBeInTheDocument();
  });
});
