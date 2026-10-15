/**
 * Deterministic schedule + notification seed/reset helpers for the Phase 4
 * scheduler E2E specs (S-161–S-164). Mirrors `seed.ts`: talks to the REAL local
 * Supabase Postgres over `pg`, resets to a known baseline per scenario, and
 * inserts exactly the rows a scenario asserts on. Never deletes the seeded
 * catalog (agents/repositories/installations).
 */

import { randomUUID } from "node:crypto";
import { withDb, getSeededIds } from "./seed";

/** Clear all schedules + notifications, leaving the seeded catalog intact. */
export async function resetSchedules(): Promise<void> {
  await withDb(async (c) => {
    await c.query(`delete from notifications`);
    await c.query(`delete from schedules`);
  });
}

export interface SeedScheduleSpec {
  state?: "active" | "paused" | "blocked";
  cadenceKind?: "hourly" | "daily" | "weekly" | "every_n_hours" | "advanced";
  cadenceMinute?: number | null;
  cadenceHour?: number | null;
  cadenceWeekday?: number | null;
  cadenceIntervalHours?: number | null;
  cadenceCron?: string | null;
  blockReason?: string | null;
  notifyOnSuccess?: boolean;
  /** null leaves next_run_at unset (the seed trigger will populate it for active). */
  nextRunAtIso?: string | null;
}

/** Insert a schedule against the seeded agent + first enabled repo. Returns id. */
export async function seedSchedule(spec: SeedScheduleSpec = {}): Promise<string> {
  const { agentId, repositoryId } = await getSeededIds();
  const id = randomUUID();
  await withDb(async (c) => {
    const inst = await c.query<{ installation_id: string }>(
      `select installation_id from repositories where id = $1`,
      [repositoryId],
    );
    await c.query(
      `insert into schedules
         (id, agent_id, repository_id, installation_id, params,
          cadence_kind, cadence_minute, cadence_hour, cadence_weekday,
          cadence_interval_hours, cadence_cron, timezone,
          state, block_reason, notify_on_success, next_run_at)
       values ($1,$2,$3,$4,'{"fix_mode":"audit_only"}'::jsonb,
               $5::cadence_kind,$6,$7,$8,$9,$10,'America/Santiago',
               $11::schedule_state,$12,$13,
               case when $14::timestamptz is null then null else $14::timestamptz end)`,
      [
        id,
        agentId,
        repositoryId,
        inst.rows[0].installation_id,
        spec.cadenceKind ?? "daily",
        spec.cadenceMinute ?? 0,
        spec.cadenceHour ?? 7,
        spec.cadenceWeekday ?? null,
        spec.cadenceIntervalHours ?? null,
        spec.cadenceCron ?? null,
        spec.state ?? "active",
        spec.blockReason ?? null,
        spec.notifyOnSuccess ?? false,
        spec.nextRunAtIso ?? null,
      ],
    );
  });
  return id;
}

/** Insert a notification (optionally tied to a run) for the feed specs. */
export async function seedNotification(spec: {
  kind: "run_failed" | "schedule_auto_paused" | "pr_opened" | "run_succeeded";
  title: string;
  detail?: string | null;
  runId?: string | null;
  scheduleId?: string | null;
  read?: boolean;
}): Promise<string> {
  const { agentId } = await getSeededIds();
  const id = randomUUID();
  await withDb(async (c) => {
    await c.query(
      `insert into notifications (id, kind, agent_id, schedule_id, run_id, title, detail, read_at)
       values ($1,$2::notification_kind,$3,$4,$5,$6,$7,
               case when $8 then now() else null end)`,
      [
        id,
        spec.kind,
        agentId,
        spec.scheduleId ?? null,
        spec.runId ?? null,
        spec.title,
        spec.detail ?? null,
        spec.read ?? false,
      ],
    );
  });
  return id;
}

export async function countSchedules(): Promise<number> {
  return withDb(async (c) =>
    c
      .query<{ n: string }>(`select count(*)::text n from schedules`)
      .then((r) => Number(r.rows[0].n)),
  );
}

export async function readSchedule(id: string): Promise<{
  state: string;
  cadence_kind: string;
  next_run_at: string | null;
  block_reason: string | null;
} | null> {
  return withDb(async (c) => {
    const r = await c.query(
      `select state, cadence_kind, next_run_at, block_reason from schedules where id=$1`,
      [id],
    );
    return r.rowCount === 0 ? null : (r.rows[0] as never);
  });
}

export async function unreadNotificationCount(): Promise<number> {
  return withDb(async (c) =>
    c
      .query<{ n: string }>(`select count(*)::text n from notifications where read_at is null`)
      .then((r) => Number(r.rows[0].n)),
  );
}
