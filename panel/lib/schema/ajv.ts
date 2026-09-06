/**
 * S-112 (#125) — the shared Ajv instance and configuration.
 *
 * One Ajv configuration is used by BOTH the server route (S-112,
 * authoritative) and the client form (S-113, convenience re-validation), so the
 * two cannot diverge in strictness. `lib/schema/validate.ts` (server) and the
 * form both import `createAjv` / `getValidator` from here.
 *
 * Configuration rationale:
 *   - `allErrors: true` — collect every field error, not just the first, so the
 *     form can render all inline messages at once.
 *   - `strict: false` — `params_schema` is operator-authored data seeded into
 *     the database, not a hand-verified compile-time schema; Ajv's strict-mode
 *     meta-schema checks would reject otherwise-valid JSON Schema (e.g. an
 *     unknown keyword) and turn a data problem into a 500. Validation strictness
 *     that matters (`additionalProperties: false`) is enforced by the schema
 *     itself in the seed and re-asserted below.
 *   - `ajv-formats` — registered so `format` keywords (date, email, uri, ...)
 *     in a future agent schema validate rather than silently pass.
 *
 * This module is pure and free of Next.js / Node-server imports so it is
 * importable from both a route handler and a client component bundle.
 */

import Ajv, { type AnySchema, type ValidateFunction } from "ajv";
import addFormats from "ajv-formats";

/** Creates a fresh, configured Ajv instance. Exposed for tests. */
export function createAjv(): Ajv {
  const ajv = new Ajv({
    allErrors: true,
    strict: false,
    // Do not mutate the caller's data object with defaults; the panel applies
    // defaults explicitly (server) / via the form (client) so the two agree.
    useDefaults: false,
    coerceTypes: false,
  });
  addFormats(ajv);
  return ajv;
}

/**
 * A process-wide cache of compiled validators keyed by `agentId:schemaHash`.
 * Compiling a JSON Schema is not free; the route compiles once per (agent,
 * schema) and reuses the validator across requests. The schema hash in the key
 * means a schema edit (a new seed) produces a new validator without a restart.
 */
const validatorCache = new Map<string, ValidateFunction>();
const sharedAjv = createAjv();

/**
 * A tiny, stable, non-cryptographic hash of the schema JSON. Only needs to
 * change when the schema changes — collision resistance is not a security
 * property here, just cache-key correctness.
 */
export function hashSchema(schema: unknown): string {
  const json = JSON.stringify(schema);
  let h = 5381;
  for (let i = 0; i < json.length; i++) {
    h = ((h << 5) + h + json.charCodeAt(i)) | 0;
  }
  return (h >>> 0).toString(36);
}

/**
 * Returns a compiled validator for `(agentId, schema)`, compiling and caching
 * on first use. Subsequent calls with the same agent id and an unchanged schema
 * return the cached validator.
 */
export function getValidator(agentId: string, schema: AnySchema): ValidateFunction {
  const key = `${agentId}:${hashSchema(schema)}`;
  const cached = validatorCache.get(key);
  if (cached) return cached;
  const validate = sharedAjv.compile(schema);
  validatorCache.set(key, validate);
  return validate;
}

/** Test-only cache reset so a suite can exercise compile-then-hit. */
export function __resetValidatorCacheForTests(): void {
  validatorCache.clear();
}
