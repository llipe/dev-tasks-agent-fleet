/**
 * Unit tests for run filter parsing/validation — S-020, sub-task 20.8.
 *
 * Tests:
 * - Tab parsing: valid, invalid, missing
 * - Status parsing: valid, invalid, missing
 * - Date range: valid, invalid dates, from > to, range > 30d clamping
 * - Duration formatting: all thresholds
 * - Token formatting: zero, non-zero
 */

import { describe, it, expect } from "vitest";
import {
  parseRunFilters,
  parseTab,
  parseStatus,
  parseDateRange,
  formatDuration,
  formatTokens,
  filtersToSearchParams,
} from "./run-filters.js";

const NOW = new Date("2026-08-25T12:00:00.000Z").getTime();
const SEVEN_DAYS_MS = 7 * 24 * 60 * 60 * 1000;
const THIRTY_DAYS_MS = 30 * 24 * 60 * 60 * 1000;

describe("parseTab", () => {
  it("returns 'runs' for undefined", () => {
    expect(parseTab(undefined)).toBe("runs");
  });

  it("returns 'runs' for empty string", () => {
    expect(parseTab("")).toBe("runs");
  });

  it("returns 'runs' for valid 'runs' value", () => {
    expect(parseTab("runs")).toBe("runs");
  });

  it("returns 'repos' for valid 'repos' value", () => {
    expect(parseTab("repos")).toBe("repos");
  });

  it("falls back to 'runs' for invalid value", () => {
    expect(parseTab("invalid")).toBe("runs");
    expect(parseTab("RUNS")).toBe("runs");
  });
});

describe("parseStatus", () => {
  it("returns undefined for undefined", () => {
    expect(parseStatus(undefined)).toBeUndefined();
  });

  it("returns undefined for empty string", () => {
    expect(parseStatus("")).toBeUndefined();
  });

  it("returns valid status values", () => {
    expect(parseStatus("running")).toBe("running");
    expect(parseStatus("success")).toBe("success");
    expect(parseStatus("failed")).toBe("failed");
    expect(parseStatus("incomplete")).toBe("incomplete");
  });

  it("returns undefined for invalid value", () => {
    expect(parseStatus("unknown")).toBeUndefined();
    expect(parseStatus("SUCCESS")).toBeUndefined();
    expect(parseStatus("error")).toBeUndefined();
  });
});

describe("parseDateRange", () => {
  it("returns defaults when both dates are undefined", () => {
    const { from, to } = parseDateRange(undefined, undefined, NOW);
    expect(to.getTime()).toBe(NOW);
    expect(from.getTime()).toBe(NOW - SEVEN_DAYS_MS);
  });

  it("returns defaults when both dates are invalid", () => {
    const { from, to } = parseDateRange("not-a-date", "also-invalid", NOW);
    expect(to.getTime()).toBe(NOW);
    expect(from.getTime()).toBe(NOW - SEVEN_DAYS_MS);
  });

  it("uses now as 'to' when only 'to' is invalid", () => {
    const fromStr = "2026-08-20T00:00:00.000Z";
    const { from, to } = parseDateRange(fromStr, "invalid", NOW);
    expect(from.toISOString()).toBe(fromStr);
    expect(to.getTime()).toBe(NOW);
  });

  it("uses default range when only 'from' is invalid", () => {
    const toStr = "2026-08-25T12:00:00.000Z";
    const { from, to } = parseDateRange("invalid", toStr, NOW);
    expect(to.toISOString()).toBe(toStr);
    expect(from.getTime()).toBe(new Date(toStr).getTime() - SEVEN_DAYS_MS);
  });

  it("resets to defaults when from > to", () => {
    const { from, to } = parseDateRange(
      "2026-08-26T00:00:00.000Z",
      "2026-08-20T00:00:00.000Z",
      NOW,
    );
    expect(to.getTime()).toBe(NOW);
    expect(from.getTime()).toBe(NOW - SEVEN_DAYS_MS);
  });

  it("clamps from to (to - 30d) when range exceeds 30 days", () => {
    const toStr = "2026-08-25T12:00:00.000Z";
    const fromStr = "2026-06-01T00:00:00.000Z"; // Way more than 30 days before
    const { from, to } = parseDateRange(fromStr, toStr, NOW);
    expect(to.toISOString()).toBe(toStr);
    expect(from.getTime()).toBe(new Date(toStr).getTime() - THIRTY_DAYS_MS);
  });

  it("accepts valid range within 30 days", () => {
    const fromStr = "2026-08-20T00:00:00.000Z";
    const toStr = "2026-08-25T00:00:00.000Z";
    const { from, to } = parseDateRange(fromStr, toStr, NOW);
    expect(from.toISOString()).toBe(fromStr);
    expect(to.toISOString()).toBe(toStr);
  });

  it("accepts range of exactly 30 days", () => {
    const toDate = new Date(NOW);
    const fromDate = new Date(NOW - THIRTY_DAYS_MS);
    const { from, to } = parseDateRange(fromDate.toISOString(), toDate.toISOString(), NOW);
    expect(from.getTime()).toBe(fromDate.getTime());
    expect(to.getTime()).toBe(toDate.getTime());
  });
});

describe("parseRunFilters", () => {
  it("returns all defaults for empty params", () => {
    const result = parseRunFilters({}, NOW);
    expect(result.tab).toBe("runs");
    expect(result.status).toBeUndefined();
    expect(result.from.getTime()).toBe(NOW - SEVEN_DAYS_MS);
    expect(result.to.getTime()).toBe(NOW);
    expect(result.run).toBeUndefined();
  });

  it("parses all valid params", () => {
    const result = parseRunFilters(
      {
        tab: "repos",
        status: "failed",
        from: "2026-08-20T00:00:00.000Z",
        to: "2026-08-25T00:00:00.000Z",
        run: "session-123",
      },
      NOW,
    );
    expect(result.tab).toBe("repos");
    expect(result.status).toBe("failed");
    expect(result.from.toISOString()).toBe("2026-08-20T00:00:00.000Z");
    expect(result.to.toISOString()).toBe("2026-08-25T00:00:00.000Z");
    expect(result.run).toBe("session-123");
  });

  it("falls back invalid params to defaults", () => {
    const result = parseRunFilters(
      {
        tab: "invalid",
        status: "bogus",
        from: "not-a-date",
        to: "also-bad",
        run: "",
      },
      NOW,
    );
    expect(result.tab).toBe("runs");
    expect(result.status).toBeUndefined();
    expect(result.from.getTime()).toBe(NOW - SEVEN_DAYS_MS);
    expect(result.to.getTime()).toBe(NOW);
    expect(result.run).toBeUndefined();
  });

  it("trims whitespace from run param", () => {
    const result = parseRunFilters({ run: "  session-456  " }, NOW);
    expect(result.run).toBe("session-456");
  });
});

describe("formatDuration", () => {
  it("returns dash for 0", () => {
    expect(formatDuration(0)).toBe("—");
  });

  it("returns dash for negative values", () => {
    expect(formatDuration(-1000)).toBe("—");
  });

  it("returns seconds for < 60s", () => {
    expect(formatDuration(45000)).toBe("45s");
    expect(formatDuration(1000)).toBe("1s");
    expect(formatDuration(59000)).toBe("59s");
  });

  it("returns minutes and seconds for < 3600s", () => {
    expect(formatDuration(150000)).toBe("2m 30s");
    expect(formatDuration(60000)).toBe("1m");
    expect(formatDuration(3599000)).toBe("59m 59s");
  });

  it("returns hours and minutes for >= 3600s", () => {
    expect(formatDuration(3900000)).toBe("1h 5m");
    expect(formatDuration(3600000)).toBe("1h");
    expect(formatDuration(7200000)).toBe("2h");
    expect(formatDuration(7260000)).toBe("2h 1m");
  });

  it("handles edge case at exactly 60s", () => {
    expect(formatDuration(60000)).toBe("1m");
  });

  it("handles NaN gracefully", () => {
    expect(formatDuration(NaN)).toBe("—");
  });
});

describe("formatTokens", () => {
  it("returns dash for zero tokens", () => {
    expect(formatTokens(0, 0)).toBe("—");
  });

  it("formats with comma separators and labels", () => {
    expect(formatTokens(1500, 500)).toBe("1,500 in / 500 out");
  });

  it("handles large numbers", () => {
    expect(formatTokens(1000000, 250000)).toBe("1,000,000 in / 250,000 out");
  });

  it("handles only input tokens", () => {
    expect(formatTokens(100, 0)).toBe("100 in / 0 out");
  });

  it("handles only output tokens", () => {
    expect(formatTokens(0, 100)).toBe("0 in / 100 out");
  });
});

describe("filtersToSearchParams", () => {
  it("includes from/to always", () => {
    const now = new Date(NOW);
    const sevenDaysAgo = new Date(NOW - SEVEN_DAYS_MS);
    const params = filtersToSearchParams({
      tab: "runs",
      status: undefined,
      from: sevenDaysAgo,
      to: now,
    });
    expect(params["from"]).toBe(sevenDaysAgo.toISOString());
    expect(params["to"]).toBe(now.toISOString());
    expect(params["tab"]).toBeUndefined(); // default tab omitted
    expect(params["status"]).toBeUndefined();
  });

  it("includes tab when not default", () => {
    const params = filtersToSearchParams({
      tab: "repos",
      status: undefined,
      from: new Date(NOW - SEVEN_DAYS_MS),
      to: new Date(NOW),
    });
    expect(params["tab"]).toBe("repos");
  });

  it("includes status when set", () => {
    const params = filtersToSearchParams({
      tab: "runs",
      status: "failed",
      from: new Date(NOW - SEVEN_DAYS_MS),
      to: new Date(NOW),
    });
    expect(params["status"]).toBe("failed");
  });

  it("includes run param when provided", () => {
    const params = filtersToSearchParams(
      {
        tab: "runs",
        status: undefined,
        from: new Date(NOW - SEVEN_DAYS_MS),
        to: new Date(NOW),
      },
      "session-789",
    );
    expect(params["run"]).toBe("session-789");
  });
});
