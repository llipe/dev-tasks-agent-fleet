/**
 * SPAN_FIELDS — single point of change for field paths used in Logs Insights queries.
 * Initially placeholder; will be populated after S-012 telemetry verification.
 *
 * Keys are the logical field names used in the control plane;
 * values are the JSON/dot paths in the raw span log records.
 */

export const SPAN_FIELDS = {
  SESSION_ID: "resource.attributes.session.id",
  SUBJECT_ID: "resource.attributes.llipe.subject.id",
  RUN_STATUS: "resource.attributes.llipe.run.status",
  OUTCOME_TYPE: "resource.attributes.llipe.outcome.type",
  OUTCOME_URL: "resource.attributes.llipe.outcome.url",
  MODEL_ID: "attributes.gen_ai.request.model",
  TOKENS_IN: "attributes.gen_ai.usage.input_tokens",
  TOKENS_OUT: "attributes.gen_ai.usage.output_tokens",
  DURATION_NS: "duration",
  SERVICE_NAME: "resource.attributes.service.name",
  TIMESTAMP: "startTimeUnixNano",
} as const;

export type SpanFieldKey = keyof typeof SPAN_FIELDS;
export type SpanFieldPath = (typeof SPAN_FIELDS)[SpanFieldKey];
