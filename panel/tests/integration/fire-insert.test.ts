import { afterEach, beforeAll, describe, expect, it } from "vitest";
import { createClient, type SupabaseClient } from "@supabase/supabase-js";
import { randomUUID } from "node:crypto";
import { probeLocalDb, localRestConfig, withDb } from "./db";
import { buildRunInsert } from "@/lib/domain/run-insert";
import {
  getScheduleById,
  getAgentById,
  insertQueuedRun,
  recordScheduleFired,
  recordScheduleFireFailure,
} from "@/lib/supabase/queries";

// Layer 2.5 — S-153 (#265): the fire path's DB operations against the real
// local stack. The invoke itself (AgentCore) is not exercised here (that is the
// endpoint's AWS boundary, mocked at L1); this proves the DB-level contract:
//  - a scheduled insert lands with trigger_type='schedule' / triggered_by (AC2);
//  - recordScheduleFired resets the counter + pins the run ref;
//  - recordScheduleFireFailure increments the counter (the G3 seam).

const probe = await probeLocalDb();

function serviceClient(): SupabaseClient {
  const { url, serviceKey } = localRestConfig();
  return createClient(url, serviceKey, {
    auth: { autoRefreshToken: false, persistSession: false },
  });
}

describe.skipIf(!probe.available)("panel Layer 2.5 — S-153 fire path DB ops", () => {
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
        .query<{ agent_id: string; repo_id: string; inst_id: string }>(
          `select a.id as agent_id, r.id as repo_id, r.installation_id as inst_id
             from agents a, repositories r
            where a.slug = 'dependency-update' and r.is_enabled and r.archived_at is null
            limit 1`,
        )
        .then((r) => r.rows[0]!),
    );
    agentId = seed.agent_id;
    repoId = seed.repo_id;
    installationId = seed.inst_id;
  });

  afterEach(async () => {
    await withDb(async (c) => {
      for (const id of runIds.splice(0)) await c.query(`delete from runs where id = $1`, [id]);
      for (const id of scheduleIds.splice(0))
        await c.query(`delete from schedules where id = $1`, [id]);
    });
  });

  async function makeSchedule(): Promise<string> {
    const id = randomUUID();
    scheduleIds.push(id);
    await withDb((c) =>
      c.query(
        `insert into schedules (id, agent_id, repository_id, installation_id, params,
                                cadence_kind, cadence_minute, cadence_hour, timezone,
                                consecutive_failures)
         values ($1,$2,$3,$4,$5::jsonb,'daily',0,7,'America/Santiago',2)`,
        [id, agentId, repoId, installationId, JSON.stringify({ fix_mode: "audit_only" })],
      ),
    );
    return id;
  }

  it("getScheduleById + getAgentById resolve the real rows", async () => {
    const scheduleId = await makeSchedule();
    const sched = await getScheduleById(client, scheduleId);
    expect(sched?.id).toBe(scheduleId);
    const agent = await getAgentById(client, agentId);
    expect(agent?.id).toBe(agentId);
  });

  it("insertQueuedRun with the schedule descriptor writes trigger_type/triggered_by (AC2)", async () => {
    const scheduleId = await makeSchedule();
    const runId = randomUUID();
    runIds.push(runId);
    const row = buildRunInsert({
      runId,
      agent: {
        id: agentId,
        version: "0.1.0",
        max_runtime_seconds: 3600,
        grace_seconds: 120,
        start_timeout_seconds: 300,
      },
      repositoryId: repoId,
      installationId,
      params: { fix_mode: "audit_only" },
      trigger: { triggerType: "schedule", triggeredBy: `schedule:${scheduleId}` },
    });
    await insertQueuedRun(client, row);

    const check = await withDb((c) =>
      c.query<{ trigger_type: string; triggered_by: string; status: string }>(
        `select trigger_type, triggered_by, status from runs where id = $1`,
        [runId],
      ),
    );
    expect(check.rows[0]).toMatchObject({
      trigger_type: "schedule",
      triggered_by: `schedule:${scheduleId}`,
      status: "queued",
    });
  });

  it("recordScheduleFired resets the counter, pins the run ref, clears block", async () => {
    const scheduleId = await makeSchedule();
    const runId = randomUUID();
    runIds.push(runId);
    await insertQueuedRun(
      client,
      buildRunInsert({
        runId,
        agent: {
          id: agentId,
          version: "0.1.0",
          max_runtime_seconds: 3600,
          grace_seconds: 120,
          start_timeout_seconds: 300,
        },
        repositoryId: repoId,
        installationId,
        params: { fix_mode: "audit_only" },
        trigger: { triggerType: "schedule", triggeredBy: `schedule:${scheduleId}` },
      }),
    );
    await recordScheduleFired(client, scheduleId, runId);
    const sched = await getScheduleById(client, scheduleId);
    expect(sched?.consecutive_failures).toBe(0);
    expect(sched?.last_run_id).toBe(runId);
    expect(sched?.last_fired_at).not.toBeNull();
  });

  it("recordScheduleFireFailure increments the counter (G3 seam)", async () => {
    const scheduleId = await makeSchedule(); // starts at 2
    await recordScheduleFireFailure(client, scheduleId, "INVOCATION_FAILED");
    const sched = await getScheduleById(client, scheduleId);
    expect(sched?.consecutive_failures).toBe(3);
    expect(sched?.last_fire_error).toBe("INVOCATION_FAILED");
  });
});

if (!probe.available) {
  describe("panel Layer 2.5 — S-153 fire path DB ops (skipped)", () => {
    it.skip(`SKIPPED: ${probe.reason}`, () => {});
  });
}
