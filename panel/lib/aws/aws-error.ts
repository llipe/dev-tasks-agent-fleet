/**
 * Issue #306 — extract the SAFE identifying fields of an AWS SDK error so a
 * production failure is a one-line diagnosis in the logs, without ever leaking
 * the error message, the payload, tokens, credentials, or recipient/sender
 * addresses.
 *
 * The AWS SDK v3 shapes a service error as `{ name, message, $metadata: {
 * httpStatusCode, requestId, ... } }`. We allowlist exactly three fields:
 *
 *   aws_error  — the error `name`, bounded to [A-Za-z0-9_.:-] and max 100 chars
 *                (so a malformed/injected `name` cannot smuggle content or break
 *                a log line). A name outside the charset is dropped to "unknown".
 *   http       — `$metadata.httpStatusCode`, kept ONLY when it is an integer.
 *   request_id — `$metadata.requestId`, kept ONLY when it is a bounded string.
 *
 * `message` is NEVER read — the SDK can echo request/response material (an
 * address, a token fragment, a payload field) into it. Everything here is an
 * allowlist: a value is included only when it is present AND matches its narrow
 * shape; otherwise it is omitted.
 *
 * The helper follows `cause` ONE level: the panel wraps STS/invoke failures in
 * `CredentialsUnavailableError` / `InvocationFailedError` with the original SDK
 * error as `cause`, so the useful name lives one hop down. It never recurses
 * past that single hop and never throws.
 *
 * This module MUST stay free of Next.js and AWS SDK imports so it is a pure,
 * trivially unit-testable function.
 */

/** The allowlisted, log-safe projection of an AWS error. */
export interface AwsErrorFields {
  /** The SDK error `name`, or `"unknown"` when absent/generic/out-of-charset. */
  aws_error: string;
  /** `$metadata.httpStatusCode`, present only when it is an integer. */
  http?: number;
  /** `$metadata.requestId`, present only when it is a bounded-charset string. */
  request_id?: string;
}

/** Bounded charset for the error `name` and `requestId` — no whitespace, no control chars. */
const SAFE_CHARSET = /^[A-Za-z0-9_.:-]+$/;
const MAX_NAME_LEN = 100;

/**
 * Error `name` values that carry no diagnostic signal — treated as unknown.
 * Includes the panel's OWN wrapper classes: their name just duplicates the
 * already-logged `code`, so when such a wrapper carries a `cause`, the useful
 * SDK name lives one hop down and `describeAwsError` should surface that.
 */
const GENERIC_NAMES = new Set([
  "Error",
  "TypeError",
  "",
  "Object",
  "CredentialsUnavailableError",
  "InvocationFailedError",
  "FlyOidcShapeError",
  "SesSendFailedError",
]);

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

/**
 * Extract a safe `name` from a single error object. Returns the bounded,
 * optionally truncated name, or `null` when it is absent, generic, or violates
 * the charset (so the caller can fall back or follow the cause).
 */
function safeName(err: Record<string, unknown>): string | null {
  const raw = err.name;
  if (typeof raw !== "string") return null;
  if (GENERIC_NAMES.has(raw)) return null;
  const truncated = raw.length > MAX_NAME_LEN ? raw.slice(0, MAX_NAME_LEN) : raw;
  // Validate the TRUNCATED value so a long name whose tail is unsafe is judged
  // on what we would actually log.
  if (!SAFE_CHARSET.test(truncated)) return null;
  return truncated;
}

/** Extract the safe `$metadata` fields from a single error object. */
function safeMetadata(err: Record<string, unknown>): { http?: number; request_id?: string } {
  const out: { http?: number; request_id?: string } = {};
  const meta = err.$metadata;
  if (!isRecord(meta)) return out;

  const status = meta.httpStatusCode;
  if (typeof status === "number" && Number.isInteger(status)) out.http = status;

  const reqId = meta.requestId;
  if (typeof reqId === "string" && reqId.length <= MAX_NAME_LEN && SAFE_CHARSET.test(reqId)) {
    out.request_id = reqId;
  }
  return out;
}

/**
 * Project `err` onto the allowlisted, log-safe fields. Pure, total, and never
 * throws. Follows `cause` exactly one level when the top-level error has no
 * usable name of its own (the panel's wrapped-error case).
 */
export function describeAwsError(err: unknown): AwsErrorFields {
  if (!isRecord(err)) return { aws_error: "unknown" };

  let name = safeName(err);
  let meta = safeMetadata(err);

  // Follow `cause` one level when the panel has wrapped the SDK error. Prefer
  // the cause's richer fields: its name (when the wrapper's is generic) and its
  // $metadata (when the wrapper carries none).
  if ((name === null || meta.http === undefined) && isRecord(err.cause)) {
    const causeName = safeName(err.cause);
    const causeMeta = safeMetadata(err.cause);
    if (name === null && causeName !== null) name = causeName;
    if (meta.http === undefined && meta.request_id === undefined) meta = causeMeta;
  }

  return { aws_error: name ?? "unknown", ...meta };
}

/**
 * Render the allowlisted fields as a `key=value` suffix for a text log line,
 * e.g. ` aws_error=AccessDeniedException http=403 request_id=r-1`. Absent
 * fields are omitted. Returned with a leading space so it appends cleanly.
 */
export function formatAwsErrorSuffix(fields: AwsErrorFields): string {
  const parts = [`aws_error=${fields.aws_error}`];
  if (fields.http !== undefined) parts.push(`http=${fields.http}`);
  if (fields.request_id !== undefined) parts.push(`request_id=${fields.request_id}`);
  return ` ${parts.join(" ")}`;
}
