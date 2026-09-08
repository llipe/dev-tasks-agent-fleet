/**
 * Deterministic per-scenario DB seed/reset helpers (S-114 task 1.7).
 *
 * Every E2E scenario resets the run-related tables to a known baseline first,
 * then inserts exactly the rows it asserts on — so no scenario depends on
 * another's order or leftovers (story Business Rules: "reset state between
 * scenarios; no dependence on scenario order").
 *
 * These helpers talk to the REAL local Supabase Postgres over `pg` (the
 * seeding path is not the panel's read path, so a direct SQL connection is the
 * right tool — it is faster and lets us set explicit clocks the app cannot).
 *
 * The base seed (`supabase/seed.sql`, applied by `global-setup.ts` via
 * `supabase db reset`) provides the `dependency-update` agent + the two repos.
 * These helpers add/clear RUNS and their children; they never delete the agent
 * or the installation, so the seeded catalog is stable across scenarios.
 */

import { randomUUID } from "node:crypto";
import { Client, type ClientConfig } from "pg";

export function localDbConfig(): ClientConfig {
  return {
    host: process.env.SUPABASE_DB_HOST ?? "127.0.0.1",
    port: Number(process.env.SUPABASE_DB_PORT ?? "54322"),
    user: process.env.SUPABASE_DB_USER ?? "postgres",
    password: process.env.SUPABASE_DB_PASSWORD ?? "postgres",
    database: process.env.SUPABASE_DB_NAME ?? "postgres",
    connectionTimeoutMillis: Number(process.env.SUPABASE_DB_TIMEOUT_MS ?? "3000"),
  };
}

export async function withDb<T>(fn: (client: Client) => Promise<T>): Promise<T> {
  const client = new Client(localDbConfig());
  await client.connect();
  try {
    return await fn(client);
  } finally {
    await client.end().catch(() => {});
  }
}

/**
 * Clear all run-scoped data, leaving the seeded catalog (agents, repositories,
 * installations) intact. Children first to satisfy FKs; `runs` cascades to its
 * children in the schema, but we delete explicitly so this helper does not
 * depend on cascade configuration.
 */
export async function resetRuns(): Promise<void> {
  await withDb(async (c) => {
    await c.query(`delete from run_events`);
    await c.query(`delete from run_artifacts`);
    await c.query(`delete from run_steps`);
    await c.query(`delete from runs`);
  });
}

/** Resolve the seeded `dependency-update` agent id + a seeded repository id. */
export async function getSeededIds(): Promise<{
  agentId: string;
  agentSlug: string;
  repositoryId: string;
  repositoryFullName: string;
}> {
  return withDb(async (c) => {
    const agent = await c.query<{ id: string; slug: string }>(
      `select id, slug from agents where slug = 'dependency-update'`,
    );
    if (agent.rowCount === 0) {
      throw new Error(
        "seed fixture: 'dependency-update' agent not found — did global-setup run `supabase db reset`?",
      );
    }
    const repo = await c.query<{ id: string; full_name: string }>(
      `select id, full_name from repositories where is_enabled = true and archived_at is null
       order by full_name limit 1`,
    );
    if (repo.rowCount === 0) {
      throw new Error("seed fixture: no enabled repository found in the seeded catalog");
    }
    return {
      agentId: agent.rows[0].id,
      agentSlug: agent.rows[0].slug,
      repositoryId: repo.rows[0].id,
      repositoryFullName: repo.rows[0].full_name,
    };
  });
}

export type RunStatus =
  | "queued"
  | "running"
  | "succeeded"
  | "failed"
  | "canceled"
  | "timed_out"
  | "failed_to_start";

export interface SeedRunSpec {
  status: RunStatus;
  /** started_at = now() - startedAgoSecs; null leaves started_at null. */
  startedAgoSecs?: number | null;
  /** queued_at = now() - queuedAgoSecs (default 60). */
  queuedAgoSecs?: number;
  finishedAgoSecs?: number | null;
  maxRuntimeSeconds?: number;
  graceSeconds?: number;
  startTimeoutSeconds?: number;
  outcome?: string | null;
  repositoryId?: string | null;
  errorMessage?: string | null;
}

/** Insert a run against the seeded agent with explicit clocks. Returns run id. */
export async function seedRun(spec: SeedRunSpec): Promise<string> {
  const { agentId } = await getSeededIds();
  const runId = randomUUID();
  await withDb(async (c) => {
    await c.query(
      `insert into runs (id, agent_id, agent_version, status, repository_id,
                         queued_at, started_at, finished_at,
                         max_runtime_seconds, grace_seconds, start_timeout_seconds,
                         outcome, error_message)
       values ($1, $2, '0.1.0', $3::run_status, $4,
               now() - make_interval(secs => $5::int),
               case when $6::int is null then null else now() - make_interval(secs => $6::int) end,
               case when $7::int is null then null else now() - make_interval(secs => $7::int) end,
               $8::int, $9::int, $10::int,
               $11::run_outcome, $12)`,
      [
        runId,
        agentId,
        spec.status,
        spec.repositoryId ?? null,
        spec.queuedAgoSecs ?? 60,
        spec.startedAgoSecs === undefined ? null : spec.startedAgoSecs,
        spec.finishedAgoSecs === undefined ? null : spec.finishedAgoSecs,
        spec.maxRuntimeSeconds ?? 3600,
        spec.graceSeconds ?? 120,
        spec.startTimeoutSeconds ?? 300,
        spec.outcome ?? null,
        spec.errorMessage ?? null,
      ],
    );
  });
  return runId;
}

/** Append a `run_events` row (agent-assigned monotonic seq). */
export async function seedEvent(
  runId: string,
  seq: number,
  message: string,
  level = "info",
): Promise<void> {
  await withDb(async (c) => {
    await c.query(
      `insert into run_events (run_id, seq, ts, level, message)
       values ($1, $2::int, now(), $3, $4)`,
      [runId, seq, level, message],
    );
  });
}

/** Attach a run artifact (e.g. a pull_request link for Scenario 7). */
export async function seedArtifact(
  runId: string,
  type: "pull_request" | "audit_report" | "diff" | "file",
  title: string,
  url: string | null,
): Promise<void> {
  await withDb(async (c) => {
    await c.query(
      `insert into run_artifacts (run_id, type, title, url) values ($1, $2::artifact_type, $3, $4)`,
      [runId, type, title, url],
    );
  });
}

/** Count runs (used by Scenario 1/5 to assert insert / no-insert). */
export async function countRuns(): Promise<number> {
  return withDb(async (c) => {
    const r = await c.query<{ n: string }>(`select count(*)::text as n from runs`);
    return Number(r.rows[0].n);
  });
}

/** Read a single run row's status + timeout snapshots (Scenario 1 assertions). */
export async function readRun(runId: string): Promise<{
  status: string;
  max_runtime_seconds: number | null;
  grace_seconds: number | null;
  start_timeout_seconds: number | null;
} | null> {
  return withDb(async (c) => {
    const r = await c.query(
      `select status, max_runtime_seconds, grace_seconds, start_timeout_seconds
       from runs where id = $1`,
      [runId],
    );
    if (r.rowCount === 0) return null;
    const row = r.rows[0];
    return {
      status: row.status,
      max_runtime_seconds: row.max_runtime_seconds,
      grace_seconds: row.grace_seconds,
      start_timeout_seconds: row.start_timeout_seconds,
    };
  });
}

/**
 * Toggle the seeded `dependency-update` agent's `is_enabled` flag. Used only by
 * the empty-fleet edge case (Scenario 1.16), which must present the dashboard's
 * "no agents configured" state; restore to `true` immediately after.
 */
export async function setSeededAgentEnabled(enabled: boolean): Promise<void> {
  await withDb(async (c) => {
    await c.query(`update agents set is_enabled = $1 where slug = 'dependency-update'`, [enabled]);
  });
}

/** The most recent run's id (Scenario 1: find the row the invoke created). */
export async function latestRunId(): Promise<string | null> {
  return withDb(async (c) => {
    const r = await c.query<{ id: string }>(`select id from runs order by created_at desc limit 1`);
    return r.rowCount === 0 ? null : r.rows[0].id;
  });
}
