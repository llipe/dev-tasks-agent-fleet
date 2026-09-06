/**
 * S-112 (#125) — the panel API error taxonomy and client-facing error shape
 * (spec §13).
 *
 * Every error the invoke route returns to the client is serialized as:
 *
 *     { error: { code, message, details? } }
 *
 * `code` is a stable machine-readable string the form (S-113) branches on
 * (inline per-field vs. banner). `message` is a human-readable, secret-free
 * summary. `details` is optional and MUST NOT carry secrets, Postgres codes,
 * STS responses, or tokens — those go to the server log only.
 *
 * The codes are shared across modules rather than redefined:
 *   - `CREDENTIALS_UNAVAILABLE` / `INVOCATION_FAILED` come from
 *     `lib/aws/errors.ts` (S-111) and are re-exported here so the route has a
 *     single import site.
 *   - `MALFORMED_REPOSITORY` comes from `lib/domain/payload.ts`.
 *   - `DATABASE_ERROR` comes from `lib/supabase/errors.ts` (S-104).
 *   - `INVALID_PARAMS` is defined here (the Ajv rejection code).
 *
 * HTTP status mapping (spec §13):
 *   MALFORMED_REPOSITORY     400  (client sent a bad repository)
 *   INVALID_PARAMS           400  (params failed the schema)
 *   CREDENTIALS_UNAVAILABLE  500  (panel could not obtain AWS credentials)
 *   INVOCATION_FAILED        502  (InvokeAgentRuntime threw downstream)
 *   DATABASE_ERROR           500  (a PostgREST/insert failure)
 */

import { CREDENTIALS_UNAVAILABLE, INVOCATION_FAILED } from "@/lib/aws/errors";
import { DATABASE_ERROR } from "@/lib/supabase/errors";
import { MALFORMED_REPOSITORY } from "@/lib/domain/payload";

export { CREDENTIALS_UNAVAILABLE, INVOCATION_FAILED, DATABASE_ERROR, MALFORMED_REPOSITORY };

/** Ajv rejected `params` against `agents.params_schema`. */
export const INVALID_PARAMS = "INVALID_PARAMS" as const;

/** The full set of codes the invoke route can return. */
export type ApiErrorCode =
  | typeof MALFORMED_REPOSITORY
  | typeof INVALID_PARAMS
  | typeof CREDENTIALS_UNAVAILABLE
  | typeof INVOCATION_FAILED
  | typeof DATABASE_ERROR;

/** The serialized error body returned to the client. */
export interface ApiErrorBody {
  error: {
    code: string;
    message: string;
    /** Optional, secret-free structured detail (e.g. per-field validation errors). */
    details?: unknown;
  };
}

/**
 * Base class for a panel API error. Carries a client-safe `code`, `status`, and
 * `message`, plus an optional `details` payload that MUST be secret-free. A
 * separate `logDetail` (never serialized) holds anything sensitive for the
 * server log.
 */
export class ApiError extends Error {
  readonly code: string;
  readonly status: number;
  readonly details: unknown | undefined;
  /** Server-log-only detail; never serialized to a client. */
  readonly logDetail: string | undefined;

  constructor(
    code: string,
    status: number,
    message: string,
    options?: { details?: unknown; logDetail?: string; cause?: unknown },
  ) {
    super(message, options?.cause !== undefined ? { cause: options.cause } : undefined);
    this.name = "ApiError";
    this.code = code;
    this.status = status;
    this.details = options?.details;
    this.logDetail = options?.logDetail;
  }

  /** The client-safe serialized body. Never includes `logDetail`. */
  toBody(): ApiErrorBody {
    return {
      error: {
        code: this.code,
        message: this.message,
        ...(this.details !== undefined ? { details: this.details } : {}),
      },
    };
  }
}

/** `INVALID_PARAMS` (400) — carries the Ajv per-field errors as `details`. */
export class InvalidParamsError extends ApiError {
  constructor(details: unknown) {
    super(INVALID_PARAMS, 400, "The provided params did not match the agent's schema.", {
      details,
    });
    this.name = "InvalidParamsError";
  }
}

/**
 * Narrows an arbitrary thrown value to an `{ code, status, message }` shape when
 * it looks like one of the app's typed errors (`ApiError`, the AWS errors, the
 * `DatabaseError`, or `MalformedRepositoryError`). Returns `null` otherwise so
 * the caller can fall back to a generic 500 without leaking the raw error.
 */
export function asTypedError(
  err: unknown,
): { code: string; status: number; message: string; details?: unknown; logDetail?: string } | null {
  if (
    typeof err === "object" &&
    err !== null &&
    "code" in err &&
    "status" in err &&
    typeof (err as { code: unknown }).code === "string" &&
    typeof (err as { status: unknown }).status === "number"
  ) {
    const e = err as {
      code: string;
      status: number;
      message?: string;
      details?: unknown;
      logDetail?: string;
    };
    return {
      code: e.code,
      status: e.status,
      message: e.message ?? "Request failed.",
      details: e.details,
      logDetail: e.logDetail,
    };
  }
  return null;
}
