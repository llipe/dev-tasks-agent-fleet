// @vitest-environment jsdom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { createElement } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { useRunStream, type UseRunStreamResult } from "@/lib/hooks/useRunStream";
import type { LogLineView } from "@/lib/domain/run-detail";

/**
 * Story S-121 — live-tail 401 handling (stop infinite reconnect).
 *
 * `EventSource` cannot send headers, so a denied SSE connection surfaces as
 * `onerror` with the stream having NEVER opened for the current attempt and
 * `readyState === CLOSED`. That is the signal that distinguishes a TERMINAL
 * authorization failure (stop, no reconnect, no timer) from a recoverable
 * mid-stream drop (the stream had opened → reconnect with the highest `seq`).
 *
 * These are Layer-1 hook tests driven by a fake `EventSource` that models the
 * two distinguishing facts a real source exposes: whether `onopen` fired and
 * the numeric `readyState`. No network, no DOM assertions — the hook's
 * observable state is captured through a headless render.
 *
 * The reconnect path in `useRunStream` is SYNCHRONOUS (it calls `connect()`
 * directly, no `setTimeout`). "Repeated failures do not accumulate timers" is
 * therefore verified structurally: the terminal path opens no further sources
 * and schedules nothing, asserted against a spied global `setTimeout`.
 */

// EventSource.CLOSED === 2, CONNECTING === 0, OPEN === 1.
const CLOSED = 2;
const OPEN = 1;

let instances: FakeEventSource[] = [];

class FakeEventSource {
  url: string;
  readyState = 0; // CONNECTING
  listeners = new Map<string, ((ev: MessageEvent) => void)[]>();
  onerror: ((ev: Event) => void) | null = null;
  onopen: ((ev: Event) => void) | null = null;
  closeCount = 0;

  constructor(url: string) {
    this.url = url;
    instances.push(this);
  }

  addEventListener(type: string, cb: (ev: MessageEvent) => void) {
    const arr = this.listeners.get(type) ?? [];
    arr.push(cb);
    this.listeners.set(type, arr);
  }

  removeEventListener(type: string, cb: (ev: MessageEvent) => void) {
    const arr = this.listeners.get(type) ?? [];
    this.listeners.set(
      type,
      arr.filter((f) => f !== cb),
    );
  }

  close() {
    this.readyState = CLOSED;
    this.closeCount += 1;
  }

  /** Simulate a successful open (the 200 text/event-stream response). */
  open() {
    this.readyState = OPEN;
    this.onopen?.(new Event("open"));
  }

  emit(type: string, data: unknown) {
    const ev = { data: JSON.stringify(data) } as MessageEvent;
    for (const cb of this.listeners.get(type) ?? []) cb(ev);
  }

  /** Simulate a 401-before-open: the browser closes and fires onerror. */
  errorClosed() {
    this.readyState = CLOSED;
    this.onerror?.(new Event("error"));
  }

  /** Simulate a mid-stream network error (source retains its prior state). */
  errorMidStream() {
    // A real EventSource sets CONNECTING while it tries to reconnect; the hook
    // decides based on whether THIS attempt opened, not on this value.
    this.readyState = 0;
    this.onerror?.(new Event("error"));
  }
}

function latest(): FakeEventSource {
  return instances[instances.length - 1];
}

function line(seq: number): LogLineView {
  return { id: seq, seq, timestamp: "00:00:00", level: "info", step: "", message: `m${seq}` };
}

/**
 * Headless harness: render the hook, expose the latest result through a ref
 * the test reads. Avoids @testing-library so this stays in the `unit` project.
 */
function renderHook(initial: LogLineView[]): {
  result: { current: UseRunStreamResult | null };
  root: Root;
  container: HTMLDivElement;
} {
  const result: { current: UseRunStreamResult | null } = { current: null };
  function Harness() {
    result.current = useRunStream({
      runId: "r1",
      initialLines: initial,
      initialStatus: "running",
      eventSourceFactory: (url) => new FakeEventSource(url) as unknown as EventSource,
    });
    return null;
  }
  const container = document.createElement("div");
  document.body.appendChild(container);
  const root = createRoot(container);
  act(() => {
    root.render(createElement(Harness));
  });
  return { result, root, container };
}

beforeEach(() => {
  instances = [];
  (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("useRunStream — S-121 terminal auth stop", () => {
  it("errored-before-open (401 on first connection) is terminal: no reconnect, authStopped set", () => {
    const setTimeoutSpy = vi.spyOn(globalThis, "setTimeout");
    const { result, root } = renderHook([line(1)]);

    expect(instances).toHaveLength(1);
    const first = latest();

    act(() => {
      first.errorClosed(); // 401 before the stream ever opened
    });

    // Terminal: no new EventSource opened, hook reports authStopped.
    expect(instances).toHaveLength(1);
    expect(result.current?.authStopped).toBe(true);
    expect(result.current?.connected).toBe(false);
    // No reconnect timer was scheduled.
    expect(setTimeoutSpy).not.toHaveBeenCalled();

    act(() => root.unmount());
  });

  it("opened-then-dropped reconnects with the highest rendered seq as after_seq (S-110 preserved)", () => {
    const { result, root } = renderHook([line(1)]);
    const first = latest();

    act(() => {
      first.open(); // authorized: 200 stream opened
      first.emit("event", {
        id: 42,
        seq: 42,
        ts: "t",
        level: "info",
        message: "x",
        step_id: null,
      });
    });

    const before = instances.length;
    act(() => {
      first.errorMidStream(); // genuine mid-stream drop
    });

    // Reconnected, NOT terminal, with the highest seq as the resume cursor.
    expect(instances.length).toBe(before + 1);
    expect(latest().url).toContain("after_seq=42");
    expect(result.current?.authStopped).toBe(false);

    act(() => root.unmount());
  });

  it("401 on a reconnect after a successful period is terminal (attempt-scoped open tracking)", () => {
    const { result, root } = renderHook([line(1)]);
    const first = latest();

    // Open, receive a line, then a genuine drop → reconnect.
    act(() => {
      first.open();
      first.emit("event", { id: 5, seq: 5, ts: "t", level: "info", message: "a", step_id: null });
      first.errorMidStream();
    });
    expect(instances).toHaveLength(2);
    const second = latest();

    // The reconnect attempt is denied (session expired) BEFORE it opens.
    act(() => {
      second.errorClosed();
    });

    // Terminal on this attempt: no third source, authStopped set.
    expect(instances).toHaveLength(2);
    expect(result.current?.authStopped).toBe(true);

    act(() => root.unmount());
  });

  it("repeated never-open failures do not accumulate sources or timers", () => {
    const setTimeoutSpy = vi.spyOn(globalThis, "setTimeout");
    const { result, root } = renderHook([]);
    const first = latest();

    act(() => {
      first.errorClosed();
    });
    // A second onerror on the already-torn-down source must be a no-op.
    act(() => {
      first.errorClosed();
      first.errorClosed();
    });

    expect(instances).toHaveLength(1);
    expect(result.current?.authStopped).toBe(true);
    expect(setTimeoutSpy).not.toHaveBeenCalled();

    act(() => root.unmount());
  });

  it("rapid open/close flapping stays recoverable while it keeps opening", () => {
    const { result, root } = renderHook([line(1)]);

    // open → drop → reconnect → open → drop → reconnect, several times.
    for (let i = 0; i < 4; i += 1) {
      const es = latest();
      act(() => {
        es.open();
        es.errorMidStream();
      });
    }

    // Each opened-then-dropped cycle reconnects; never terminal.
    expect(result.current?.authStopped).toBe(false);
    expect(instances.length).toBe(5); // initial + 4 reconnects

    act(() => root.unmount());
  });

  it("a terminal `closed` frame arriving with a 401-style error does not flip authStopped", () => {
    // Run reaches terminal state (closed) at essentially the same time as a
    // socket error: the closed frame wins (closedRef short-circuits onerror),
    // so this is a normal terminal close, not an auth stop.
    const { result, root } = renderHook([line(1)]);
    const first = latest();

    act(() => {
      first.open();
      first.emit("closed", { reason: "succeeded" });
      first.errorClosed(); // arrives just after the closed frame
    });

    expect(result.current?.authStopped).toBe(false);
    expect(result.current?.closedReason).toBe("succeeded");
    expect(instances).toHaveLength(1); // no reconnect

    act(() => root.unmount());
  });
});
