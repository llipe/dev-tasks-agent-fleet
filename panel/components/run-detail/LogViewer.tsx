"use client";

import { useCallback, useMemo, useState } from "react";

import { LogLine } from "@/components/LogLine";
import { priorWindowRange, LOG_WINDOW_SIZE, type SeqEvent } from "@/lib/domain/log-window";
import type { LogLineView } from "@/lib/domain/run-detail";
import { applyLogFilter, NO_LOG_FILTER, type LogFilterState } from "@/lib/domain/log-filter";

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
  /**
   * The step + log-level filter (Story S-145, FR10/FR11), applied client-side
   * over the loaded window via `applyLogFilter` — never re-fetches. Optional
   * for backward compatibility with call sites that predate S-145; defaults to
   * `NO_LOG_FILTER` (the full, unfiltered tail).
   */
  filter?: LogFilterState;
}

export function LogViewer({
  initialLines,
  hasEarlier,
  oldestSeq,
  loadEarlier,
  filter = NO_LOG_FILTER,
}: LogViewerProps) {
  const [lines, setLines] = useState<LogLineView[]>(initialLines);
  const [cursor, setCursor] = useState<number | null>(oldestSeq);
  const [more, setMore] = useState<boolean>(hasEarlier);
  const [loading, setLoading] = useState(false);

  // The filter never mutates `lines` (the "load earlier"/pagination state
  // above stays over the FULL loaded window) — only what is RENDERED narrows.
  const filteredLines = useMemo(() => applyLogFilter(lines, filter), [lines, filter]);
  const filterActive = filter.stepId !== null || filter.level !== "all";

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
        {filteredLines.length === 0 ? (
          <p className={styles.empty}>
            {filterActive && lines.length > 0
              ? "No log lines match the current filter."
              : "No log events for this run."}
          </p>
        ) : (
          filteredLines.map((l) => (
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
