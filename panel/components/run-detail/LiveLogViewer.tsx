"use client";

import { useCallback, useLayoutEffect, useRef, useState } from "react";

import { LogLine } from "@/components/LogLine";
import { StatusPill } from "@/components/StatusPill";
import { useRunStream } from "@/lib/hooks/useRunStream";
import { effectiveStatus, type RunStatus } from "@/lib/domain/status";
import { shouldAutoScroll } from "@/lib/sse/autoscroll";
import type { LogLineView } from "@/lib/domain/run-detail";

import { LiveTailButton } from "./LiveTailButton";
import styles from "./LogViewer.module.css";

/**
 * LiveLogViewer (Story S-110) — the client viewer that tails a run live.
 *
 * Joins `useRunStream` (the SSE hook) to the S-109 log grid and adds the two
 * live behaviors S-109 deliberately deferred:
 *  - **AC5 — live status via `effectiveStatus`.** The pill shows the status
 *    derived from the run snapshot at the current instant, NOT the raw status a
 *    `run` push carries. A late `running` push on an expired run therefore
 *    still reads `timed_out` (SD4). The derivation is the shared one; it is
 *    never restated here.
 *  - **AC6 — auto-scroll / pause / resume (/DESIGN.md §6.6).** New lines follow
 *    the scroll only while within 24px of the bottom; scrolling up pauses and
 *    the live-tail control shows the paused state; clicking it resumes and
 *    re-scrolls to the bottom.
 *
 * The message is rendered by the `LogLine` primitive as an inert text node —
 * never `dangerouslySetInnerHTML` (security guard #6, SC-12).
 *
 * This is used for runs that may still be live. A terminal run needs no live
 * behavior and the server-rendered `LogViewer` suffices.
 */

export interface LiveLogViewerProps {
  runId: string;
  initialLines: LogLineView[];
  /** Raw run status at render (the hook forwards raw; we derive here). */
  initialStatus: RunStatus | (string & {});
  /** Run snapshot fields needed to derive `effectiveStatus` (SD4). */
  maxRuntimeSeconds: number | null;
  graceSeconds: number | null;
  startTimeoutSeconds: number | null;
  startedAtMs: number | null;
  queuedAtMs: number | null;
  /** Injectable for tests; defaults to the global EventSource. */
  eventSourceFactory?: (url: string) => EventSource;
  timeZone?: string;
}

export function LiveLogViewer({
  runId,
  initialLines,
  initialStatus,
  maxRuntimeSeconds,
  graceSeconds,
  startTimeoutSeconds,
  startedAtMs,
  queuedAtMs,
  eventSourceFactory,
  timeZone = "UTC",
}: LiveLogViewerProps) {
  const { lines, status, connected, closedReason } = useRunStream({
    runId,
    initialLines,
    initialStatus,
    eventSourceFactory,
    timeZone,
  });

  // AC5 — derive the displayed status through the shared effectiveStatus, so a
  // raw `running` push on an expired run cannot present as running. Recomputed
  // at the current instant on each render while the run is live.
  const derived = effectiveStatus(
    {
      status,
      startedAtMs,
      queuedAtMs,
      maxRuntimeSeconds,
      graceSeconds,
      startTimeoutSeconds,
    },
    Date.now(),
  );

  // AC6 — follow state. `following` is true while the log auto-scrolls; it
  // flips to false when the user scrolls up past the 24px threshold and back to
  // true when they click the live-tail control (which re-pins to the bottom).
  const [following, setFollowing] = useState(true);
  const logRef = useRef<HTMLDivElement | null>(null);

  const onScroll = useCallback(() => {
    const el = logRef.current;
    if (el === null) return;
    setFollowing(shouldAutoScroll(el));
  }, []);

  const resume = useCallback(() => {
    const el = logRef.current;
    if (el !== null) el.scrollTop = el.scrollHeight;
    setFollowing(true);
  }, []);

  // After each new line, if following, pin to the bottom (§6.6).
  useLayoutEffect(() => {
    const el = logRef.current;
    if (el !== null && following) el.scrollTop = el.scrollHeight;
  }, [lines, following]);

  // If the stream closes, following is meaningless — drop the control.
  const isLive = connected && closedReason === null;

  return (
    <div className={styles.viewer}>
      <div className={styles.liveBar}>
        <StatusPill status={derived} />
        {isLive && <LiveTailButton following={following} onResume={resume} />}
      </div>
      <div
        className={styles.log}
        role="log"
        aria-live="polite"
        aria-label="Run log"
        data-sse-mount="run-log"
        ref={logRef}
        onScroll={onScroll}
      >
        {lines.length === 0 ? (
          <p className={styles.empty}>No log events for this run.</p>
        ) : (
          lines.map((l) => (
            <LogLine
              key={l.id}
              timestamp={l.timestamp}
              level={l.level}
              step={l.step}
              message={l.message}
            />
          ))
        )}
      </div>
    </div>
  );
}
