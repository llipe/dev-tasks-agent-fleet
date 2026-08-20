/**
 * Single-run trace query for the run panel's span timeline.
 *
 * Queries all spans for a given session_id and maps them to timeline entries
 * for rendering in the run side panel (S-021).
 */

import type { ReadOutcome } from "../repository/types.js";
import { executeRunQuery } from "./query-executor.js";
import { buildSessionQueryParams } from "./query-builder.js";
import { mapRowsToTimeline, type TimelineSpan } from "./span-to-run-mapper.js";

export interface TraceQueryInput {
  sessionId: string;
  from: Date;
  to: Date;
}

/**
 * Query all spans for a single session and map to timeline entries.
 * Returns spans ordered chronologically for the run panel timeline.
 */
export async function querySessionTrace(
  input: TraceQueryInput,
): Promise<ReadOutcome<TimelineSpan[]>> {
  const params = buildSessionQueryParams({
    sessionId: input.sessionId,
    from: input.from,
    to: input.to,
  });

  const outcome = await executeRunQuery(params);

  if (outcome.status !== "ok") {
    return outcome;
  }

  const timeline = mapRowsToTimeline(outcome.data.rows);

  if (timeline.length === 0) {
    return { status: "empty", correlationId: outcome.correlationId };
  }

  return { status: "ok", data: timeline, correlationId: outcome.correlationId };
}
