/**
 * Run list merge — S-018.
 *
 * Merges two sources of run data:
 * - Span runs: derived from Logs Insights (S-017), have full telemetry data
 * - Config runs: projected from DynamoDB SubjectAgentItem rows
 *
 * Merge rules:
 * - Key: session_id
 * - If a run appears in both sources: span data wins (more complete)
 * - Config-only runs are always included (regardless of status)
 * - Span-only runs are always included
 *
 * Post-merge: apply status filter, date-range filter, sort startedAt desc.
 */

import type { Run, ModelUsage } from "./span-to-run-mapper.js";
import type { ConfigRun } from "./config-projection.js";

/**
 * Extended Run type with source discriminator and optional cost.
 */
export interface MergedRun {
  sessionId: string;
  subjectId: string;
  agentName: string;
  status: string;
  outcomeType: string;
  outcomeUrl: string;
  startedAt: string;
  durationMs: number;
  perModel: ModelUsage[];
  source: "spans" | "config";
  cost?: { usd: number; complete: boolean; unpricedModels: string[] };
}

export interface MergeFilters {
  statusFilter?: string;
  from?: Date;
  to?: Date;
}

/**
 * Merge span runs and config runs into a unified list.
 *
 * - Keyed by session_id
 * - Span wins on conflict
 * - Config-only runs included regardless of status
 * - Filters and sort applied after merge
 */
export function mergeRuns(
  spanRuns: Run[],
  configRuns: ConfigRun[],
  filters?: MergeFilters,
): MergedRun[] {
  const merged = new Map<string, MergedRun>();

  // Add all config runs first (span wins on conflict, so we write config first)
  for (const configRun of configRuns) {
    merged.set(configRun.sessionId, toMergedRun(configRun));
  }

  // Add span runs — overwrites config if same session_id (span wins)
  for (const spanRun of spanRuns) {
    merged.set(spanRun.sessionId, toMergedRun(spanRun));
  }

  let result = Array.from(merged.values());

  // Apply filters
  if (filters?.statusFilter) {
    const status = filters.statusFilter;
    result = result.filter((r) => r.status === status);
  }

  if (filters?.from) {
    const fromMs = filters.from.getTime();
    result = result.filter((r) => {
      const startMs = new Date(r.startedAt).getTime();
      return !isNaN(startMs) && startMs >= fromMs;
    });
  }

  if (filters?.to) {
    const toMs = filters.to.getTime();
    result = result.filter((r) => {
      const startMs = new Date(r.startedAt).getTime();
      return !isNaN(startMs) && startMs <= toMs;
    });
  }

  // Sort by startedAt descending (most recent first)
  result.sort((a, b) => {
    const aMs = new Date(a.startedAt).getTime();
    const bMs = new Date(b.startedAt).getTime();
    return bMs - aMs;
  });

  return result;
}

function toMergedRun(run: Run | ConfigRun): MergedRun {
  return {
    sessionId: run.sessionId,
    subjectId: run.subjectId,
    agentName: run.agentName,
    status: run.status,
    outcomeType: run.outcomeType,
    outcomeUrl: run.outcomeUrl,
    startedAt: run.startedAt,
    durationMs: run.durationMs,
    perModel: run.perModel,
    source: run.source,
  };
}
