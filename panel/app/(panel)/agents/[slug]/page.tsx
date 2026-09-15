import Link from "next/link";
import { notFound } from "next/navigation";

import { createServerClient } from "@/lib/supabase/server";
import {
  getAgentBySlug,
  getAllRunsByAgentSlug,
  getEnabledRepositories,
  getFilteredRuns,
  getRunStatusCounts,
  getStepProgressForRuns,
} from "@/lib/supabase/queries";
import type { AgentRow, Json, VRunRow } from "@/lib/supabase/types";
import {
  buildAgentHeader,
  buildRunRows,
  shouldRunHistory404,
  type AgentHeaderInput,
  type RunRowInput,
} from "@/lib/domain/run-row";
import { parseRunFilter, serializeRunFilter, type RunFilter } from "@/lib/domain/run-filter";
import { AgentHeader } from "@/components/runs/AgentHeader";
import { RunHistoryTable } from "@/components/runs/RunHistoryTable";
import { RunFilterBar } from "@/components/runs/RunFilterBar";

import styles from "./page.module.css";

/** Run History page size (spec §8.1's pagination decision, `PAGE_SIZE = 25`). */
const PAGE_SIZE = 25;

/**
 * Agent run history (`/agents/[slug]`, Story S-108).
 *
 * Route-segment config is declared **inline** — Next.js silently ignores these
 * values when re-exported and falls back to static rendering (S-104 audit D4,
 * technical-guidelines §12). A cached run list is exactly the staleness FR11a
 * exists to prevent (a run's derived status changes second-to-second), so this
 * is a correctness requirement, not a convention.
 */
export const dynamic = "force-dynamic";
export const revalidate = 0;
export const fetchCache = "force-no-store";

// The invoke route (S-113, /agents/[slug]/invoke) shipped in Wave 4 (PR #143),
// so the Invoke action links through to it.
const INVOKE_ROUTE_AVAILABLE = true;

/** Count of top-level properties in a JSON-Schema `params_schema`. */
function paramsCount(schema: Json): number {
  if (schema != null && typeof schema === "object" && !Array.isArray(schema)) {
    const props = (schema as Record<string, Json>).properties;
    if (props != null && typeof props === "object" && !Array.isArray(props)) {
      return Object.keys(props).length;
    }
  }
  return 0;
}

function toRunInput(row: VRunRow, done: number, total: number): RunRowInput {
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
  };
}

/**
 * The branch for a run, when the params carry one. The schema keeps the branch
 * in `params` (the repository model is separate, §7); a run without a branch
 * renders none rather than a placeholder.
 */
function repositoryBranch(row: VRunRow): string | null {
  const params = row.params;
  if (params != null && typeof params === "object" && !Array.isArray(params)) {
    const branch = (params as Record<string, Json>).branch;
    if (typeof branch === "string" && branch.length > 0) return branch;
  }
  return null;
}

export default async function AgentRunHistoryPage({
  params,
  searchParams,
}: {
  params: Promise<{ slug: string }>;
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  const { slug } = await params;
  const client = createServerClient();

  // Unknown slug OR a disabled agent both 404 — not an empty list (task 3.9).
  const agent: AgentRow | null = await getAgentBySlug(client, slug);
  if (shouldRunHistory404(agent)) {
    notFound();
  }
  // `shouldRunHistory404` returns false only for a non-null, enabled agent;
  // `notFound()` throws, so `agent` is a resolved AgentRow past this point.
  const resolved = agent as AgentRow;

  // The URL is the single source of filter/pagination truth (spec §8.1
  // Business Rule) — `parseRunFilter` is total and never throws for a
  // malformed query string.
  const rawSearchParams = await searchParams;
  const urlSearchParams = new URLSearchParams();
  for (const [key, value] of Object.entries(rawSearchParams)) {
    if (typeof value === "string") urlSearchParams.set(key, value);
    else if (Array.isArray(value) && value.length > 0) urlSearchParams.set(key, value[0]!);
  }
  const filter: RunFilter = { ...parseRunFilter(urlSearchParams), agentSlug: slug };

  // The header's metadata (params count, p50 duration, success rate) is
  // agent-level, not scoped to the active filter (`/DESIGN.md` §5.2) — it
  // reads the full unfiltered history, same cost class as before this story
  // (S-108). The table below reads the filtered, paginated set via the new
  // `getFilteredRuns` (S-143, spec §8.1) — a deliberate two-reads shape, not
  // an oversight, so the header never contradicts itself when an operator
  // narrows the table with a filter.
  const [allRunsForHeader, filtered, statusCounts, repositories] = await Promise.all([
    getAllRunsByAgentSlug(client, slug),
    getFilteredRuns(client, filter, PAGE_SIZE),
    getRunStatusCounts(client, {
      agentSlug: slug,
      repositoryId: filter.repositoryId,
      search: filter.search,
    }),
    getEnabledRepositories(client),
  ]);

  const progress = await getStepProgressForRuns(
    client,
    filtered.rows.map((r) => r.id),
  );

  // A single injected instant for every relative time + status derivation on
  // this render, so nothing reads an ambient clock mid-render.
  const nowMs = Date.now();

  const headerRunInputs: RunRowInput[] = allRunsForHeader.map((r) => toRunInput(r, 0, 0));

  const headerInput: AgentHeaderInput = {
    name: resolved.name,
    slug: resolved.slug,
    description: resolved.description,
    paramsCount: paramsCount(resolved.params_schema),
    isEnabled: resolved.is_enabled,
    runs: headerRunInputs,
  };

  const tableRunInputs: RunRowInput[] = filtered.rows.map((r) => {
    const p = progress.get(r.id) ?? { done: 0, total: 0 };
    return toRunInput(r, p.done, p.total);
  });

  const header = buildAgentHeader(headerInput, nowMs);
  const rows = buildRunRows(tableRunInputs, nowMs);
  const invokeHref = INVOKE_ROUTE_AVAILABLE ? `/agents/${slug}/invoke` : null;

  const basePath = `/agents/${slug}`;
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
    <section className={styles.page} aria-label={`${resolved.name} run history`}>
      <AgentHeader header={header} invokeHref={invokeHref} />
      <RunFilterBar
        basePath={basePath}
        filter={filter}
        statusCounts={statusCounts}
        repositories={repositories.map((r) => ({ id: r.id, fullName: r.full_name }))}
      />
      <RunHistoryTable
        rows={rows}
        invokeHref={invokeHref}
        hasActiveFilter={hasActiveFilter}
        clearFiltersHref={clearFiltersHref}
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
