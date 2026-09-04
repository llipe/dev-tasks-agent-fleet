/**
 * Error taxonomy for the AWS credential + invocation path (spec §13).
 *
 * Two failures are deliberately kept distinct because their runbooks differ
 * (R6): "the panel could not obtain credentials" is not the same problem as
 * "AgentCore rejected the call". Conflating them sends the operator to the
 * wrong runbook.
 *
 *   CREDENTIALS_UNAVAILABLE (500) — STS or the Fly OIDC socket failed. The
 *                                   panel never got usable credentials.
 *   INVOCATION_FAILED       (502) — `InvokeAgentRuntime` itself threw. The
 *                                   panel had credentials but the downstream
 *                                   call failed.
 *
 * Neither error carries a token, an STS response, or assumed-role credentials.
 * Messages name error codes and, for the OIDC-shape case, the *keys* received
 * — never their values.
 */

export const CREDENTIALS_UNAVAILABLE = "CREDENTIALS_UNAVAILABLE" as const;
export const INVOCATION_FAILED = "INVOCATION_FAILED" as const;

/**
 * The Fly OIDC socket returned a body whose shape we do not recognize — no
 * `value` and no `token` string. Thrown instead of silently forwarding some
 * other field (e.g. the audience) to STS as a web-identity token, which would
 * produce a misleading downstream auth error. This is the F5 fix: the message
 * names the keys actually received so a first-deploy shape mismatch (SR1/OQ1)
 * is a one-line diagnosis rather than a confusing STS rejection.
 *
 * The message contains only the *key names* of the parsed body, never the
 * values, so no token material can leak into a log line.
 */
export class FlyOidcShapeError extends Error {
  readonly code = CREDENTIALS_UNAVAILABLE;
  /** HTTP status a route handler should surface for this failure. */
  readonly status = 500;
  /** The key names observed in the socket response (values never included). */
  readonly receivedKeys: readonly string[];

  constructor(receivedKeys: readonly string[], detail?: string) {
    const keyList = receivedKeys.length > 0 ? receivedKeys.join(", ") : "(none)";
    super(
      `Fly OIDC token response had an unrecognized shape: expected a string "value" or "token" ` +
        `field, received keys [${keyList}]${detail ? ` (${detail})` : ""}.`,
    );
    this.name = "FlyOidcShapeError";
    this.receivedKeys = receivedKeys;
  }
}

/**
 * The panel could not obtain AWS credentials — a Fly OIDC socket failure, an
 * STS `AssumeRoleWithWebIdentity` rejection, or a missing configuration value
 * (e.g. the role ARN). Distinct from `InvocationFailedError` (502) so the
 * operator reads the credential runbook, not the invocation runbook (R6).
 *
 * The `cause` is retained for the server log only; it is not serialized to a
 * client. Callers log `error.code` (+ `credentialSource()`), never the cause's
 * contents, to keep token/STS material out of logs.
 */
export class CredentialsUnavailableError extends Error {
  readonly code = CREDENTIALS_UNAVAILABLE;
  readonly status = 500;

  constructor(message: string, options?: { cause?: unknown }) {
    super(message, options);
    this.name = "CredentialsUnavailableError";
  }
}

/**
 * `InvokeAgentRuntime` threw after credentials were successfully obtained.
 * Surfaced as 502 (a downstream/upstream failure), explicitly separate from
 * `CredentialsUnavailableError` (500). The route handler that consumes this
 * (S-112) navigates to the run detail, which shows `failed_to_start`.
 */
export class InvocationFailedError extends Error {
  readonly code = INVOCATION_FAILED;
  readonly status = 502;

  constructor(message: string, options?: { cause?: unknown }) {
    super(message, options);
    this.name = "InvocationFailedError";
  }
}
