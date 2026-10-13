import { afterEach, beforeAll, describe, expect, it } from "vitest";
import { createClient, type SupabaseClient } from "@supabase/supabase-js";
import { randomUUID } from "node:crypto";
import { probeLocalDb, localRestConfig, withDb } from "./db";
import { recordScheduleFireFailure, recordScheduleFired } from "@/lib/supabase/queries";

// Layer 2.5 — S-157 (#269): G3 circuit breaker (consecutive-failure auto-pause).
//
// After N consecutive failed firings the schedule flips to 'paused' with
// block_reason='auto_paused:consecutive_failures' and records EXACTLY ONE
// schedule_auto_paused notification (AC6). A success resets the counter. The
// increment+trip+notify is atomic (public.scheduler_record_fire_failure).
// Docker-gated (#134).

const probe = await probeLocalDb();

function serviceClient(): SupabaseClient {
  const { url, serviceKey } = localRestConfig();
  return createClient(url, serviceKey, {
    auth: { autoRefreshToken: false, persistSession: false },
  });
}

describe.skipIf(!probe.available)("panel Layer 2.5 — S-157 G3 circuit breaker", () => {
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
  });

  afterEach(async () => {
    await withDb(async (c) => {
      for (const id of scheduleIds.splice(0)) {
        await c.query(`delete from notifications where schedule_id=$1`, [id]);
        await c.query(`delete from schedules where id=$1`, [id]);
      }
      for (const id of runIds.splice(0)) await c.query(`delete from runs where id=$1`, [id]);
    });
  });

  async function makeSchedule(threshold = 3): Promise<string> {
    const id = randomUUID();
    scheduleIds.push(id);
    await withDb((c) =>
      c.query(
        `insert into schedules (id, agent_id, repository_id, installation_id, params,
            cadence_kind, cadence_minute, cadence_hour, timezone, auto_pause_threshold)
         values ($1,$2,$3,$4,'{"fix_mode":"audit_only"}'::jsonb,'daily',0,7,'America/Santiago',$5)`,
        [id, agentId, repoId, installationId, threshold],
      ),
    );
    return id;
  }

  async function row(id: string) {
    return withDb((c) =>
      c
        .query(`select state, block_reason, consecutive_failures from schedules where id=$1`, [id])
        .then((r) => r.rows[0]!),
    );
  }
  async function autoPauseNotifs(id: string): Promise<number> {
    return withDb((c) =>
      c
        .query<{
          n: string;
        }>(
          `select count(*)::text n from notifications where schedule_id=$1 and kind='schedule_auto_paused'`,
          [id],
        )
        .then((r) => Number(r.rows[0]!.n)),
    );
  }

  it("increments on each failure, pauses + notifies exactly once at the threshold (AC6)", async () => {
    const sch = await makeSchedule(3);
    await recordScheduleFireFailure(client, sch, "INVOCATION_FAILED");
    expect((await row(sch)).consecutive_failures).toBe(1);
    expect((await row(sch)).state).toBe("active");

    await recordScheduleFireFailure(client, sch, "INVOCATION_FAILED");
    expect((await row(sch)).consecutive_failures).toBe(2);
    expect((await row(sch)).state).toBe("active");

    await recordScheduleFireFailure(client, sch, "RUNTIME_TIMEOUT");
    const s = await row(sch);
    expect(s.consecutive_failures).toBe(3);
    expect(s.state).toBe("paused");
    expect(s.block_reason).toBe("auto_paused:consecutive_failures");
    expect(await autoPauseNotifs(sch)).toBe(1); // EXACTLY one
  });

  it("a success resets the counter (2 fail, success, 2 fail -> no pause)", async () => {
    const sch = await makeSchedule(3);
    const runId = randomUUID();
    runIds.push(runId);
    await withDb((c) =>
      c.query(
        `insert into runs (id, agent_id, agent_version, repository_id, installation_id,
            trigger_type, params, status, queued_at, max_runtime_seconds, grace_seconds,
            start_timeout_seconds) values ($1,$2,'0.1.0',$3,$4,'schedule','{}'::jsonb,'queued',
            now(),3600,120,300)`,
        [runId, agentId, repoId, installationId],
      ),
    );

    await recordScheduleFireFailure(client, sch, "e");
    await recordScheduleFireFailure(client, sch, "e");
    await recordScheduleFired(client, sch, runId); // success resets
    expect((await row(sch)).consecutive_failures).toBe(0);

    await recordScheduleFireFailure(client, sch, "e");
    await recordScheduleFireFailure(client, sch, "e");
    const s = await row(sch);
    expect(s.consecutive_failures).toBe(2);
    expect(s.state).toBe("active"); // never reached 3-in-a-row
    expect(await autoPauseNotifs(sch)).toBe(0);
  });

  it("respects a per-schedule threshold of 1 (pause on the first failure)", async () => {
    const sch = await makeSchedule(1);
    await recordScheduleFireFailure(client, sch, "e");
    const s = await row(sch);
    expect(s.state).toBe("paused");
    expect(await autoPauseNotifs(sch)).toBe(1);
  });
});

if (!probe.available) {
  describe("panel Layer 2.5 — S-157 G3 circuit breaker (skipped)", () => {
    it.skip(`SKIPPED: ${probe.reason}`, () => {});
  });
}
