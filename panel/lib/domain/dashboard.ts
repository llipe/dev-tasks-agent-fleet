/**
 * Dashboard aggregation shaper (task 2.2 / 2.12a).
 *
 * Turns the flat, `v_runs`-shaped rows the query layer returns into one
 * per-agent summary that all three §5.1 variants render from the same payload.
 *
 * The one property that carries FR11a (CT-1): **every status this module
 * emits — the per-run status in `recentRuns`, the `lastRun`, and every count
 * in `breakdown`/`legend` — is the `effectiveStatus` derivation, never the raw
 * `status` column.** A stale `running` row is counted as `timed_out`, so a
 * count can never disagree with the pill a variant renders for the same run.
 * The derivation lives only in `lib/domain/status.ts`; this module imports it
 * and never restates the threshold arithmetic (CT-3).
 *
 * Pure and clock-injected: `now` is passed in so a stale row is stale at an
 * instant the caller controls (EC-8).
 */

import { effectiveStatus, type RunStatus } from "@/lib/domain/status";
import type { RunOutcome } from "@/lib/supabase/types";

/** The minimal per-run projection the shaper needs. Timestamps are epoch ms. */
export interface DashboardRun {
  status: RunStatus | (string & {});
  startedAtMs: number | null;
  queuedAtMs: number | null;
  finishedAtMs: number | null;
  createdAtMs: number | null;
  maxRuntimeSeconds: number | null;
  graceSeconds: number | null;
  startTimeoutSeconds: number | null;
  outcome: RunOutcome | null;
}

/** The per-agent input the shaper consumes (one entry per enabled agent). */
export interface AgentSummaryInput {
  id: string;
  slug: string;
  name: string;
  description: string | null;
  requiresRepository: boolean;
  runs: DashboardRun[];
}

/** A run reduced to what a variant renders, with its status already derived. */
export interface SummaryRun {
  effectiveStatus: RunStatus | (string & {});
  createdAtMs: number | null;
}

/** The newest run, with its status derived and a single display timestamp. */
export interface LastRun {
  effectiveStatus: RunStatus | (string & {});
  outcome: RunOutcome | null;
  /** finished_at, else started_at, else created_at (epoch ms) */
  atMs: number | null;
}

/**
 * Count of runs per *effective* status. Every `run_status` enum value has a
 * bucket so a variant can render any of them without a lookup miss; an unknown
 * future value is dropped from these named buckets but still counted in
 * `runCount` and rendered in `recentRuns`/`lastRun` via the status-meta
 * fallback (EC-23).
 */
export interface StatusBreakdown {
  queued: number;
  running: number;
  succeeded: number;
  failed: number;
  timed_out: number;
  failed_to_start: number;
  canceled: number;
}

/** The three legend buckets DESIGN §7.3 / `formatStatusLegend` render. */
export interface LegendCounts {
  ok: number;
  fail: number;
  timeout: number;
}

export interface AgentSummary {
  id: string;
  slug: string;
  name: string;
  description: string | null;
  requiresRepository: boolean;
  runCount: number;
  breakdown: StatusBreakdown;
  legend: LegendCounts;
  lastRun: LastRun | null;
  recentRuns: SummaryRun[];
}

export interface BuildOptions {
  /** Cap for `recentRuns` (the §3.9 RunStrip shows 24). Default 24. */
  recentLimit?: number;
}

const DEFAULT_RECENT_LIMIT = 24;

function zeroBreakdown(): StatusBreakdown {
  return {
    queued: 0,
    running: 0,
    succeeded: 0,
    failed: 0,
    timed_out: 0,
    failed_to_start: 0,
    canceled: 0,
  };
}

/** Derive one run's effective status from its snapshot + the injected clock. */
function deriveStatus(run: DashboardRun, nowMs: number): RunStatus | (string & {}) {
  return effectiveStatus(
    {
      status: run.status,
      startedAtMs: run.startedAtMs,
      queuedAtMs: run.queuedAtMs,
      maxRuntimeSeconds: run.maxRuntimeSeconds,
      graceSeconds: run.graceSeconds,
      startTimeoutSeconds: run.startTimeoutSeconds,
    },
    nowMs,
  );
}

/** finished_at → started_at → created_at (first non-null), for last-run time. */
function displayTime(run: DashboardRun): number | null {
  return run.finishedAtMs ?? run.startedAtMs ?? run.createdAtMs;
}

/**
 * Build one summary per agent. Statuses are derived once here; nothing
 * downstream re-derives or reads a raw status.
 */
export function buildAgentSummaries(
  agents: AgentSummaryInput[],
  nowMs: number,
  options: BuildOptions = {},
): AgentSummary[] {
  const recentLimit = options.recentLimit ?? DEFAULT_RECENT_LIMIT;

  return agents.map((agent) => {
    const breakdown = zeroBreakdown();

    // Sort oldest-first by createdAt so "recent newest-last" and "last run =
    // newest" both fall out of one ordering. Undated runs sort as oldest.
    const ordered = [...agent.runs].sort(
      (a, b) => (a.createdAtMs ?? -Infinity) - (b.createdAtMs ?? -Infinity),
    );

    const derived: SummaryRun[] = ordered.map((run) => {
      const status = deriveStatus(run, nowMs);
      if (status in breakdown) {
        breakdown[status as keyof StatusBreakdown] += 1;
      }
      return { effectiveStatus: status, createdAtMs: run.createdAtMs };
    });

    const legend: LegendCounts = {
      ok: breakdown.succeeded,
      fail: breakdown.failed,
      timeout: breakdown.timed_out,
    };

    let lastRun: LastRun | null = null;
    if (ordered.length > 0) {
      const newest = ordered[ordered.length - 1];
      lastRun = {
        effectiveStatus: deriveStatus(newest, nowMs),
        outcome: newest.outcome,
        atMs: displayTime(newest),
      };
    }

    return {
      id: agent.id,
      slug: agent.slug,
      name: agent.name,
      description: agent.description,
      requiresRepository: agent.requiresRepository,
      runCount: agent.runs.length,
      breakdown,
      legend,
      lastRun,
      recentRuns: derived.slice(-recentLimit),
    };
  });
}

/**
 * Whether an agent matches the filter query (AC-107.8). Case-insensitive
 * substring over name + slug. The query is trimmed; an empty or whitespace-only
 * query matches everything. The comparison is a plain `String.includes`, never
 * a constructed `RegExp`, so metacharacters (`.` `*` `[` `\`) match literally
 * and a stray `[` cannot throw (EC-25).
 */
export function matchesQuery(summary: AgentSummary, query: string): boolean {
  const q = query.trim().toLowerCase();
  if (q === "") return true;
  return summary.name.toLowerCase().includes(q) || summary.slug.toLowerCase().includes(q);
}

/** Filter a summary list by the query (transient; never persisted). */
export function filterAgentSummaries(summaries: AgentSummary[], query: string): AgentSummary[] {
  const q = query.trim();
  if (q === "") return summaries;
  return summaries.filter((s) => matchesQuery(s, q));
}
