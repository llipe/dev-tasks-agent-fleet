/**
 * Session ID resolution from span records.
 *
 * Strategy:
 * 1. Primary: `resource.attributes["session.id"]` (AgentCore may inject this automatically)
 * 2. Fallback: `resource.attributes["llipe.session.id"]` (explicitly emitted by the agent)
 *
 * If neither is present, returns undefined — the caller must handle missing session IDs.
 *
 * Decision: We emit BOTH `session.id` and `llipe.session.id` from the agent (see emission.py)
 * so that regardless of whether AgentCore injects its own `session.id`, we always have a
 * deterministic value to query by.
 */

import { SPAN_FIELDS } from "./span-fields.js";

/**
 * The two paths checked in priority order for session ID resolution.
 */
export const SESSION_ID_PATHS = [
  SPAN_FIELDS.SESSION_ID, // "resource.attributes.session.id"
  SPAN_FIELDS.SESSION_ID_FALLBACK, // "resource.attributes.llipe.session.id"
] as const;

/**
 * Resolve a nested dot-path on a span record.
 *
 * OTEL span records use literal dots in attribute keys (e.g., "session.id",
 * "gen_ai.usage.input_tokens"). The path format uses dots as BOTH structural
 * separators AND part of attribute key names.
 *
 * Resolution strategy (greedy match):
 * Try the longest possible key at each level first (greedy), falling back to
 * shorter prefixes. This correctly resolves both:
 * - "resource.attributes.session.id" → resource → attributes → "session.id"
 * - "attributes.gen_ai.usage.input_tokens" → attributes → "gen_ai.usage.input_tokens"
 */
export function resolveFieldPath(span: Record<string, unknown>, path: string): unknown {
  return resolveGreedy(span, path.split("."), 0);
}

function resolveGreedy(current: unknown, segments: string[], start: number): unknown {
  if (start >= segments.length) return current;
  if (current === null || current === undefined) return undefined;
  if (typeof current !== "object") return undefined;

  const obj = current as Record<string, unknown>;

  // Try progressively longer key fragments (greedy: longest first)
  for (let end = segments.length; end > start; end--) {
    const key = segments.slice(start, end).join(".");
    if (key in obj) {
      const result = resolveGreedy(obj[key], segments, end);
      if (result !== undefined) return result;
    }
  }

  return undefined;
}

/**
 * Extract session ID from a span record, trying primary then fallback path.
 * Returns undefined if neither path resolves to a non-empty string.
 */
export function resolveSessionId(span: Record<string, unknown>): string | undefined {
  for (const path of SESSION_ID_PATHS) {
    const value = resolveFieldPath(span, path);
    if (typeof value === "string" && value.length > 0) {
      return value;
    }
  }
  return undefined;
}
