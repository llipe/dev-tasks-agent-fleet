/**
 * SSE relay core (Story S-110) — the dependency-injected engine behind
 * `app/api/runs/[id]/events/stream/route.ts`.
 *
 * Kept free of Next.js and Supabase specifics so it is testable with a fake
 * clock and a fake Realtime channel. The route adapter supplies the production
 * dependencies (a Supabase-backed backfill, a terminal-status probe, and a
 * Supabase Realtime channel); this module owns the SD6 sequencing and the SR5
 * lifecycle logging.
 *
 * Sequencing contract (SD6, AC2):
 *  1. Backfill `seq > after_seq` FIRST and emit those rows in order.
 *  2. THEN open the Realtime subscription.
 *  3. Drop any pushed row whose `seq` is at or below the highest already sent.
 *
 * Lifecycle contract (SR5, AC7): open and close are logged as a pair carrying
 * `run_id` and the last `seq`; the subscription is unsubscribed exactly once on
 * terminal state or on request `abort`.
 */

import { SeqCursor, dedupeAndOrder } from "@/lib/sse/cursor";
import { serializeFrame } from "@/lib/sse/serialize";

/** A `run_events` row as the relay needs it: a `seq` plus the payload. */
export interface RelayEventRow {
  seq: number;
  [key: string]: unknown;
}

/**
 * The minimal Realtime channel the relay drives. The route adapter wraps a
 * Supabase `RealtimeChannel`; the test supplies a fake with the same shape.
 */
export interface RealtimeLike {
  onEvent(cb: (row: RelayEventRow) => void): this;
  onRun(cb: (row: Record<string, unknown>) => void): this;
  subscribe(): this;
  unsubscribe(): void;
}

/** Injectable dependencies — production values come from the route adapter. */
export interface StreamDeps {
  /** Read `run_events` with `seq > afterSeq`, ascending. */
  backfill: (runId: string, afterSeq: number) => Promise<RelayEventRow[]>;
  /**
   * Resolve the run's terminal reason if it is already terminal at connect (so
   * the relay can emit `closed` immediately and never open a subscription), or
   * null when the run is still live.
   */
  isTerminal: (runId: string) => Promise<string | null>;
  /** Open a Realtime channel scoped to this run's `run_events` + `runs`. */
  openChannel: (runId: string) => RealtimeLike;
  /** Heartbeat cadence in ms (15_000 in production). */
  heartbeatMs: number;
  /** Structured logger (stdout JSON in production). */
  log: (msg: "sse_open" | "sse_close", fields: Record<string, unknown>) => void;
}

const TERMINAL_STATUSES = new Set([
  "succeeded",
  "failed",
  "canceled",
  "timed_out",
  "failed_to_start",
]);

/** Whether a `runs.status` value is terminal (the relay closes on these). */
export function isTerminalStatus(status: unknown): status is string {
  return typeof status === "string" && TERMINAL_STATUSES.has(status);
}

/**
 * Build the SSE `Response`. Starts the backfill→subscribe→relay pipeline inside
 * a `ReadableStream`, registers cleanup on `signal.abort`, and returns
 * immediately with the streaming body.
 */
export function createStreamResponse(
  runId: string,
  afterSeq: number,
  deps: StreamDeps,
  signal: AbortSignal,
): Response {
  const encoder = new TextEncoder();
  const cursor = new SeqCursor(afterSeq);

  let channel: RealtimeLike | null = null;
  let heartbeat: ReturnType<typeof setInterval> | null = null;
  let closed = false;

  const stream = new ReadableStream<Uint8Array>({
    start(controller) {
      const emit = (event: Parameters<typeof serializeFrame>[0], data: unknown) => {
        if (closed) return;
        controller.enqueue(encoder.encode(serializeFrame(event, data)));
      };

      const cleanup = (reason: string | null) => {
        if (closed) return;
        closed = true;
        if (heartbeat !== null) clearInterval(heartbeat);
        if (channel !== null) channel.unsubscribe();
        deps.log("sse_close", { run_id: runId, last_seq: cursor.highest, reason });
        try {
          controller.close();
        } catch {
          // Already closed by the runtime (e.g. client vanished) — ignore.
        }
      };

      const closeWithReason = (reason: string) => {
        if (closed) return;
        emit("closed", { reason });
        cleanup(reason);
      };

      // Abort (client disconnect / request torn down) — unsubscribe once.
      signal.addEventListener("abort", () => cleanup(null), { once: true });

      deps.log("sse_open", { run_id: runId, after_seq: cursor.highest });

      void (async () => {
        // 1. Backfill FIRST (SD6 step 1).
        const rows = await deps.backfill(runId, cursor.highest);
        if (closed || signal.aborted) {
          cleanup(null);
          return;
        }
        for (const row of dedupeAndOrder(rows, cursor.highest)) {
          if (cursor.admit(row.seq)) emit("event", row);
        }

        // If the run is already terminal, emit closed and never subscribe (EC-3).
        const terminalReason = await deps.isTerminal(runId);
        if (closed || signal.aborted) {
          cleanup(null);
          return;
        }
        if (terminalReason !== null) {
          closeWithReason(terminalReason);
          return;
        }

        // 2. THEN subscribe (SD6 step 2).
        channel = deps
          .openChannel(runId)
          .onEvent((row) => {
            // 3. Drop at/below the highest already sent (SD6 step 3).
            if (cursor.admit(row.seq)) emit("event", row);
          })
          .onRun((row) => {
            emit("run", row);
            if (isTerminalStatus(row.status)) {
              closeWithReason(row.status as string);
            }
          })
          .subscribe();

        // Heartbeat so an intermediary does not idle the connection out.
        heartbeat = setInterval(() => emit("heartbeat", {}), deps.heartbeatMs);
      })();
    },
    cancel() {
      // Reader cancelled (client went away) — same teardown as abort.
      if (closed) return;
      closed = true;
      if (heartbeat !== null) clearInterval(heartbeat);
      if (channel !== null) channel.unsubscribe();
      deps.log("sse_close", { run_id: runId, last_seq: cursor.highest, reason: null });
    },
  });

  return new Response(stream, {
    headers: {
      "content-type": "text/event-stream; charset=utf-8",
      "cache-control": "no-cache, no-transform",
      connection: "keep-alive",
    },
  });
}
