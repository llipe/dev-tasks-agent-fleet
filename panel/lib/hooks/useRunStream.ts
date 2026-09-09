"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { SeqCursor } from "@/lib/sse/cursor";
import type { LogLineView } from "@/lib/domain/run-detail";
import type { RunStatus } from "@/lib/domain/status";

/**
 * Client live-tail hook (Story S-110, AC4/AC5).
 *
 * Subscribes to `GET /api/runs/[id]/events/stream` via `EventSource` and:
 *  - appends incoming `event` frames, de-duplicating by `seq` on the client too
 *    (a reconnect overlap or an out-of-order push must not double-render — the
 *    same SD6 invariant the server enforces, applied defensively here);
 *  - tracks the highest rendered `seq` and, on an UNEXPECTED drop, reconnects
 *    with it as `after_seq` so no line is lost;
 *  - stops reconnecting once the server sends `closed` (the run is terminal);
 *  - exposes the latest raw `run` status. It does NOT derive the effective
 *    status — the viewer applies `effectiveStatus` (SD4/AC5) so a `running`
 *    push cannot overwrite a derived `timed_out`.
 *
 * `eventSourceFactory` is injected so the hook is testable with a fake source.
 */

/** A `run_events` row as it arrives over the wire (carries `seq`). */
interface StreamEventRow {
  id: number;
  seq: number;
  ts: string;
  level: string;
  message: string;
  step_id: string | null;
}

export interface UseRunStreamArgs {
  runId: string;
  /** Server-rendered initial window (ascending by `seq`). */
  initialLines: LogLineView[];
  /** The run's status at page render (raw). */
  initialStatus: RunStatus | (string & {});
  /** Injectable for tests; defaults to the global `EventSource`. */
  eventSourceFactory?: (url: string) => EventSource;
  /** Timezone for the appended line clock (matches the server render). */
  timeZone?: string;
}

export interface UseRunStreamResult {
  lines: LogLineView[];
  /** The latest RAW status from a `run` push (or the initial). */
  status: RunStatus | (string & {});
  /** True while an EventSource is open and not yet `closed`. */
  connected: boolean;
  /** The reason from the terminal `closed` frame, once received. */
  closedReason: string | null;
  /**
   * True once the hook has stopped for an authorization failure (Story S-121).
   *
   * A denied SSE connection surfaces as `onerror` with the stream having NEVER
   * opened for the current attempt (`EventSource` cannot send headers, so the
   * gate returns a plain `401` BEFORE a `text/event-stream` response opens —
   * spec OQ3). That "never opened" signal is terminal: the hook stops and does
   * NOT reconnect, so an expired session cannot produce an infinite 401
   * reconnect loop. The viewer surfaces a session-expired notice on this flag.
   */
  authStopped: boolean;
}

function streamUrl(runId: string, afterSeq: number): string {
  return `/api/runs/${encodeURIComponent(runId)}/events/stream?after_seq=${afterSeq}`;
}

/**
 * `EventSource.CLOSED` numeric value (Story S-121). Defined as a local constant
 * rather than referencing `EventSource.CLOSED` so the check is safe when the
 * global `EventSource` is undefined (SSR/node) and stable across fakes.
 */
const EVENT_SOURCE_CLOSED = 2;

function toLogLine(row: StreamEventRow, timeZone: string): LogLineView {
  // Kept lightweight: the appended clock uses the same formatter the server
  // used. Step labeling is best-effort ("" when unknown) — live lines rarely
  // resolve a step title client-side, and the grid tolerates an empty step.
  const date = new Date(row.ts);
  const timestamp = Number.isNaN(date.getTime())
    ? ""
    : date.toLocaleTimeString("en-GB", { hour12: false, timeZone });
  return {
    id: row.id,
    seq: row.seq,
    timestamp,
    level: row.level,
    step: "",
    message: row.message,
  };
}

export function useRunStream({
  runId,
  initialLines,
  initialStatus,
  eventSourceFactory,
  timeZone = "UTC",
}: UseRunStreamArgs): UseRunStreamResult {
  const [lines, setLines] = useState<LogLineView[]>(initialLines);
  const [status, setStatus] = useState<RunStatus | (string & {})>(initialStatus);
  const [connected, setConnected] = useState(false);
  const [closedReason, setClosedReason] = useState<string | null>(null);
  const [authStopped, setAuthStopped] = useState(false);

  // Refs so the effect's callbacks always see current values without
  // re-subscribing on every render.
  const cursorRef = useRef<SeqCursor>(
    new SeqCursor(initialLines.length > 0 ? initialLines[initialLines.length - 1].seq : 0),
  );
  const sourceRef = useRef<EventSource | null>(null);
  const closedRef = useRef(false);
  // Story S-121: whether the CURRENT attempt ever opened. Reset on every
  // connect(). A real EventSource fires `onopen` on the 200 response before any
  // frame; receiving any frame therefore also implies "opened". A 401 arrives
  // as `onerror` with this still false and readyState === CLOSED.
  const openedRef = useRef(false);
  const factoryRef = useRef(eventSourceFactory);
  factoryRef.current = eventSourceFactory;

  const connect = useCallback(() => {
    if (closedRef.current) return;
    const globalES =
      typeof EventSource !== "undefined" ? (url: string) => new EventSource(url) : null;
    const make = factoryRef.current ?? globalES;
    // No EventSource available (SSR, or a test env without one) and no injected
    // factory — nothing to connect. The server-rendered lines still show.
    if (make === null) return;
    // New attempt: it has not opened yet.
    openedRef.current = false;
    const es = make(streamUrl(runId, cursorRef.current.highest));
    sourceRef.current = es;
    setConnected(true);

    es.onopen = () => {
      // The 200 text/event-stream response opened — this attempt is authorized.
      openedRef.current = true;
    };

    es.addEventListener("event", (ev: MessageEvent) => {
      // A frame can only arrive after the stream opened; record it defensively
      // in case a fake/real source delivers a frame without firing `onopen`.
      openedRef.current = true;
      const row = JSON.parse(ev.data) as StreamEventRow;
      // Client-side dedupe/order guard (defensive; the server already dedupes).
      if (!cursorRef.current.admit(row.seq)) return;
      setLines((prev) => [...prev, toLogLine(row, timeZone)]);
    });

    es.addEventListener("run", (ev: MessageEvent) => {
      openedRef.current = true;
      const row = JSON.parse(ev.data) as { status?: string };
      if (typeof row.status === "string") setStatus(row.status);
    });

    es.addEventListener("closed", (ev: MessageEvent) => {
      const row = JSON.parse(ev.data) as { reason?: string };
      closedRef.current = true;
      setClosedReason(row.reason ?? "closed");
      setConnected(false);
      es.close();
    });

    es.onerror = () => {
      // A terminal `closed` already tore us down — do not reconnect (S-110 AC4).
      if (closedRef.current) return;

      // Story S-121: an error on an attempt that NEVER opened, with the source
      // now CLOSED, is an authorization failure (the gate's plain 401 before the
      // stream opens — spec OQ3). This is TERMINAL: stop, do NOT reconnect, and
      // do NOT schedule any timer, so an expired session cannot loop forever.
      if (!openedRef.current && es.readyState === EVENT_SOURCE_CLOSED) {
        closedRef.current = true;
        es.close();
        sourceRef.current = null;
        setConnected(false);
        setAuthStopped(true);
        return;
      }

      // Genuine mid-stream drop (the stream HAD opened): close this source and
      // reopen with the highest rendered seq as after_seq, so no line is lost
      // (S-110 AC4/SC-6). Existing seq dedupe (SeqCursor) prevents duplicates.
      es.close();
      setConnected(false);
      connect();
    };
  }, [runId, timeZone]);

  useEffect(() => {
    closedRef.current = false;
    connect();
    return () => {
      closedRef.current = true;
      sourceRef.current?.close();
      sourceRef.current = null;
    };
  }, [connect]);

  return { lines, status, connected, closedReason, authStopped };
}
