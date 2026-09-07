/**
 * Bounded log-window math (SD11) — pure, testable at exact boundaries.
 *
 * `run_events` is the largest table by two orders of magnitude (R3), so the
 * run-detail viewer never renders an unbounded log. The initial fetch is bounded
 * at the most recent `LOG_WINDOW_SIZE` events (the bound is on the RECENT end:
 * the query reads `seq desc` then reverses for display). If earlier events
 * exist, a "load earlier" control fetches the window immediately before what is
 * loaded.
 *
 * This module is the pure arithmetic behind that behavior; it does no I/O. The
 * query layer (`getRunEvents`, and the load-earlier variant) applies these
 * ranges against PostgREST.
 */

/** SD11 — the bounded initial `run_events` window. Mirrors RUN_EVENTS_READ_LIMIT. */
export const LOG_WINDOW_SIZE = 2000;

/** The minimal shape the window math needs: a monotonic `seq`. */
export interface SeqEvent {
  seq: number;
}

export interface RecentWindow<T extends SeqEvent> {
  /** The selected events, ascending by `seq` (reading order). */
  events: T[];
  /** True when events older than `oldestSeq` exist (show "load earlier"). */
  hasEarlier: boolean;
  /** The lowest `seq` in the window, or null when the window is empty. */
  oldestSeq: number | null;
}

/**
 * Select the most-recent `size` events from `all`, returned ascending by `seq`.
 *
 * Input order is not trusted — the agent buffers, so arrival order is not
 * emission order (D5); the selection sorts by `seq` first. When `all` holds
 * more than `size` events, the oldest are dropped and `hasEarlier` is true.
 */
export function selectRecentWindow<T extends SeqEvent>(all: T[], size: number): RecentWindow<T> {
  const sorted = [...all].sort((a, b) => a.seq - b.seq);
  const hasEarlier = sorted.length > size;
  const events = hasEarlier ? sorted.slice(sorted.length - size) : sorted;
  const oldestSeq = events.length > 0 ? events[0].seq : null;
  return { events, hasEarlier, oldestSeq };
}

/** An inclusive `seq` range to fetch for a "load earlier" step. */
export interface SeqRange {
  fromSeq: number;
  toSeq: number;
}

/**
 * The `seq` range of the window immediately before the currently-loaded window,
 * given the oldest `seq` already loaded. Returns null when nothing precedes it
 * (the oldest loaded event is `seq = 1`, or the input is non-positive).
 *
 * The range is [oldestLoadedSeq - size, oldestLoadedSeq - 1], clamped so
 * `fromSeq` never drops below 1. It is exactly contiguous with the loaded
 * window (`toSeq = oldestLoadedSeq - 1`) so the union has no gap and no overlap.
 */
export function priorWindowRange(oldestLoadedSeq: number, size: number): SeqRange | null {
  if (oldestLoadedSeq <= 1) return null;
  const toSeq = oldestLoadedSeq - 1;
  const fromSeq = Math.max(1, oldestLoadedSeq - size);
  return { fromSeq, toSeq };
}
