import { act } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";

import { LiveLogViewer } from "@/components/run-detail/LiveLogViewer";
import type { LogLineView } from "@/lib/domain/run-detail";
import type { LogFilterState } from "@/lib/domain/log-filter";

/**
 * `next/navigation` is mocked following `tests/component/Sidebar.test.tsx`.
 * `useRouter().refresh` is the single mechanism Story S-153 (#244) uses to
 * re-render the server tree when a live run reaches a terminal state (D-08).
 */
const refreshMock = vi.fn();
vi.mock("next/navigation", () => ({
  useRouter: () => ({ refresh: refreshMock }),
}));

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

function stepLine(seq: number, stepId: string | null, message = `m${seq}`): LogLineView {
  return {
    id: seq,
    seq,
    timestamp: "00:00:00",
    level: "info",
    step: stepId ?? "",
    stepId,
    message,
  };
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

describe("LiveLogViewer — step/level filter composition with live tail (Story S-145, AC4)", () => {
  it("with no filter prop, renders every live-appended line (backward compatible default)", () => {
    render(
      <LiveLogViewer
        runId="r1"
        initialLines={[stepLine(1, "step-1")]}
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
        ts: "t",
        level: "info",
        message: "m2",
        step_id: "step-2",
      });
    });
    expect(screen.getByText("m1")).toBeInTheDocument();
    expect(screen.getByText("m2")).toBeInTheDocument();
  });

  it("a step filter hides a live-appended line for a DIFFERENT (filtered-out) step", () => {
    const filter: LogFilterState = { stepId: "step-1", level: "all" };
    render(
      <LiveLogViewer
        runId="r1"
        initialLines={[stepLine(1, "step-1")]}
        initialStatus="running"
        maxRuntimeSeconds={900}
        graceSeconds={60}
        startTimeoutSeconds={300}
        startedAtMs={Date.now()}
        queuedAtMs={Date.now()}
        eventSourceFactory={factory}
        filter={filter}
      />,
    );
    act(() => {
      latest().emit("event", {
        id: 2,
        seq: 2,
        ts: "t",
        level: "info",
        message: "filtered-out-step",
        step_id: "step-2",
      });
    });
    expect(screen.queryByText("filtered-out-step")).toBeNull();
  });

  it("a live-appended line for the FILTERED-IN step still appears and still autoscrolls (AC4/S-110)", () => {
    const filter: LogFilterState = { stepId: "step-1", level: "all" };
    render(
      <LiveLogViewer
        runId="r1"
        initialLines={[stepLine(1, "step-1")]}
        initialStatus="running"
        maxRuntimeSeconds={900}
        graceSeconds={60}
        startTimeoutSeconds={300}
        startedAtMs={Date.now()}
        queuedAtMs={Date.now()}
        eventSourceFactory={factory}
        filter={filter}
      />,
    );
    const region = screen.getByRole("log", { name: /run log/i });
    setScrollGeometry(region, { scrollHeight: 200, clientHeight: 200, scrollTop: 0 });

    act(() => {
      latest().emit("event", {
        id: 2,
        seq: 2,
        ts: "t",
        level: "info",
        message: "filtered-in-step",
        step_id: "step-1",
      });
    });
    expect(screen.getByText("filtered-in-step")).toBeInTheDocument();
    // Still following (default) — pinned to the bottom (S-110 AC6 behavior
    // preserved under an active filter).
    expect(region.scrollTop).toBe(region.scrollHeight);
  });

  it("a level filter composes with the step filter for live-appended lines (AC3+AC4)", () => {
    const filter: LogFilterState = { stepId: "step-1", level: "error" };
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
        filter={filter}
      />,
    );
    act(() => {
      latest().emit("event", {
        id: 1,
        seq: 1,
        ts: "t",
        level: "info",
        message: "step1-info",
        step_id: "step-1",
      });
      latest().emit("event", {
        id: 2,
        seq: 2,
        ts: "t",
        level: "error",
        message: "step1-error",
        step_id: "step-1",
      });
    });
    expect(screen.queryByText("step1-info")).toBeNull();
    expect(screen.getByText("step1-error")).toBeInTheDocument();
  });
});

/**
 * Refresh-on-terminal wiring (Story #244, D-08). When the live stream delivers
 * the terminal `closed` frame, the viewer waits 500ms and calls
 * `router.refresh()` exactly once per mount so the server-rendered summary
 * (finished_at, outcome, artifacts, audit findings) re-reads without a reload.
 *
 * Trigger rule (D-08): fire only when `closedReason` becomes non-null; never on
 * `authStopped`, stream errors, or reconnects; a 500ms debounce; exactly one
 * refresh per mount (ref flag); clear the timer on unmount; no retry.
 *
 * These use fake timers to assert the debounce precisely; the EventSource is
 * the same injected `FakeEventSource`, and `next/navigation` is mocked above.
 */
describe("LiveLogViewer — refresh on terminal (#244, D-08)", () => {
  const liveProps = {
    runId: "r1",
    initialLines: [line(1)],
    initialStatus: "running" as const,
    maxRuntimeSeconds: 900,
    graceSeconds: 60,
    startTimeoutSeconds: 300,
    startedAtMs: Date.now(),
    queuedAtMs: Date.now(),
    eventSourceFactory: factory,
  };

  beforeEach(() => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
  });

  afterEach(() => {
    vi.runOnlyPendingTimers();
    vi.useRealTimers();
  });

  it("calls router.refresh exactly once, 500ms after a terminal closed frame (AC1/AC4)", () => {
    render(<LiveLogViewer {...liveProps} />);

    act(() => {
      latest().emit("closed", { reason: "succeeded" });
    });
    // Nothing yet — the debounce has not elapsed.
    expect(refreshMock).not.toHaveBeenCalled();

    act(() => {
      vi.advanceTimersByTime(499);
    });
    expect(refreshMock).not.toHaveBeenCalled();

    act(() => {
      vi.advanceTimersByTime(1);
    });
    expect(refreshMock).toHaveBeenCalledTimes(1);
  });

  it("does NOT call refresh again on a second closed frame (reconnect race, AC3/EC-244-3)", () => {
    render(<LiveLogViewer {...liveProps} />);

    act(() => {
      latest().emit("closed", { reason: "succeeded" });
    });
    act(() => {
      vi.advanceTimersByTime(500);
    });
    expect(refreshMock).toHaveBeenCalledTimes(1);

    // A second terminal frame (e.g. a reconnect race) must not schedule again.
    act(() => {
      latest().emit("closed", { reason: "succeeded" });
    });
    act(() => {
      vi.advanceTimersByTime(500);
    });
    expect(refreshMock).toHaveBeenCalledTimes(1);
  });

  it("does NOT call refresh on a stream error / reconnect (no closed frame) (AC3/EC-244-?)", () => {
    render(<LiveLogViewer {...liveProps} />);

    // A mid-stream drop reconnects (the hook had opened); no `closed` frame.
    act(() => {
      const es = latest();
      // Mark it opened then fire a non-terminal error → the hook reconnects.
      es.onopen?.(new Event("open"));
      es.onerror?.(new Event("error"));
      vi.advanceTimersByTime(1000);
    });
    expect(refreshMock).not.toHaveBeenCalled();
  });

  it("does NOT call refresh on a terminal auth stop (authStopped, AC3/EC-244-4/S-121)", () => {
    render(<LiveLogViewer {...liveProps} />);

    // A 401 before the stream ever opened → terminal auth stop, NOT a `closed`.
    act(() => {
      latest().errorClosed();
      vi.advanceTimersByTime(1000);
    });
    expect(refreshMock).not.toHaveBeenCalled();
  });

  it("does NOT call refresh if unmounted before the 500ms debounce elapses (AC4/EC-244-1)", () => {
    const { unmount } = render(<LiveLogViewer {...liveProps} />);

    act(() => {
      latest().emit("closed", { reason: "succeeded" });
      vi.advanceTimersByTime(499);
    });
    expect(refreshMock).not.toHaveBeenCalled();

    unmount();
    act(() => {
      vi.advanceTimersByTime(1000);
    });
    expect(refreshMock).not.toHaveBeenCalled();
  });

  it("refreshes once for a run already terminal at connect time (closed immediately) (EC-244-5)", () => {
    render(<LiveLogViewer {...liveProps} />);

    // The relay emits `closed` immediately for an already-terminal run.
    act(() => {
      latest().emit("closed", { reason: "timed_out" });
    });
    act(() => {
      vi.advanceTimersByTime(500);
    });
    expect(refreshMock).toHaveBeenCalledTimes(1);
  });

  it("still refreshes once for a closed frame with an EMPTY reason (CT-6: hook maps it to 'closed')", () => {
    render(<LiveLogViewer {...liveProps} />);

    // CT-6: a `closed` frame with no/empty reason. `useRunStream` maps a missing
    // reason to the string "closed" (non-null), so `closedReason` becomes
    // non-null and the refresh fires. This pins the CURRENT hook behavior.
    act(() => {
      latest().emit("closed", {});
    });
    act(() => {
      vi.advanceTimersByTime(500);
    });
    expect(refreshMock).toHaveBeenCalledTimes(1);
  });
});

/** Mulberry32 — a tiny deterministic PRNG (no dependency), matching RT-1/RT-2. */
function mulberry32(seed: number): () => number {
  let a = seed >>> 0;
  return () => {
    a |= 0;
    a = (a + 0x6d2b79f5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

/**
 * RT-3 (test-plan §7, seed 244001). A stateful random walk over the live
 * viewer's refresh effect: 500 walks of length 1–30 over the step alphabet
 * {line, run-status push, error, reconnect, 401, closed(reason), advance(0–1000ms),
 * unmount}. Oracle (deterministic): `refresh` is called ≤ 1 time; exactly once
 * iff a `closed` frame occurred with no prior 401 (authStopped) or unmount AND
 * ≥500ms of mounted time elapsed after it; never before 500ms. No new dependency.
 */
describe("LiveLogViewer — refresh effect random walk (RT-3, #244)", () => {
  const baseProps = {
    runId: "r1",
    initialLines: [line(1)],
    initialStatus: "running" as const,
    maxRuntimeSeconds: 900,
    graceSeconds: 60,
    startTimeoutSeconds: 300,
    startedAtMs: Date.now(),
    queuedAtMs: Date.now(),
    eventSourceFactory: factory,
  };

  type Step =
    | { kind: "line"; seq: number }
    | { kind: "run" }
    | { kind: "error" }
    | { kind: "closed" }
    | { kind: "auth401" }
    | { kind: "advance"; ms: number }
    | { kind: "unmount" };

  it("refresh ≤ 1 per mount; = 1 iff a non-auth closed + 500ms elapsed before unmount (seed 244001)", () => {
    const seed = Number(process.env.TEST_SEED ?? 244001);
    const rand = mulberry32(seed);
    const pick = (n: number) => Math.floor(rand() * n);

    for (let walk = 0; walk < 500; walk++) {
      instances = [];
      refreshMock.mockClear();
      vi.useFakeTimers({ shouldAdvanceTime: true });

      const len = 1 + pick(30);
      // Model expected outcome in parallel with the live component.
      let unmounted = false;
      let authStopped = false;
      let streamClosed = false; // a `closed` frame has torn the source down
      let msSinceClose: number | null = null; // mounted ms elapsed after the first eligible close
      let expectRefresh = false;
      let seqCounter = 1;

      const { unmount } = render(<LiveLogViewer {...baseProps} />);

      const steps: Step[] = [];
      for (let i = 0; i < len; i++) {
        const r = pick(7);
        if (r === 0) steps.push({ kind: "line", seq: ++seqCounter });
        else if (r === 1) steps.push({ kind: "run" });
        else if (r === 2) steps.push({ kind: "error" });
        else if (r === 3) steps.push({ kind: "closed" });
        else if (r === 4) steps.push({ kind: "auth401" });
        else if (r === 5) steps.push({ kind: "advance", ms: pick(1001) });
        else steps.push({ kind: "unmount" });
      }

      for (const step of steps) {
        if (unmounted) break;
        const es = latest();
        act(() => {
          switch (step.kind) {
            case "line":
              if (!authStopped && !streamClosed && es) {
                es.onopen?.(new Event("open"));
                es.emit("event", {
                  id: step.seq,
                  seq: step.seq,
                  ts: "t",
                  level: "info",
                  message: `m${step.seq}`,
                  step_id: null,
                });
              }
              break;
            case "run":
              if (!authStopped && !streamClosed && es) {
                es.onopen?.(new Event("open"));
                es.emit("run", { status: "running" });
              }
              break;
            case "error":
              // A mid-stream drop (stream had opened) → hook reconnects; no refresh.
              if (!authStopped && !streamClosed && es) {
                es.onopen?.(new Event("open"));
                es.onerror?.(new Event("error"));
              }
              break;
            case "closed":
              if (!authStopped && !streamClosed && es) {
                es.emit("closed", { reason: "succeeded" });
                streamClosed = true;
                if (msSinceClose === null) msSinceClose = 0;
              }
              break;
            case "auth401":
              // A 401 before open is terminal only on a source that has not
              // closed/opened cleanly; model it as an auth stop if still live.
              if (!authStopped && !streamClosed && es) {
                es.errorClosed();
                authStopped = true;
              }
              break;
            case "advance":
              vi.advanceTimersByTime(step.ms);
              if (msSinceClose !== null && !expectRefresh) {
                msSinceClose += step.ms;
                if (msSinceClose >= 500) expectRefresh = true;
              }
              break;
            case "unmount":
              unmount();
              unmounted = true;
              break;
          }
        });
      }

      // Drain any still-pending timer so the component settles (does not change
      // the oracle: the debounce only fires if ≥500ms elapsed while mounted).
      if (!unmounted) {
        act(() => {
          unmount();
        });
      }

      const calls = refreshMock.mock.calls.length;
      expect(calls).toBeLessThanOrEqual(1);
      if (expectRefresh) {
        expect(calls, `walk ${walk} (seed ${seed}) expected one refresh`).toBe(1);
      } else {
        expect(calls, `walk ${walk} (seed ${seed}) expected no refresh`).toBe(0);
      }

      vi.useRealTimers();
      cleanup();
    }
  });
});
