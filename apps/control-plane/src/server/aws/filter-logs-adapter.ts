/**
 * CloudWatch FilterLogEvents adapter.
 *
 * Fetches log lines filtered by session_id.
 * Handles pagination to retrieve all matching log events.
 * Results are NOT cached — logs are read when the operator needs current truth.
 */

import {
  CloudWatchLogsClient,
  FilterLogEventsCommand,
  type FilteredLogEvent,
} from "@aws-sdk/client-cloudwatch-logs";
import { credentialsProvider, awsRegion } from "./credentials.js";
import { withRetry } from "../retry.js";
import type { ReadOutcome } from "../repository/types.js";
import { makeCorrelationId } from "../repository/types.js";

export interface FilterLogsParams {
  logGroupName: string;
  sessionId: string;
  startTime?: number; // Unix epoch ms
  endTime?: number; // Unix epoch ms
}

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

function extractMessage(event: FilteredLogEvent): string | null {
  return event.message?.trimEnd() ?? null;
}

/**
 * Fetch log events for a specific session_id.
 * Uses a JSON filter pattern on the session_id field.
 * Paginates through all matching events.
 */
export async function filterLogsBySessionId(
  params: FilterLogsParams,
): Promise<ReadOutcome<string[]>> {
  const correlationId = makeCorrelationId();

  try {
    const lines: string[] = [];
    let nextToken: string | undefined;

    do {
      const response = await withRetry(() =>
        getClient().send(
          new FilterLogEventsCommand({
            logGroupName: params.logGroupName,
            filterPattern: `{ $.session_id = "${params.sessionId}" }`,
            startTime: params.startTime,
            endTime: params.endTime,
            nextToken,
          }),
        ),
      );

      const events = response.events ?? [];
      for (const event of events) {
        const line = extractMessage(event);
        if (line !== null) {
          lines.push(line);
        }
      }

      nextToken = response.nextToken;
    } while (nextToken);

    if (lines.length === 0) {
      return { status: "empty", correlationId };
    }

    return { status: "ok", data: lines, correlationId };
  } catch (error: unknown) {
    const message = error instanceof Error ? error.message : "Unknown error filtering logs";
    return { status: "error", error: message, correlationId };
  }
}

/** Replace client for testing */
export function _setClient(c: CloudWatchLogsClient): void {
  client = c;
}
