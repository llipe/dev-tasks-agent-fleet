/**
 * SPAN_FIELDS — single point of change for field paths used in Logs Insights queries.
 *
 * Populated with EXPECTED paths based on OTEL/ADOT documentation (S-012).
 * Status: PENDING LIVE VERIFICATION — paths are derived from:
 *   - OpenTelemetry Span data model (resource.attributes.*, attributes.*)
 *   - AWS ADOT CloudWatch exporter conventions
 *   - AgentCore span emission behavior
 *
 * Keys are the logical field names used in the control plane;
 * values are the JSON/dot paths in the raw span log records.
 *
 * Root span identification:
 *   - `parentSpanId` is empty string or absent
 *   - Has `llipe.*` resource attributes (specifically `llipe.run.status`)
 *
 * Child span (gen_ai) identification:
 *   - `parentSpanId` is populated
 *   - Has `gen_ai.*` attributes (model, tokens)
 *   - Token usage (`gen_ai.usage.*`) is on child spans, NOT root
 */

export const SPAN_FIELDS = {
  /** Primary session ID path (AgentCore-injected) */
  SESSION_ID: "resource.attributes.session.id",
  /** Fallback session ID path (explicitly emitted by agent) */
  SESSION_ID_FALLBACK: "resource.attributes.llipe.session.id",
  /** Normalized subject identifier (owner/repo) */
  SUBJECT_ID: "resource.attributes.llipe.subject.id",
  /** Run outcome status: "success" | "failed" */
  RUN_STATUS: "resource.attributes.llipe.run.status",
  /** Outcome type: "pr" | "none" */
  OUTCOME_TYPE: "resource.attributes.llipe.outcome.type",
  /** Outcome URL (PR link or empty string) */
  OUTCOME_URL: "resource.attributes.llipe.outcome.url",
  /** Model ID used in gen_ai call (child spans only) */
  MODEL_ID: "attributes.gen_ai.request.model",
  /** Input token count (child spans only) */
  TOKENS_IN: "attributes.gen_ai.usage.input_tokens",
  /** Output token count (child spans only) */
  TOKENS_OUT: "attributes.gen_ai.usage.output_tokens",
  /** Span duration in nanoseconds */
  DURATION_NS: "duration",
  /** Agent service name */
  SERVICE_NAME: "resource.attributes.service.name",
  /** Span start time in Unix nanoseconds */
  TIMESTAMP: "startTimeUnixNano",
  /** Parent span ID — empty/absent for root spans */
  PARENT_SPAN_ID: "parentSpanId",
  /** Span name */
  SPAN_NAME: "name",
} as const;

export type SpanFieldKey = keyof typeof SPAN_FIELDS;
export type SpanFieldPath = (typeof SPAN_FIELDS)[SpanFieldKey];
