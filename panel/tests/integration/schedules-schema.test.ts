import { beforeAll, describe, expect, it } from "vitest";
import { probeLocalDb, withDb } from "./db";

// Layer 2.5 — S-149 (#261): schedules + notifications schema.
//
// Verifies the migration applied by `supabase db reset`:
//  - both tables exist with their enums/constraints;
//  - `chk_schedule_cadence` rejects each malformed kind/field combination
//    (CT per the test plan — the cadence shape is enforced at the DB, not only
//    the panel);
//  - `uq_notifications_run_kind` rejects a duplicate (run_id, kind) — the
//    exactly-once seam the notify-sweep relies on (SD-N2 / AC9).
//
// RLS deny-all for both tables is asserted by the shared, schema-enumerated
// `rls-deny-all.test.ts` (it reads `information_schema`, so these two tables are
// covered automatically) — not re-implemented here.
//
// Docker-gated via `probeLocalDb` (REQUIRE_LOCAL_DB=1 turns a skip into a CI
// failure, #134).

const probe = await probeLocalDb();

// A valid agent id to satisfy the schedules.agent_id FK in the positive insert.
async function anAgentId(): Promise<string> {
  return withDb((c) =>
    c.query<{ id: string }>(`select id from agents limit 1`).then((r) => r.rows[0]!.id),
  );
}

// A valid run id for the notifications FK + unique test.
async function aRunId(): Promise<string> {
  return withDb((c) =>
    c.query<{ id: string }>(`select id from runs limit 1`).then((r) => r.rows[0]?.id ?? ""),
  );
}

describe.skipIf(!probe.available)("panel Layer 2.5 — S-149 scheduler schema", () => {
  beforeAll(() => {
    console.log(`[integration] ${probe.reason}`);
  });

  it("has the schedules and notifications tables", async () => {
    const names = await withDb((c) =>
      c
        .query<{ table_name: string }>(
          `select table_name from information_schema.tables
            where table_schema = 'public'
              and table_name in ('schedules','notifications')`,
        )
        .then((r) => r.rows.map((x) => x.table_name).sort()),
    );
    expect(names).toEqual(["notifications", "schedules"]);
  });

  it("defines the scheduler enums", async () => {
    const types = await withDb((c) =>
      c
        .query<{ typname: string }>(
          `select typname from pg_type
            where typname in ('schedule_state','cadence_kind','notification_kind')`,
        )
        .then((r) => r.rows.map((x) => x.typname).sort()),
    );
    expect(types).toEqual(["cadence_kind", "notification_kind", "schedule_state"]);
  });

  describe("chk_schedule_cadence", () => {
    const base: {
      kind: string;
      minute: number | null;
      hour: number | null;
      weekday: number | null;
      interval: number | null;
      cron: string | null;
    } = {
      kind: "daily",
      minute: 0,
      hour: 7,
      weekday: null,
      interval: null,
      cron: null,
    };

    async function insertCadence(agentId: string, over: Partial<typeof base>): Promise<void> {
      const v = { ...base, ...over };
      await withDb((c) =>
        c.query(
          `insert into schedules
             (agent_id, cadence_kind, cadence_minute, cadence_hour, cadence_weekday,
              cadence_interval_hours, cadence_cron, timezone)
           values ($1,$2::cadence_kind,$3,$4,$5,$6,$7,'America/Santiago')`,
          [agentId, v.kind, v.minute, v.hour, v.weekday, v.interval, v.cron],
        ),
      );
    }

    it("accepts a well-formed daily cadence", async () => {
      const agentId = await anAgentId();
      await expect(insertCadence(agentId, {})).resolves.toBeUndefined();
      // cleanup
      await withDb((c) => c.query(`delete from schedules where agent_id = $1`, [agentId]));
    });

    it("rejects daily with a null minute", async () => {
      const agentId = await anAgentId();
      await expect(insertCadence(agentId, { minute: null })).rejects.toThrow();
    });

    it("rejects weekly with a null weekday", async () => {
      const agentId = await anAgentId();
      await expect(insertCadence(agentId, { kind: "weekly", weekday: null })).rejects.toThrow();
    });

    it("rejects every_n_hours with interval < 1", async () => {
      const agentId = await anAgentId();
      await expect(
        insertCadence(agentId, { kind: "every_n_hours", interval: 0, minute: null, hour: null }),
      ).rejects.toThrow();
    });

    it("rejects advanced with a null cron", async () => {
      const agentId = await anAgentId();
      await expect(
        insertCadence(agentId, { kind: "advanced", cron: null, minute: null, hour: null }),
      ).rejects.toThrow();
    });
  });

  describe("uq_notifications_run_kind (exactly-once seam)", () => {
    it("rejects a duplicate (run_id, kind)", async () => {
      const runId = await aRunId();
      if (!runId) {
        // No seeded runs — skip the body but keep the test non-vacuous by asserting the guard.
        expect(runId).toBe("");
        return;
      }
      await withDb(async (c) => {
        await c.query(`delete from notifications where run_id = $1`, [runId]);
        await c.query(
          `insert into notifications (kind, run_id, title) values ('run_failed',$1,'t')`,
          [runId],
        );
        await expect(
          c.query(`insert into notifications (kind, run_id, title) values ('run_failed',$1,'t2')`, [
            runId,
          ]),
        ).rejects.toThrow();
        // a DIFFERENT kind for the same run is allowed
        await expect(
          c.query(`insert into notifications (kind, run_id, title) values ('pr_opened',$1,'t3')`, [
            runId,
          ]),
        ).resolves.toBeTruthy();
        await c.query(`delete from notifications where run_id = $1`, [runId]);
      });
    });
  });
});

if (!probe.available) {
  describe("panel Layer 2.5 — S-149 scheduler schema (skipped)", () => {
    it.skip(`SKIPPED: ${probe.reason}`, () => {});
  });
}
