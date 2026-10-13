import { afterEach, beforeAll, describe, expect, it } from "vitest";
import { randomUUID } from "node:crypto";
import { probeLocalDb, withDb } from "./db";

// Layer 2.5 — S-158 (#270): notify-sweep tick.
//
// scheduler.sweep_schedule_notifications() records the notable scheduled-run
// events the fire endpoint did not observe synchronously (SD-N1):
//   * run_failed    for terminal-failed scheduled runs (incl. reaper, AC10),
//                   feeding the G3 counter exactly once;
//   * pr_opened     for a late pull_request artifact + arming the G5 block;
//   * run_succeeded only when the schedule opted in (notify_on_success).
// Exactly-once via uq_notifications_run_kind -> idempotent (SD-N2). Docker-gated.

const probe = await probeLocalDb();

describe.skipIf(!probe.available)("panel Layer 2.5 — S-158 notify-sweep", () => {
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
      for (const id of runIds.splice(0)) {
        await c.query(`delete from notifications where run_id=$1`, [id]);
        await c.query(`delete from run_artifacts where run_id=$1`, [id]);
        await c.query(`delete from runs where id=$1`, [id]);
      }
      for (const id of scheduleIds.splice(0)) {
        await c.query(`delete from notifications where schedule_id=$1`, [id]);
        await c.query(`delete from schedules where id=$1`, [id]);
      }
    });
  });

  async function makeSchedule(
    opts: { notifyOnSuccess?: boolean; threshold?: number } = {},
  ): Promise<string> {
    const id = randomUUID();
    scheduleIds.push(id);
    await withDb((c) =>
      c.query(
        `insert into schedules (id, agent_id, repository_id, installation_id, params,
            cadence_kind, cadence_minute, cadence_hour, timezone, auto_pause_threshold, notify_on_success)
         values ($1,$2,$3,$4,'{"fix_mode":"audit_only"}'::jsonb,'daily',0,7,'America/Santiago',$5,$6)`,
        [id, agentId, repoId, installationId, opts.threshold ?? 3, opts.notifyOnSuccess ?? false],
      ),
    );
    return id;
  }

  async function makeRun(scheduleId: string, status: string): Promise<string> {
    const id = randomUUID();
    runIds.push(id);
    await withDb((c) =>
      c.query(
        `insert into runs (id, agent_id, agent_version, repository_id, installation_id,
            trigger_type, triggered_by, params, status, outcome, queued_at, finished_at, error_code,
            max_runtime_seconds, grace_seconds, start_timeout_seconds)
         values ($1,$2,'0.1.0',$3,$4,'schedule',$5,'{}'::jsonb,$6::run_status,
            case when $6='succeeded' then 'not_applicable'::run_outcome else null end, now(),
            case when $6 in ('failed','timed_out','failed_to_start','succeeded') then now() else null end,
            case when $6='failed' then 'INVOCATION_FAILED' else null end,
            3600,120,300)`,
        [id, agentId, repoId, installationId, `schedule:${scheduleId}`, status],
      ),
    );
    return id;
  }

  const sweep = () =>
    withDb((c) =>
      c
        .query<{ n: number }>(`select scheduler.sweep_schedule_notifications() n`)
        .then((r) => r.rows[0]!.n),
    );
  const notifsFor = (runId: string, kind: string) =>
    withDb((c) =>
      c
        .query<{
          n: string;
        }>(`select count(*)::text n from notifications where run_id=$1 and kind=$2`, [runId, kind])
        .then((r) => Number(r.rows[0]!.n)),
    );
  const scheduleRow = (id: string) =>
    withDb((c) =>
      c
        .query(
          `select state, block_reason, consecutive_failures, pr_block_run_id from schedules where id=$1`,
          [id],
        )
        .then((r) => r.rows[0]!),
    );

  it("records exactly one run_failed for a terminal-failed scheduled run and feeds G3 (AC10)", async () => {
    const sch = await makeSchedule({ threshold: 3 });
    const run = await makeRun(sch, "failed");

    expect(await sweep()).toBeGreaterThanOrEqual(1);
    expect(await notifsFor(run, "run_failed")).toBe(1);
    expect((await scheduleRow(sch)).consecutive_failures).toBe(1); // G3 fed once

    // Idempotent: a second sweep adds no duplicate and does not re-increment.
    await sweep();
    expect(await notifsFor(run, "run_failed")).toBe(1);
    expect((await scheduleRow(sch)).consecutive_failures).toBe(1);
  });

  it("materializes a reaper 'timed_out' failure via effective_status (AC10)", async () => {
    const sch = await makeSchedule();
    // A run left 'running' past max_runtime+grace -> v_runs.effective_status='timed_out'.
    const run = randomUUID();
    runIds.push(run);
    await withDb((c) =>
      c.query(
        `insert into runs (id, agent_id, agent_version, repository_id, installation_id,
            trigger_type, triggered_by, params, status, queued_at, started_at,
            max_runtime_seconds, grace_seconds, start_timeout_seconds)
         values ($1,$2,'0.1.0',$3,$4,'schedule',$5,'{}'::jsonb,'running',
            now() - interval '2 hours', now() - interval '2 hours', 60, 60, 300)`,
        [run, agentId, repoId, installationId, `schedule:${sch}`],
      ),
    );
    await sweep();
    expect(await notifsFor(run, "run_failed")).toBe(1);
    expect((await scheduleRow(sch)).consecutive_failures).toBe(1);
  });

  it("three terminal failures auto-pause the schedule (G3 via the sweep)", async () => {
    const sch = await makeSchedule({ threshold: 3 });
    await makeRun(sch, "failed");
    await sweep();
    await makeRun(sch, "failed");
    await sweep();
    await makeRun(sch, "timed_out");
    await sweep();
    const s = await scheduleRow(sch);
    expect(s.consecutive_failures).toBe(3);
    expect(s.state).toBe("paused");
  });

  it("records pr_opened for a late PR artifact and arms the G5 block (SD-N3)", async () => {
    const sch = await makeSchedule();
    const run = await makeRun(sch, "succeeded");
    await withDb((c) =>
      c.query(
        `insert into run_artifacts (run_id, type, title, url, metadata)
         values ($1,'pull_request','Bump deps','https://github.com/o/r/pull/7','{"number":7}'::jsonb)`,
        [run],
      ),
    );
    expect(await sweep()).toBeGreaterThanOrEqual(1);
    expect(await notifsFor(run, "pr_opened")).toBe(1);
    const s = await scheduleRow(sch);
    expect(s.state).toBe("blocked");
    expect(s.block_reason).toBe("open_pr");
    expect(s.pr_block_run_id).toBe(run);

    await sweep(); // idempotent
    expect(await notifsFor(run, "pr_opened")).toBe(1);
  });

  it("records run_succeeded only when the schedule opted in", async () => {
    const optOut = await makeSchedule({ notifyOnSuccess: false });
    const optIn = await makeSchedule({ notifyOnSuccess: true });
    const runOut = await makeRun(optOut, "succeeded");
    const runIn = await makeRun(optIn, "succeeded");

    await sweep();
    expect(await notifsFor(runOut, "run_succeeded")).toBe(0);
    expect(await notifsFor(runIn, "run_succeeded")).toBe(1);
  });
});

if (!probe.available) {
  describe("panel Layer 2.5 — S-158 notify-sweep (skipped)", () => {
    it.skip(`SKIPPED: ${probe.reason}`, () => {});
  });
}
