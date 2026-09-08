import { describe, expect, it } from "vitest";

import { parseAfterSeq } from "@/lib/sse/cursor";

/**
 * `after_seq` query-parameter parsing (Story S-110, AC1 / CT-2 / CT-3 / RT-3).
 *
 * Contract: integer, default 0. The spec left coerce-vs-reject unstated
 * (test-plan §7 flag 1); this implementation coerces any non-parseable or
 * negative value to 0 (never rejects, never returns a non-integer/NaN cursor),
 * so a malformed `after_seq` degrades to a full backfill rather than a 500.
 */

describe("parseAfterSeq", () => {
  it("defaults to 0 when omitted (CT-2)", () => {
    expect(parseAfterSeq(null)).toBe(0);
  });

  it("parses a valid non-negative integer (AC1)", () => {
    expect(parseAfterSeq("0")).toBe(0);
    expect(parseAfterSeq("7")).toBe(7);
    expect(parseAfterSeq("999999")).toBe(999999);
  });

  it("coerces malformed values to 0, never NaN, never negative (CT-3, RT-3)", () => {
    const corpus = ["abc", "", "-1", "-3", "1.9", "NaN", "0x10", "  ", "5;DROP", "1e999"];
    for (const raw of corpus) {
      const out = parseAfterSeq(raw);
      expect(Number.isInteger(out)).toBe(true);
      expect(out).toBeGreaterThanOrEqual(0);
    }
    expect(parseAfterSeq("abc")).toBe(0);
    expect(parseAfterSeq("-1")).toBe(0);
  });

  it("floors a positive non-integer to an integer", () => {
    // "1.9" -> Number 1.9 -> floor 1. A fractional cursor is meaningless; floor
    // is safe because it never skips an integer seq.
    expect(parseAfterSeq("1.9")).toBe(1);
  });

  it("property: never returns a negative or non-integer for any string (RT-3)", () => {
    const seed = 1725500002; // recorded seed: fuzz-AC1-1725500002-c3d5
    let state = seed >>> 0;
    const rand = () => {
      state ^= state << 13;
      state ^= state >>> 17;
      state ^= state << 5;
      return (state >>> 0) / 0xffffffff;
    };
    const chars = "0123456789-.eExXabc; ".split("");
    for (let i = 0; i < 300; i++) {
      const len = Math.floor(rand() * 8);
      let s = "";
      for (let k = 0; k < len; k++) s += chars[Math.floor(rand() * chars.length)];
      const out = parseAfterSeq(s);
      expect(Number.isInteger(out)).toBe(true);
      expect(out).toBeGreaterThanOrEqual(0);
    }
  });
});
