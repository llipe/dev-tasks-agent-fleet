import { beforeAll, describe, expect, it } from "vitest";
import { probeLocalDb, withDb } from "./db";

// Layer 2.5 — S-152 (#264): compute_next_run_at + cron matcher + RPC.
//
// The highest-risk surface (test plan §7). All computation is done in the
// schedule's timezone and returned as a UTC timestamptz. The DST assertions are
// the strongest check: for a fixed local "daily 07:00", the resulting UTC
// instant must differ across a DST boundary (AC1 / RT-2).
//
// America/Santiago (Chile) 2026 DST: spring-forward Sun 2026-09-06 (UTC-4 ->
// UTC-3), fall-back Sun 2026-04-05 (UTC-3 -> UTC-4). So:
//   - standard time (UTC-4, e.g. July): 07:00 local == 11:00Z
//   - daylight time (UTC-3, e.g. December): 07:00 local == 10:00Z
//
// Docker-gated (REQUIRE_LOCAL_DB=1 -> CI failure, #134).

const probe = await probeLocalDb();

// Call the explicit-args compute_next_run_at; returns the ISO UTC string.
async function nextRun(args: {
  kind: string;
  minute?: number | null;
  hour?: number | null;
  weekday?: number | null;
  interval?: number | null;
  cron?: string | null;
  tz: string;
  from: string; // ISO
  lastFired?: string | null;
}): Promise<string | null> {
  return withDb((c) =>
    c
      .query<{ ts: string | null }>(
        `select scheduler.compute_next_run_at(
                  $1::cadence_kind, $2, $3, $4, $5, $6, $7, $8::timestamptz, $9::timestamptz) as ts`,
        [
          args.kind,
          args.minute ?? null,
          args.hour ?? null,
          args.weekday ?? null,
          args.interval ?? null,
          args.cron ?? null,
          args.tz,
          args.from,
          args.lastFired ?? null,
        ],
      )
      .then((r) => r.rows[0]?.ts ?? null),
  );
}

describe.skipIf(!probe.available)("panel Layer 2.5 — S-152 compute_next_run_at", () => {
  beforeAll(() => {
    console.log(`[integration] ${probe.reason}`);
  });

  describe("DST correctness (AC1) — daily 07:00 America/Santiago", () => {
    it("fires at 11:00Z in standard time (UTC-4, July)", async () => {
      // from: 2026-07-10 06:00 local == 10:00Z; next 07:00 local same day == 11:00Z
      const ts = await nextRun({
        kind: "daily",
        minute: 0,
        hour: 7,
        tz: "America/Santiago",
        from: "2026-07-10T10:00:00Z",
      });
      expect(new Date(ts!).toISOString()).toBe("2026-07-10T11:00:00.000Z");
    });

    it("fires at 10:00Z in daylight time (UTC-3, December) — the UTC instant shifted", async () => {
      // from: 2026-12-10 06:00 local == 09:00Z; next 07:00 local == 10:00Z
      const ts = await nextRun({
        kind: "daily",
        minute: 0,
        hour: 7,
        tz: "America/Santiago",
        from: "2026-12-10T09:00:00Z",
      });
      expect(new Date(ts!).toISOString()).toBe("2026-12-10T10:00:00.000Z");
    });

    it("UTC fixed-offset is unaffected (control)", async () => {
      const ts = await nextRun({
        kind: "daily",
        minute: 0,
        hour: 7,
        tz: "UTC",
        from: "2026-07-10T06:00:00Z",
      });
      expect(new Date(ts!).toISOString()).toBe("2026-07-10T07:00:00.000Z");
    });
  });

  describe("preset kinds", () => {
    it("hourly fires at the next minute-00 boundary", async () => {
      const ts = await nextRun({
        kind: "hourly",
        minute: 0,
        tz: "UTC",
        from: "2026-07-10T06:30:00Z",
      });
      expect(new Date(ts!).toISOString()).toBe("2026-07-10T07:00:00.000Z");
    });

    it("weekly Monday (dow=1) 04:00 lands on the next Monday", async () => {
      // 2026-07-10 is a Friday; next Monday is 2026-07-13 04:00 local (UTC-4) == 08:00Z
      const ts = await nextRun({
        kind: "weekly",
        minute: 0,
        hour: 4,
        weekday: 1,
        tz: "America/Santiago",
        from: "2026-07-10T12:00:00Z",
      });
      expect(new Date(ts!).toISOString()).toBe("2026-07-13T08:00:00.000Z");
    });

    it("every_n_hours chains from last_fired_at", async () => {
      const ts = await nextRun({
        kind: "every_n_hours",
        interval: 6,
        tz: "UTC",
        from: "2026-07-10T09:00:00Z",
        lastFired: "2026-07-10T06:00:00Z",
      });
      // 06:00 + 6h = 12:00Z, strictly after the 09:00 from
      expect(new Date(ts!).toISOString()).toBe("2026-07-10T12:00:00.000Z");
    });
  });

  describe("advanced cron (interpreted in schedule tz, OQ-S2)", () => {
    it("'0 4 * * 1' (Mon 04:00) matches the next Monday in local tz", async () => {
      const ts = await nextRun({
        kind: "advanced",
        cron: "0 4 * * 1",
        tz: "America/Santiago",
        from: "2026-07-10T12:00:00Z",
      });
      expect(new Date(ts!).toISOString()).toBe("2026-07-13T08:00:00.000Z");
    });

    it("'*/15 * * * *' matches the next quarter hour", async () => {
      const ts = await nextRun({
        kind: "advanced",
        cron: "*/15 * * * *",
        tz: "UTC",
        from: "2026-07-10T06:07:00Z",
      });
      expect(new Date(ts!).toISOString()).toBe("2026-07-10T06:15:00.000Z");
    });

    it("a leap-only cron '0 0 29 2 *' resolves to a leap year (2028)", async () => {
      const ts = await nextRun({
        kind: "advanced",
        cron: "0 0 29 2 *",
        tz: "UTC",
        from: "2026-07-10T06:00:00Z",
      });
      expect(ts).not.toBeNull();
      expect(new Date(ts!).getUTCFullYear()).toBe(2028);
      expect(new Date(ts!).getUTCMonth()).toBe(1); // Feb
      expect(new Date(ts!).getUTCDate()).toBe(29);
    });

    it("an invalid cron (bad field) returns null", async () => {
      const ts = await nextRun({
        kind: "advanced",
        cron: "99 4 * * 1",
        tz: "UTC",
        from: "2026-07-10T06:00:00Z",
      });
      expect(ts).toBeNull();
    });

    it("a wrong-arity cron returns null", async () => {
      const ts = await nextRun({
        kind: "advanced",
        cron: "0 4 * *",
        tz: "UTC",
        from: "2026-07-10T06:00:00Z",
      });
      expect(ts).toBeNull();
    });
  });

  describe("cron_field_matches grammar (direct)", () => {
    async function matches(spec: string, value: number, lo: number, hi: number) {
      return withDb((c) =>
        c
          .query<{
            m: boolean | null;
          }>(`select scheduler.cron_field_matches($1,$2,$3,$4) as m`, [spec, value, lo, hi])
          .then((r) => r.rows[0]?.m),
      );
    }
    it("accepts *, number, list, range, step", async () => {
      expect(await matches("*", 5, 0, 59)).toBe(true);
      expect(await matches("5", 5, 0, 59)).toBe(true);
      expect(await matches("5", 6, 0, 59)).toBe(false);
      expect(await matches("1,15,30", 15, 0, 59)).toBe(true);
      expect(await matches("1-5", 3, 0, 59)).toBe(true);
      expect(await matches("1-5", 6, 0, 59)).toBe(false);
      expect(await matches("*/15", 30, 0, 59)).toBe(true);
      expect(await matches("*/15", 31, 0, 59)).toBe(false);
    });
    it("rejects out-of-range, inverted, and garbage (null)", async () => {
      expect(await matches("60", 60, 0, 59)).toBeNull();
      expect(await matches("5-1", 3, 0, 59)).toBeNull();
      expect(await matches("*/0", 0, 0, 59)).toBeNull();
      expect(await matches("abc", 0, 0, 59)).toBeNull();
    });
  });

  describe("preview_next_runs RPC (SD-T6) parity", () => {
    it("returns N chained future instants equal to repeated compute_next_run_at", async () => {
      const rpc = await withDb((c) =>
        c
          .query<{ ts: string }>(
            `select scheduler.preview_next_runs(
                      'daily'::cadence_kind, 0, 7, null, null, null,
                      'America/Santiago', 3, $1::timestamptz) as ts`,
            ["2026-07-10T10:00:00Z"],
          )
          .then((r) => r.rows.map((x) => new Date(x.ts).toISOString())),
      );
      expect(rpc).toEqual([
        "2026-07-10T11:00:00.000Z",
        "2026-07-11T11:00:00.000Z",
        "2026-07-12T11:00:00.000Z",
      ]);
    });

    it("returns empty for an invalid advanced cron", async () => {
      const rpc = await withDb((c) =>
        c
          .query(
            `select scheduler.preview_next_runs(
                      'advanced'::cadence_kind, null, null, null, null, '99 4 * * 1',
                      'UTC', 3, now()) as ts`,
          )
          .then((r) => r.rows),
      );
      expect(rpc).toHaveLength(0);
    });
  });
});

if (!probe.available) {
  describe("panel Layer 2.5 — S-152 compute_next_run_at (skipped)", () => {
    it.skip(`SKIPPED: ${probe.reason}`, () => {});
  });
}
