import type { NextRequest } from "next/server";

import { createServerClient } from "@/lib/supabase/server";
import { getRunEventsAfterSeq, getRunById } from "@/lib/supabase/queries";
import { effectiveStatus } from "@/lib/domain/status";
import {
  createStreamResponse,
  isTerminalStatus,
  type RealtimeLike,
  type RelayEventRow,
  type StreamDeps,
} from "@/lib/sse/relay";
import type { RunEventRow, VRunRow } from "@/lib/supabase/types";

/**
 * SSE live-tail relay — `GET /api/runs/[id]/events/stream` (Story S-110, FR12).
 *
 * Route-segment config is declared **inline** (S-104 audit D4 / §12): a stream
 * must never be cached or statically rendered. This is the panel's only
 * `text/event-stream` endpoint, and the one server-side Supabase Realtime
 * subscription — the browser holds no credentials (SD2).
 *
 * The relay engine (`lib/sse/relay.ts`) owns the SD6 sequencing (backfill →
 * subscribe → dedupe) and the SR5 open/close logging; this adapter supplies the
 * production dependencies: a Supabase-backed backfill, a terminal-status probe
 * derived through the shared `effectiveStatus` (SD4), and a Supabase Realtime
 * channel scoped to this run.
 */
export const dynamic = "force-dynamic";
export const revalidate = 0;
export const fetchCache = "force-no-store";
export const runtime = "nodejs";

const HEARTBEAT_MS = 15_000;

/** Parse `after_seq` from the query — non-negative integer, else 0 (CT-2/CT-3). */
export function parseAfterSeq(raw: string | null): number {
  if (raw === null) return 0;
  const n = Number(raw);
  if (!Number.isFinite(n) || n < 0) return 0;
  return Math.floor(n);
}

/** The subset of a run row the relay's terminal probe needs. */
function isRunTerminal(run: VRunRow, nowMs: number): string | null {
  const status = effectiveStatus(
    {
      status: run.status,
      startedAtMs: run.started_at ? Date.parse(run.started_at) : null,
      queuedAtMs: Date.parse(run.queued_at),
      maxRuntimeSeconds: run.max_runtime_seconds,
      graceSeconds: run.grace_seconds,
      startTimeoutSeconds: run.start_timeout_seconds,
    },
    nowMs,
  );
  return isTerminalStatus(status) ? status : null;
}

/** Project a `run_events` row into the relay's event shape (carries `seq`). */
function toRelayRow(e: RunEventRow): RelayEventRow {
  return {
    seq: e.seq,
    id: e.id,
    ts: e.ts,
    level: e.level,
    message: e.message,
    step_id: e.step_id,
  };
}

export async function GET(request: NextRequest, ctx: { params: Promise<{ id: string }> }) {
  const { id: runId } = await ctx.params;
  const afterSeq = parseAfterSeq(request.nextUrl.searchParams.get("after_seq"));

  // One client for the connection's lifetime (backfill + terminal probe +
  // Realtime). force-dynamic guarantees this request does not share it.
  const client = createServerClient();

  const deps: StreamDeps = {
    backfill: async (id, after) => {
      const rows = await getRunEventsAfterSeq(client, id, after);
      return rows.map(toRelayRow);
    },
    isTerminal: async (id) => {
      const run = await getRunById(client, id);
      // Unknown run id → treat as terminal with an explicit reason so the
      // stream closes cleanly instead of hanging (EC-13).
      if (run === null) return "not_found";
      return isRunTerminal(run, Date.now());
    },
    openChannel: (id) => wrapSupabaseChannel(client, id),
    heartbeatMs: HEARTBEAT_MS,
    log: (msg, fields) => {
      // Structured JSON to stdout (Fly captures it, §13). Open/close pair keyed
      // by run_id + last seq so a subscription imbalance is diagnosable (SR5).
      console.log(JSON.stringify({ event: msg, ...fields }));
    },
  };

  return createStreamResponse(runId, afterSeq, deps, request.signal);
}

/**
 * Adapt a Supabase Realtime channel to the relay's `RealtimeLike` shape. The
 * server holds the subscription; the browser never touches Supabase (SD2).
 * Subscribes to `run_events` INSERTs (new log lines) and `runs` UPDATEs (status
 * changes) filtered to this run id.
 */
function wrapSupabaseChannel(
  client: ReturnType<typeof createServerClient>,
  runId: string,
): RealtimeLike {
  const channel = client.channel(`run-stream:${runId}`);
  let eventCb: ((row: RelayEventRow) => void) | null = null;
  let runCb: ((row: Record<string, unknown>) => void) | null = null;

  const wrapper: RealtimeLike = {
    onEvent(cb) {
      eventCb = cb;
      return wrapper;
    },
    onRun(cb) {
      runCb = cb;
      return wrapper;
    },
    subscribe() {
      channel
        .on(
          "postgres_changes",
          { event: "INSERT", schema: "public", table: "run_events", filter: `run_id=eq.${runId}` },
          (payload: { new: Record<string, unknown> }) => {
            const row = payload.new as unknown as RunEventRow;
            eventCb?.(toRelayRow(row));
          },
        )
        .on(
          "postgres_changes",
          { event: "UPDATE", schema: "public", table: "runs", filter: `id=eq.${runId}` },
          (payload: { new: Record<string, unknown> }) => {
            runCb?.(payload.new);
          },
        )
        .subscribe();
      return wrapper;
    },
    unsubscribe() {
      void client.removeChannel(channel);
    },
  };
  return wrapper;
}
