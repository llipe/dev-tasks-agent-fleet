import Link from "next/link";

import { createServerClient } from "@/lib/supabase/server";
import {
  getEnabledRepositories,
  getFilteredRuns,
  getPullRequestArtifactsForRuns,
  getRunStatusCounts,
  getStepProgressForRuns,
} from "@/lib/supabase/queries";
import type { Json, VRunRow } from "@/lib/supabase/types";
import { buildRunRows, type RunRowInput } from "@/lib/domain/run-row";
import { parseRunFilter, serializeRunFilter, type RunFilter } from "@/lib/domain/run-filter";
import { RunHistoryTable } from "@/components/runs/RunHistoryTable";
import { RunFilterBar } from "@/components/runs/RunFilterBar";

import styles from "./page.module.css";

/** Same page size as `/agents/[slug]` (S-143's `PAGE_SIZE = 25`). */
const PAGE_SIZE = 25;

/**
 * All Runs — cross-agent run feed (`/runs`, Story S-146, issue #206, FR13/FR14).
 *
 * Reverses the v2.1 §10 non-goal that deferred "All runs" out of Phase 2. This
 * is almost entirely composition of S-143's foundation: the same
 * `RunFilterBar` + `getFilteredRuns`/`getRunStatusCounts`, called with
 * `filter.agentSlug = null` so the read is never scoped to one agent — no new
 * query is introduced (spec §10, Business Rule).
 *
 * Unlike `/agents/[slug]`, this screen has no agent-level header and no
 * disabled-agent 404 guard: a disabled agent's historical runs still appear
 * here, since disabling an agent doesn't delete its runs (S-146 edge case —
 * deliberately different from `/agents/[slug]`'s `shouldRunHistory404`).
 *
 * Route-segment config is declared **inline** — same correctness requirement
 * as every other run-data screen (S-104 audit D4, technical-guidelines §12):
 * a run's derived status changes second-to-second (FR11a), so this can never
 * be statically cached.
 */
export const dynamic = "force-dynamic";
export const revalidate = 0;
export const fetchCache = "force-no-store";

function toRunInput(
  row: VRunRow,
  done: number,
  total: number,
  pullRequestUrl: string | null = null,
): RunRowInput {
  return {
    id: row.id,
    status: row.status,
    startedAtMs: row.started_at ? Date.parse(row.started_at) : null,
    queuedAtMs: Date.parse(row.queued_at),
    finishedAtMs: row.finished_at ? Date.parse(row.finished_at) : null,
    createdAtMs: Date.parse(row.created_at),
    durationMs: row.duration_ms,
    maxRuntimeSeconds: row.max_runtime_seconds,
    graceSeconds: row.grace_seconds,
    startTimeoutSeconds: row.start_timeout_seconds,
    outcome: row.outcome,
    repositoryFullName: row.repository_full_name,
    repositoryBranch: repositoryBranch(row),
    stepsDone: done,
    stepsTotal: total,
    pullRequestUrl,
    // The one field `/agents/[slug]`'s `toRunInput` never sets — this screen
    // is unscoped, so every row needs its own agent identity (AC1).
    agentName: row.agent_name,
    agentSlug: row.agent_slug,
  };
}

/** The branch for a run, when the params carry one (same helper as `/agents/[slug]`). */
function repositoryBranch(row: VRunRow): string | null {
  const params = row.params;
  if (params != null && typeof params === "object" && !Array.isArray(params)) {
    const branch = (params as Record<string, Json>).branch;
    if (typeof branch === "string" && branch.length > 0) return branch;
  }
  return null;
}

export default async function AllRunsPage({
  searchParams,
}: {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  const client = createServerClient();

  // The URL is the single source of filter/pagination truth (spec §8.1
  // Business Rule, reused by S-146 as-is). `filter.agentSlug` stays `null`
  // here — this screen never scopes to one agent (FR13).
  const rawSearchParams = await searchParams;
  const urlSearchParams = new URLSearchParams();
  for (const [key, value] of Object.entries(rawSearchParams)) {
    if (typeof value === "string") urlSearchParams.set(key, value);
    else if (Array.isArray(value) && value.length > 0) urlSearchParams.set(key, value[0]!);
  }
  const filter: RunFilter = { ...parseRunFilter(urlSearchParams), agentSlug: null };

  const [filtered, statusCounts, repositories] = await Promise.all([
    getFilteredRuns(client, filter, PAGE_SIZE),
    getRunStatusCounts(client, {
      agentSlug: null,
      repositoryId: filter.repositoryId,
      search: filter.search,
    }),
    getEnabledRepositories(client),
  ]);

  const filteredRunIds = filtered.rows.map((r) => r.id);
  // Two grouped reads for the visible page of rows, same pattern as
  // `/agents/[slug]` — never N+1 regardless of row count.
  const [progress, pullRequestArtifacts] = await Promise.all([
    getStepProgressForRuns(client, filteredRunIds),
    getPullRequestArtifactsForRuns(client, filteredRunIds),
  ]);

  // A single injected instant for every relative time + status derivation on
  // this render.
  const nowMs = Date.now();

  const tableRunInputs: RunRowInput[] = filtered.rows.map((r) => {
    const p = progress.get(r.id) ?? { done: 0, total: 0 };
    const pullRequestUrl = pullRequestArtifacts[r.id]?.url ?? null;
    return toRunInput(r, p.done, p.total, pullRequestUrl);
  });

  const rows = buildRunRows(tableRunInputs, nowMs);

  const basePath = "/runs";
  const hasActiveFilter =
    filter.status !== "all" || filter.repositoryId != null || (filter.search ?? "") !== "";
  const clearFiltersHref = basePath;

  const shownCount = rows.length;
  const totalCount = filtered.totalCount;
  const nextPageHref =
    shownCount < totalCount
      ? `${basePath}?${serializeRunFilter({ ...filter, page: filter.page + 1 }).toString()}`
      : null;

  return (
    <section className={styles.page} aria-label="All runs">
      <RunFilterBar
        basePath={basePath}
        filter={filter}
        statusCounts={statusCounts}
        repositories={repositories.map((r) => ({ id: r.id, fullName: r.full_name }))}
      />
      <RunHistoryTable
        rows={rows}
        // No single-agent invoke context on this screen — the empty state
        // renders its disabled variant, same as every route that predates the
        // relevant invoke route (S-113 precedent).
        invokeHref={null}
        hasActiveFilter={hasActiveFilter}
        clearFiltersHref={clearFiltersHref}
        showAgentColumn
      />
      {rows.length > 0 && (
        <div className={styles.pagination}>
          <span className={styles.paginationCount}>
            {shownCount} of {totalCount}
          </span>
          {nextPageHref != null && (
            <Link href={nextPageHref} className={styles.loadMore}>
              Load more
            </Link>
          )}
        </div>
      )}
    </section>
  );
}
