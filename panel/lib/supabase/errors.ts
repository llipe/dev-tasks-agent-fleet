/**
 * Shared error shape for the server-side data layer (spec §13).
 *
 * Any PostgREST/Supabase failure surfaces to callers as a `DatabaseError`
 * carrying the HTTP status `500` and a stable `code` of `DATABASE_ERROR`. The
 * underlying Postgres error code (e.g. `42501` insufficient-privilege) and the
 * raw message are captured for the **server log only** — they are held on
 * non-enumerable-in-response fields and MUST NOT be returned to a client, on
 * an app with no authentication in front of it (D16, EC-9). Route handlers log
 * `error.logDetail` and return only `{ code, status }` to the client.
 */

export const DATABASE_ERROR = "DATABASE_ERROR" as const;

export class DatabaseError extends Error {
  readonly code = DATABASE_ERROR;
  readonly status = 500;
  /** Postgres error code (e.g. "42501"), for the server log only. */
  readonly pgCode: string | undefined;
  /** Full underlying detail, for the server log only — never serialized to a client. */
  readonly logDetail: string;

  constructor(operation: string, cause?: unknown) {
    // Client-safe message: names the operation, never the Postgres detail.
    super(`Database read failed during "${operation}".`);
    this.name = "DatabaseError";

    const c = cause as { code?: string; message?: string; details?: string } | undefined;
    this.pgCode = c?.code;
    this.logDetail = [
      `operation=${operation}`,
      c?.code ? `pgCode=${c.code}` : undefined,
      c?.message ? `message=${c.message}` : undefined,
      c?.details ? `details=${c.details}` : undefined,
    ]
      .filter(Boolean)
      .join(" ");
  }
}

/**
 * Wraps a Supabase `{ data, error }` result: throws a `DatabaseError` when the
 * query errored, otherwise returns `data`. Centralizes the "log the pg code,
 * never return it" rule so every helper is consistent.
 */
export function unwrap<T>(operation: string, result: { data: T | null; error: unknown | null }): T {
  if (result.error) {
    throw new DatabaseError(operation, result.error);
  }
  // A successful read with no rows returns an empty array / null from
  // PostgREST depending on the call; callers normalize list vs single.
  return result.data as T;
}
