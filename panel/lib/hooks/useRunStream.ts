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
}

function streamUrl(runId: string, afterSeq: number): string {
  return `/api/runs/${encodeURIComponent(runId)}/events/stream?after_seq=${afterSeq}`;
}

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

  // Refs so the effect's callbacks always see current values without
  // re-subscribing on every render.
  const cursorRef = useRef<SeqCursor>(
    new SeqCursor(initialLines.length > 0 ? initialLines[initialLines.length - 1].seq : 0),
  );
  const sourceRef = useRef<EventSource | null>(null);
  const closedRef = useRef(false);
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
    const es = make(streamUrl(runId, cursorRef.current.highest));
    sourceRef.current = es;
    setConnected(true);

    es.addEventListener("event", (ev: MessageEvent) => {
      const row = JSON.parse(ev.data) as StreamEventRow;
      // Client-side dedupe/order guard (defensive; the server already dedupes).
      if (!cursorRef.current.admit(row.seq)) return;
      setLines((prev) => [...prev, toLogLine(row, timeZone)]);
    });

    es.addEventListener("run", (ev: MessageEvent) => {
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
      // A terminal `closed` already tore us down — do not reconnect (AC4).
      if (closedRef.current) return;
      // Unexpected drop: close this source and reopen with the highest rendered
      // seq as after_seq, so no line is lost (AC4/SC-6).
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

  return { lines, status, connected, closedReason };
}
