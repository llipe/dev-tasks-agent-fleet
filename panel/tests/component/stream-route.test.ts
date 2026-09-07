import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { parseFrames } from "@/lib/sse/serialize";
import {
  createStreamResponse,
  type StreamDeps,
  type RealtimeLike,
  type RelayEventRow,
} from "@/lib/sse/relay";

/**
 * SSE relay route handler (Story S-110) — component tests with Supabase and
 * Realtime mocked. The handler logic lives in `lib/sse/relay.ts` (a pure,
 * dependency-injected core) so `app/api/runs/[id]/events/stream/route.ts` stays
 * a thin adapter; testing the core here avoids fighting the Next.js runtime.
 *
 * Covers: backfill-before-subscribe + dedupe (AC2), four event types + closed
 * payload (AC3/CT-5), heartbeat cadence (EC-10), unsubscribe on abort (AC7/EC-8),
 * open/close log pair (AC7/SR5), terminal-at-connect (EC-3), burst (EC-12).
 */

interface FakeRow {
  seq: number;
  message: string;
  [key: string]: unknown;
}

/** A controllable fake Realtime channel matching the shape the relay uses. */
class FakeChannel implements RealtimeLike {
  eventHandler: ((row: RelayEventRow) => void) | null = null;
  runHandler: ((row: Record<string, unknown>) => void) | null = null;
  subscribed = false;
  unsubscribed = 0;

  onEvent(cb: (row: RelayEventRow) => void): this {
    this.eventHandler = cb;
    return this;
  }
  onRun(cb: (row: Record<string, unknown>) => void): this {
    this.runHandler = cb;
    return this;
  }
  subscribe(): this {
    this.subscribed = true;
    return this;
  }
  unsubscribe(): void {
    this.unsubscribed += 1;
  }
  pushEvent(row: FakeRow) {
    this.eventHandler?.(row);
  }
  pushRun(row: Record<string, unknown>) {
    this.runHandler?.(row);
  }
}

function makeDeps(overrides: Partial<StreamDeps> = {}): {
  deps: StreamDeps;
  channel: FakeChannel;
  logs: Array<{ msg: string; fields: Record<string, unknown> }>;
} {
  const channel = new FakeChannel();
  const logs: Array<{ msg: string; fields: Record<string, unknown> }> = [];
  const deps: StreamDeps = {
    backfill: vi.fn().mockResolvedValue([]),
    isTerminal: vi.fn().mockResolvedValue(null),
    openChannel: vi.fn().mockReturnValue(channel),
    heartbeatMs: 15_000,
    log: (msg, fields) => logs.push({ msg, fields }),
    ...overrides,
  };
  return { deps, channel, logs };
}

/** Read the whole SSE body of a Response into parsed frames. */
async function readAllFrames(res: Response): Promise<ReturnType<typeof parseFrames>> {
  const text = await res.text();
  return parseFrames(text);
}

/**
 * Read a stream to completion into a single string. The stream must already be
 * closing/closed (the test aborts the request or the run goes terminal first),
 * so this terminates. Reading to `done` is deterministic under fake timers —
 * no racing required.
 */
async function readToEnd(reader: ReadableStreamDefaultReader<Uint8Array>): Promise<string> {
  const decoder = new TextDecoder();
  let out = "";
  for (;;) {
    const { value, done } = await reader.read();
    if (value !== undefined) out += decoder.decode(value, { stream: true });
    if (done) break;
  }
  return out;
}

beforeEach(() => {
  vi.useFakeTimers();
});

afterEach(() => {
  vi.useRealTimers();
  vi.clearAllMocks();
});

describe("createStreamResponse", () => {
  it("returns text/event-stream (AC1)", async () => {
    const { deps } = makeDeps();
    const controller = new AbortController();
    const res = createStreamResponse("run-1", 0, deps, controller.signal);
    expect(res.headers.get("content-type")).toContain("text/event-stream");
    controller.abort();
  });

  it("backfills seq > after_seq FIRST, then subscribes (AC2, SD6)", async () => {
    const order: string[] = [];
    const { deps, channel } = makeDeps({
      backfill: vi.fn().mockImplementation(async () => {
        order.push("backfill");
        return [
          { seq: 1, message: "a" },
          { seq: 2, message: "b" },
        ];
      }),
      openChannel: vi.fn().mockImplementation(() => {
        order.push("subscribe");
        return channel;
      }),
    });
    const controller = new AbortController();
    const res = createStreamResponse("run-1", 0, deps, controller.signal);
    const reader = res.body!.getReader();
    await vi.advanceTimersByTimeAsync(0);
    controller.abort();
    const text = await readToEnd(reader);

    expect(order).toEqual(["backfill", "subscribe"]);
    const frames = parseFrames(text);
    const eventFrames = frames.filter((f) => f.event === "event");
    expect(eventFrames.map((f) => (f.data as FakeRow).seq)).toEqual([1, 2]);
  });

  it("drops a pushed row at or below the highest already sent — no duplicate (AC2, EC-5)", async () => {
    const { deps, channel } = makeDeps({
      backfill: vi.fn().mockResolvedValue([
        { seq: 1, message: "a" },
        { seq: 2, message: "b" },
      ]),
    });
    const controller = new AbortController();
    const res = createStreamResponse("run-1", 0, deps, controller.signal);
    const reader = res.body!.getReader();
    await vi.advanceTimersByTimeAsync(0);
    channel.pushEvent({ seq: 2, message: "dup" }); // duplicate
    channel.pushEvent({ seq: 3, message: "c" }); // new
    await vi.advanceTimersByTimeAsync(0);
    controller.abort();
    const text = await readToEnd(reader);

    const seqs = parseFrames(text)
      .filter((f) => f.event === "event")
      .map((f) => (f.data as FakeRow).seq);
    expect(seqs).toEqual([1, 2, 3]);
  });

  it("emits a heartbeat every 15s (AC3, EC-10)", async () => {
    const { deps } = makeDeps();
    const controller = new AbortController();
    const res = createStreamResponse("run-1", 0, deps, controller.signal);
    const reader = res.body!.getReader();
    await vi.advanceTimersByTimeAsync(0);
    await vi.advanceTimersByTimeAsync(15_000);
    controller.abort();
    const text = await readToEnd(reader);
    const beats = parseFrames(text).filter((f) => f.event === "heartbeat");
    expect(beats.length).toBeGreaterThanOrEqual(1);
  });

  it("emits closed{reason} and stops when the run is terminal at connect (AC3, EC-3, CT-5)", async () => {
    const { deps, channel } = makeDeps({
      backfill: vi.fn().mockResolvedValue([{ seq: 1, message: "done" }]),
      isTerminal: vi.fn().mockResolvedValue("succeeded"),
    });
    const controller = new AbortController();
    const res = createStreamResponse("run-1", 0, deps, controller.signal);
    await vi.advanceTimersByTimeAsync(0);
    const frames = await readAllFrames(res);

    const closed = frames.find((f) => f.event === "closed");
    expect(closed).toBeDefined();
    expect((closed!.data as { reason: string }).reason).toBe("succeeded");
    // Terminal-at-connect never opens a subscription.
    expect(channel.subscribed).toBe(false);
  });

  it("emits a run event and a closed event when a run transitions to terminal (AC3)", async () => {
    const { deps, channel } = makeDeps();
    const controller = new AbortController();
    const res = createStreamResponse("run-1", 0, deps, controller.signal);
    const reader = res.body!.getReader();
    await vi.advanceTimersByTimeAsync(0);
    channel.pushRun({ status: "succeeded", outcome: "fixed", finished_at: "2026-01-01T00:00:00Z" });
    await vi.advanceTimersByTimeAsync(0);
    const text = await readToEnd(reader);

    const frames = parseFrames(text);
    expect(frames.some((f) => f.event === "run")).toBe(true);
    const closed = frames.find((f) => f.event === "closed");
    expect(closed).toBeDefined();
    expect((closed!.data as { reason: string }).reason).toBe("succeeded");
  });

  it("unsubscribes on request abort and logs a balanced open/close pair (AC7, EC-8, SR5)", async () => {
    const { deps, channel, logs } = makeDeps();
    const controller = new AbortController();
    createStreamResponse("run-42", 5, deps, controller.signal);
    await vi.advanceTimersByTimeAsync(0);
    expect(channel.subscribed).toBe(true);

    controller.abort();
    await vi.advanceTimersByTimeAsync(0);

    expect(channel.unsubscribed).toBe(1);
    const opens = logs.filter((l) => l.msg === "sse_open");
    const closes = logs.filter((l) => l.msg === "sse_close");
    expect(opens).toHaveLength(1);
    expect(closes).toHaveLength(1);
    // Both carry run_id and last seq (SR5).
    expect(opens[0].fields.run_id).toBe("run-42");
    expect(closes[0].fields.run_id).toBe("run-42");
    expect(closes[0].fields.last_seq).toBeGreaterThanOrEqual(5);
  });

  it("does not leak a subscription when aborted mid-backfill (EC-8)", async () => {
    let resolveBackfill!: (rows: FakeRow[]) => void;
    const { deps, channel } = makeDeps({
      backfill: vi.fn().mockReturnValue(
        new Promise<FakeRow[]>((r) => {
          resolveBackfill = r;
        }),
      ),
    });
    const controller = new AbortController();
    createStreamResponse("run-1", 0, deps, controller.signal);
    await vi.advanceTimersByTimeAsync(0);
    // Abort while backfill is still pending (subscription not yet opened).
    controller.abort();
    resolveBackfill([{ seq: 1, message: "late" }]);
    await vi.advanceTimersByTimeAsync(0);
    // Never subscribed, so nothing to leak; if it did subscribe, it unsubscribed.
    expect(channel.subscribed ? channel.unsubscribed : 0).toBe(channel.subscribed ? 1 : 0);
  });

  it("relays a burst of 200 events in one flush, once each in seq order (EC-12)", async () => {
    const { deps, channel } = makeDeps();
    const controller = new AbortController();
    const res = createStreamResponse("run-1", 0, deps, controller.signal);
    const reader = res.body!.getReader();
    await vi.advanceTimersByTimeAsync(0);
    for (let s = 1; s <= 200; s++) channel.pushEvent({ seq: s, message: `m${s}` });
    await vi.advanceTimersByTimeAsync(0);
    controller.abort();
    const text = await readToEnd(reader);

    const seqs = parseFrames(text)
      .filter((f) => f.event === "event")
      .map((f) => (f.data as FakeRow).seq);
    expect(seqs).toHaveLength(200);
    expect(seqs).toEqual([...Array(200)].map((_, i) => i + 1));
  });
});
