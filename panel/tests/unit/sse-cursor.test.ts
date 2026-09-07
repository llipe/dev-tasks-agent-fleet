import { describe, expect, it } from "vitest";

import { SeqCursor, dedupeAndOrder } from "@/lib/sse/cursor";

/**
 * Cursor / dedupe reducer (Story S-110, SD6). This is where gaps and duplicates
 * come from, so it is tested first and hardest.
 *
 * The invariant (RT-1): the emitted `seq` stream is strictly increasing,
 * contains every input `seq > after_seq` exactly once, and the tracked cursor
 * is monotonic non-decreasing (never regresses on reconnect).
 */

describe("SeqCursor", () => {
  it("starts at the initial after_seq and admits only strictly greater seq (AC1/AC2)", () => {
    const c = new SeqCursor(0);
    expect(c.highest).toBe(0);
    expect(c.admit(1)).toBe(true);
    expect(c.highest).toBe(1);
    // At or below the highest already sent is dropped (SD6 step 3).
    expect(c.admit(1)).toBe(false);
    expect(c.admit(0)).toBe(false);
    expect(c.admit(2)).toBe(true);
    expect(c.highest).toBe(2);
  });

  it("respects a non-zero initial cursor (resume) — backfill only newer (SC-2)", () => {
    const c = new SeqCursor(7);
    expect(c.admit(7)).toBe(false);
    expect(c.admit(8)).toBe(true);
    expect(c.admit(9)).toBe(true);
    expect(c.highest).toBe(9);
  });

  it("de-duplicates the backfill/subscription overlap (EC-5)", () => {
    // Backfill emitted 1..5; Realtime replays 5 then sends 6.
    const c = new SeqCursor(0);
    for (const s of [1, 2, 3, 4, 5]) expect(c.admit(s)).toBe(true);
    expect(c.admit(5)).toBe(false); // duplicate push dropped
    expect(c.admit(6)).toBe(true);
    expect(c.highest).toBe(6);
  });

  it("drops out-of-order pushes at or below the highest sent, admits genuinely-new (EC-6)", () => {
    // Pushes arrive 7, 6, 8 (D5 buffering: arrival order != emission order).
    const c = new SeqCursor(5);
    expect(c.admit(7)).toBe(true); // new
    expect(c.admit(6)).toBe(false); // <= highest(7) -> dropped
    expect(c.admit(8)).toBe(true); // new
    expect(c.highest).toBe(8);
  });

  it("cursor is monotonic non-decreasing — a regression never moves it back (EC-7)", () => {
    const c = new SeqCursor(0);
    c.admit(10);
    expect(c.highest).toBe(10);
    c.admit(3); // regression
    expect(c.highest).toBe(10); // unchanged
    c.admit(9); // still below
    expect(c.highest).toBe(10);
  });
});

describe("dedupeAndOrder", () => {
  it("returns strictly increasing seq with no duplicates (SC-3)", () => {
    const out = dedupeAndOrder([{ seq: 3 }, { seq: 1 }, { seq: 2 }, { seq: 2 }, { seq: 3 }], 0);
    expect(out.map((e) => e.seq)).toEqual([1, 2, 3]);
  });

  it("drops everything at or below after_seq (SC-2)", () => {
    const out = dedupeAndOrder([{ seq: 5 }, { seq: 6 }, { seq: 7 }], 6);
    expect(out.map((e) => e.seq)).toEqual([7]);
  });

  it("keeps the first occurrence of a duplicate seq (payload stability)", () => {
    const out = dedupeAndOrder(
      [
        { seq: 1, tag: "a" },
        { seq: 1, tag: "b" },
      ],
      0,
    );
    expect(out).toEqual([{ seq: 1, tag: "a" }]);
  });

  it("handles an empty input (EC-2)", () => {
    expect(dedupeAndOrder([], 0)).toEqual([]);
  });

  // RT-1 — property: for any interleaving with duplicates and out-of-order
  // arrivals, the reducer never gaps and never duplicates.
  it("property: emits every seq > after_seq exactly once, strictly increasing (RT-1)", () => {
    const seed = 1725500000; // recorded seed: prop-AC2-1725500000-a3f1
    let state = seed >>> 0;
    const rand = () => {
      // xorshift32 — deterministic, seed-replayable.
      state ^= state << 13;
      state ^= state >>> 17;
      state ^= state << 5;
      return ((state >>> 0) % 1000) / 1000;
    };

    for (let iter = 0; iter < 500; iter++) {
      const afterSeq = Math.floor(rand() * 5);
      const distinct = 1 + Math.floor(rand() * 40);
      // The universe of seq values that should survive.
      const expected: number[] = [];
      for (let s = 1; s <= distinct; s++) if (s > afterSeq) expected.push(s);

      // Build a noisy input: each expected seq appears 1-3 times, plus some
      // <= afterSeq noise, then shuffled (out-of-order arrival).
      const input: { seq: number }[] = [];
      for (let s = 1; s <= distinct; s++) {
        const copies = 1 + Math.floor(rand() * 3);
        for (let k = 0; k < copies; k++) input.push({ seq: s });
      }
      for (let k = 0; k < 5; k++) input.push({ seq: Math.floor(rand() * (afterSeq + 1)) });
      // Fisher-Yates shuffle.
      for (let i = input.length - 1; i > 0; i--) {
        const j = Math.floor(rand() * (i + 1));
        [input[i], input[j]] = [input[j], input[i]];
      }

      const out = dedupeAndOrder(input, afterSeq).map((e) => e.seq);
      // Strictly increasing.
      for (let i = 1; i < out.length; i++) {
        expect(out[i]).toBeGreaterThan(out[i - 1]);
      }
      // Exactly the expected set.
      expect(out).toEqual(expected);
    }
  });
});
