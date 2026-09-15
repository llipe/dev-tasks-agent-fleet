/**
 * Run-detail presentation logic (Story S-109) — pure and clock-injected.
 *
 * Everything the run-detail screen needs to *decide* (as opposed to *render*)
 * lives here so it is unit-testable without a browser:
 *  - `selectBanner` — the DESIGN §8.3 terminal-state banner selection, a total
 *    function of status.
 *  - `buildLogLines` — projects `run_events` into the LogLine grid, labeling
 *    each line with its step and formatting the clock. The message is carried
 *    verbatim (never truncated, §7.5); the React component renders it as an
 *    inert text node (the XSS guard is at the render site, SC-13).
 *  - `buildSummary` — derives the summary status through the shared
 *    `effectiveStatus` (SD4, never the raw column) plus the metadata fields.
 *
 * The status derivation is imported from `lib/domain/status.ts` and never
 * restated here, so the summary pill can never disagree with the row screens.
 */

import { effectiveStatus, type RunStatus } from "@/lib/domain/status";
import type { RunOutcome, StepStatus } from "@/lib/supabase/types";
import { formatClock, formatDuration, formatDurationShort, formatRunId } from "@/lib/format";
import { outcomeLabel } from "@/lib/domain/run-row";

// ---------------------------------------------------------------------------
// Terminal-state banner (DESIGN §8.3)
// ---------------------------------------------------------------------------

/** The two statuses that carry a terminal-state banner above the log viewer. */
export type BannerStatus = "timed_out" | "failed_to_start";

export interface Banner {
  status: BannerStatus;
  /** Short human title for the banner heading. */
  title: string;
}

const BANNER_TITLE: Record<BannerStatus, string> = {
  timed_out: "Run timed out",
  failed_to_start: "Run failed to start",
};

/**
 * Select the terminal-state banner for a run's effective status, or null when
 * the status carries no banner. Total over every status value (RT-4): only
 * `timed_out` and `failed_to_start` produce a banner; everything else — the
 * live and success/failure/cancel states, and any unknown future value —
 * produces none.
 */
export function selectBanner(status: RunStatus | (string & {})): Banner | null {
  if (status === "timed_out") {
    return { status: "timed_out", title: BANNER_TITLE.timed_out };
  }
  if (status === "failed_to_start") {
    return { status: "failed_to_start", title: BANNER_TITLE.failed_to_start };
  }
  return null;
}

// ---------------------------------------------------------------------------
// Log lines
// ---------------------------------------------------------------------------

/** The minimal `run_events` projection the log viewer needs. */
export interface LogEventInput {
  id: number;
  seq: number;
  /** ISO-8601 timestamp string (or epoch ms). */
  ts: string | number;
  level: string;
  message: string;
  stepId: string | null;
}

/** The minimal `run_steps` projection needed to label a log line. */
export interface LogStepInput {
  id: string;
  key: string;
  title: string | null;
}

/** A log line ready for the LogLine primitive. */
export interface LogLineView {
  id: number;
  seq: number;
  timestamp: string;
  level: string;
  /** Step label (title → key), or "" when unlabeled/unresolvable. */
  step: string;
  /**
   * The raw `run_events.step_id`, or null/unresolvable (Story S-145, FR10) —
   * carried separately from the display `step` label so `applyLogFilter` can
   * match on the stable id rather than the (potentially duplicated) label.
   * Optional so existing call sites/fixtures that predate S-145 still type-check.
   */
  stepId?: string | null;
  /** The raw message, verbatim — never truncated. Rendered as inert text. */
  message: string;
}

/** Shared step-label rule: the title when present, else the key. Never "undefined". */
function stepLabel(step: { title: string | null; key: string }): string {
  return step.title && step.title.length > 0 ? step.title : step.key;
}

/**
 * Project events into log-line views, labeling each with its step. The caller
 * provides events already in display order (ascending `seq`); this preserves
 * that order and does not re-sort. A null or unresolvable `step_id` yields an
 * empty step label (never "undefined").
 */
export function buildLogLines(
  events: LogEventInput[],
  steps: LogStepInput[],
  timeZone = "UTC",
): LogLineView[] {
  const stepById = new Map<string, LogStepInput>(steps.map((s) => [s.id, s]));
  return events.map((e) => {
    const step = e.stepId != null ? stepById.get(e.stepId) : undefined;
    const label = step ? stepLabel(step) : "";
    return {
      id: e.id,
      seq: e.seq,
      timestamp: formatClock(e.ts, timeZone),
      level: e.level,
      step: label,
      stepId: e.stepId,
      message: e.message,
    };
  });
}

// ---------------------------------------------------------------------------
// Summary
// ---------------------------------------------------------------------------

/** The minimal run projection the summary needs. Timestamps are epoch ms. */
export interface SummaryInput {
  id: string;
  status: RunStatus | (string & {});
  startedAtMs: number | null;
  queuedAtMs: number | null;
  finishedAtMs: number | null;
  durationMs: number | null;
  maxRuntimeSeconds: number | null;
  graceSeconds: number | null;
  startTimeoutSeconds: number | null;
  outcome: RunOutcome | null;
  repositoryFullName: string | null;
  branch: string | null;
  /** Reaper/agent explanatory text, surfaced in the banner for terminal runs. */
  errorMessage: string | null;
}

/** The derived summary the RunSummary component renders. */
export interface RunSummaryView {
  shortId: string;
  effectiveStatus: RunStatus | (string & {});
  outcomeLabel: string;
  hasOutcome: boolean;
  repositoryFullName: string | null;
  hasRepository: boolean;
  branch: string | null;
  duration: string;
  queuedClock: string;
  startedClock: string;
  finishedClock: string;
  /** The terminal-state banner for this run, or null. */
  banner: Banner | null;
  /** Explanatory text for the banner (reaper/agent message). */
  errorMessage: string | null;
}

function clockOrDash(ms: number | null, timeZone: string): string {
  return ms == null ? "—" : formatClock(ms, timeZone);
}

/**
 * The duration a run accrued: `duration_ms` when present, else finished−started,
 * else null (never started). A live run is shown as `—` in the summary metadata
 * grid because its running duration belongs to the status pill, not the grid.
 */
function summaryDurationMs(run: SummaryInput): number | null {
  if (run.durationMs != null) return run.durationMs;
  if (run.startedAtMs != null && run.finishedAtMs != null) {
    return run.finishedAtMs - run.startedAtMs;
  }
  return null;
}

/**
 * Build the run summary. The status is derived through the shared
 * `effectiveStatus` (SD4), so a stale `running` run presents `timed_out` and
 * the banner selection agrees with the pill.
 */
export function buildSummary(run: SummaryInput, nowMs: number, timeZone = "UTC"): RunSummaryView {
  const effective = effectiveStatus(
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

  const durMs = summaryDurationMs(run);

  return {
    shortId: formatRunId(run.id),
    effectiveStatus: effective,
    outcomeLabel: outcomeLabel(run.outcome),
    hasOutcome: run.outcome != null,
    repositoryFullName: run.repositoryFullName,
    hasRepository: run.repositoryFullName != null,
    branch: run.branch,
    duration: durMs == null ? "—" : formatDuration(durMs),
    queuedClock: clockOrDash(run.queuedAtMs, timeZone),
    startedClock: clockOrDash(run.startedAtMs, timeZone),
    finishedClock: clockOrDash(run.finishedAtMs, timeZone),
    banner: selectBanner(effective),
    errorMessage: run.errorMessage,
  };
}

// ---------------------------------------------------------------------------
// Steps panel (Story S-145, FR9)
// ---------------------------------------------------------------------------

/** The minimal `run_steps` projection the steps panel needs. Timestamps are epoch ms. */
export interface RunStepInput {
  id: string;
  key: string;
  title: string | null;
  /**
   * `run_steps.status` — NOT `effective_status`. Steps carry no reaper-computed
   * "effective" state; a reaped run's orphan steps are already closed `failed`
   * by the reaper's step-closure (technical-guidelines §8), so no additional
   * stale-step handling belongs here.
   */
  status: StepStatus;
  startedAtMs: number | null;
  finishedAtMs: number | null;
}

/** A steps-panel row (DESIGN §5.3): colored dot (from `status`), name, duration, event count. */
export interface StepPanelRow {
  id: string;
  /** Display label — title → key, reusing the same rule `buildLogLines` uses. */
  title: string;
  status: StepStatus;
  /** `formatDurationShort` (lib/format.ts), or "—" when the step never finished. */
  duration: string;
  eventCount: number;
}

/**
 * Project `run_steps` rows into steps-panel rows. `eventCountByStep` is
 * derived by the CALLER from the already-loaded `run_events` window
 * (`selectRecentWindow`, spec §8.2) — this function issues no query and takes
 * no client; event counts are zero marginal DB reads (CT-5: the sum of the
 * counts this returns can never exceed the loaded window's total, since it is
 * a partition of that window, not an independent count).
 *
 * A step with no matching key in `eventCountByStep` reports `0`, never
 * `undefined`/`NaN` (a zero-event step is not an error). A step still running
 * (no `finished_at`) or never started shows a dash duration rather than
 * inventing a running-duration display — the steps panel is a static list,
 * not a live-updating timer.
 */
export function buildStepsPanel(
  steps: RunStepInput[],
  eventCountByStep: Record<string, number>,
): StepPanelRow[] {
  return steps.map((s) => {
    const durMs =
      s.startedAtMs != null && s.finishedAtMs != null ? s.finishedAtMs - s.startedAtMs : null;
    return {
      id: s.id,
      title: stepLabel(s),
      status: s.status,
      duration: durMs == null ? "—" : formatDurationShort(durMs),
      eventCount: eventCountByStep[s.id] ?? 0,
    };
  });
}
