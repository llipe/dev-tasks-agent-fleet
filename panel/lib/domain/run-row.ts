/**
 * Run-history row shaper (task 3.2, Story S-108).
 *
 * Turns the flat, `v_runs`-shaped rows the query layer returns into the per-row
 * projection the run-history table renders, and derives the three agent-header
 * metrics (p50 duration, success rate; params count is read off the schema).
 *
 * The one property that carries FR11a: **every status this module emits is the
 * `effectiveStatus` derivation, never the raw `status` column** — including the
 * status that feeds the success-rate metric. A stale `running` row presents
 * `timed_out`, so a row can never display `timed_out` while the header rate
 * counts it as still-running. The derivation lives only in
 * `lib/domain/status.ts`; this module imports it and never restates the
 * threshold arithmetic (CT-3 analogue).
 *
 * Pure and clock-injected: `now` is passed in so a stale row is stale at an
 * instant the caller controls (EC-8). Formatting is delegated to the shared
 * `lib/format.ts` §7 formatters — this module never reimplements them.
 */

import { effectiveStatus, type RunStatus } from "@/lib/domain/status";
import type { RunOutcome } from "@/lib/supabase/types";
import {
  formatDuration,
  formatRelative,
  formatRunningDuration,
  formatRunId,
  formatStepProgress,
} from "@/lib/format";

/** The minimal per-run projection the row shaper needs. Timestamps are epoch ms. */
export interface RunRowInput {
  id: string;
  status: RunStatus | (string & {});
  /** Optional pre-derived effective status (unused by default; the shaper derives it). */
  effectiveStatusFallback?: RunStatus | (string & {});
  startedAtMs: number | null;
  queuedAtMs: number | null;
  finishedAtMs: number | null;
  createdAtMs: number | null;
  /** duration_ms from the row when present; else derived from finished−started. */
  durationMs: number | null;
  maxRuntimeSeconds: number | null;
  graceSeconds: number | null;
  startTimeoutSeconds: number | null;
  outcome: RunOutcome | null;
  repositoryFullName: string | null;
  repositoryBranch: string | null;
  stepsDone: number;
  stepsTotal: number;
}

/** A run reduced to what the run-history table renders. */
export interface RunRow {
  id: string;
  shortId: string;
  effectiveStatus: RunStatus | (string & {});
  outcomeLabel: string;
  hasOutcome: boolean;
  /** `Xm XXs`, `running · Xm`, or `—`. */
  duration: string;
  /** `n/m`. */
  steps: string;
  repositoryFullName: string | null;
  repositoryBranch: string | null;
  hasRepository: boolean;
  /** Relative start time (`14 min ago`), from started_at → created_at. */
  startedRelative: string;
}

/** Outcome tag text (§8.2, uppercase). `—` for a pending/absent outcome. */
export function outcomeLabel(outcome: RunOutcome | null): string {
  switch (outcome) {
    case "fixed":
      return "FIXED";
    case "no_vulnerabilities":
      return "NO VULNS";
    case "partial":
      return "PARTIAL";
    case "needs_review":
      return "NEEDS REVIEW";
    case "not_applicable":
      return "N/A";
    default:
      return "—";
  }
}

/** Derive one run's effective status from its snapshot + the injected clock. */
function deriveStatus(run: RunRowInput, nowMs: number): RunStatus | (string & {}) {
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

/**
 * The duration a run has actually accrued, in ms, or null when there is none
 * to show. A finished run uses `duration_ms` when present, else `finished −
 * started`. A running run has no fixed duration (the row shows `running · Xm`
 * instead). A run that never started (`failed_to_start`) has no duration.
 */
function finishedDurationMs(run: RunRowInput): number | null {
  if (run.durationMs != null) return run.durationMs;
  if (run.startedAtMs != null && run.finishedAtMs != null) {
    return run.finishedAtMs - run.startedAtMs;
  }
  return null;
}

/**
 * Present a run's duration:
 *  - a live run (`effective === running`) → `running · Xm` from started_at
 *  - a run with an accrued duration → `Xm XXs`
 *  - otherwise (never started, no duration) → `—`, never `NaN` / `0m 00s`
 */
function presentDuration(
  run: RunRowInput,
  effective: RunStatus | (string & {}),
  nowMs: number,
): string {
  if (effective === "running") {
    // Elapsed since start; if somehow no start, fall back to em dash.
    if (run.startedAtMs != null) {
      return formatRunningDuration(nowMs - run.startedAtMs);
    }
    return "—";
  }
  const ms = finishedDurationMs(run);
  if (ms == null) return "—";
  return formatDuration(ms);
}

/** Present the relative start time, from started_at → created_at. */
function presentStartedRelative(run: RunRowInput, nowMs: number): string {
  const at = run.startedAtMs ?? run.createdAtMs;
  if (at == null) return "—";
  return formatRelative(at, nowMs);
}

/** Shape one run into its row projection. */
export function buildRunRow(run: RunRowInput, nowMs: number): RunRow {
  const effective = deriveStatus(run, nowMs);
  return {
    id: run.id,
    shortId: formatRunId(run.id),
    effectiveStatus: effective,
    outcomeLabel: outcomeLabel(run.outcome),
    hasOutcome: run.outcome != null,
    duration: presentDuration(run, effective, nowMs),
    steps: formatStepProgress(run.stepsDone, run.stepsTotal),
    repositoryFullName: run.repositoryFullName,
    repositoryBranch: run.repositoryBranch,
    hasRepository: run.repositoryFullName != null,
    startedRelative: presentStartedRelative(run, nowMs),
  };
}

/**
 * Shape a list of runs into rows, preserving the newest-first order the query
 * returns — the shaper does not re-sort (the query's `order by created_at desc`
 * is the single source of ordering, so the UI and the query never disagree).
 */
export function buildRunRows(runs: RunRowInput[], nowMs: number): RunRow[] {
  return runs.map((r) => buildRunRow(r, nowMs));
}

// ---------------------------------------------------------------------------
// Agent header metrics
// ---------------------------------------------------------------------------

/** The per-agent header input the metrics derive from. */
export interface AgentHeaderInput {
  name: string;
  slug: string;
  description: string | null;
  /** Count of top-level properties in `params_schema` (computed at the read boundary). */
  paramsCount: number;
  isEnabled: boolean;
  runs: RunRowInput[];
}

/** The derived agent header. */
export interface AgentHeader {
  name: string;
  slug: string;
  description: string | null;
  paramsCount: number;
  isEnabled: boolean;
  runCount: number;
  /** p50 (median) finished-run duration as `Xm XXs`, or null when no run has a duration. */
  p50Duration: string | null;
  /** Whole-percent success rate (succeeded / total via effective status), or null for zero runs. */
  successRate: number | null;
}

/**
 * The median of a numeric list. For an even count we take the lower-middle
 * element deterministically (rather than averaging the two middles), so the
 * reported p50 is always an actually-observed duration — a real run's time,
 * not a synthetic midpoint. Assumes `values` is non-empty.
 */
function lowerMedian(values: number[]): number {
  const sorted = [...values].sort((a, b) => a - b);
  const mid = Math.floor((sorted.length - 1) / 2);
  return sorted[mid];
}

/**
 * Build the agent header, deriving p50 duration and success rate from the
 * returned rows. Both statuses feeding the rate are `effectiveStatus`, so a
 * stale `running` run counts as `timed_out` (not a success) — the header can
 * never disagree with the rows below it (FR11a).
 */
export function buildAgentHeader(agent: AgentHeaderInput, nowMs: number): AgentHeader {
  const runCount = agent.runs.length;

  const durations = agent.runs
    .map((r) => finishedDurationMs(r))
    .filter((ms): ms is number => ms != null);
  const p50Duration = durations.length > 0 ? formatDuration(lowerMedian(durations)) : null;

  let successRate: number | null = null;
  if (runCount > 0) {
    const succeeded = agent.runs.filter((r) => deriveStatus(r, nowMs) === "succeeded").length;
    successRate = Math.round((succeeded / runCount) * 100);
  }

  return {
    name: agent.name,
    slug: agent.slug,
    description: agent.description,
    paramsCount: agent.paramsCount,
    isEnabled: agent.isEnabled,
    runCount,
    p50Duration,
    successRate,
  };
}
