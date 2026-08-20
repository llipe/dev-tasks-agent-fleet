/**
 * CloudWatch Logs Insights adapter.
 *
 * Executes StartQuery → polls GetQueryResults → StopQuery on timeout.
 *
 * Poll backoff: 200ms → 400ms → 800ms → ... capped at 3s.
 * Total deadline: 25 seconds.
 * If deadline exceeded: calls StopQuery, returns { status: "timeout" }.
 * If query returns Failed or Cancelled: returns appropriate status.
 */

import {
  CloudWatchLogsClient,
  StartQueryCommand,
  GetQueryResultsCommand,
  StopQueryCommand,
  type ResultField,
} from "@aws-sdk/client-cloudwatch-logs";
import { credentialsProvider, awsRegion } from "./credentials.js";
import { withRetry } from "../retry.js";
import type { ReadOutcome } from "../repository/types.js";
import { makeCorrelationId } from "../repository/types.js";

/** Domain type for Logs Insights results */
export interface LogsInsightsResult {
  rows: LogsInsightsRow[];
}

export type LogsInsightsRow = Record<string, string>;

export interface LogsInsightsQueryParams {
  logGroupName: string;
  queryString: string;
  startTime: number; // Unix epoch seconds
  endTime: number; // Unix epoch seconds
}

/** Configuration for polling behavior */
export interface PollConfig {
  /** Initial poll delay in ms (default: 200) */
  initialDelayMs?: number;
  /** Max poll delay in ms (default: 3000) */
  maxDelayMs?: number;
  /** Total deadline in ms (default: 25000) */
  deadlineMs?: number;
}

const DEFAULT_POLL_CONFIG: Required<PollConfig> = {
  initialDelayMs: 200,
  maxDelayMs: 3000,
  deadlineMs: 25000,
};

let client: CloudWatchLogsClient | undefined;

function getClient(): CloudWatchLogsClient {
  if (!client) {
    client = new CloudWatchLogsClient({
      region: awsRegion,
      credentials: credentialsProvider,
    });
  }
  return client;
}

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function parseResultFields(fields: ResultField[]): LogsInsightsRow {
  const row: LogsInsightsRow = {};
  for (const field of fields) {
    if (field.field && field.value !== undefined) {
      row[field.field] = field.value;
    }
  }
  return row;
}

/**
 * Execute a Logs Insights query with polling and deadline.
 * Returns a ReadOutcome with the query results, or timeout/error status.
 */
export async function executeInsightsQuery(
  params: LogsInsightsQueryParams,
  pollConfig?: PollConfig,
): Promise<ReadOutcome<LogsInsightsResult>> {
  const config = { ...DEFAULT_POLL_CONFIG, ...pollConfig };
  const correlationId = makeCorrelationId();

  // Start the query
  let queryId: string;
  try {
    const startResponse = await withRetry(() =>
      getClient().send(
        new StartQueryCommand({
          logGroupName: params.logGroupName,
          queryString: params.queryString,
          startTime: params.startTime,
          endTime: params.endTime,
        }),
      ),
    );

    if (!startResponse.queryId) {
      return { status: "error", error: "No queryId returned from StartQuery", correlationId };
    }
    queryId = startResponse.queryId;
  } catch (error: unknown) {
    const message = error instanceof Error ? error.message : "Unknown error starting query";
    return { status: "error", error: message, correlationId };
  }

  // Poll with capped backoff
  const startedAt = Date.now();
  let delay = config.initialDelayMs;

  while (true) {
    // Check deadline
    if (Date.now() - startedAt >= config.deadlineMs) {
      // Deadline exceeded — stop the query
      try {
        await getClient().send(new StopQueryCommand({ queryId }));
      } catch {
        // Best-effort stop
      }
      return { status: "timeout", correlationId };
    }

    await sleep(delay);

    try {
      const result = await withRetry(() =>
        getClient().send(new GetQueryResultsCommand({ queryId })),
      );

      const status = result.status;

      if (status === "Complete") {
        const rows = (result.results ?? []).map((fields) => parseResultFields(fields));
        if (rows.length === 0) {
          return { status: "empty", correlationId };
        }
        return { status: "ok", data: { rows }, correlationId };
      }

      if (status === "Failed") {
        return { status: "error", error: "Query failed", correlationId };
      }

      if (status === "Cancelled") {
        return { status: "error", error: "Query cancelled", correlationId };
      }

      // Still Running or Scheduled — continue polling
    } catch (error: unknown) {
      const message = error instanceof Error ? error.message : "Unknown error polling query";
      return { status: "error", error: message, correlationId };
    }

    // Increase delay with cap
    delay = Math.min(delay * 2, config.maxDelayMs);
  }
}

/** Replace client for testing */
export function _setClient(c: CloudWatchLogsClient): void {
  client = c;
}
