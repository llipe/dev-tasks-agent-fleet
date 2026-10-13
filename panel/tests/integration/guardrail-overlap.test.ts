import { afterEach, beforeAll, describe, expect, it } from "vitest";
import { randomUUID } from "node:crypto";
import { probeLocalDb, withDb } from "./db";

// Layer 2.5 — S-155 (#267): G1 overlap suppression.
//
// A schedule must not fire while a prior run for the same (agent, repository)
// is non-terminal by effective_status (SD-G1/SD-G0). The block is sticky
// (state='blocked'/block_reason='overlap') and auto-clears once the run is
// terminal — AC4. A stale 'running' past its reaper threshold reads as
// timed_out via v_runs and must NOT block forever.
//
// Docker-gated (REQUIRE_LOCAL_DB=1 -> CI failure, #134).

const probe = await probeLocalDb();

describe.skipIf(!probe.available)("panel Layer 2.5 — S-155 G1 overlap", () => {
  let agentId: string;
  let repoId: string;
  let installationId: string;
  const scheduleIds: string[] = [];
  const runIds: string[] = [];

  beforeAll(async () => {
    console.log(`[integration] ${probe.reason}`);
    const seed = await withDb((c) =>
      c
        .query<{ a: string; r: string; i: string }>(
          `select a.id a, r.id r, r.installation_id i
             from agents a, repositories r
            where a.slug='dependency-update' and r.is_enabled and r.archived_at is null limit 1`,
        )
        .then((x) => x.rows[0]!),
    );
    agentId = seed.a;
    repoId = seed.r;
    installationId = seed.i;
    await withDb((c) => c.query(`update scheduler.config set value='3' where key='max_inflight'`));
  });

  afterEach(async () => {
    await withDb(async (c) => {
      for (const id of runIds.splice(0)) await c.query(`delete from runs where id=$1`, [id]);
      for (const id of scheduleIds.splice(0)) await c.query(`delete from schedules where id=$1`, [id]);
    });
  });

  async function dueSchedule(): Promise<string> {
    const id = randomUUID();
    scheduleIds.push(id);
    await withDb((c) =>
      c.query(
        `insert into schedules (id, agent_id, repository_id, installation_id, params,
            cadence_kind, cadence_minute, cadence_hour, timezone, state, is_enabled, next_run_at)
         values ($1,$2,$3,$4,'{"fix_mode":"audit_only"}'::jsonb,'daily',0,7,'America/Santiago',
                 'active', true, now() - interval '5 minutes')`,
        [id, agentId, repoId, installationId],
      ),
    );
    return id;
  }

  // Insert a run for the SAME (agent, repo). `freshRunning` is well within its
  // timeout (active); `staleRunning` is far past max_runtime+grace (reaper will
  // flip it, so v_runs reads timed_out).
  async function insertRun(kind: "fresh-running" | "stale-running" | "succeeded"): Promise<string> {
    const id = randomUUID();
    runIds.push(id);
    const startedAgo = kind === "stale-running" ? "10 hours" : "1 minute";
    const status = kind === "succeeded" ? "succeeded" : "running";
    await withDb((c) =>
      c.query(
        `insert into runs (id, agent_id, agent_version, repository_id, installation_id,
            trigger_type, params, status, queued_at, started_at,
            max_runtime_seconds, grace_seconds, start_timeout_seconds, outcome)
         values ($1,$2,'0.1.0',$3,$4,'schedule','{}'::jsonb,$5::run_status,
                 now()-interval '${startedAgo}', now()-interval '${startedAgo}',
                 3600,120,300, $6)`,
        [id, agentId, repoId, installationId, status, kind === "succeeded" ? "no_vulnerabilities" : null],
      ),
    );
    return id;
  }

  async function fire(): Promise<number> {
    return withDb((c) =>
      c.query<{ n: number }>(`select scheduler.fire_due_schedules() as n`).then((r) => r.rows[0]!.n),
    );
  }
  async function state(id: string) {
    return withDb((c) =>
      c
        .query(`select state, block_reason, last_fired_at from schedules where id=$1`, [id])
        .then((r) => r.rows[0]!),
    );
  }

  it("blocks a due schedule while a fresh running run for the same (agent,repo) exists (AC4)", async () => {
    const sch = await dueSchedule();
    await insertRun("fresh-running");
    const dispatched = await fire();
    expect(dispatched).toBe(0);
    const s = await state(sch);
    expect(s.state).toBe("blocked");
    expect(s.block_reason).toBe("overlap");
    expect(s.last_fired_at).toBeNull();
  });

  it("auto-clears and fires once the prior run is terminal (AC4)", async () => {
    const sch = await dueSchedule();
    const run = await insertRun("fresh-running");
    await fire(); // blocked
    expect((await state(sch)).state).toBe("blocked");

    // the run finishes
    await withDb((c) =>
      c.query(`update runs set status='succeeded', outcome='no_vulnerabilities', finished_at=now() where id=$1`, [run]),
    );
    const dispatched = await fire(); // should auto-clear + fire
    expect(dispatched).toBe(1);
    const s = await state(sch);
    expect(s.state).toBe("active");
    expect(s.block_reason).toBeNull();
    expect(s.last_fired_at).not.toBeNull();
  });

  it("a STALE running run (past reaper threshold) does NOT block (effective_status=timed_out)", async () => {
    const sch = await dueSchedule();
    await insertRun("stale-running");
    const dispatched = await fire();
    expect(dispatched).toBe(1); // not blocked — v_runs reads it as timed_out
    expect((await state(sch)).state).toBe("active");
  });

  it("does not block a different repository's schedule (block scope is (agent,repo))", async () => {
    // active run on repoId; a schedule for the SAME agent but with repository_id null
    const other = randomUUID();
    scheduleIds.push(other);
    await withDb((c) =>
      c.query(
        `insert into schedules (id, agent_id, repository_id, installation_id, params,
            cadence_kind, cadence_minute, cadence_hour, timezone, state, is_enabled, next_run_at)
         values ($1,$2,null,null,'{"fix_mode":"audit_only"}'::jsonb,'daily',0,7,'America/Santiago',
                 'active', true, now() - interval '5 minutes')`,
        [other, agentId],
      ),
    );
    await insertRun("fresh-running"); // on repoId
    await fire();
    // the null-repo schedule is a different (agent,repo) key -> not blocked
    expect((await state(other)).state).toBe("active");
  });
});

if (!probe.available) {
  describe("panel Layer 2.5 — S-155 G1 overlap (skipped)", () => {
    it.skip(`SKIPPED: ${probe.reason}`, () => {});
  });
}
