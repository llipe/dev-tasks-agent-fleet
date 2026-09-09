import { act } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";

import { LiveLogViewer } from "@/components/run-detail/LiveLogViewer";
import type { LogLineView } from "@/lib/domain/run-detail";

/**
 * Live log viewer (Story S-110) — the client wrapper that joins the SSE hook to
 * the S-109 log grid, plus the auto-scroll / pause / resume behavior (AC6) and
 * the live-status derivation (AC5).
 *
 * The SSE hook is driven through an injected fake EventSource, and the scroll
 * container's geometry is stubbed (jsdom reports 0 for layout).
 */

let instances: FakeEventSource[] = [];

class FakeEventSource {
  url: string;
  readyState = 0; // CONNECTING
  listeners = new Map<string, ((ev: MessageEvent) => void)[]>();
  onerror: ((ev: Event) => void) | null = null;
  onopen: ((ev: Event) => void) | null = null;
  closed = false;
  constructor(url: string) {
    this.url = url;
    instances.push(this);
  }
  addEventListener(type: string, cb: (ev: MessageEvent) => void) {
    const arr = this.listeners.get(type) ?? [];
    arr.push(cb);
    this.listeners.set(type, arr);
  }
  removeEventListener() {}
  close() {
    this.readyState = 2; // CLOSED
    this.closed = true;
  }
  emit(type: string, data: unknown) {
    const ev = { data: JSON.stringify(data) } as MessageEvent;
    for (const cb of this.listeners.get(type) ?? []) cb(ev);
  }
  /** Simulate a 401-before-open (Story S-121): closed, onerror, never opened. */
  errorClosed() {
    this.readyState = 2; // CLOSED
    this.onerror?.(new Event("error"));
  }
}

function latest() {
  return instances[instances.length - 1];
}

function line(seq: number, message = `m${seq}`): LogLineView {
  return { id: seq, seq, timestamp: "00:00:00", level: "info", step: "", message };
}

/** Stub a scroll region's geometry so distanceFromBottom is controllable. */
function setScrollGeometry(
  el: HTMLElement,
  {
    scrollHeight,
    clientHeight,
    scrollTop,
  }: { scrollHeight: number; clientHeight: number; scrollTop: number },
) {
  Object.defineProperty(el, "scrollHeight", { value: scrollHeight, configurable: true });
  Object.defineProperty(el, "clientHeight", { value: clientHeight, configurable: true });
  let _top = scrollTop;
  Object.defineProperty(el, "scrollTop", {
    get: () => _top,
    set: (v: number) => {
      _top = v;
    },
    configurable: true,
  });
}

beforeEach(() => {
  instances = [];
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

const factory = (url: string) => new FakeEventSource(url) as unknown as EventSource;

describe("LiveLogViewer", () => {
  it("renders the initial server lines and marks the region aria-live (AC8)", () => {
    render(
      <LiveLogViewer
        runId="r1"
        initialLines={[line(1)]}
        initialStatus="running"
        maxRuntimeSeconds={900}
        graceSeconds={60}
        startTimeoutSeconds={300}
        startedAtMs={Date.now()}
        queuedAtMs={Date.now()}
        eventSourceFactory={factory}
      />,
    );
    expect(screen.getByRole("log", { name: /run log/i })).toHaveAttribute("aria-live", "polite");
    expect(screen.getByText("m1")).toBeInTheDocument();
  });

  it("appends a live event line (AC8)", () => {
    render(
      <LiveLogViewer
        runId="r1"
        initialLines={[line(1)]}
        initialStatus="running"
        maxRuntimeSeconds={900}
        graceSeconds={60}
        startTimeoutSeconds={300}
        startedAtMs={Date.now()}
        queuedAtMs={Date.now()}
        eventSourceFactory={factory}
      />,
    );
    act(() => {
      latest().emit("event", {
        id: 2,
        seq: 2,
        ts: "2026-01-01T00:00:02Z",
        level: "info",
        message: "live-line",
        step_id: null,
      });
    });
    expect(screen.getByText("live-line")).toBeInTheDocument();
  });

  it("renders a message containing HTML as inert text — never as markup (SC-12, security #6)", () => {
    render(
      <LiveLogViewer
        runId="r1"
        initialLines={[]}
        initialStatus="running"
        maxRuntimeSeconds={900}
        graceSeconds={60}
        startTimeoutSeconds={300}
        startedAtMs={Date.now()}
        queuedAtMs={Date.now()}
        eventSourceFactory={factory}
      />,
    );
    act(() => {
      latest().emit("event", {
        id: 3,
        seq: 3,
        ts: "t",
        level: "error",
        message: "<script>alert(1)</script>",
        step_id: null,
      });
    });
    // The literal text is present; no <script> element was created.
    expect(screen.getByText("<script>alert(1)</script>")).toBeInTheDocument();
    expect(document.querySelector("script")).toBeNull();
  });

  it("derives live status through effectiveStatus: a running push cannot overwrite timed_out (AC5, SC-7)", () => {
    // Run started well past its max_runtime + grace, so it is effectively
    // timed_out even though the raw/pushed status says running.
    const startedAtMs = Date.now() - (900 + 60 + 100) * 1000;
    render(
      <LiveLogViewer
        runId="r1"
        initialLines={[]}
        initialStatus="running"
        maxRuntimeSeconds={900}
        graceSeconds={60}
        startTimeoutSeconds={300}
        startedAtMs={startedAtMs}
        queuedAtMs={startedAtMs}
        eventSourceFactory={factory}
      />,
    );
    // A late Realtime push still says running.
    act(() => {
      latest().emit("run", { status: "running" });
    });
    // The pill reflects the DERIVED status, not the raw push. StatusPill shows
    // "timed out" (label) for the timed_out status.
    expect(screen.getByText("timed out")).toBeInTheDocument();
    expect(screen.queryByText(/^running$/)).toBeNull();
  });

  it("pauses auto-scroll when scrolled up and resumes on live-tail click (AC6, DESIGN §6.6)", () => {
    render(
      <LiveLogViewer
        runId="r1"
        initialLines={[line(1)]}
        initialStatus="running"
        maxRuntimeSeconds={900}
        graceSeconds={60}
        startTimeoutSeconds={300}
        startedAtMs={Date.now()}
        queuedAtMs={Date.now()}
        eventSourceFactory={factory}
      />,
    );
    const region = screen.getByRole("log", { name: /run log/i });
    // Scroll up beyond the 24px threshold.
    setScrollGeometry(region, { scrollHeight: 1000, clientHeight: 200, scrollTop: 0 });
    fireEvent.scroll(region);

    // The live-tail control reflects the paused state.
    const button = screen.getByRole("button", { name: /live tail/i });
    expect(button).toHaveAttribute("aria-pressed", "false");

    // Clicking live tail resumes (re-pins) — aria-pressed flips to true.
    setScrollGeometry(region, { scrollHeight: 1000, clientHeight: 200, scrollTop: 800 });
    fireEvent.click(button);
    expect(button).toHaveAttribute("aria-pressed", "true");
  });

  it("stops following after the run closes (AC4 surfaced in the UI)", () => {
    render(
      <LiveLogViewer
        runId="r1"
        initialLines={[line(1)]}
        initialStatus="running"
        maxRuntimeSeconds={900}
        graceSeconds={60}
        startTimeoutSeconds={300}
        startedAtMs={Date.now()}
        queuedAtMs={Date.now()}
        eventSourceFactory={factory}
      />,
    );
    act(() => {
      latest().emit("closed", { reason: "succeeded" });
    });
    expect(latest().closed).toBe(true);
    // Live-tail control disappears once the stream is closed (nothing to tail).
    expect(screen.queryByRole("button", { name: /live tail/i })).toBeNull();
  });

  it("shows a session-expired notice and drops the live control on a terminal auth stop (S-121)", () => {
    render(
      <LiveLogViewer
        runId="r1"
        initialLines={[line(1)]}
        initialStatus="running"
        maxRuntimeSeconds={900}
        graceSeconds={60}
        startTimeoutSeconds={300}
        startedAtMs={Date.now()}
        queuedAtMs={Date.now()}
        eventSourceFactory={factory}
      />,
    );
    // No notice while the stream is healthy.
    expect(screen.queryByRole("alert")).toBeNull();

    // A 401 before the stream ever opened → terminal auth stop.
    act(() => {
      latest().errorClosed();
    });

    const notice = screen.getByRole("alert");
    expect(notice).toHaveTextContent(/session expired/i);
    // The live-tail control is gone (the tail has stopped, not paused).
    expect(screen.queryByRole("button", { name: /live tail/i })).toBeNull();
    // The server-rendered lines are still visible — the log did not vanish.
    expect(screen.getByText("m1")).toBeInTheDocument();
  });

  it("does NOT show the session-expired notice while the stream is live (S-121)", () => {
    render(
      <LiveLogViewer
        runId="r1"
        initialLines={[line(1)]}
        initialStatus="running"
        maxRuntimeSeconds={900}
        graceSeconds={60}
        startTimeoutSeconds={300}
        startedAtMs={Date.now()}
        queuedAtMs={Date.now()}
        eventSourceFactory={factory}
      />,
    );
    act(() => {
      latest().emit("event", {
        id: 2,
        seq: 2,
        ts: "2026-01-01T00:00:02Z",
        level: "info",
        message: "still-live",
        step_id: null,
      });
    });
    expect(screen.queryByRole("alert")).toBeNull();
    expect(screen.getByText("still-live")).toBeInTheDocument();
  });
});
