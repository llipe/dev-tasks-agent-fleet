import { beforeAll, describe, expect, it } from "vitest";
import { probeLocalDb, withDb } from "./db";

// Layer 2.5 — S-151 (#263): pg_net + Vault + settings.
//
// Verifies the trigger path's prerequisites exist after `supabase db reset`:
//  - pg_net + supabase_vault extensions installed;
//  - scheduler.read_secret() resolves the dev-bootstrapped trigger secret
//    (the single read path the pg_net call uses, SD-A2/SD-T4);
//  - the runtime GUCs app.panel_base_url + app.scheduler_max_inflight read back.
//
// Docker-gated via probeLocalDb (REQUIRE_LOCAL_DB=1 -> CI failure, #134).

const probe = await probeLocalDb();

describe.skipIf(!probe.available)("panel Layer 2.5 — S-151 scheduler extensions + settings", () => {
  beforeAll(() => {
    console.log(`[integration] ${probe.reason}`);
  });

  it("has pg_net and supabase_vault installed", async () => {
    const rows = await withDb((c) =>
      c
        .query<{
          extname: string;
        }>(`select extname from pg_extension where extname in ('pg_net','supabase_vault')`)
        .then((r) => r.rows.map((x) => x.extname).sort()),
    );
    expect(rows).toEqual(["pg_net", "supabase_vault"]);
  });

  it("has the scheduler schema and its secret helpers", async () => {
    const fns = await withDb((c) =>
      c
        .query<{ proname: string }>(
          `select p.proname
             from pg_proc p join pg_namespace n on n.oid = p.pronamespace
            where n.nspname = 'scheduler' and p.proname in ('read_secret','set_secret')`,
        )
        .then((r) => r.rows.map((x) => x.proname).sort()),
    );
    expect(fns).toEqual(["read_secret", "set_secret"]);
  });

  it("scheduler.read_secret resolves the bootstrapped trigger secret", async () => {
    const secret = await withDb((c) =>
      c
        .query<{
          s: string | null;
        }>(`select scheduler.read_secret('scheduler_trigger_secret') as s`)
        .then((r) => r.rows[0]?.s),
    );
    expect(typeof secret).toBe("string");
    expect((secret ?? "").length).toBeGreaterThan(0);
  });

  it("scheduler.read_secret returns null for an unknown secret (callers treat as config error)", async () => {
    const secret = await withDb((c) =>
      c
        .query<{ s: string | null }>(`select scheduler.read_secret('no_such_secret') as s`)
        .then((r) => r.rows[0]?.s),
    );
    expect(secret).toBeNull();
  });

  it("set_secret upserts idempotently (no duplicate rows, value updates)", async () => {
    await withDb(async (c) => {
      await c.query(`select scheduler.set_secret('test_tmp_secret', 'v1')`);
      await c.query(`select scheduler.set_secret('test_tmp_secret', 'v2')`);
      const n = await c.query<{ n: string }>(
        `select count(*)::text as n from vault.secrets where name = 'test_tmp_secret'`,
      );
      expect(Number(n.rows[0]!.n)).toBe(1);
      const v = await c.query<{ s: string }>(
        `select scheduler.read_secret('test_tmp_secret') as s`,
      );
      expect(v.rows[0]!.s).toBe("v2");
      // cleanup
      await c.query(`delete from vault.secrets where name = 'test_tmp_secret'`);
    });
  });

  it("exposes the panel_base_url and max_inflight settings via scheduler.config", async () => {
    const row = await withDb((c) =>
      c
        .query<{ base: string; cap: number }>(
          `select scheduler.get_setting('panel_base_url') as base,
                  scheduler.max_inflight() as cap`,
        )
        .then((r) => r.rows[0]),
    );
    expect(row?.base ?? "").toMatch(/^https?:\/\//);
    expect(Number(row?.cap)).toBeGreaterThanOrEqual(1);
  });
});

if (!probe.available) {
  describe("panel Layer 2.5 — S-151 scheduler extensions (skipped)", () => {
    it.skip(`SKIPPED: ${probe.reason}`, () => {});
  });
}
