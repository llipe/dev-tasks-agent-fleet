import { afterEach, beforeAll, describe, expect, it } from "vitest";
import { randomUUID } from "node:crypto";
import { probeLocalDb, withDb } from "./db";

// Layer 2.5 — fix regression: a newly created schedule MUST get an initial
// next_run_at (the seed trigger, 20261013170000) and MUST then be fireable by
// fire_due_schedules(). The original design left next_run_at NULL on insert and
// the tick only selects `next_run_at is not null and <= now()`, so a brand-new
// schedule never fired -- caught in live step-6 verification. Docker-gated.

const probe = await probeLocalDb();

describe.skipIf(!probe.available)("panel Layer 2.5 — next_run_at seeding (fire bootstrap)", () => {
  let agentId: string;
  let repoId: string;
  let installationId: string;
  const made: string[] = [];

  beforeAll(async () => {
    console.log(`[integration] ${probe.reason}`);
    const seed = await withDb((c) =>
      c
        .query<{ a: string; r: string; i: string }>(
          `select a.id a, r.id r, r.installation_id i from agents a, repositories r
            where a.slug='dependency-update' and r.is_enabled and r.archived_at is null limit 1`,
        )
        .then((x) => x.rows[0]!),
    );
    agentId = seed.a;
    repoId = seed.r;
    installationId = seed.i;
  });

  afterEach(async () => {
    await withDb(async (c) => {
      for (const id of made.splice(0)) await c.query(`delete from schedules where id=$1`, [id]);
    });
  });

  async function insert(cols: string, vals: unknown[]): Promise<string> {
    const id = randomUUID();
    made.push(id);
    await withDb((c) =>
      c.query(
        `insert into schedules (id, agent_id, repository_id, installation_id, params, timezone, ${cols})
         values ($1,$2,$3,$4,'{"fix_mode":"audit_only"}'::jsonb,'America/Santiago',${vals.map((_, i) => `$${i + 5}`).join(",")})`,
        [id, agentId, repoId, installationId, ...vals],
      ),
    );
    return id;
  }
  const nextRunAt = (id: string) =>
    withDb((c) =>
      c
        .query(`select next_run_at from schedules where id=$1`, [id])
        .then((r) => r.rows[0]!.next_run_at),
    );

  it("seeds next_run_at on insert for an active enabled schedule (never null)", async () => {
    const id = await insert("cadence_kind, cadence_minute, cadence_hour", ["daily", 0, 7]);
    expect(await nextRunAt(id)).not.toBeNull();
  });

  it("does NOT seed a paused schedule (stays null — not due)", async () => {
    const id = await insert("cadence_kind, cadence_minute, cadence_hour, state", [
      "daily",
      0,
      7,
      "paused",
    ]);
    expect(await nextRunAt(id)).toBeNull();
  });

  it("re-seeds when a paused schedule is resumed to active", async () => {
    const id = await insert("cadence_kind, cadence_minute, cadence_hour, state", [
      "daily",
      0,
      7,
      "paused",
    ]);
    await withDb((c) =>
      c.query(`update schedules set state='active', next_run_at=null where id=$1`, [id]),
    );
    expect(await nextRunAt(id)).not.toBeNull();
  });

  it("a due schedule (next_run_at in the past) is fired by the tick (end-to-end bootstrap)", async () => {
    // every_n_hours seeds a cursor; force it due, then run the tick with config
    // present so it attempts a dispatch and advances the cursor (G2 cursor move).
    const id = await insert("cadence_kind, cadence_interval_hours", ["every_n_hours", 1]);
    expect(await nextRunAt(id)).not.toBeNull();
    await withDb((c) =>
      c.query(`update schedules set next_run_at = now() - interval '1 min' where id=$1`, [id]),
    );

    // Ensure the fire path has config so it doesn't early-return config_missing.
    await withDb(async (c) => {
      await c.query(
        `update scheduler.config set value='http://127.0.0.1:54321' where key='panel_base_url'`,
      );
    });
    await withDb((c) => c.query(`select scheduler.fire_due_schedules()`));

    const after = await withDb((c) =>
      c
        .query(
          `select next_run_at, last_fired_at, last_skipped_reason from schedules where id=$1`,
          [id],
        )
        .then((r) => r.rows[0]!),
    );
    // The tick either fired (last_fired_at set + cursor advanced into the future)
    // or skipped for a concrete reason — but it must NOT leave the row stuck in
    // the past with no action (the original bug).
    const advanced = after.last_fired_at !== null || after.last_skipped_reason !== null;
    expect(advanced).toBe(true);
  });
});

if (!probe.available) {
  describe("panel Layer 2.5 — next_run_at seeding (skipped)", () => {
    it.skip(`SKIPPED: ${probe.reason}`, () => {});
  });
}
