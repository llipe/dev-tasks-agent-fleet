import { notFound } from "next/navigation";

import { createServerClient } from "@/lib/supabase/server";
import {
  getRunById,
  getRunSteps,
  getRunEvents,
  getRunEventsInRange,
  getRunArtifacts,
  RUN_EVENTS_READ_LIMIT,
} from "@/lib/supabase/queries";
import type { Json, RunEventRow, RunStepRow, VRunRow } from "@/lib/supabase/types";
import {
  buildSummary,
  buildLogLines,
  type LogEventInput,
  type LogStepInput,
  type LogLineView,
  type SummaryInput,
} from "@/lib/domain/run-detail";
import { selectRecentWindow } from "@/lib/domain/log-window";
import { effectiveStatus } from "@/lib/domain/status";
import { RunSummary } from "@/components/run-detail/RunSummary";
import { StateBanner } from "@/components/run-detail/StateBanner";
import { LogViewer } from "@/components/run-detail/LogViewer";
import { LiveLogViewer } from "@/components/run-detail/LiveLogViewer";
import { Breadcrumb } from "@/components/Breadcrumb";
import type { ArtifactView } from "@/components/run-detail/ArtifactLinks";

import styles from "./page.module.css";

/**
 * Run detail (`/runs/[id]`, Story S-109).
 *
 * Route-segment config is declared **inline** — Next.js silently ignores these
 * values when re-exported and falls back to static rendering (S-104 audit D4,
 * technical-guidelines §12). Run data must never be cached: a run's derived
 * status changes second-to-second (FR11a / SD4), so this is a correctness
 * requirement, not a convention.
 */
export const dynamic = "force-dynamic";
export const revalidate = 0;
export const fetchCache = "force-no-store";

function toStepInput(s: RunStepRow): LogStepInput {
  return { id: s.id, key: s.key, title: s.title };
}

function toEventInput(e: RunEventRow): LogEventInput {
  return {
    id: e.id,
    seq: e.seq,
    ts: e.ts,
    level: e.level,
    message: e.message,
    stepId: e.step_id,
  };
}

function toArtifactView(a: {
  id: string;
  type: ArtifactView["type"];
  title: string | null;
  url: string | null;
}): ArtifactView {
  return { id: a.id, type: a.type, title: a.title, url: a.url };
}

/** The branch a run ran against, read from `params` (the repo model is separate, §7). */
function runBranch(row: VRunRow): string | null {
  const params = row.params;
  if (params != null && typeof params === "object" && !Array.isArray(params)) {
    const branch = (params as Record<string, Json>).branch;
    if (typeof branch === "string" && branch.length > 0) return branch;
  }
  return null;
}

function toSummaryInput(row: VRunRow): SummaryInput {
  return {
    id: row.id,
    status: row.status,
    startedAtMs: row.started_at ? Date.parse(row.started_at) : null,
    queuedAtMs: Date.parse(row.queued_at),
    finishedAtMs: row.finished_at ? Date.parse(row.finished_at) : null,
    durationMs: row.duration_ms,
    maxRuntimeSeconds: row.max_runtime_seconds,
    graceSeconds: row.grace_seconds,
    startTimeoutSeconds: row.start_timeout_seconds,
    outcome: row.outcome,
    repositoryFullName: row.repository_full_name,
    branch: runBranch(row),
    errorMessage: row.error_message,
  };
}

export default async function RunDetailPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const client = createServerClient();

  // Unknown run id → 404 (AC9). A malformed/non-UUID id also resolves to null
  // (the read is parameterized, so no injection), and 404s the same way.
  const run = await getRunById(client, id);
  if (run === null) {
    notFound();
  }
  const resolved = run as VRunRow;

  const [steps, events, artifacts] = await Promise.all([
    getRunSteps(client, resolved.id),
    getRunEvents(client, resolved.id),
    getRunArtifacts(client, resolved.id),
  ]);

  // A single injected instant so the summary status + banner agree on one clock.
  const nowMs = Date.now();
  const stepInputs = steps.map(toStepInput);

  const summary = buildSummary(toSummaryInput(resolved), nowMs);

  // `getRunEvents` already bounds at the most-recent RUN_EVENTS_READ_LIMIT
  // events (seq desc, reversed to ascending). Whether earlier events exist is
  // computed from the window: a full window means older events may exist.
  const window = selectRecentWindow(events, RUN_EVENTS_READ_LIMIT);
  const initialLines = buildLogLines(window.events.map(toEventInput), stepInputs);
  // If the read returned a full window, older events may precede it. The oldest
  // loaded seq is the load-earlier cursor.
  const oldestLoadedSeq = window.oldestSeq;
  const hasEarlier = events.length >= RUN_EVENTS_READ_LIMIT && (oldestLoadedSeq ?? 1) > 1;

  const runId = resolved.id;

  // Whether the run is still live decides which viewer renders. A run whose
  // EFFECTIVE status (SD4) is not terminal gets the SSE live-tail viewer
  // (S-110); a terminal run gets the server-rendered viewer with "load earlier"
  // (S-109) — a terminal run has nothing to tail. `effectiveStatus` is the
  // shared derivation, so this agrees with the summary pill.
  const TERMINAL = new Set(["succeeded", "failed", "canceled", "timed_out", "failed_to_start"]);
  const derivedStatus = effectiveStatus(
    {
      status: resolved.status,
      startedAtMs: resolved.started_at ? Date.parse(resolved.started_at) : null,
      queuedAtMs: Date.parse(resolved.queued_at),
      maxRuntimeSeconds: resolved.max_runtime_seconds,
      graceSeconds: resolved.grace_seconds,
      startTimeoutSeconds: resolved.start_timeout_seconds,
    },
    nowMs,
  );
  const isLive = !TERMINAL.has(derivedStatus);

  /**
   * Server action for "load earlier" (AC5). Fetches the prior `seq` window and
   * returns it as log lines. Bound to this run id; a fresh server client is
   * created per invocation. This is a read-only progressive fetch — the SSE
   * live-tail relay (S-110) is a separate route and does not replace this.
   */
  async function loadEarlier(fromSeq: number, toSeq: number): Promise<LogLineView[]> {
    "use server";
    const c = createServerClient();
    const earlier = await getRunEventsInRange(c, runId, fromSeq, toSeq);
    const earlierSteps = (await getRunSteps(c, runId)).map(toStepInput);
    return buildLogLines(earlier.map(toEventInput), earlierSteps);
  }

  return (
    <section className={styles.page} aria-label={`Run ${summary.shortId}`}>
      <div className={styles.head}>
        <Breadcrumb
          items={[
            { label: "agents", href: "/" },
            { label: resolved.agent_slug, href: `/agents/${resolved.agent_slug}` },
            { label: summary.shortId, active: true },
          ]}
        />
      </div>

      {summary.banner != null && (
        <StateBanner banner={summary.banner} message={summary.errorMessage} />
      )}

      <RunSummary summary={summary} artifacts={artifacts.map(toArtifactView)} />

      {isLive ? (
        <LiveLogViewer
          runId={runId}
          initialLines={initialLines}
          initialStatus={resolved.status}
          maxRuntimeSeconds={resolved.max_runtime_seconds}
          graceSeconds={resolved.grace_seconds}
          startTimeoutSeconds={resolved.start_timeout_seconds}
          startedAtMs={resolved.started_at ? Date.parse(resolved.started_at) : null}
          queuedAtMs={Date.parse(resolved.queued_at)}
        />
      ) : (
        <LogViewer
          initialLines={initialLines}
          hasEarlier={hasEarlier}
          oldestSeq={oldestLoadedSeq}
          loadEarlier={loadEarlier}
        />
      )}
    </section>
  );
}
