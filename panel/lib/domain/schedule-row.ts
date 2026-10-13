/**
 * S-161 (#273) — pure presentation shaper for the `/schedules` table (SD-UI-1,
 * DESIGN.md §5.7). Turns a flat `v_schedules` row into the per-cell projection
 * the table renders: the state pill, the cadence summary (reusing
 * `lib/domain/cadence.ts`), the next-run and last-run cells, and the unified
 * blocked/skipped reason chip (SD-G6).
 *
 * Pure and clock-injected (`nowMs`) so relative times are deterministic in
 * tests. Absolute times render in the schedule's own IANA timezone via
 * `formatClock`/Intl — the standing note is "all times America/Santiago unless
 * noted", but a per-schedule zone is honored. This module never computes the
 * next-run instant itself (that is the DB's authority, SD-T6); it only formats
 * the `next_run_at` the row already carries.
 */

import { cadenceLabel, type CadenceSpec } from "@/lib/domain/cadence";
import type { RunStatus } from "@/lib/domain/status";
import type { RunOutcome, ScheduleState } from "@/lib/supabase/types";

export interface ScheduleRowInput {
  id: string;
  state: ScheduleState;
  agentName: string;
  agentSlug: string;
  repositoryFullName: string | null;
  repositoryBranch: string | null;
  cadence: CadenceSpec;
  timezone: string;
  nextRunAtMs: number | null;
  blockReason: string | null;
  lastSkippedReason: string | null;
  prBlockRunId: string | null;
  lastRunStatus: RunStatus | null;
  lastRunOutcome: RunOutcome | null;
  lastRunFinishedAtMs: number | null;
  lastRunId: string | null;
}

export type StatePillKind = "active" | "paused" | "blocked";

export interface ReasonChip {
  /** Which glyph the chip leads with (mapped to an icon in the view). */
  glyph: "open_pr" | "auto_paused" | "manual_pause" | "skip";
  tone: "timeout" | "muted" | "faint";
  text: string;
  /** True for an open_pr block → renders the "PR handled · resume anyway" clear. */
  clearable: boolean;
}

export interface ScheduleCellModel {
  statePill: StatePillKind;
  cadenceText: string;
  timezone: string;
  nextRun: { relative: string; absolute: string } | null;
  /** The held/paused placeholder for the next-run cell when not firing. */
  nextRunPlaceholder: "paused" | "held" | null;
  lastRun: { label: string; outcome: RunOutcome | null; status: RunStatus | null } | null;
  reason: ReasonChip | null;
}

function pad2(n: number): string {
  return String(n).padStart(2, "0");
}

/** Forward relative: `in 40m`, `in 3h 40m`, `tomorrow`, `in 3d`. Past → `due now`. */
export function formatRelativeFuture(targetMs: number, nowMs: number): string {
  const delta = targetMs - nowMs;
  if (delta <= 0) return "due now";
  const MIN = 60_000;
  const HOUR = 60 * MIN;
  const DAY = 24 * HOUR;
  if (delta < HOUR) return `in ${Math.max(1, Math.floor(delta / MIN))}m`;
  if (delta < DAY) {
    const h = Math.floor(delta / HOUR);
    const m = Math.floor((delta % HOUR) / MIN);
    return m > 0 ? `in ${h}h ${m}m` : `in ${h}h`;
  }
  const d = Math.floor(delta / DAY);
  if (d === 1) return "tomorrow";
  return `in ${d}d`;
}

/** `Wed 14 Oct · 07:00` in the schedule's timezone. */
export function formatAbsolute(targetMs: number, timeZone: string): string {
  const d = new Date(targetMs);
  try {
    const date = new Intl.DateTimeFormat("en-GB", {
      weekday: "short",
      day: "2-digit",
      month: "short",
      timeZone,
    }).format(d);
    const parts = new Intl.DateTimeFormat("en-GB", {
      hour: "2-digit",
      minute: "2-digit",
      hour12: false,
      timeZone,
    }).formatToParts(d);
    const get = (t: string) => parts.find((p) => p.type === t)?.value ?? "00";
    const hh = get("hour") === "24" ? "00" : get("hour");
    return `${date} · ${hh}:${get("minute")}`;
  } catch {
    // An invalid IANA zone must never throw in render — fall back to UTC-ish.
    return `${pad2(d.getUTCHours())}:${pad2(d.getUTCMinutes())}`;
  }
}

const LAST_RUN_LABEL: Record<string, string> = {
  succeeded: "success",
  failed: "failed",
  failed_to_start: "failed",
  timed_out: "timed out",
  canceled: "canceled",
  running: "running",
  queued: "queued",
};

/** Map a block/skip reason string to the unified reason chip (SD-G6). */
export function reasonChipFor(input: ScheduleRowInput): ReasonChip | null {
  const reason = input.blockReason ?? input.lastSkippedReason;
  if (!reason) return null;

  if (reason === "open_pr") {
    return {
      glyph: "open_pr",
      tone: "timeout",
      text: input.prBlockRunId
        ? "Blocked: a prior run's PR is still open"
        : "Blocked: open PR awaiting review",
      clearable: true,
    };
  }
  if (reason.startsWith("auto_paused")) {
    return {
      glyph: "auto_paused",
      tone: "timeout",
      text: "Auto-paused after repeated failures",
      clearable: false,
    };
  }
  if (reason === "manual_pause") {
    return { glyph: "manual_pause", tone: "muted", text: "Paused manually", clearable: false };
  }
  if (reason === "overlap") {
    return {
      glyph: "skip",
      tone: "faint",
      text: "Skipped: a prior run is still active",
      clearable: false,
    };
  }
  if (reason === "concurrency_cap") {
    return {
      glyph: "skip",
      tone: "faint",
      text: "Skipped: concurrency cap reached",
      clearable: false,
    };
  }
  if (reason === "config_missing") {
    return {
      glyph: "skip",
      tone: "faint",
      text: "Skipped: scheduler not configured",
      clearable: false,
    };
  }
  // Unknown reason: still surface it rather than hide a block.
  return { glyph: "skip", tone: "faint", text: `Note: ${reason}`, clearable: false };
}

/** Shape a `v_schedules` row into the table's per-cell model. Pure. */
export function buildScheduleCellModel(input: ScheduleRowInput, nowMs: number): ScheduleCellModel {
  const statePill: StatePillKind = input.state;

  let nextRun: ScheduleCellModel["nextRun"] = null;
  let nextRunPlaceholder: ScheduleCellModel["nextRunPlaceholder"] = null;
  if (input.state === "paused") {
    nextRunPlaceholder = "paused";
  } else if (input.state === "blocked") {
    nextRunPlaceholder = "held";
  } else if (input.nextRunAtMs != null) {
    nextRun = {
      relative: formatRelativeFuture(input.nextRunAtMs, nowMs),
      absolute: formatAbsolute(input.nextRunAtMs, input.timezone),
    };
  }

  const lastRun =
    input.lastRunId && input.lastRunStatus
      ? {
          label: LAST_RUN_LABEL[input.lastRunStatus] ?? input.lastRunStatus,
          outcome: input.lastRunOutcome,
          status: input.lastRunStatus,
        }
      : null;

  return {
    statePill,
    cadenceText: cadenceLabel(input.cadence),
    timezone: input.timezone,
    nextRun,
    nextRunPlaceholder,
    lastRun,
    reason: reasonChipFor(input),
  };
}
