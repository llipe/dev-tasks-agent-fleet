/**
 * Span-to-run field mapper.
 *
 * Extracts structured run data from raw OTEL span records as stored by ADOT
 * in CloudWatch. Handles root spans (run-level metadata) and gen_ai child spans
 * (model invocation details) separately.
 *
 * Root span identification:
 *   - `parentSpanId` is empty string or absent
 *   - Has `resource.attributes["llipe.run.status"]` present
 *
 * Gen AI child span identification:
 *   - `parentSpanId` is populated (non-empty)
 *   - Has `attributes["gen_ai.request.model"]` present
 */

import { SPAN_FIELDS } from "./span-fields.js";
import { resolveFieldPath, resolveSessionId } from "./span-session-resolver.js";

/**
 * Mapped fields from a root span representing a complete run.
 */
export interface MappedRunFields {
  sessionId: string;
  subjectId: string;
  runStatus: string;
  outcomeType: string;
  outcomeUrl: string;
  serviceName: string;
  durationNs: number;
  timestamp: string;
}

/**
 * Mapped fields from a gen_ai child span representing a model invocation.
 */
export interface MappedGenAiFields {
  sessionId: string;
  modelId: string;
  tokensIn: number;
  tokensOut: number;
  durationNs: number;
  timestamp: string;
}

/**
 * Determine if a span is a root span.
 * Root spans have empty/absent parentSpanId AND contain llipe.run.status.
 */
export function isRootSpan(span: Record<string, unknown>): boolean {
  const parentSpanId = resolveFieldPath(span, SPAN_FIELDS.PARENT_SPAN_ID);
  if (parentSpanId !== "" && parentSpanId !== undefined && parentSpanId !== null) {
    // Non-empty parentSpanId means this is a child
    if (typeof parentSpanId === "string" && parentSpanId.length > 0) {
      return false;
    }
  }

  // Must have llipe.run.status to be considered a root span
  const runStatus = resolveFieldPath(span, SPAN_FIELDS.RUN_STATUS);
  return typeof runStatus === "string" && runStatus.length > 0;
}

/**
 * Determine if a span is a gen_ai child span.
 * Must have non-empty parentSpanId AND gen_ai.request.model attribute.
 */
export function isGenAiChildSpan(span: Record<string, unknown>): boolean {
  const parentSpanId = resolveFieldPath(span, SPAN_FIELDS.PARENT_SPAN_ID);
  if (typeof parentSpanId !== "string" || parentSpanId.length === 0) {
    return false;
  }

  const modelId = resolveFieldPath(span, SPAN_FIELDS.MODEL_ID);
  return typeof modelId === "string" && modelId.length > 0;
}

/**
 * Map a root span to run-level fields.
 * Returns null if the span is not a root span or if required fields are missing.
 */
export function mapSpanToRunFields(span: Record<string, unknown>): MappedRunFields | null {
  if (!isRootSpan(span)) return null;

  const sessionId = resolveSessionId(span);
  if (!sessionId) return null;

  const subjectId = resolveFieldPath(span, SPAN_FIELDS.SUBJECT_ID);
  const runStatus = resolveFieldPath(span, SPAN_FIELDS.RUN_STATUS);
  const outcomeType = resolveFieldPath(span, SPAN_FIELDS.OUTCOME_TYPE);
  const outcomeUrl = resolveFieldPath(span, SPAN_FIELDS.OUTCOME_URL);
  const serviceName = resolveFieldPath(span, SPAN_FIELDS.SERVICE_NAME);
  const durationNs = resolveFieldPath(span, SPAN_FIELDS.DURATION_NS);
  const timestamp = resolveFieldPath(span, SPAN_FIELDS.TIMESTAMP);

  if (typeof subjectId !== "string") return null;
  if (typeof runStatus !== "string") return null;
  if (typeof serviceName !== "string") return null;

  return {
    sessionId,
    subjectId,
    runStatus,
    outcomeType: typeof outcomeType === "string" ? outcomeType : "",
    outcomeUrl: typeof outcomeUrl === "string" ? outcomeUrl : "",
    serviceName,
    durationNs: typeof durationNs === "number" ? durationNs : 0,
    timestamp: typeof timestamp === "string" ? timestamp : "",
  };
}

/**
 * Map a gen_ai child span to model invocation fields.
 * Returns null if the span is not a gen_ai child span or required fields are missing.
 */
export function mapSpanToGenAiFields(span: Record<string, unknown>): MappedGenAiFields | null {
  if (!isGenAiChildSpan(span)) return null;

  const sessionId = resolveSessionId(span);
  if (!sessionId) return null;

  const modelId = resolveFieldPath(span, SPAN_FIELDS.MODEL_ID);
  const tokensIn = resolveFieldPath(span, SPAN_FIELDS.TOKENS_IN);
  const tokensOut = resolveFieldPath(span, SPAN_FIELDS.TOKENS_OUT);
  const durationNs = resolveFieldPath(span, SPAN_FIELDS.DURATION_NS);
  const timestamp = resolveFieldPath(span, SPAN_FIELDS.TIMESTAMP);

  if (typeof modelId !== "string") return null;

  return {
    sessionId,
    modelId,
    tokensIn: typeof tokensIn === "number" ? tokensIn : 0,
    tokensOut: typeof tokensOut === "number" ? tokensOut : 0,
    durationNs: typeof durationNs === "number" ? durationNs : 0,
    timestamp: typeof timestamp === "string" ? timestamp : "",
  };
}
