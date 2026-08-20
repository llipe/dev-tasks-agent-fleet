/**
 * Query builder for Logs Insights run queries.
 *
 * Reads SPAN_FIELDS and SPANS_LOG_GROUP from the shared config —
 * no hardcoded log group names or field paths.
 *
 * Delegates actual query string construction to the shared `buildRunListQuery`
 * and `buildSessionSpansQuery` functions. This module composes them with
 * the log group configuration and date-range validation.
 */

import { SPANS_LOG_GROUP, buildRunListQuery, buildSessionSpansQuery } from "@fleet/shared";
import type { LogsInsightsQueryParams } from "../aws/logs-insights-adapter.js";

/** Maximum query range in days */
export const MAX_QUERY_RANGE_DAYS = 30;

/** Maximum results per query */
export const MAX_QUERY_LIMIT = 5000;

export interface RunListQueryInput {
  agentName?: string;
  from: Date;
  to: Date;
  limit?: number;
}

export interface SessionQueryInput {
  sessionId: string;
  from: Date;
  to: Date;
}

/**
 * Build a complete Logs Insights query params object for the run list.
 * Validates date range (max 30 days) and caps limit at 5000.
 */
export function buildRunListQueryParams(input: RunListQueryInput): LogsInsightsQueryParams {
  const { from, to } = validateDateRange(input.from, input.to);
  const limit = Math.min(input.limit ?? MAX_QUERY_LIMIT, MAX_QUERY_LIMIT);

  const queryString = buildRunListQuery({
    agentName: input.agentName,
    limit,
  });

  return {
    logGroupName: SPANS_LOG_GROUP,
    queryString,
    startTime: Math.floor(from.getTime() / 1000),
    endTime: Math.floor(to.getTime() / 1000),
  };
}

/**
 * Build a complete Logs Insights query params object for a single session's spans.
 * Used by the run panel's span timeline.
 */
export function buildSessionQueryParams(input: SessionQueryInput): LogsInsightsQueryParams {
  const { from, to } = validateDateRange(input.from, input.to);

  const queryString = buildSessionSpansQuery(input.sessionId);

  return {
    logGroupName: SPANS_LOG_GROUP,
    queryString,
    startTime: Math.floor(from.getTime() / 1000),
    endTime: Math.floor(to.getTime() / 1000),
  };
}

/**
 * Validate and clamp date range to MAX_QUERY_RANGE_DAYS.
 * If the range exceeds the max, the `from` is adjusted forward.
 */
function validateDateRange(from: Date, to: Date): { from: Date; to: Date } {
  const maxRangeMs = MAX_QUERY_RANGE_DAYS * 24 * 60 * 60 * 1000;
  const rangeMs = to.getTime() - from.getTime();

  if (rangeMs > maxRangeMs) {
    return { from: new Date(to.getTime() - maxRangeMs), to };
  }

  return { from, to };
}
