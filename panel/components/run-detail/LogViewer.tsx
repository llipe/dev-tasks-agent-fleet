"use client";

import { useCallback, useState } from "react";

import { LogLine } from "@/components/LogLine";
import { priorWindowRange, LOG_WINDOW_SIZE, type SeqEvent } from "@/lib/domain/log-window";
import type { LogLineView } from "@/lib/domain/run-detail";

import styles from "./LogViewer.module.css";

/**
 * LogViewer — /DESIGN.md §3.6 + §5.3. The 4-column log grid (time / level /
 * step / message) rendered from `run_events`, ordered by `seq`.
 *
 * Behavioral contracts this component carries:
 *  - **AC7 / security guard #6:** every message is rendered as an inert text
 *    node via the `LogLine` primitive — never `dangerouslySetInnerHTML`. HTML
 *    or script content in a message displays literally.
 *  - **AC8:** the scroll region is `aria-live="polite"` so appended lines are
 *    announced (matters for S-110's live tail).
 *  - **AC5:** when earlier events exist, a "load earlier" control fetches the
 *    prior window via the injected `loadEarlier` action, prepending the result.
 *  - **S-110 forward-compat:** a stable SSE mount point (`data-sse-mount`) is
 *    left in the markup so the live-tail story attaches without restructuring.
 *
 * The component is client-side only for the "load earlier" interaction; the
 * initial window is server-rendered. `loadEarlier` is injected so the component
 * is testable without a server round-trip.
 */

export interface LogViewerProps {
  /** The initial (most-recent) window, ascending by `seq`. */
  initialLines: LogLineView[];
  /** True when events older than the oldest loaded line exist. */
  hasEarlier: boolean;
  /** The oldest `seq` currently loaded (the load-earlier cursor). */
  oldestSeq: number | null;
  /**
   * Fetch a prior window by inclusive `seq` range. Returns the lines ascending
   * by `seq`. Injected (a server action on the page) so this stays testable.
   */
  loadEarlier: (fromSeq: number, toSeq: number) => Promise<LogLineView[]>;
}

export function LogViewer({ initialLines, hasEarlier, oldestSeq, loadEarlier }: LogViewerProps) {
  const [lines, setLines] = useState<LogLineView[]>(initialLines);
  const [cursor, setCursor] = useState<number | null>(oldestSeq);
  const [more, setMore] = useState<boolean>(hasEarlier);
  const [loading, setLoading] = useState(false);

  const onLoadEarlier = useCallback(async () => {
    if (cursor == null || loading) return;
    const range = priorWindowRange(cursor, LOG_WINDOW_SIZE);
    if (range === null) {
      setMore(false);
      return;
    }
    setLoading(true);
    try {
      const earlier = await loadEarlier(range.fromSeq, range.toSeq);
      if (earlier.length > 0) {
        setLines((prev) => dedupeBySeq([...earlier, ...prev]));
        setCursor(earlier[0].seq);
      }
      // Anything below the fetched fromSeq only exists if we did not reach 1.
      setMore(range.fromSeq > 1);
    } finally {
      setLoading(false);
    }
  }, [cursor, loading, loadEarlier]);

  return (
    <div className={styles.viewer}>
      {more && (
        <div className={styles.earlierBar}>
          <button
            type="button"
            className={styles.earlierButton}
            onClick={onLoadEarlier}
            disabled={loading}
          >
            {loading ? "Loading…" : "Load earlier"}
          </button>
        </div>
      )}
      <div
        className={styles.log}
        role="log"
        aria-live="polite"
        aria-label="Run log"
        data-sse-mount="run-log"
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

/** De-duplicate by `seq`, keeping first occurrence, preserving order. */
function dedupeBySeq<T extends SeqEvent>(items: T[]): T[] {
  const seen = new Set<number>();
  const out: T[] = [];
  for (const item of items) {
    if (seen.has(item.seq)) continue;
    seen.add(item.seq);
    out.push(item);
  }
  return out;
}
