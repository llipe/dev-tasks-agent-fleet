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
import { DatabaseError, unwrap } from "@/lib/supabase/errors";
import type { RunInsert } from "@/lib/domain/run-insert";
import { escapeIlikeWildcards, type RunFilter } from "@/lib/domain/run-filter";
import type { RunStatus } from "@/lib/domain/status";
import type {
  AgentRow,
  GithubInstallationRow,
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

/**
 * 3b. One repository by id, or null when absent (S-112 / #125).
 *
 * The invoke route resolves the repository the operator selected, then checks
 * `is_enabled` / `archived_at` at the route level so it can return a precise
 * error. This helper does the raw read only.
 */
export async function getRepositoryById(
  client: SupabaseClient,
  id: string,
): Promise<RepositoryRow | null> {
  const result = await client.from("repositories").select("*").eq("id", id).maybeSingle();
  return unwrap<RepositoryRow | null>("getRepositoryById", result);
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
 * 11b. Pull-request artifacts for a set of runs, in ONE grouped read (never
 * N+1 — Story S-144, spec §10/§11, issue #204). Mirrors the
 * `getStepProgressForRuns` shape exactly: a single `run_artifacts` read
 * filtered to `type = 'pull_request'` for every given run id, folded into a
 * `run_id → RunArtifactRow` map (returned as a plain object per the story's
 * documented `Record<string, RunArtifactRow>` shape).
 *
 * **Tie-break (v1.1 addendum, binding):** a single run may carry more than
 * one `pull_request` artifact (e.g. superseded/reopened PR). The read orders
 * `created_at` DESCENDING, and the fold keeps only the FIRST artifact seen per
 * `run_id` — i.e. the most-recently-created one wins (`order by created_at
 * desc limit 1` per `run_id`), never incidental row order.
 *
 * A run absent from the result has no `pull_request` artifact — the row
 * renders its existing branch-only markup, unchanged (AC2). Paged with
 * `.range()` below the PostgREST `max_rows` ceiling (same pattern as
 * `getStepProgressForRuns`), so a page with an unusually large number of PRs
 * per run is never silently truncated mid-tie-break.
 *
 * Returns `{}` for an empty id list — never issues a read for nothing
 * (zero-cost, AC3).
 */
export async function getPullRequestArtifactsForRuns(
  client: SupabaseClient,
  runIds: string[],
): Promise<Record<string, RunArtifactRow>> {
  const result: Record<string, RunArtifactRow> = {};
  if (runIds.length === 0) return result;

  let offset = 0;
  for (;;) {
    const query = client
      .from("run_artifacts")
      .select("*")
      .in("run_id", runIds)
      .eq("type", "pull_request")
      .order("created_at", { ascending: false })
      .range(offset, offset + PAGE_SIZE - 1);
    const res = await query;
    const page = unwrap<RunArtifactRow[]>("getPullRequestArtifactsForRuns", res) ?? [];
    for (const artifact of page) {
      // First occurrence per run_id wins — `created_at desc` ordering makes
      // that occurrence the most-recently-created one (the binding tie-break).
      if (!(artifact.run_id in result)) {
        result[artifact.run_id] = artifact;
      }
    }
    if (page.length < PAGE_SIZE) break;
    offset += page.length;
  }
  return result;
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

/**
 * 12b. The Run History filter/pagination read (Story S-143, spec §8.1,
 * FR1–FR6/FR13). Runs come from `v_runs` (so `effective_status` is always the
 * filtered/displayed status, never raw `runs.status` — FR11a), newest-first,
 * cumulative-offset-paged (spec §8.1's pagination decision: `page` means
 * "show pages 1..page inclusive", matching the codebase's exclusive use of
 * `.range()`-based offset paging elsewhere).
 *
 * `filter.agentSlug` scopes to one agent (`/agents/[slug]`); `null` reads
 * across every agent (S-146's `/runs`, FR13 reuse). `filter.status === "all"`
 * applies no status filter. `filter.search` is escaped for `ilike` wildcard
 * metacharacters before being interpolated (spec §8.1 v1.1 addendum) and
 * matches a `repository_full_name` substring, plus an exact `id` match when
 * the search term is itself a syntactically valid UUID (a discovered query-
 * shape constraint: PostgREST's `.or()` grammar rejects a `::type` cast in a
 * filter column, and Postgres rejects an un-cast `ilike` against a `uuid`
 * column — substring matching the run id is not reachable without a schema
 * change, out of scope for this reads-only story; documented here as a shape
 * decision). `branch` lives inside the unfilterable `params` JSON blob and is
 * likewise out of scope (the binding spec text names only `repository_full_name`
 * and the run id).
 *
 * Returns `{ rows: [], totalCount: 0 }` for a zero-match filter — never
 * `null`/`undefined` (CT-2).
 */
export interface FilteredRunsResult {
  rows: VRunRow[];
  totalCount: number;
}

/** Builds the shared conditional filters (every clause except `.range()` and status). */
function applyRunFilterClauses(
  query: { eq: (col: string, val: string) => unknown; or: (clause: string) => unknown },
  filter: Pick<RunFilter, "agentSlug" | "repositoryId" | "search">,
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
): any {
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  let q: any = query;
  if (filter.agentSlug != null) {
    q = q.eq("agent_slug", filter.agentSlug);
  }
  if (filter.repositoryId != null) {
    q = q.eq("repository_id", filter.repositoryId);
  }
  const trimmedSearch = filter.search?.trim();
  if (trimmedSearch != null && trimmedSearch !== "") {
    const escaped = escapeIlikeWildcards(trimmedSearch);
    // `id` is a `uuid` column. PostgREST's embedded `.or()` logic-tree grammar
    // does not accept a `::type` cast in the column reference (confirmed
    // against the local stack — `PGRST100 failed to parse logic tree`), and an
    // un-cast `ilike` against a `uuid` column is rejected by Postgres itself
    // (`42883 operator does not exist: uuid ~~* unknown`). Substring matching
    // against the run id is therefore not reachable through this read without
    // a schema change (out of scope — this story is reads-only, N/A opt-out).
    // A search term that is itself a syntactically valid UUID still resolves
    // an exact `id` match (the common real case — pasting a full run id),
    // composed with the repository-name substring match via `.or()`.
    const clauses = [`repository_full_name.ilike.%${escaped}%`];
    if (isUuidLike(trimmedSearch)) {
      clauses.push(`id.eq.${trimmedSearch}`);
    }
    q = q.or(clauses.join(","));
  }
  return q;
}

const UUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

function isUuidLike(value: string): boolean {
  return UUID_RE.test(value);
}

export async function getFilteredRuns(
  client: SupabaseClient,
  filter: RunFilter,
  pageSize: number,
): Promise<FilteredRunsResult> {
  let query = client.from("v_runs").select("*", { count: "exact" });
  query = applyRunFilterClauses(query, filter);
  if (filter.status !== "all") {
    query = query.eq("effective_status", filter.status);
  }
  query = query
    .order("created_at", { ascending: false })
    .range(0, Math.max(filter.page, 1) * pageSize - 1);

  const result = await query;
  const rows = unwrap<VRunRow[]>("getFilteredRuns", result) ?? [];
  const totalCount = result.count ?? 0;
  return { rows, totalCount };
}

/**
 * 12c. Per-status run counts for the segmented control (FR1's "colored dot +
 * live count per option"). Counts reflect every filter EXCEPT `status` itself
 * (so each option's count is "how many rows would this option show given the
 * current repo/search/agent scope") — a single grouped read, paged with
 * `.range()` below the PostgREST `max_rows` ceiling and folded in JS (same
 * "one grouped read, never N+1" pattern as `getStepProgressForRuns`), rather
 * than one query per status value.
 */
export type RunStatusCounts = Record<RunStatus | "all", number>;

function zeroStatusCounts(): RunStatusCounts {
  return {
    all: 0,
    queued: 0,
    running: 0,
    succeeded: 0,
    failed: 0,
    timed_out: 0,
    failed_to_start: 0,
    canceled: 0,
  };
}

export async function getRunStatusCounts(
  client: SupabaseClient,
  filter: Pick<RunFilter, "agentSlug" | "repositoryId" | "search">,
): Promise<RunStatusCounts> {
  const counts = zeroStatusCounts();
  let offset = 0;
  for (;;) {
    let query = client
      .from("v_runs")
      .select("effective_status")
      .range(offset, offset + PAGE_SIZE - 1);
    query = applyRunFilterClauses(query, filter);
    const result = await query;
    const page =
      unwrap<Array<{ effective_status: string }>>(
        "getRunStatusCounts",
        result as unknown as {
          data: Array<{ effective_status: string }> | null;
          error: unknown;
        },
      ) ?? [];
    for (const row of page) {
      counts.all += 1;
      if (row.effective_status in counts) {
        counts[row.effective_status as RunStatus] += 1;
      }
    }
    if (page.length < PAGE_SIZE) break;
    offset += page.length;
  }
  return counts;
}

/**
 * 7b. `run_events` for a run within an inclusive `seq` range (Story S-109 —
 * the "load earlier" fetch). Returns the events with `fromSeq <= seq <= toSeq`,
 * ascending by `seq` for display. The range is computed by
 * `lib/domain/log-window.priorWindowRange`, which bounds it to the window size,
 * so this stays below the PostgREST `max_rows` ceiling in one read; it pages
 * defensively with `.range()` in case a caller requests a wider span.
 *
 * Unlike `getRunEvents` (which bounds the RECENT end), this reads a fixed
 * historical slice, so it orders ascending directly.
 */
export async function getRunEventsInRange(
  client: SupabaseClient,
  runId: string,
  fromSeq: number,
  toSeq: number,
): Promise<RunEventRow[]> {
  if (toSeq < fromSeq) return [];
  const collected: RunEventRow[] = [];
  let offset = 0;
  for (;;) {
    const result = await client
      .from("run_events")
      .select("*")
      .eq("run_id", runId)
      .gte("seq", fromSeq)
      .lte("seq", toSeq)
      .order("seq", { ascending: true })
      .range(offset, offset + PAGE_SIZE - 1);
    const page = unwrap<RunEventRow[]>("getRunEventsInRange", result) ?? [];
    collected.push(...page);
    if (page.length < PAGE_SIZE) break;
    offset += page.length;
  }
  return collected;
}

/**
 * 7c. `run_events` for a run with `seq > afterSeq`, ascending (Story S-110 —
 * the SSE relay backfill, SD6 step 1). Unbounded on the upper end (the relay
 * emits the whole tail above the cursor, then subscribes for the rest), paged
 * with `.range()` below the PostgREST `max_rows` ceiling.
 *
 * There is no upper `seq` bound: `run_events.seq` is a Postgres `integer`, so a
 * sentinel ceiling like `Number.MAX_SAFE_INTEGER` overflows the column type
 * (pg 22003). The correct query is simply `seq > afterSeq`.
 */
export async function getRunEventsAfterSeq(
  client: SupabaseClient,
  runId: string,
  afterSeq: number,
): Promise<RunEventRow[]> {
  const collected: RunEventRow[] = [];
  let offset = 0;
  for (;;) {
    const result = await client
      .from("run_events")
      .select("*")
      .eq("run_id", runId)
      .gt("seq", afterSeq)
      .order("seq", { ascending: true })
      .range(offset, offset + PAGE_SIZE - 1);
    const page = unwrap<RunEventRow[]>("getRunEventsAfterSeq", result) ?? [];
    collected.push(...page);
    if (page.length < PAGE_SIZE) break;
    offset += page.length;
  }
  return collected;
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

// ---------------------------------------------------------------------------
// Write helpers (S-112 / #125) — the panel's first database writes.
//
// The invoke route inserts the `queued` run BEFORE contacting AgentCore (D1),
// then either records the invocation refs on success or marks the run
// `failed_to_start` if `InvokeAgentRuntime` throws (AC12). Each helper takes an
// explicit client and surfaces a PostgREST failure as a `DatabaseError` (500,
// pg code logged never returned) — the same contract as the read helpers.
// ---------------------------------------------------------------------------

/**
 * Insert the `queued` run row (D1). Uses `Prefer: return=representation` so the
 * inserted id is confirmed. A PostgREST failure (constraint, RLS, connectivity)
 * throws `DatabaseError` and the route returns before any invocation — no
 * orphan invoke without a row.
 */
export async function insertQueuedRun(client: SupabaseClient, row: RunInsert): Promise<void> {
  const result = await client.from("runs").insert(row).select("id").single();
  if (result.error) {
    throw new DatabaseError("insertQueuedRun", result.error);
  }
}

/**
 * Record the AgentCore invocation references on a run after a successful
 * invoke. Best-effort in the sense that the run already exists and is visible;
 * a failure here still throws `DatabaseError` so the route can log it, but the
 * run is not lost.
 */
export async function updateRunInvocationRefs(
  client: SupabaseClient,
  runId: string,
  refs: { session_id?: string | null; runtime_invocation_id?: string | null },
): Promise<void> {
  const result = await client.from("runs").update(refs).eq("id", runId);
  if (result.error) {
    throw new DatabaseError("updateRunInvocationRefs", result.error);
  }
}

/**
 * Mark a run `failed_to_start` after `InvokeAgentRuntime` threw (AC12). The
 * panel does this itself rather than waiting for the reaper, so the failure is
 * immediately visible. `error_code`/`error_message` explain why.
 */
export async function markRunFailedToStart(
  client: SupabaseClient,
  runId: string,
  errorCode: string,
  errorMessage: string,
): Promise<void> {
  const result = await client
    .from("runs")
    .update({
      status: "failed_to_start",
      error_code: errorCode,
      error_message: errorMessage,
      finished_at: new Date().toISOString(),
    })
    .eq("id", runId);
  if (result.error) {
    throw new DatabaseError("markRunFailedToStart", result.error);
  }
}

// ---------------------------------------------------------------------------
// Repositories — list + add-by-reference (S-147 / #207) and archive (S-148).
//
// The panel's second user-triggered write and its first Server-Action-shaped
// write (spec §6). `insertRepository` never calls the GitHub API (PRD §8
// Business Rule) — it is a shape-validated INSERT against the existing
// `repositories` table only. A duplicate `full_name` under the installation
// is rejected with a friendly `REPOSITORY_ALREADY_EXISTS`, checked BOTH
// pre-insert (the common case) and via the `23505` unique-violation fallback
// (a race between two adds is still possible — spec §6/§12).
// ---------------------------------------------------------------------------

/** Postgres unique-violation SQLSTATE. */
const PG_UNIQUE_VIOLATION = "23505";

export const REPOSITORY_ALREADY_EXISTS = "REPOSITORY_ALREADY_EXISTS" as const;

/**
 * A `full_name` already exists under the target installation. Never surfaces
 * the raw Postgres constraint error — this is the friendly, client-safe
 * shape (spec §6/§12).
 */
export class RepositoryAlreadyExistsError extends Error {
  readonly code = REPOSITORY_ALREADY_EXISTS;
  readonly status = 400;

  constructor(fullName: string) {
    super(`Repository "${fullName}" already exists under this installation.`);
    this.name = "RepositoryAlreadyExistsError";
  }
}

/**
 * 13. Resolves the single GitHub App installation row (`product-context.md`
 * §11 — there is exactly one). Used to scope the Add-repository form's write
 * without an installation picker (PRD §15 Assumption). Throws `DatabaseError`
 * on a PostgREST failure; a genuinely empty table (mis-seeded environment) is
 * a configuration fault, surfaced the same way rather than a silent null.
 */
export async function getSingleInstallation(
  client: SupabaseClient,
): Promise<GithubInstallationRow> {
  const result = await client.from("github_installations").select("*").limit(1).maybeSingle();
  const row = unwrap<GithubInstallationRow | null>("getSingleInstallation", result);
  if (!row) {
    throw new DatabaseError(
      "getSingleInstallation",
      new Error("No github_installations row exists — the environment is not seeded."),
    );
  }
  return row;
}

/**
 * 14. Repositories list (FR15). Excludes archived rows by default
 * (`includeArchived` opts in); ordered by `full_name` for a stable list.
 * Returns `[]` for an empty table — never null (EC-17 convention).
 */
export async function getRepositories(
  client: SupabaseClient,
  opts?: { includeArchived?: boolean },
): Promise<RepositoryRow[]> {
  let query = client.from("repositories").select("*").order("full_name", { ascending: true });
  if (!opts?.includeArchived) {
    query = query.is("archived_at", null);
  }
  const result = await query;
  return unwrap<RepositoryRow[]>("getRepositories", result) ?? [];
}

/**
 * 15. Insert a new repository by reference (FR16). NEVER calls the GitHub
 * API — a shape-validated write only (the caller, `addRepository`, validates
 * `full_name` via `parseFullName` first; this helper trusts its input).
 *
 * Duplicate rejection happens twice, deliberately:
 *   1. A pre-check `select` scoped to `(installationId, fullName)` — the
 *      common case, gives a fast friendly rejection without ever attempting
 *      the insert.
 *   2. A `23505` unique-violation fallback on the insert itself — because a
 *      race between two concurrent adds of the same `full_name` can still
 *      slip past the pre-check (TOCTOU). Both paths throw the SAME
 *      `RepositoryAlreadyExistsError`, so the caller never has to
 *      distinguish which one fired.
 *
 * Any other Postgres failure throws `DatabaseError` (pg code logged only).
 */
export async function insertRepository(
  client: SupabaseClient,
  row: { installationId: string; fullName: string; defaultBranch: string },
): Promise<RepositoryRow> {
  const precheck = await client
    .from("repositories")
    .select("id")
    .eq("installation_id", row.installationId)
    .eq("full_name", row.fullName)
    .maybeSingle();
  if (precheck.error) {
    throw new DatabaseError("insertRepository:precheck", precheck.error);
  }
  if (precheck.data) {
    throw new RepositoryAlreadyExistsError(row.fullName);
  }

  const result = await client
    .from("repositories")
    .insert({
      installation_id: row.installationId,
      full_name: row.fullName,
      default_branch: row.defaultBranch,
      is_enabled: true,
    })
    .select("*")
    .single();

  if (result.error) {
    const pgCode = (result.error as { code?: string }).code;
    if (pgCode === PG_UNIQUE_VIOLATION) {
      throw new RepositoryAlreadyExistsError(row.fullName);
    }
    throw new DatabaseError("insertRepository", result.error);
  }
  return result.data as RepositoryRow;
}

/**
 * 16. Archive a repository (FR17, soft delete — Story S-148 / #208). A plain
 * `UPDATE ... SET archived_at = now() WHERE id = $1` — NEVER a `DELETE`.
 * `runs.repository_id` is a nullable FK with `on delete set null`; a hard
 * delete would silently sever every historical run's repository link. The
 * soft delete exists specifically to keep that link intact (spec §8.4/§12,
 * Business Rule).
 *
 * Idempotent by construction: re-running the same `UPDATE` against an
 * already-archived row is not an error — it just re-sets `archived_at` to a
 * newer `now()` (still non-null, never regressing to an earlier value) and
 * affects zero-or-one row either way. Returns `void`; the caller does not
 * need the updated row (the Server Action returns `{ ok: true }` only).
 */
export async function archiveRepository(client: SupabaseClient, id: string): Promise<void> {
  const result = await client
    .from("repositories")
    .update({ archived_at: new Date().toISOString() })
    .eq("id", id);
  if (result.error) {
    throw new DatabaseError("archiveRepository", result.error);
  }
}
