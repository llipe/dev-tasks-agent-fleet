/**
 * The eight typed read helpers for the panel's server-side data layer (AC2).
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

/** 8. `run_artifacts` for a run, newest-first. */
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
