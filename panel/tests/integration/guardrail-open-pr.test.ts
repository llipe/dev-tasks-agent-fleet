import { afterEach, beforeAll, describe, expect, it } from "vitest";
import { createClient, type SupabaseClient } from "@supabase/supabase-js";
import { randomUUID } from "node:crypto";
import { probeLocalDb, localRestConfig, withDb } from "./db";
import { clearSchedulePrBlock } from "@/lib/supabase/queries";

// Layer 2.5 — S-156 (#268): G5 open-PR backoff (phased a+c).
//
// A schedule is blocked while a prior run of the same (agent, repository) left
// an unresolved pull_request artifact (AC8). Resolved by: a manual clear
// (pr_block_cleared_at, G5-c) OR a later manual run (supersede, G5-a). v1 makes
// NO GitHub call. Docker-gated (#134).

const probe = await probeLocalDb();

function serviceClient(): SupabaseClient {
  const { url, serviceKey } = localRestConfig();
  return createClient(url, serviceKey, {
    auth: { autoRefreshToken: false, persistSession: false },
  });
}

describe.skipIf(!probe.available)("panel Layer 2.5 — S-156 G5 open-PR backoff", () => {
  let client: SupabaseClient;
  let agentId: string;
  let repoId: string;
  let installationId: string;
  const scheduleIds: string[] = [];
  const runIds: string[] = [];

  beforeAll(async () => {
    console.log(`[integration] ${probe.reason}`);
    client = serviceClient();
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
    await withDb((c) => c.query(`update scheduler.config set value='3' where key='max_inflight'`));
  });

  afterEach(async () => {
    await withDb(async (c) => {
      for (const id of runIds.splice(0)) await c.query(`delete from runs where id=$1`, [id]);
      for (const id of scheduleIds.splice(0))
        await c.query(`delete from schedules where id=$1`, [id]);
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

  // A terminal run that opened a PR (artifact), `minutesAgo` in the past.
  async function prRun(trigger: "schedule" | "manual", minutesAgo: number): Promise<string> {
    const id = randomUUID();
    runIds.push(id);
    await withDb(async (c) => {
      await c.query(
        `insert into runs (id, agent_id, agent_version, repository_id, installation_id,
            trigger_type, params, status, queued_at, started_at, finished_at, outcome,
            max_runtime_seconds, grace_seconds, start_timeout_seconds, created_at)
         values ($1,$2,'0.1.0',$3,$4,$5::trigger_type,'{}'::jsonb,'succeeded',
                 now()-interval '${minutesAgo} minutes', now()-interval '${minutesAgo} minutes',
                 now()-interval '${minutesAgo} minutes','fixed',3600,120,300,
                 now()-interval '${minutesAgo} minutes')`,
        [id, agentId, repoId, installationId, trigger],
      );
      await c.query(
        `insert into run_artifacts (run_id, type, title, url, created_at)
         values ($1,'pull_request','PR','https://github.com/x/y/pull/1', now()-interval '${minutesAgo} minutes')`,
        [id],
      );
    });
    return id;
  }

  // A terminal MANUAL run with no PR, `minutesAgo` in the past (supersede trigger).
  async function manualRun(minutesAgo: number): Promise<string> {
    const id = randomUUID();
    runIds.push(id);
    await withDb((c) =>
      c.query(
        `insert into runs (id, agent_id, agent_version, repository_id, installation_id,
            trigger_type, params, status, queued_at, started_at, finished_at, outcome,
            max_runtime_seconds, grace_seconds, start_timeout_seconds, created_at)
         values ($1,$2,'0.1.0',$3,$4,'manual','{}'::jsonb,'succeeded',
                 now()-interval '${minutesAgo} minutes', now()-interval '${minutesAgo} minutes',
                 now()-interval '${minutesAgo} minutes','no_vulnerabilities',3600,120,300,
                 now()-interval '${minutesAgo} minutes')`,
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
  async function state(id: string) {
    return withDb((c) =>
      c
        .query(
          `select state, block_reason, pr_block_run_id, last_fired_at from schedules where id=$1`,
          [id],
        )
        .then((r) => r.rows[0]!),
    );
  }

  it("blocks a due schedule while a prior run's PR is unresolved (AC8)", async () => {
    const sch = await dueSchedule();
    const run = await prRun("schedule", 30);
    const dispatched = await fire();
    expect(dispatched).toBe(0);
    const s = await state(sch);
    expect(s.state).toBe("blocked");
    expect(s.block_reason).toBe("open_pr");
    expect(s.pr_block_run_id).toBe(run);
  });

  it("resumes firing after a manual clear (G5-c)", async () => {
    const sch = await dueSchedule();
    await prRun("schedule", 30);
    await fire(); // blocked
    expect((await state(sch)).state).toBe("blocked");

    await clearSchedulePrBlock(client, sch); // operator: PR handled
    const dispatched = await fire(); // auto-clears + fires
    expect(dispatched).toBe(1);
    const s = await state(sch);
    expect(s.state).toBe("active");
    expect(s.block_reason).toBeNull();
  });

  it("resumes firing when a later manual run supersedes the PR (G5-a)", async () => {
    const sch = await dueSchedule();
    await prRun("schedule", 60); // PR 60 min ago
    await fire(); // blocked
    expect((await state(sch)).state).toBe("blocked");

    await manualRun(10); // a manual run 10 min ago supersedes the 60-min-old PR
    const dispatched = await fire();
    expect(dispatched).toBe(1);
    expect((await state(sch)).state).toBe("active");
  });

  it("stays blocked when a NEW PR appears after a prior clear (re-block, EC-18)", async () => {
    const sch = await dueSchedule();
    await prRun("schedule", 60);
    await fire(); // blocked
    // operator clears, but we pin the clear time to 30 min ago so a "newer" PR
    // (below) is unambiguously after it.
    await withDb((c) =>
      c.query(
        `update schedules set pr_block_cleared_at = now() - interval '30 minutes' where id=$1`,
        [sch],
      ),
    );
    await fire(); // clears + fires
    expect((await state(sch)).state).toBe("active");

    // a NEW scheduled run opens a NEW PR 1 min ago — newer than the 30-min-old clear
    await prRun("schedule", 1);
    // make the schedule due again (the earlier fire advanced its cursor)
    await withDb((c) =>
      c.query(`update schedules set next_run_at = now() - interval '5 minutes' where id=$1`, [sch]),
    );
    await fire();
    expect((await state(sch)).state).toBe("blocked"); // re-blocked on the new PR
  });
});

if (!probe.available) {
  describe("panel Layer 2.5 — S-156 G5 open-PR backoff (skipped)", () => {
    it.skip(`SKIPPED: ${probe.reason}`, () => {});
  });
}
