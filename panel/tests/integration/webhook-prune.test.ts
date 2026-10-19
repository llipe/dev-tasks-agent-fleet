import { beforeAll, describe, expect, it } from "vitest";
import type { Client } from "pg";
import { probeLocalDb, withDb } from "./db";

// Layer 2.5 — S-167 (#311): webhook.prune_deliveries() + the daily pg_cron job.
//
//  - deletes deliveries older than webhook.config.delivery_retention_days and
//    keeps newer ones (D-W14);
//  - deletes at most p_batch rows per call, oldest first (EC-35), and returns
//    the count;
//  - pruning a `fired` delivery never deletes its run (I-8, run_id FK set-null
//    only matters in the other direction — the run row must survive);
//  - a horizon change in webhook.config takes effect on the next call;
//  - a freshly inserted row is never pruned (EC-17);
//  - the cron job is registered daily and calls the function;
//  - only service_role (and the cron owner) may execute it (#357 pattern).
//
// Each test runs in a rolled-back transaction. now() is the transaction start,
// so "aged" rows are inserted with explicit created_at values.

const probe = await probeLocalDb();
const TOKEN = "s167-test-token-aaaaaaaaaaaaaaaaaaaaaa";

async function inTx<T>(fn: (c: Client) => Promise<T>): Promise<T> {
  return withDb(async (c) => {
    await c.query("begin");
    try {
      return await fn(c);
    } finally {
      await c.query("rollback");
    }
  });
}

async function seedEndpoint(c: Client): Promise<string> {
  return c
    .query<{
      id: string;
    }>(`insert into webhook_endpoints (name, url_token) values ('s167', $1) returning id`, [TOKEN])
    .then((r) => r.rows[0]!.id);
}

/** Insert one delivery `ageDays` old; returns its id. */
async function delivery(c: Client, ep: string, ageDays: number, runId: string | null = null) {
  return c
    .query<{ id: string }>(
      `insert into webhook_deliveries (endpoint_id, outcome, run_id, created_at, received_at)
       values ($1, $2, $3, now() - make_interval(days => $4), now() - make_interval(days => $4))
       returning id`,
      [ep, runId ? "fired" : "no_match", runId, ageDays],
    )
    .then((r) => r.rows[0]!.id);
}

async function remaining(c: Client, ep: string): Promise<number> {
  return c
    .query<{
      n: number;
    }>(`select count(*)::int as n from webhook_deliveries where endpoint_id = $1`, [ep])
    .then((r) => r.rows[0]!.n);
}

describe.skipIf(!probe.available)("panel Layer 2.5 — S-167 webhook delivery prune", () => {
  beforeAll(() => {
    console.log(`[integration] ${probe.reason}`);
  });

  it("deletes rows past the 30-day horizon and keeps newer ones", async () => {
    await inTx(async (c) => {
      const ep = await seedEndpoint(c);
      const keep = [await delivery(c, ep, 0), await delivery(c, ep, 29)];
      await delivery(c, ep, 31);
      await delivery(c, ep, 400);
      const deleted = await c
        .query<{ n: number }>(`select webhook.prune_deliveries() as n`)
        .then((r) => r.rows[0]!.n);
      expect(deleted).toBe(2);
      const left = await c
        .query<{
          id: string;
        }>(`select id from webhook_deliveries where endpoint_id = $1 order by id`, [ep])
        .then((r) => r.rows.map((x) => x.id));
      expect(left).toEqual([...keep].sort());
    });
  });

  it("deletes at most p_batch rows per call, oldest first (EC-35)", async () => {
    await inTx(async (c) => {
      const ep = await seedEndpoint(c);
      for (const age of [40, 50, 60, 70, 80]) await delivery(c, ep, age);
      const first = await c
        .query<{ n: number }>(`select webhook.prune_deliveries(3) as n`)
        .then((r) => r.rows[0]!.n);
      expect(first).toBe(3);
      // The three oldest went first: the 40- and 50-day rows remain.
      const ages = await c
        .query<{ d: number }>(
          `select extract(day from now() - created_at)::int as d
             from webhook_deliveries where endpoint_id = $1 order by created_at desc`,
          [ep],
        )
        .then((r) => r.rows.map((x) => x.d));
      expect(ages).toEqual([40, 50]);
      const second = await c
        .query<{ n: number }>(`select webhook.prune_deliveries(3) as n`)
        .then((r) => r.rows[0]!.n);
      expect(second).toBe(2);
      expect(await remaining(c, ep)).toBe(0);
    });
  });

  it("rejects a non-positive batch size", async () => {
    await inTx(async (c) => {
      await c.query("savepoint s");
      await expect(c.query(`select webhook.prune_deliveries(0)`)).rejects.toThrow();
      await c.query("rollback to savepoint s");
    });
  });

  it("never deletes the run behind a pruned fired delivery (I-8)", async () => {
    await inTx(async (c) => {
      const ep = await seedEndpoint(c);
      const runId = await c
        .query<{ id: string }>(
          `insert into runs (id, agent_id, agent_version, trigger_type, triggered_by, status,
                             max_runtime_seconds, grace_seconds, start_timeout_seconds)
           select gen_random_uuid(), id, version, 'webhook', 'webhook:s167', 'queued',
                  max_runtime_seconds, grace_seconds, start_timeout_seconds
             from agents order by slug limit 1 returning id`,
        )
        .then((r) => r.rows[0]!.id);
      await delivery(c, ep, 90, runId);
      await c.query(`select webhook.prune_deliveries()`);
      expect(await remaining(c, ep)).toBe(0);
      const run = await c.query(`select id from runs where id = $1`, [runId]);
      expect(run.rows).toHaveLength(1);
    });
  });

  it("applies a horizon change from webhook.config", async () => {
    await inTx(async (c) => {
      const ep = await seedEndpoint(c);
      await delivery(c, ep, 5);
      await delivery(c, ep, 10);
      await c.query(`update webhook.config set value = '7' where key = 'delivery_retention_days'`);
      await c.query(`select webhook.prune_deliveries()`);
      expect(await remaining(c, ep)).toBe(1);
    });
  });

  it("never prunes a freshly inserted row, even with the shortest horizon (EC-17)", async () => {
    await inTx(async (c) => {
      const ep = await seedEndpoint(c);
      await c.query(`update webhook.config set value = '1' where key = 'delivery_retention_days'`);
      await c.query(`insert into webhook_deliveries (endpoint_id) values ($1)`, [ep]);
      await c.query(`select webhook.prune_deliveries()`);
      expect(await remaining(c, ep)).toBe(1);
    });
  });

  it("registers a daily pg_cron job that calls the prune", async () => {
    const job = await withDb((c) =>
      c
        .query<{
          schedule: string;
          command: string;
          active: boolean;
        }>(
          `select schedule, command, active from cron.job where jobname = 'webhook-prune-deliveries'`,
        )
        .then((r) => r.rows),
    );
    expect(job).toHaveLength(1);
    expect(job[0]!.active).toBe(true);
    expect(job[0]!.command).toMatch(/webhook\.prune_deliveries\(\)/);
    // Daily: fixed minute and hour, every day/month/weekday.
    expect(job[0]!.schedule).toMatch(/^\d{1,2} \d{1,2} \* \* \*$/);
  });

  it("is executable by service_role only", async () => {
    const p = await withDb((c) =>
      c
        .query<{ anon: boolean; authed: boolean; svc: boolean }>(
          `select has_function_privilege('anon', 'webhook.prune_deliveries(integer)', 'execute') as anon,
                  has_function_privilege('authenticated', 'webhook.prune_deliveries(integer)', 'execute') as authed,
                  has_function_privilege('service_role', 'webhook.prune_deliveries(integer)', 'execute') as svc`,
        )
        .then((r) => r.rows[0]!),
    );
    expect(p).toEqual({ anon: false, authed: false, svc: true });
  });
});

if (!probe.available) {
  describe("panel Layer 2.5 — S-167 webhook delivery prune (skipped)", () => {
    it.skip(`SKIPPED: ${probe.reason}`, () => {});
  });
}
