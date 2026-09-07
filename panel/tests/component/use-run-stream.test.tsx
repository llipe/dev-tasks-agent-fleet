import { act } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";

import { useRunStream } from "@/lib/hooks/useRunStream";
import type { LogLineView } from "@/lib/domain/run-detail";

/**
 * Client stream hook (Story S-110, AC4/AC5). Tested with a fake `EventSource`
 * so reconnect and stop-after-closed are deterministic.
 *
 *  - AC4: stop reconnecting after `closed`; on an unexpected drop, reconnect
 *    with the highest rendered `seq` as `after_seq`.
 *  - AC5: a `run` push is exposed so the viewer can re-derive status; the hook
 *    itself does not overwrite status (the derivation is the viewer's job).
 */

let instances: FakeEventSource[] = [];

class FakeEventSource {
  url: string;
  listeners = new Map<string, ((ev: MessageEvent) => void)[]>();
  onerror: ((ev: Event) => void) | null = null;
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
  removeEventListener(type: string, cb: (ev: MessageEvent) => void) {
    const arr = this.listeners.get(type) ?? [];
    this.listeners.set(
      type,
      arr.filter((f) => f !== cb),
    );
  }
  close() {
    this.closed = true;
  }
  emit(type: string, data: unknown) {
    const ev = { data: JSON.stringify(data) } as MessageEvent;
    for (const cb of this.listeners.get(type) ?? []) cb(ev);
  }
  error() {
    this.onerror?.(new Event("error"));
  }
}

function latest(): FakeEventSource {
  return instances[instances.length - 1];
}

/** A tiny harness component that renders the hook's observable state. */
function Harness({ runId, initial }: { runId: string; initial: LogLineView[] }) {
  const { lines, status, connected } = useRunStream({
    runId,
    initialLines: initial,
    initialStatus: "running",
    // inject the fake so the hook never touches the global.
    eventSourceFactory: (url) => new FakeEventSource(url) as unknown as EventSource,
  });
  return (
    <div>
      <span data-testid="status">{status}</span>
      <span data-testid="connected">{connected ? "yes" : "no"}</span>
      <ol data-testid="lines">
        {lines.map((l) => (
          <li key={l.id}>{l.seq}</li>
        ))}
      </ol>
    </div>
  );
}

beforeEach(() => {
  instances = [];
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

function line(seq: number): LogLineView {
  return { id: seq, seq, timestamp: "00:00:00", level: "info", step: "", message: `m${seq}` };
}

describe("useRunStream", () => {
  it("opens with after_seq = highest initial seq", () => {
    render(<Harness runId="r1" initial={[line(1), line(2)]} />);
    expect(latest().url).toContain("/api/runs/r1/events/stream");
    expect(latest().url).toContain("after_seq=2");
  });

  it("opens with after_seq=0 when there are no initial lines", () => {
    render(<Harness runId="r1" initial={[]} />);
    expect(latest().url).toContain("after_seq=0");
  });

  it("appends an incoming event line (AC8)", () => {
    render(<Harness runId="r1" initial={[line(1)]} />);
    act(() => {
      latest().emit("event", {
        id: 2,
        seq: 2,
        ts: "2026-01-01T00:00:02Z",
        level: "info",
        message: "hi",
        step_id: null,
      });
    });
    const items = screen.getByTestId("lines").querySelectorAll("li");
    expect([...items].map((li) => li.textContent)).toEqual(["1", "2"]);
  });

  it("ignores a duplicate/out-of-order event (dedupe on the client, EC-5/EC-6)", () => {
    render(<Harness runId="r1" initial={[line(5)]} />);
    act(() => {
      latest().emit("event", {
        id: 5,
        seq: 5,
        ts: "t",
        level: "info",
        message: "dup",
        step_id: null,
      });
      latest().emit("event", {
        id: 3,
        seq: 3,
        ts: "t",
        level: "info",
        message: "old",
        step_id: null,
      });
      latest().emit("event", {
        id: 6,
        seq: 6,
        ts: "t",
        level: "info",
        message: "new",
        step_id: null,
      });
    });
    const items = screen.getByTestId("lines").querySelectorAll("li");
    expect([...items].map((li) => li.textContent)).toEqual(["5", "6"]);
  });

  it("stops reconnecting after `closed` (AC4)", () => {
    render(<Harness runId="r1" initial={[line(1)]} />);
    const first = latest();
    act(() => {
      first.emit("closed", { reason: "succeeded" });
    });
    expect(first.closed).toBe(true);
    // An error after closed must NOT open a new EventSource.
    act(() => {
      first.error();
    });
    expect(instances).toHaveLength(1);
    expect(screen.getByTestId("connected").textContent).toBe("no");
  });

  it("reconnects with the highest rendered seq on an unexpected drop (AC4, SC-6)", () => {
    render(<Harness runId="r1" initial={[line(1)]} />);
    act(() => {
      latest().emit("event", {
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
      latest().error(); // unexpected drop
    });
    expect(instances.length).toBe(before + 1);
    expect(latest().url).toContain("after_seq=42");
  });

  it("exposes a run push so the viewer can re-derive status (AC5)", () => {
    render(<Harness runId="r1" initial={[line(1)]} />);
    act(() => {
      latest().emit("run", { status: "succeeded", outcome: "fixed" });
    });
    // The hook forwards the raw status; the viewer applies effectiveStatus.
    expect(screen.getByTestId("status").textContent).toBe("succeeded");
  });
});
