import { notFound } from "next/navigation";

import { createServerClient } from "@/lib/supabase/server";
import {
  getAgentBySlug,
  getAllRunsByAgentSlug,
  getStepProgressForRuns,
} from "@/lib/supabase/queries";
import type { AgentRow, Json, VRunRow } from "@/lib/supabase/types";
import {
  buildAgentHeader,
  buildRunRows,
  type AgentHeaderInput,
  type RunRowInput,
} from "@/lib/domain/run-row";
import { AgentHeader } from "@/components/runs/AgentHeader";
import { RunHistoryTable } from "@/components/runs/RunHistoryTable";

import styles from "./page.module.css";

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

// The invoke route (S-113) does not exist yet; render Invoke disabled until it
// lands (task 3.8) rather than linking to a 404.
const INVOKE_ROUTE_AVAILABLE = false;

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
}: {
  params: Promise<{ slug: string }>;
}) {
  const { slug } = await params;
  const client = createServerClient();

  // Unknown slug OR a disabled agent both 404 — not an empty list (task 3.9).
  const agent: AgentRow | null = await getAgentBySlug(client, slug);
  if (agent === null || !agent.is_enabled) {
    notFound();
  }

  const runs = await getAllRunsByAgentSlug(client, slug);
  const progress = await getStepProgressForRuns(
    client,
    runs.map((r) => r.id),
  );

  // A single injected instant for every relative time + status derivation on
  // this render, so nothing reads an ambient clock mid-render.
  const nowMs = Date.now();

  const runInputs: RunRowInput[] = runs.map((r) => {
    const p = progress.get(r.id) ?? { done: 0, total: 0 };
    return toRunInput(r, p.done, p.total);
  });

  const headerInput: AgentHeaderInput = {
    name: agent.name,
    slug: agent.slug,
    description: agent.description,
    paramsCount: paramsCount(agent.params_schema),
    isEnabled: agent.is_enabled,
    runs: runInputs,
  };

  const header = buildAgentHeader(headerInput, nowMs);
  const rows = buildRunRows(runInputs, nowMs);
  const invokeHref = INVOKE_ROUTE_AVAILABLE ? `/agents/${slug}/invoke` : null;

  return (
    <section className={styles.page} aria-label={`${agent.name} run history`}>
      <AgentHeader header={header} invokeHref={invokeHref} />
      <RunHistoryTable rows={rows} invokeHref={invokeHref} />
    </section>
  );
}
