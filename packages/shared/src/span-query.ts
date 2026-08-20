/**
 * Logs Insights query builders for span data.
 *
 * These produce CloudWatch Logs Insights query strings that the control plane
 * executes via StartQuery/GetQueryResults. The field paths come from SPAN_FIELDS
 * to ensure a single point of change.
 *
 * Query design:
 * - Run list query: returns root spans (one per run) with all metadata
 * - Session spans query: returns all spans for a given session (root + children)
 *
 * Status: Queries use EXPECTED paths pending live verification.
 */

import { SPAN_FIELDS } from "./span-fields.js";

export const QUERY_LIMITS = {
  /** Default limit for run list queries */
  RUN_LIST: 100,
  /** Default limit for session span queries */
  SESSION_SPANS: 500,
} as const;

export interface RunListQueryOptions {
  /** Maximum number of results (default: QUERY_LIMITS.RUN_LIST) */
  limit?: number;
  /** Filter by agent/service name */
  agentName?: string;
}

/**
 * Build a Logs Insights query for the run list view.
 *
 * Returns root spans only (identified by presence of `llipe.run.status`),
 * projecting all fields needed for the agents/runs table.
 *
 * Example output:
 * ```
 * fields resource.attributes.`session.id` as session_id, ...
 * | filter ispresent(resource.attributes.`llipe.run.status`)
 * | sort @timestamp desc
 * | limit 100
 * ```
 */
export function buildRunListQuery(options: RunListQueryOptions = {}): string {
  const limit = options.limit ?? QUERY_LIMITS.RUN_LIST;

  const fields = [
    `${backtickPath(SPAN_FIELDS.SESSION_ID)} as session_id`,
    `${backtickPath(SPAN_FIELDS.SESSION_ID_FALLBACK)} as session_id_fallback`,
    `${backtickPath(SPAN_FIELDS.SUBJECT_ID)} as subject_id`,
    `${backtickPath(SPAN_FIELDS.RUN_STATUS)} as run_status`,
    `${backtickPath(SPAN_FIELDS.OUTCOME_TYPE)} as outcome_type`,
    `${backtickPath(SPAN_FIELDS.OUTCOME_URL)} as outcome_url`,
    `${backtickPath(SPAN_FIELDS.SERVICE_NAME)} as service_name`,
    `${SPAN_FIELDS.DURATION_NS} as duration_ns`,
    `${SPAN_FIELDS.TIMESTAMP} as start_time`,
  ];

  const filters = [`ispresent(${backtickPath(SPAN_FIELDS.RUN_STATUS)})`];

  if (options.agentName) {
    filters.push(`${backtickPath(SPAN_FIELDS.SERVICE_NAME)} = '${options.agentName}'`);
  }

  const lines = [
    `fields ${fields.join(", ")}`,
    `| filter ${filters.join(" and ")}`,
    `| sort @timestamp desc`,
    `| limit ${limit}`,
  ];

  return lines.join("\n");
}

/**
 * Build a Logs Insights query for all spans in a session.
 *
 * Returns both root and child spans for the given session ID, ordered
 * chronologically for timeline rendering. Handles both session.id and
 * llipe.session.id paths for resilience.
 */
export function buildSessionSpansQuery(sessionId: string): string {
  const fields = [
    `${backtickPath(SPAN_FIELDS.SESSION_ID)} as session_id`,
    `${backtickPath(SPAN_FIELDS.SESSION_ID_FALLBACK)} as session_id_fallback`,
    `${backtickPath(SPAN_FIELDS.SUBJECT_ID)} as subject_id`,
    `${backtickPath(SPAN_FIELDS.RUN_STATUS)} as run_status`,
    `${backtickPath(SPAN_FIELDS.OUTCOME_TYPE)} as outcome_type`,
    `${backtickPath(SPAN_FIELDS.OUTCOME_URL)} as outcome_url`,
    `${backtickPath(SPAN_FIELDS.MODEL_ID)} as model_id`,
    `${backtickPath(SPAN_FIELDS.TOKENS_IN)} as tokens_in`,
    `${backtickPath(SPAN_FIELDS.TOKENS_OUT)} as tokens_out`,
    `${backtickPath(SPAN_FIELDS.SERVICE_NAME)} as service_name`,
    `${SPAN_FIELDS.DURATION_NS} as duration_ns`,
    `${SPAN_FIELDS.TIMESTAMP} as start_time`,
    `${SPAN_FIELDS.PARENT_SPAN_ID} as parent_span_id`,
    `${SPAN_FIELDS.SPAN_NAME} as span_name`,
  ];

  // Filter by either session.id OR llipe.session.id to handle both paths
  const sessionFilter = [
    `${backtickPath(SPAN_FIELDS.SESSION_ID)} = '${sessionId}'`,
    `${backtickPath(SPAN_FIELDS.SESSION_ID_FALLBACK)} = '${sessionId}'`,
  ].join(" or ");

  const lines = [
    `fields ${fields.join(", ")}`,
    `| filter (${sessionFilter})`,
    `| sort @timestamp asc`,
    `| limit ${QUERY_LIMITS.SESSION_SPANS}`,
  ];

  return lines.join("\n");
}

/**
 * Wrap a dot-path in backticks for Logs Insights field reference syntax.
 * In Logs Insights, dots in field names must be backtick-escaped at each segment
 * that contains a dot in the original key name.
 *
 * For paths like "resource.attributes.session.id":
 * → resource.attributes.`session.id`
 *
 * For paths like "attributes.gen_ai.usage.input_tokens":
 * → attributes.`gen_ai.usage.input_tokens`
 */
function backtickPath(path: string): string {
  // Known structural prefixes — everything after these is a single attribute key
  const structuralPrefixes = ["resource.attributes.", "attributes."];

  for (const prefix of structuralPrefixes) {
    if (path.startsWith(prefix)) {
      const attributeKey = path.slice(prefix.length);
      // If the attribute key contains dots, backtick it
      if (attributeKey.includes(".")) {
        return `${prefix}\`${attributeKey}\``;
      }
      return path;
    }
  }

  // Top-level fields (duration, startTimeUnixNano, etc.) — no backticks needed
  return path;
}
