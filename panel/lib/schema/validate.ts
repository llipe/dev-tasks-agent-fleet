/**
 * S-112 (#125) — server-authoritative `params` validation (security-negative
 * #3, AC5/AC13).
 *
 * Validates a submitted `params` object against an agent's `params_schema`
 * using the shared Ajv config (`lib/schema/ajv.ts`). The seeded schemas declare
 * `additionalProperties: false`, so an unexpected key is rejected — and because
 * we build the outgoing agent payload only from schema-present keys (below), a
 * key that somehow slipped past is still never forwarded.
 *
 * The route calls `validateParams` BEFORE generating a `run_id` or inserting a
 * `runs` row, so an invalid submission leaves no database trace (AC13).
 */

import type { AnySchema } from "ajv";
import { getValidator } from "@/lib/schema/ajv";

export interface ParamsValidationOk {
  valid: true;
  /** The params projected to schema-present keys only (never extra keys). */
  params: Record<string, unknown>;
}

export interface ParamsValidationError {
  valid: false;
  /** Ajv error objects, safe to return to the client (no secrets). */
  errors: Array<{ instancePath: string; message: string; keyword: string }>;
}

export type ParamsValidationResult = ParamsValidationOk | ParamsValidationError;

/** The property names declared on a JSON-Schema object, or `[]` if none. */
function schemaPropertyNames(schema: AnySchema): string[] {
  if (
    typeof schema === "object" &&
    schema !== null &&
    "properties" in schema &&
    typeof (schema as { properties?: unknown }).properties === "object" &&
    (schema as { properties?: unknown }).properties !== null
  ) {
    return Object.keys((schema as { properties: Record<string, unknown> }).properties);
  }
  return [];
}

/**
 * Validates `input` against `schema` for the given agent. On success returns
 * the params projected to schema-present keys only (belt-and-braces against
 * `additionalProperties` even if a schema omitted it). On failure returns the
 * Ajv errors, which the route wraps in `InvalidParamsError` (400) and the form
 * renders inline per field.
 *
 * A non-object `input` (null, array, scalar) is rejected — `params` is always
 * an object.
 */
export function validateParams(
  agentId: string,
  schema: AnySchema,
  input: unknown,
): ParamsValidationResult {
  if (typeof input !== "object" || input === null || Array.isArray(input)) {
    return {
      valid: false,
      errors: [{ instancePath: "", message: "params must be an object", keyword: "type" }],
    };
  }

  const validate = getValidator(agentId, schema);
  const ok = validate(input);

  if (!ok) {
    const errors = (validate.errors ?? []).map((e) => ({
      instancePath: e.instancePath,
      message: e.message ?? "is invalid",
      keyword: e.keyword,
    }));
    return { valid: false, errors };
  }

  // Project to schema-present keys only. If the schema declares no properties
  // (e.g. an empty `{}` schema), pass the validated object through unchanged.
  const allowed = schemaPropertyNames(schema);
  const source = input as Record<string, unknown>;
  if (allowed.length === 0) {
    return { valid: true, params: { ...source } };
  }
  const projected: Record<string, unknown> = {};
  for (const key of allowed) {
    if (key in source) projected[key] = source[key];
  }
  return { valid: true, params: projected };
}
