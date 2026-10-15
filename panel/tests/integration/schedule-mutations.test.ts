import { afterEach, beforeAll, describe, expect, it } from "vitest";
import { createClient, type SupabaseClient } from "@supabase/supabase-js";
import { probeLocalDb, localRestConfig, withDb } from "./db";
import {
  deleteSchedule,
  getSchedules,
  getScheduleCountByAgent,
  insertSchedule,
  pauseSchedule,
  previewNextRuns,
  resumeSchedule,
  updateSchedule,
  type ScheduleWriteInput,
} from "@/lib/supabase/queries";

// Layer 2.5 — S-161/S-162: schedule list read, mutations, create/edit, and the
// preview RPC against the real DB. Docker-gated (#134).

const probe = await probeLocalDb();

function serviceClient(): SupabaseClient {
  const { url, serviceKey } = localRestConfig();
  return createClient(url, serviceKey, {
    auth: { autoRefreshToken: false, persistSession: false },
  });
}

describe.skipIf(!probe.available)("panel Layer 2.5 — S-161/S-162 schedule list + CRUD", () => {
  let client: SupabaseClient;
  let agentId: string;
  let repoId: string;
  let installationId: string;
  const made: string[] = [];

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
      for (const id of made.splice(0)) await c.query(`delete from schedules where id=$1`, [id]);
    });
  });

  function writeInput(overrides: Partial<ScheduleWriteInput> = {}): ScheduleWriteInput {
    return {
      agentId,
      repositoryId: repoId,
      installationId,
      name: "nightly",
      params: { fix_mode: "audit_only" },
      cadenceKind: "daily",
      cadenceMinute: 0,
      cadenceHour: 7,
      cadenceWeekday: null,
      cadenceIntervalHours: null,
      cadenceCron: null,
      timezone: "America/Santiago",
      autoPauseThreshold: 3,
      notifyOnSuccess: false,
      ...overrides,
    };
  }

  it("insert → list (v_schedules carries agent/repo joins) → delete", async () => {
    const id = await insertSchedule(client, writeInput());
    made.push(id);

    const list = await getSchedules(client);
    const row = list.find((s) => s.id === id);
    expect(row).toBeTruthy();
    expect(row!.agent_slug).toBe("dependency-update");
    expect(row!.repository_full_name).toBeTruthy();
    expect(row!.cadence_kind).toBe("daily");

    await deleteSchedule(client, id);
    made.splice(made.indexOf(id), 1);
    expect((await getSchedules(client)).find((s) => s.id === id)).toBeUndefined();
  });

  it("pause sets paused+manual reason; resume clears state and the failure counter", async () => {
    const id = await insertSchedule(client, writeInput());
    made.push(id);
    await withDb((c) => c.query(`update schedules set consecutive_failures=2 where id=$1`, [id]));

    await pauseSchedule(client, id);
    let row = (await getSchedules(client)).find((s) => s.id === id)!;
    expect(row.state).toBe("paused");
    expect(row.block_reason).toBe("manual_pause");

    await resumeSchedule(client, id);
    row = (await getSchedules(client)).find((s) => s.id === id)!;
    expect(row.state).toBe("active");
    expect(row.block_reason).toBeNull();
    expect(row.consecutive_failures).toBe(0);
  });

  it("update rewrites cadence and re-seeds next_run_at (seed trigger bootstraps the cursor)", async () => {
    const id = await insertSchedule(client, writeInput());
    made.push(id);
    await withDb((c) => c.query(`update schedules set next_run_at=now() where id=$1`, [id]));

    await updateSchedule(
      client,
      id,
      writeInput({ cadenceKind: "weekly", cadenceWeekday: 1, cadenceHour: 4 }),
    );
    const row = (await getSchedules(client)).find((s) => s.id === id)!;
    expect(row.cadence_kind).toBe("weekly");
    expect(row.cadence_weekday).toBe(1);
    // updateSchedule nulls next_run_at; the BEFORE-UPDATE seed trigger immediately
    // recomputes it (active+enabled) so the schedule is never left un-fireable
    // (the live step-6 bug this fix closes).
    expect(row.next_run_at).not.toBeNull();
  });

  it("getScheduleCountByAgent counts the agent's schedules", async () => {
    const before = await getScheduleCountByAgent(client, agentId);
    const id = await insertSchedule(client, writeInput());
    made.push(id);
    expect(await getScheduleCountByAgent(client, agentId)).toBe(before + 1);
  });

  it("previewNextRuns returns upcoming instants from the authoritative RPC", async () => {
    const runs = await previewNextRuns(client, {
      kind: "daily",
      minute: 0,
      hour: 7,
      weekday: null,
      intervalHours: null,
      cron: null,
      timezone: "America/Santiago",
    });
    expect(runs.length).toBe(3);
    expect(new Date(runs[0]!).getTime()).toBeGreaterThan(Date.now());
  });
});

if (!probe.available) {
  describe("panel Layer 2.5 — S-161/S-162 schedule list + CRUD (skipped)", () => {
    it.skip(`SKIPPED: ${probe.reason}`, () => {});
  });
}
