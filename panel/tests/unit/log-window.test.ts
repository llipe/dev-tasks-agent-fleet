import { describe, expect, it } from "vitest";

import {
  selectRecentWindow,
  priorWindowRange,
  LOG_WINDOW_SIZE,
  type SeqEvent,
} from "@/lib/domain/log-window";

/**
 * Layer 1 (unit) — the SD11 bounded log-window selector (test-plan SC-8/9, RT-3).
 *
 * `run_events` grows two orders of magnitude beyond every other table (R3), so
 * the initial fetch is bounded at the most recent `LOG_WINDOW_SIZE` (2,000)
 * events — the bound is on the RECENT end (query `seq desc`, reversed for
 * display). If earlier events exist, a "load earlier" control fetches the prior
 * window.
 *
 * `log-window.ts` is the pure math behind that:
 *  - `selectRecentWindow(events, size)` returns the most-recent `size` events in
 *    ascending `seq` order, and reports whether earlier events exist.
 *  - `priorWindowRange(oldestLoadedSeq, size)` computes the [fromSeq, toSeq]
 *    (inclusive) range of the window immediately before what is loaded, for the
 *    "load earlier" fetch — with no overlap and no gap.
 *
 * Load-bearing properties (RT-3, the partition property):
 *  - Across the initial window + every "load earlier" window, each event
 *    appears exactly once, order is `seq`-monotonic, and the union has no gap.
 */

function events(count: number, startSeq = 1): SeqEvent[] {
  return Array.from({ length: count }, (_, i) => ({ seq: startSeq + i }));
}

describe("LOG_WINDOW_SIZE", () => {
  it("is the SD11 cap of 2000", () => {
    expect(LOG_WINDOW_SIZE).toBe(2000);
  });
});

describe("selectRecentWindow — most-recent-N selection", () => {
  it("returns [] and hasEarlier=false for zero events", () => {
    const w = selectRecentWindow([], LOG_WINDOW_SIZE);
    expect(w.events).toEqual([]);
    expect(w.hasEarlier).toBe(false);
    expect(w.oldestSeq).toBeNull();
  });

  it("returns the single event for one event, no earlier", () => {
    const w = selectRecentWindow(events(1), LOG_WINDOW_SIZE);
    expect(w.events.map((e) => e.seq)).toEqual([1]);
    expect(w.hasEarlier).toBe(false);
    expect(w.oldestSeq).toBe(1);
  });

  it("returns all events, ascending, when below the window size", () => {
    const w = selectRecentWindow(events(1500), 2000);
    expect(w.events).toHaveLength(1500);
    expect(w.events[0].seq).toBe(1);
    expect(w.events[1499].seq).toBe(1500);
    expect(w.hasEarlier).toBe(false);
  });

  it("returns exactly the window size at the boundary (2000), no earlier", () => {
    const w = selectRecentWindow(events(2000), 2000);
    expect(w.events).toHaveLength(2000);
    expect(w.events[0].seq).toBe(1);
    expect(w.events[1999].seq).toBe(2000);
    expect(w.hasEarlier).toBe(false);
  });

  it("returns the MOST RECENT window and flags earlier when over the size (2500)", () => {
    const w = selectRecentWindow(events(2500), 2000);
    expect(w.events).toHaveLength(2000);
    // Most recent 2000 = seq 501..2500, ascending for display.
    expect(w.events[0].seq).toBe(501);
    expect(w.events[1999].seq).toBe(2500);
    expect(w.hasEarlier).toBe(true);
    expect(w.oldestSeq).toBe(501);
  });

  it("sorts unsorted input by seq ascending (arrival order is not emission order, D5)", () => {
    const shuffled: SeqEvent[] = [{ seq: 3 }, { seq: 1 }, { seq: 2 }];
    const w = selectRecentWindow(shuffled, 2000);
    expect(w.events.map((e) => e.seq)).toEqual([1, 2, 3]);
  });

  it("just over the boundary (2001) keeps the newest 2000 and drops seq 1", () => {
    const w = selectRecentWindow(events(2001), 2000);
    expect(w.events).toHaveLength(2000);
    expect(w.events[0].seq).toBe(2);
    expect(w.events[1999].seq).toBe(2001);
    expect(w.hasEarlier).toBe(true);
  });
});

describe("priorWindowRange — load-earlier math", () => {
  it("computes the inclusive range immediately before the loaded window", () => {
    // Loaded oldest seq = 501; prior window is seq 1..500 for size 2000.
    const range = priorWindowRange(501, 2000);
    expect(range).toEqual({ fromSeq: 1, toSeq: 500 });
  });

  it("clamps fromSeq at 1 when the prior window is smaller than the size", () => {
    // Loaded oldest = 300; a full 2000 window before it would start below 1.
    const range = priorWindowRange(300, 2000);
    expect(range).toEqual({ fromSeq: 1, toSeq: 299 });
  });

  it("returns null when nothing precedes the loaded window (oldest seq is 1)", () => {
    expect(priorWindowRange(1, 2000)).toBeNull();
  });

  it("returns null for a non-positive oldest seq (defensive)", () => {
    expect(priorWindowRange(0, 2000)).toBeNull();
    expect(priorWindowRange(-5, 2000)).toBeNull();
  });
});

describe("partition property (RT-3) — no gap, no duplicate across windows", () => {
  it("initial window + successive load-earlier ranges tile [1..N] exactly once", () => {
    const N = 5300;
    const size = 2000;
    const all = events(N);

    // Initial window: most recent `size`.
    const initial = selectRecentWindow(all, size);
    const covered = new Set<number>(initial.events.map((e) => e.seq));
    let oldest = initial.oldestSeq;

    // Walk backwards with priorWindowRange until nothing precedes.
    let guard = 0;
    while (oldest !== null) {
      const range = priorWindowRange(oldest, size);
      if (range === null) break;
      for (let s = range.fromSeq; s <= range.toSeq; s++) {
        // No seq is covered twice (no overlap).
        expect(covered.has(s)).toBe(false);
        covered.add(s);
      }
      oldest = range.fromSeq;
      if (++guard > 100) throw new Error("load-earlier did not terminate");
    }

    // Union is exactly [1..N] — no gap, no duplicate.
    expect(covered.size).toBe(N);
    for (let s = 1; s <= N; s++) {
      expect(covered.has(s)).toBe(true);
    }
  });

  it("property holds for a range of random-ish counts (RT-3, deterministic)", () => {
    let seed = 0x1234abcd;
    const rand = () => {
      seed ^= seed << 13;
      seed ^= seed >>> 17;
      seed ^= seed << 5;
      return (seed >>> 0) / 0xffffffff;
    };
    for (let trial = 0; trial < 50; trial++) {
      const N = Math.floor(rand() * 6000);
      const size = 2000;
      const all = events(N);
      const initial = selectRecentWindow(all, size);
      const covered = new Set<number>(initial.events.map((e) => e.seq));
      let oldest = initial.oldestSeq;
      let guard = 0;
      while (oldest !== null) {
        const range = priorWindowRange(oldest, size);
        if (range === null) break;
        for (let s = range.fromSeq; s <= range.toSeq; s++) {
          expect(covered.has(s)).toBe(false);
          covered.add(s);
        }
        oldest = range.fromSeq;
        if (++guard > 200) throw new Error(`no termination at N=${N}`);
      }
      expect(covered.size).toBe(N);
    }
  });
});
