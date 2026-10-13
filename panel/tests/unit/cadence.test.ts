import { describe, expect, it } from "vitest";
import { cadenceLabel, cadenceSummary, validateCron, type CadenceSpec } from "@/lib/domain/cadence";

// Layer 1 — S-152 (#264): the TS cron pre-validator + cadence formatters.
// The grammar mirrors scheduler.cron_field_matches (reject-before-save); the DB
// stays the final authority on whether a valid-grammar expression ever matches.

describe("validateCron — grammar (mirrors the plpgsql matcher)", () => {
  it("accepts each token form", () => {
    for (const c of [
      "* * * * *",
      "0 4 * * 1",
      "1,15,30 * * * *",
      "0 0-6 * * *",
      "*/15 * * * *",
      "0 0 29 2 *",
    ]) {
      expect(validateCron(c), c).toEqual({ valid: true, error: null });
    }
  });

  it("rejects wrong arity", () => {
    expect(validateCron("0 4 * *").valid).toBe(false);
    expect(validateCron("0 4 * * 1 7").valid).toBe(false);
    expect(validateCron("").valid).toBe(false);
  });

  it("rejects out-of-range tokens per field", () => {
    expect(validateCron("60 * * * *").valid).toBe(false); // minute > 59
    expect(validateCron("* 24 * * *").valid).toBe(false); // hour > 23
    expect(validateCron("* * 0 * *").valid).toBe(false); // dom < 1
    expect(validateCron("* * * 13 *").valid).toBe(false); // month > 12
    expect(validateCron("* * * * 8").valid).toBe(false); // dow > 7
  });

  it("rejects inverted ranges and zero steps and garbage", () => {
    expect(validateCron("5-1 * * * *").valid).toBe(false);
    expect(validateCron("*/0 * * * *").valid).toBe(false);
    expect(validateCron("abc * * * *").valid).toBe(false);
  });

  it("accepts dow 7 as Sunday (grammar allows 0..7)", () => {
    expect(validateCron("0 0 * * 7").valid).toBe(true);
  });

  it("names the offending field in the error", () => {
    expect(validateCron("60 * * * *").error).toMatch(/minute/);
    expect(validateCron("* * * 13 *").error).toMatch(/month/);
  });
});

describe("cadenceLabel", () => {
  const cases: Array<[CadenceSpec, string]> = [
    [{ kind: "hourly", minute: 0 }, "Hourly"],
    [{ kind: "daily", minute: 0, hour: 7 }, "Daily · 07:00"],
    [{ kind: "daily", minute: 30, hour: 22 }, "Daily · 22:30"],
    [{ kind: "weekly", minute: 0, hour: 4, weekday: 1 }, "Weekly · Mon 04:00"],
    [{ kind: "weekly", minute: 0, hour: 5, weekday: 5 }, "Weekly · Fri 05:00"],
    [{ kind: "every_n_hours", intervalHours: 6 }, "Every 6h"],
    [{ kind: "advanced", cron: "0 4 * * 1-5" }, "Cron · 0 4 * * 1-5"],
  ];
  it.each(cases)("%o -> %s", (spec, expected) => {
    expect(cadenceLabel(spec)).toBe(expected);
  });
});

describe("cadenceSummary", () => {
  it("renders the human sentence per kind", () => {
    expect(cadenceSummary({ kind: "hourly", minute: 0 })).toBe("Runs every hour on the hour");
    expect(cadenceSummary({ kind: "daily", minute: 0, hour: 7 })).toBe("Runs daily at 07:00");
    expect(cadenceSummary({ kind: "weekly", minute: 0, hour: 4, weekday: 1 })).toBe(
      "Runs every Monday at 04:00",
    );
    expect(cadenceSummary({ kind: "every_n_hours", intervalHours: 6 })).toBe("Runs every 6 hours");
    expect(cadenceSummary({ kind: "advanced", cron: "0 4 * * 1" })).toBe("Runs on cron 0 4 * * 1");
  });
});
