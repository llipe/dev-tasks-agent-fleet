/**
 * Log-viewer filtering (Story S-145, FR10/FR11) — pure, client-side only.
 *
 * Both the step filter (FR10 — click a step in the steps panel) and the
 * log-level filter (FR11 — "errors and warnings only") operate over the log
 * window ALREADY loaded by the existing S-109/S-110 windowing
 * (`selectRecentWindow`, spec §8.2). This module adds no I/O and no new server
 * read for either filter — it is a total, synchronous reducer over the
 * already-fetched `LogLineView[]`.
 *
 * Level semantics: `level` is a SEVERITY THRESHOLD, not an exact match — the
 * PRD's own example ("errors and warnings only") is a compound selection, so
 * selecting `"warn"` keeps `warn` AND `error` lines (everything at or above
 * that severity), matching the shared `debug < info < warn < error` ordering.
 * Selecting `"error"` narrows to errors only. `"all"` disables the level
 * filter entirely.
 */

import type { LogLevel } from "@/lib/supabase/types";
import type { LogLineView } from "./run-detail";

export interface LogFilterState {
  /** The selected step, or null for "All steps" (FR10). */
  stepId: string | null;
  /** The minimum severity to show, or "all" to disable the level filter (FR11). */
  level: LogLevel | "all";
}

/** The filter that shows the full tail — both controls at their default. */
export const NO_LOG_FILTER: LogFilterState = { stepId: null, level: "all" };

const SEVERITY: Record<LogLevel, number> = { debug: 0, info: 1, warn: 2, error: 3 };

function severityOf(level: string): number {
  return (SEVERITY as Record<string, number>)[level] ?? SEVERITY.info;
}

/**
 * Apply the step + level filter to an already-loaded window of log lines.
 * Total and pure: never throws, always returns a subset of `lines` (CT-4) —
 * an unknown `stepId` (no line carries it) yields `[]`, not a crash. The
 * empty filter (`NO_LOG_FILTER`) is the identity function.
 */
export function applyLogFilter(lines: LogLineView[], filter: LogFilterState): LogLineView[] {
  const { stepId, level } = filter;
  if (stepId === null && level === "all") return lines;

  const minSeverity = level === "all" ? null : SEVERITY[level];

  return lines.filter((line) => {
    if (stepId !== null && (line.stepId ?? null) !== stepId) return false;
    if (minSeverity !== null && severityOf(line.level) < minSeverity) return false;
    return true;
  });
}
