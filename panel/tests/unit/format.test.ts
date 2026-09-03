import { describe, expect, it } from "vitest";

import {
  formatClock,
  formatRelative,
  formatDuration,
  formatDurationShort,
  formatRunningDuration,
  formatRunId,
  formatRunCount,
  formatStepProgress,
  formatEventCount,
  formatStatusLegend,
  formatStatusLegendCompact,
  formatPagination,
} from "@/lib/format";

/**
 * Table-driven tests for the /DESIGN.md §7 data-formatting conventions.
 * Every formatter is pure and clock-injected so boundaries are testable
 * deterministically (no ambient Date.now()).
 */

describe("formatClock — §7.1 24h HH:MM:SS", () => {
  // Use a fixed UTC instant and assert against its UTC wall clock so the test
  // is timezone-independent.
  it.each([
    // 2026-01-02T14:02:13Z
    [Date.UTC(2026, 0, 2, 14, 2, 13), "14:02:13"],
    // zero-pads every field
    [Date.UTC(2026, 0, 2, 4, 5, 6), "04:05:06"],
    // midnight
    [Date.UTC(2026, 0, 2, 0, 0, 0), "00:00:00"],
    // one second before midnight
    [Date.UTC(2026, 0, 2, 23, 59, 59), "23:59:59"],
  ])("formats %i as %s (UTC)", (ms, expected) => {
    expect(formatClock(ms, "UTC")).toBe(expected);
  });

  it("accepts an ISO string", () => {
    expect(formatClock("2026-01-02T14:02:07Z", "UTC")).toBe("14:02:07");
  });
});

describe("formatRelative — §7.1 relative time", () => {
  const now = Date.UTC(2026, 5, 15, 12, 0, 0);
  const sec = 1000;
  const min = 60 * sec;
  const hour = 60 * min;
  const day = 24 * hour;

  it.each([
    ["just now (0s)", now, "just now"],
    ["seconds ago", now - 5 * sec, "just now"],
    ["exactly 1 minute", now - min, "1 min ago"],
    ["2 minutes", now - 2 * min, "2 min ago"],
    ["14 minutes", now - 14 * min, "14 min ago"],
    ["exactly 1 hour", now - hour, "1h ago"],
    ["6 hours", now - 6 * hour, "6h ago"],
    ["yesterday (1 day)", now - day, "yesterday"],
    ["23 days", now - 23 * day, "23d ago"],
    ["far past (400 days)", now - 400 * day, "400d ago"],
  ])("%s", (_label, thenMs, expected) => {
    expect(formatRelative(thenMs, now)).toBe(expected);
  });

  it("clamps a future timestamp (clock skew) to 'just now'", () => {
    expect(formatRelative(now + 5 * sec, now)).toBe("just now");
  });
});

describe("formatDuration — §7.2 Xm XXs", () => {
  it.each([
    [0, "0m 00s"],
    [4_000, "0m 04s"],
    [72_000, "1m 12s"],
    [184_000, "3m 04s"],
    [3_600_000, "60m 00s"],
    // sub-second rounds down to whole seconds
    [4_900, "0m 04s"],
  ])("%i ms -> %s", (ms, expected) => {
    expect(formatDuration(ms)).toBe(expected);
  });

  it("clamps negative input to zero", () => {
    expect(formatDuration(-5_000)).toBe("0m 00s");
  });
});

describe("formatDurationShort — §7.2 step/history short form", () => {
  it.each([
    [4_000, "4s"],
    [72_000, "1m 12s"],
    [108_000, "1m 48s"],
    [59_000, "59s"],
    [0, "0s"],
    // sub-second
    [900, "0s"],
  ])("%i ms -> %s", (ms, expected) => {
    expect(formatDurationShort(ms)).toBe(expected);
  });

  it("clamps negative input to 0s", () => {
    expect(formatDurationShort(-1_000)).toBe("0s");
  });
});

describe("formatRunningDuration — §7.2 running · Xm", () => {
  it.each([
    [0, "running · 0m"],
    [120_000, "running · 2m"],
    // rounds down to whole minutes
    [179_000, "running · 2m"],
    [3_600_000, "running · 60m"],
  ])("%i ms -> %s", (ms, expected) => {
    expect(formatRunningDuration(ms)).toBe(expected);
  });
});

describe("formatRunId — §7.3 short uppercase mono", () => {
  it("uppercases and takes the leading 8 chars", () => {
    expect(formatRunId("01j8xq2f9k3m4n5p6q7r8s9t")).toBe("01J8XQ2F");
  });

  it("uppercases a UUID and strips dashes for the short form", () => {
    expect(formatRunId("f63ac9f3-14b0-4157-9484-f2f6b062f846")).toBe("F63AC9F3");
  });

  it("returns a short id unchanged (uppercased)", () => {
    expect(formatRunId("abc123")).toBe("ABC123");
  });

  it("handles empty input", () => {
    expect(formatRunId("")).toBe("");
  });
});

describe("formatRunCount — §7.3 counts", () => {
  it.each([
    [0, "0 runs"],
    [1, "1 run"],
    [82, "82 runs"],
  ])("%i -> %s", (n, expected) => {
    expect(formatRunCount(n)).toBe(expected);
  });
});

describe("formatStepProgress — §7.3 n/m", () => {
  it.each([
    [2, 4, "2/4"],
    [0, 0, "0/0"],
    [4, 4, "4/4"],
  ])("(%i, %i) -> %s", (done, total, expected) => {
    expect(formatStepProgress(done, total)).toBe(expected);
  });
});

describe("formatEventCount — §7.3 event count", () => {
  it.each([
    [0, "0 ev"],
    [12, "12 ev"],
  ])("%i -> %s", (n, expected) => {
    expect(formatEventCount(n)).toBe(expected);
  });
});

describe("formatStatusLegend — §7.3 status legend", () => {
  it("renders the dotted ok/fail/timeout legend", () => {
    expect(formatStatusLegend({ ok: 65, fail: 11, timeout: 6 })).toBe(
      "65 ok · 11 fail · 6 timeout",
    );
  });

  it("omits zero buckets", () => {
    expect(formatStatusLegend({ ok: 65, fail: 0, timeout: 0 })).toBe("65 ok");
  });

  it("renders an empty legend when all zero", () => {
    expect(formatStatusLegend({ ok: 0, fail: 0, timeout: 0 })).toBe("");
  });
});

describe("formatStatusLegendCompact — §7.3 card glyph legend", () => {
  it("renders the glyph legend", () => {
    expect(formatStatusLegendCompact({ ok: 65, fail: 11, timeout: 6 })).toBe("65 ✓ · 11 ✕ · 6 ⧗");
  });

  it("omits zero buckets", () => {
    expect(formatStatusLegendCompact({ ok: 65, fail: 0, timeout: 0 })).toBe("65 ✓");
  });
});

describe("formatPagination — §7.3 X of Y", () => {
  it.each([
    [8, 82, "8 of 82"],
    [0, 0, "0 of 0"],
  ])("(%i, %i) -> %s", (shown, total, expected) => {
    expect(formatPagination(shown, total)).toBe(expected);
  });
});
