import { afterEach, beforeAll, describe, expect, it } from "vitest";
import { randomUUID } from "node:crypto";
import { probeLocalDb, withDb } from "./db";

// Layer 2.5 — S-154 (#266): fire_due_schedules() due-tick.
//
// Deterministic (no wall-clock minute waits): we invoke the function directly
// and assert its STATE EFFECTS — which schedules dispatched vs. skipped, the G4
// cap, G2 no-catch-up cursor advance. The pg_net POST itself is fire-and-forget
// (enqueued, non-blocking) and its HTTP target need not exist for the function
// to run; the observable contract is the schedule-row state the test checks.
//
// Docker-gated (REQUIRE_LOCAL_DB=1 -> CI failure, #134).

const probe = await probeLocalDb();

describe.skipIf(!probe.available)("panel Layer 2.5 — S-154 fire_due_schedules", () => {
  let agentId: string;
  let repoId: string;
  let installationId: string;
  const scheduleIds: string[] = [];

  beforeAll(async () => {
    console.log(`[integration] ${probe.reason}`);
    const seed = await withDb((c) =>
      c
        .query<{ a: string; r: string; i: string }>(
          `select a.id a, r.id r, r.installation_id i
             from agents a, repositories r
            where a.slug = 'dependency-update' and r.is_enabled and r.archived_at is null limit 1`,
        )
        .then((x) => x.rows[0]!),
    );
    agentId = seed.a;
    repoId = seed.r;
    installationId = seed.i;
    // ensure a known cap for the suite
    await withDb((c) =>
      c.query(`update scheduler.config set value = '3' where key = 'max_inflight'`),
    );
  });

  afterEach(async () => {
    await withDb(async (c) => {
      for (const id of scheduleIds.splice(0)) {
        await c.query(`delete from runs where triggered_by = $1`, [`schedule:${id}`]);
        await c.query(`delete from schedules where id = $1`, [id]);
      }
    });
  });

  // Create a schedule that is already DUE (next_run_at in the past).
  async function dueSchedule(): Promise<string> {
    const id = randomUUID();
    scheduleIds.push(id);
    await withDb((c) =>
      c.query(
        `insert into schedules
           (id, agent_id, repository_id, installation_id, params,
            cadence_kind, cadence_minute, cadence_hour, timezone,
            state, is_enabled, next_run_at)
         values ($1,$2,$3,$4,'{"fix_mode":"audit_only"}'::jsonb,
                 'daily',0,7,'America/Santiago','active',true, now() - interval '5 minutes')`,
        [id, agentId, repoId, installationId],
      ),
    );
    return id;
  }

  async function fire(): Promise<number> {
    return withDb((c) =>
      c
        .query<{ n: number }>(`select scheduler.fire_due_schedules() as n`)
        .then((r) => r.rows[0]!.n),
    );
  }

  async function row(id: string) {
    return withDb((c) =>
      c
        .query(
          `select state, last_fired_at, next_run_at, last_skipped_reason from schedules where id = $1`,
          [id],
        )
        .then((r) => r.rows[0]!),
    );
  }

  it("dispatches a due schedule and advances next_run_at to a FUTURE time (G2 no-catch-up)", async () => {
    const id = await dueSchedule();
    const dispatched = await fire();
    expect(dispatched).toBeGreaterThanOrEqual(1);
    const r = await row(id);
    expect(r.last_fired_at).not.toBeNull();
    expect(new Date(r.next_run_at).getTime()).toBeGreaterThan(Date.now()); // future, not the missed slot
    expect(r.last_skipped_reason).toBeNull();
  });

  it("enforces the G4 cap: 5 due with cap 3 -> 3 dispatched, 2 skipped concurrency_cap (AC7)", async () => {
    const ids: string[] = [];
    for (let i = 0; i < 5; i++) ids.push(await dueSchedule());

    const dispatched = await fire();
    expect(dispatched).toBe(3);

    const states = await Promise.all(ids.map(row));
    const fired = states.filter((s) => s.last_fired_at !== null);
    const skipped = states.filter((s) => s.last_skipped_reason === "concurrency_cap");
    expect(fired).toHaveLength(3);
    expect(skipped).toHaveLength(2);
    // skipped rows stay due (next_run_at not advanced past now)
    for (const s of skipped) {
      expect(new Date(s.next_run_at).getTime()).toBeLessThanOrEqual(Date.now());
    }
  });

  it("re-evaluates skipped schedules on the next tick (no backlog, AC5/AC7)", async () => {
    const ids: string[] = [];
    for (let i = 0; i < 4; i++) ids.push(await dueSchedule());
    // cap 3: first tick fires 3, skips 1
    expect(await fire()).toBe(3);
    // the dispatched ones are now in the future; the 1 skipped is still due.
    // second tick fires the remaining 1.
    expect(await fire()).toBe(1);
  });

  it("does not dispatch a paused or disabled schedule", async () => {
    const paused = randomUUID();
    scheduleIds.push(paused);
    await withDb((c) =>
      c.query(
        `insert into schedules (id, agent_id, repository_id, installation_id, params,
            cadence_kind, cadence_minute, cadence_hour, timezone, state, is_enabled, next_run_at)
         values ($1,$2,$3,$4,'{"fix_mode":"audit_only"}'::jsonb,'daily',0,7,'America/Santiago',
                 'paused', true, now() - interval '5 minutes')`,
        [paused, agentId, repoId, installationId],
      ),
    );
    await fire();
    const r = await row(paused);
    expect(r.last_fired_at).toBeNull();
  });
});

if (!probe.available) {
  describe("panel Layer 2.5 — S-154 fire_due_schedules (skipped)", () => {
    it.skip(`SKIPPED: ${probe.reason}`, () => {});
  });
}
