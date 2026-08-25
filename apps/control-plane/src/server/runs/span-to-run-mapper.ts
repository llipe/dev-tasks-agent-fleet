/**
 * Pure span-to-Run mapper.
 *
 * Takes raw Logs Insights result rows and folds them into Run objects:
 * - Groups rows by session_id
 * - From root spans: extracts run metadata (subject, status, outcome, duration)
 * - From gen_ai child spans: extracts model usage (model, tokens)
 * - Aggregates token counts per model across all child spans in the session
 *
 * Design:
 * - Pure function, no side effects except console.warn on malformed rows
 * - Skips malformed rows gracefully (warn, don't crash)
 * - Zero-token runs are valid (deterministic happy path with no model invocations)
 */

import type { LogsInsightsRow } from "../aws/logs-insights-adapter.js";

/**
 * Aggregated model usage for a single model within a run.
 */
export interface ModelUsage {
  modelId: string;
  tokensIn: number;
  tokensOut: number;
  calls: number;
}

/**
 * A complete run derived from spans.
 */
export interface Run {
  sessionId: string;
  subjectId: string;
  agentName: string;
  status: string;
  outcomeType: string;
  outcomeUrl: string;
  startedAt: string;
  durationMs: number;
  perModel: ModelUsage[];
  source: "spans";
}

/**
 * A span entry for the single-run timeline view.
 */
export interface TimelineSpan {
  spanName: string;
  parentSpanId: string;
  startTime: string;
  durationMs: number;
  modelId: string;
  tokensIn: number;
  tokensOut: number;
  isRoot: boolean;
}

/**
 * Map raw Logs Insights rows into Run objects.
 *
 * Each row is a single span (root or child). This function:
 * 1. Identifies root spans (have run_status, no parent_span_id)
 * 2. Identifies gen_ai child spans (have model_id and parent_span_id)
 * 3. Groups by session_id
 * 4. Builds one Run per session from root span + aggregated children
 */
export function mapRowsToRuns(rows: LogsInsightsRow[]): Run[] {
  // Group rows by session_id
  const sessionMap = new Map<
    string,
    { root: LogsInsightsRow | null; children: LogsInsightsRow[] }
  >();

  for (const row of rows) {
    const sessionId = resolveSessionIdFromRow(row);
    if (!sessionId) {
      console.warn("[span-to-run-mapper] Skipping row with missing session_id", {
        keys: Object.keys(row),
      });
      continue;
    }

    if (!sessionMap.has(sessionId)) {
      sessionMap.set(sessionId, { root: null, children: [] });
    }

    const group = sessionMap.get(sessionId);
    if (!group) continue;

    if (isRootRow(row)) {
      group.root = row;
    } else if (isGenAiRow(row)) {
      group.children.push(row);
    }
    // Rows that are neither root nor gen_ai are silently skipped (e.g., internal spans)
  }

  // Build Run objects from grouped data
  const runs: Run[] = [];

  for (const [sessionId, group] of sessionMap) {
    if (!group.root) {
      // No root span for this session — can't build a Run without metadata
      console.warn("[span-to-run-mapper] Session has no root span, skipping", { sessionId });
      continue;
    }

    const run = buildRunFromGroup(sessionId, group.root, group.children);
    if (run) {
      runs.push(run);
    }
  }

  return runs;
}

/**
 * Map rows from a session spans query into timeline entries.
 * Returns all spans ordered chronologically for the run panel timeline.
 */
export function mapRowsToTimeline(rows: LogsInsightsRow[]): TimelineSpan[] {
  const spans: TimelineSpan[] = [];

  for (const row of rows) {
    const spanName = row["span_name"] ?? row["name"] ?? "";
    const parentSpanId = row["parent_span_id"] ?? "";
    const startTime = row["start_time"] ?? "";
    const durationNs = parseFloat(row["duration_ns"] ?? "0");
    const modelId = row["model_id"] ?? "";
    const tokensIn = parseInt(row["tokens_in"] ?? "0", 10) || 0;
    const tokensOut = parseInt(row["tokens_out"] ?? "0", 10) || 0;

    spans.push({
      spanName,
      parentSpanId,
      startTime,
      durationMs: nanosToMs(durationNs),
      modelId,
      tokensIn,
      tokensOut,
      isRoot: parentSpanId === "" || parentSpanId === undefined,
    });
  }

  return spans;
}

// --- Internal helpers ---

function resolveSessionIdFromRow(row: LogsInsightsRow): string | undefined {
  // Primary: session_id from query alias
  const primary = row["session_id"];
  if (primary && primary.trim().length > 0) return primary.trim();

  // Fallback: session_id_fallback from query alias
  const fallback = row["session_id_fallback"];
  if (fallback && fallback.trim().length > 0) return fallback.trim();

  return undefined;
}

function isRootRow(row: LogsInsightsRow): boolean {
  // Root rows have run_status set and no parent_span_id (or empty)
  const runStatus = row["run_status"];
  const parentSpanId = row["parent_span_id"] ?? "";
  return typeof runStatus === "string" && runStatus.length > 0 && parentSpanId === "";
}

function isGenAiRow(row: LogsInsightsRow): boolean {
  // Gen AI rows have model_id and a non-empty parent_span_id
  const modelId = row["model_id"];
  const parentSpanId = row["parent_span_id"] ?? "";
  return typeof modelId === "string" && modelId.length > 0 && parentSpanId.length > 0;
}

function buildRunFromGroup(
  sessionId: string,
  root: LogsInsightsRow,
  children: LogsInsightsRow[],
): Run | null {
  const subjectId = root["subject_id"];
  if (!subjectId) {
    console.warn("[span-to-run-mapper] Root span missing subject_id, skipping", { sessionId });
    return null;
  }

  const agentName = root["service_name"] ?? "";
  const status = root["run_status"] ?? "";
  const outcomeType = root["outcome_type"] ?? "";
  const outcomeUrl = root["outcome_url"] ?? "";
  const startTime = root["start_time"] ?? "";
  const durationNs = parseFloat(root["duration_ns"] ?? "0");

  // Fold children into per-model usage
  const perModel = foldModelUsage(children);

  return {
    sessionId,
    subjectId,
    agentName,
    status,
    outcomeType,
    outcomeUrl,
    startedAt: nanosToIso(startTime),
    durationMs: nanosToMs(durationNs),
    perModel,
    source: "spans",
  };
}

/**
 * Fold gen_ai child spans into aggregated per-model usage.
 * Multiple spans for the same model are summed.
 */
function foldModelUsage(children: LogsInsightsRow[]): ModelUsage[] {
  const modelMap = new Map<string, ModelUsage>();

  for (const child of children) {
    const modelId = child["model_id"];
    if (!modelId) continue;

    const tokensIn = parseInt(child["tokens_in"] ?? "0", 10) || 0;
    const tokensOut = parseInt(child["tokens_out"] ?? "0", 10) || 0;

    const existing = modelMap.get(modelId);
    if (existing) {
      existing.tokensIn += tokensIn;
      existing.tokensOut += tokensOut;
      existing.calls += 1;
    } else {
      modelMap.set(modelId, { modelId, tokensIn, tokensOut, calls: 1 });
    }
  }

  return Array.from(modelMap.values());
}

/**
 * Convert a nanosecond duration to milliseconds.
 */
function nanosToMs(ns: number): number {
  if (isNaN(ns) || ns <= 0) return 0;
  return Math.round(ns / 1_000_000);
}

/**
 * Convert a startTimeUnixNano string to ISO 8601 string.
 * The value from Logs Insights may be the Unix epoch nanoseconds as a string.
 */
function nanosToIso(startTimeNano: string): string {
  if (!startTimeNano) return "";

  const ns = parseFloat(startTimeNano);
  if (isNaN(ns) || ns <= 0) return "";

  // Convert nanoseconds to milliseconds for Date constructor
  const ms = Math.floor(ns / 1_000_000);
  try {
    return new Date(ms).toISOString();
  } catch {
    return "";
  }
}
