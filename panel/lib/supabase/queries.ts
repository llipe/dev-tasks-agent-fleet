/**
 * The typed read helpers for the panel's server-side data layer (AC2).
 *
 * Every helper takes an explicit `SupabaseClient` (created per request via
 * `createServerClient`) so it is trivially testable against a seeded local
 * stack, and surfaces any PostgREST failure as a `DatabaseError` (500) via
 * `unwrap` — the Postgres code is logged, never returned (§13, EC-9).
 *
 * Runs are always read through the `v_runs` view, never the raw `runs` table,
 * so `effective_status`, `agent_slug`, and `repository_full_name` are always
 * present (SD4 read path). List helpers return `[]` for an empty result, never
 * `null` (EC-17).
 */

import type { SupabaseClient } from "@supabase/supabase-js";
import { unwrap } from "@/lib/supabase/errors";
import type {
  AgentRow,
  RepositoryRow,
  RunArtifactRow,
  RunEventRow,
  RunStepRow,
  VRunRow,
} from "@/lib/supabase/types";

/** SD11 — the bounded initial `run_events` read cap. The SSE relay (S-110) */
/** streams the tail beyond this; the panel never issues an unbounded read. */
export const RUN_EVENTS_READ_LIMIT = 2000;

/** 1. Enabled agents, name-ordered. */
export async function getEnabledAgents(client: SupabaseClient): Promise<AgentRow[]> {
  const result = await client
    .from("agents")
    .select("*")
    .eq("is_enabled", true)
    .order("name", { ascending: true });
  return unwrap<AgentRow[]>("getEnabledAgents", result) ?? [];
}

/** 2. One agent by slug, or null when absent. */
export async function getAgentBySlug(
  client: SupabaseClient,
  slug: string,
): Promise<AgentRow | null> {
  const result = await client.from("agents").select("*").eq("slug", slug).maybeSingle();
  return unwrap<AgentRow | null>("getAgentBySlug", result);
}

/** 3. Enabled, non-archived repositories, name-ordered. */
export async function getEnabledRepositories(client: SupabaseClient): Promise<RepositoryRow[]> {
  const result = await client
    .from("repositories")
    .select("*")
    .eq("is_enabled", true)
    .is("archived_at", null)
    .order("full_name", { ascending: true });
  return unwrap<RepositoryRow[]>("getEnabledRepositories", result) ?? [];
}

/** 4. Runs for an agent slug, newest-first, from `v_runs`. */
export async function getRunsByAgentSlug(
  client: SupabaseClient,
  slug: string,
  limit = 50,
): Promise<VRunRow[]> {
  const result = await client
    .from("v_runs")
    .select("*")
    .eq("agent_slug", slug)
    .order("created_at", { ascending: false })
    .limit(limit);
  return unwrap<VRunRow[]>("getRunsByAgentSlug", result) ?? [];
}

/** 5. One run by id, from `v_runs`, or null when absent. */
export async function getRunById(client: SupabaseClient, id: string): Promise<VRunRow | null> {
  const result = await client.from("v_runs").select("*").eq("id", id).maybeSingle();
  return unwrap<VRunRow | null>("getRunById", result);
}

/** 6. `run_steps` for a run, `seq`-ordered ascending. */
export async function getRunSteps(client: SupabaseClient, runId: string): Promise<RunStepRow[]> {
  const result = await client
    .from("run_steps")
    .select("*")
    .eq("run_id", runId)
    .order("seq", { ascending: true });
  return unwrap<RunStepRow[]>("getRunSteps", result) ?? [];
}

/**
 * 7. `run_events` for a run — bounded (SD11) and `seq`-ordered ascending.
 *
 * The bound is applied to the **most recent** end (`seq` descending), then
 * re-sorted ascending for display, so a run with more than the cap yields its
 * latest `RUN_EVENTS_READ_LIMIT` events in reading order (EC-19).
 *
 * PostgREST enforces a per-request `max_rows` ceiling (1000 in this project's
 * `supabase/config.toml`), which is below the SD11 cap of 2000. A single
 * `.limit(2000)` would therefore silently return only 1000 rows. To honor the
 * SD11 contract without changing platform config, the read is paged with
 * `.range()` in chunks bounded by `PAGE_SIZE`, accumulating until it reaches
 * `limit` or the stream is exhausted.
 */
const PAGE_SIZE = 1000;

export async function getRunEvents(
  client: SupabaseClient,
  runId: string,
  limit = RUN_EVENTS_READ_LIMIT,
): Promise<RunEventRow[]> {
  const collected: RunEventRow[] = [];
  let offset = 0;
  while (collected.length < limit) {
    const pageSize = Math.min(PAGE_SIZE, limit - collected.length);
    const result = await client
      .from("run_events")
      .select("*")
      .eq("run_id", runId)
      .order("seq", { ascending: false })
      .range(offset, offset + pageSize - 1);
    const page = unwrap<RunEventRow[]>("getRunEvents", result) ?? [];
    collected.push(...page);
    if (page.length < pageSize) {
      break; // stream exhausted
    }
    offset += page.length;
  }
  // Collected newest-first (seq desc); return oldest-first for display.
  return collected.sort((a, b) => a.seq - b.seq);
}

/**
 * The minimal per-run projection the dashboard shaper (`lib/domain/dashboard.ts`)
 * consumes. Selecting only these columns keeps the grouped read light even
 * when an agent has thousands of runs, and every field the shaper needs to
 * derive `effective_status` is present (SD4 read-time derivation).
 */
export interface DashboardRunRow {
  agent_id: string;
  status: VRunRow["status"];
  started_at: string | null;
  queued_at: string;
  finished_at: string | null;
  created_at: string;
  max_runtime_seconds: number;
  grace_seconds: number;
  start_timeout_seconds: number;
  outcome: VRunRow["outcome"];
}

export interface DashboardData {
  agents: AgentRow[];
  /** Every run for the enabled agents, `agent_id`-keyed by the shaper. */
  runs: DashboardRunRow[];
}

const DASHBOARD_PAGE_SIZE = 1000;

/**
 * 9. The dashboard read (AC-107.1 / task 2.4).
 *
 * **Two reads total, never N+1 (CT-7):** one for the enabled agents, then a
 * single grouped `v_runs` read for the runs of *all* those agents via
 * `.in("agent_id", ids)`. The request count does not grow with the number of
 * agents — 8 agents and 16 agents each cost exactly two reads.
 *
 * **Bounded below PostgREST `max_rows`, and the count stays true (CT-8):** the
 * runs read pages internally with `.range()` in `DASHBOARD_PAGE_SIZE` chunks
 * (like `getRunEvents`), so an agent with more than 1,000 runs is fully
 * counted rather than silently truncated at the `max_rows=1000` ceiling. The
 * shaper computes counts from the returned rows, so a complete read is what
 * makes `runCount` the true count.
 *
 * Runs come from `v_runs`, never the raw table, so the shaper could read
 * `effective_status` directly; it re-derives from the snapshot instead (via
 * the shared `effectiveStatus`) so the dashboard and the row screens share one
 * derivation. Only the lightweight projection above is selected.
 *
 * Returns `{ agents: [], runs: [] }` for an empty fleet — never null (EC-19).
 */
export async function getDashboardData(client: SupabaseClient): Promise<DashboardData> {
  const agents = await getEnabledAgents(client);
  if (agents.length === 0) {
    return { agents: [], runs: [] };
  }

  const agentIds = agents.map((a) => a.id);
  const projection =
    "agent_id,status,started_at,queued_at,finished_at,created_at," +
    "max_runtime_seconds,grace_seconds,start_timeout_seconds,outcome";

  const runs: DashboardRunRow[] = [];
  let offset = 0;
  // Page until a short page signals the stream is exhausted. Ordered
  // newest-first so, if a future cap is introduced, it keeps the freshest runs.
  for (;;) {
    const result = await client
      .from("v_runs")
      .select(projection)
      .in("agent_id", agentIds)
      .order("created_at", { ascending: false })
      .range(offset, offset + DASHBOARD_PAGE_SIZE - 1);
    // A string projection loses PostgREST's row-type inference; the runtime
    // shape is DashboardRunRow[]. Cast through the unwrap contract.
    const page =
      unwrap<DashboardRunRow[]>(
        "getDashboardData",
        result as unknown as { data: DashboardRunRow[] | null; error: unknown },
      ) ?? [];
    runs.push(...page);
    if (page.length < DASHBOARD_PAGE_SIZE) break;
    offset += page.length;
  }

  return { agents, runs };
}

/**
 * Per-run step progress `done/total` (Story S-108).
 *
 * `n` (done) counts steps that have left `pending` (i.e. `status <> 'pending'`),
 * mirroring the prototype's `2/4`; `m` (total) counts every step of the run.
 */
export interface RunStepProgress {
  done: number;
  total: number;
}

/**
 * 11. Step progress for a set of runs, in ONE grouped read (never N+1).
 *
 * Reads only the two columns the aggregate needs (`run_id`, `status`) for every
 * step of the given run ids, then folds them into a `run_id → {done,total}`
 * map. A run absent from the map has no steps (`0/0`), which the row shaper
 * treats as such. Paged with `.range()` below the PostgREST `max_rows` ceiling
 * so a large history is not silently truncated (same pattern as getRunEvents).
 *
 * Returns an empty map for an empty id list — never issues a read for nothing.
 */
export async function getStepProgressForRuns(
  client: SupabaseClient,
  runIds: string[],
): Promise<Map<string, RunStepProgress>> {
  const progress = new Map<string, RunStepProgress>();
  if (runIds.length === 0) return progress;

  let offset = 0;
  for (;;) {
    const result = await client
      .from("run_steps")
      .select("run_id,status")
      .in("run_id", runIds)
      .order("run_id", { ascending: true })
      .range(offset, offset + PAGE_SIZE - 1);
    const page =
      unwrap<Array<{ run_id: string; status: string }>>(
        "getStepProgressForRuns",
        result as unknown as {
          data: Array<{ run_id: string; status: string }> | null;
          error: unknown;
        },
      ) ?? [];
    for (const step of page) {
      const current = progress.get(step.run_id) ?? { done: 0, total: 0 };
      current.total += 1;
      if (step.status !== "pending") current.done += 1;
      progress.set(step.run_id, current);
    }
    if (page.length < PAGE_SIZE) break;
    offset += page.length;
  }
  return progress;
}

/**
 * 12. Every run for an agent slug, newest-first, unfiltered and unpaginated
 * (Story S-108 / AC-108.1). Runs come from `v_runs`, so `effective_status`,
 * `agent_slug`, and `repository_full_name` are present.
 *
 * Unlike `getRunsByAgentSlug` (default limit 50), the run-history screen shows
 * the full history, so this pages through the whole result set with `.range()`
 * below the PostgREST `max_rows` ceiling (same pattern as getDashboardData) —
 * the count and the metrics stay true beyond 1,000 runs. Filters, search, and
 * pagination are deferred (PRD section 10); this returns the unbounded list.
 *
 * Returns `[]` for an agent with no runs — never null.
 */
export async function getAllRunsByAgentSlug(
  client: SupabaseClient,
  slug: string,
): Promise<VRunRow[]> {
  const runs: VRunRow[] = [];
  let offset = 0;
  for (;;) {
    const result = await client
      .from("v_runs")
      .select("*")
      .eq("agent_slug", slug)
      .order("created_at", { ascending: false })
      .range(offset, offset + PAGE_SIZE - 1);
    const page = unwrap<VRunRow[]>("getAllRunsByAgentSlug", result) ?? [];
    runs.push(...page);
    if (page.length < PAGE_SIZE) break;
    offset += page.length;
  }
  return runs;
}

/** 10. `run_artifacts` for a run, newest-first. */
export async function getRunArtifacts(
  client: SupabaseClient,
  runId: string,
): Promise<RunArtifactRow[]> {
  const result = await client
    .from("run_artifacts")
    .select("*")
    .eq("run_id", runId)
    .order("created_at", { ascending: false });
  return unwrap<RunArtifactRow[]>("getRunArtifacts", result) ?? [];
}
