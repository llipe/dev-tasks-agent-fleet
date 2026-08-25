/**
 * Query executor for Logs Insights.
 *
 * Composes the query builder with the logs-insights-adapter, adding:
 * - QueryOutcome type mapping (ok, empty, timeout, error)
 * - Timeout → StopQuery (handled by adapter)
 * - Failed/Cancelled → error variant
 *
 * The adapter already implements the 25s deadline with capped backoff.
 * This module provides the higher-level API consumed by the run-query-service.
 */

import type { ReadOutcome } from "../repository/types.js";
import {
  executeInsightsQuery,
  type LogsInsightsQueryParams,
  type LogsInsightsResult,
} from "../aws/logs-insights-adapter.js";

/**
 * QueryOutcome reuses ReadOutcome<T> from S-015:
 *   ok | empty | timeout | error
 *
 * - ok: query completed with results
 * - empty: query completed with zero results
 * - timeout: 25s deadline exceeded, StopQuery called
 * - error: Failed, Cancelled, or exception
 */
export type QueryOutcome<T> = ReadOutcome<T>;

/**
 * Execute a Logs Insights query with the standard deadline/backoff config.
 * Maps adapter results into QueryOutcome<LogsInsightsResult>.
 */
export async function executeRunQuery(
  params: LogsInsightsQueryParams,
): Promise<QueryOutcome<LogsInsightsResult>> {
  return executeInsightsQuery(params);
}
