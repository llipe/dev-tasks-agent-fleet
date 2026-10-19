# ADR-009: Allowlisted AWS error logging on panel AWS failures

## Status

Accepted

## Context

`docs/technical-guidelines.md` §5 ("Front-end authentication against AWS")
documents the panel's AWS credential + invocation path and its security
contract: on a credential/OIDC/STS failure (`CREDENTIALS_UNAVAILABLE`, 500) or a
downstream `InvokeAgentRuntime` failure (`INVOCATION_FAILED`, 502), the panel
logs the coarse error *code* and `credentialSource()`, and **nothing ever logs
the token, the STS response, or the assumed-role credentials**.

Issue #306 (found during #280, D-09) recorded that this coarse code is not
enough to diagnose a production failure. An IAM `AccessDeniedException` on
`InvokeAgentRuntime` surfaced only as `INVOCATION_FAILED`, so the root cause
required a hand-built SigV4 replay from the Machine; the same wall was hit on the
`AssumeRoleWithWebIdentity` issuer mismatch. The 2026-10-19 11:00Z production
daily digest logged `send_failed` / `SES_SEND_FAILED` with no AWS error name for
the same reason (the 2026-10-19 scope addition to #306).

The underlying AWS SDK error already carries the fields that make each of these
a one-line diagnosis — the error `name` (e.g. `AccessDeniedException`,
`InvalidIdentityTokenException`), `$metadata.httpStatusCode`, and
`$metadata.requestId` (which lets AWS support / CloudTrail correlate). The
difficulty is logging those **without** widening the surface to the error
`message`, the invoke payload, the OIDC token, STS/credential material, or (on
the SES path) recipient/sender addresses and the email body — all of which the
SDK can echo into a `message` or response.

## Decision

Log the AWS error via a **strict allowlist**, implemented as a pure,
dependency-free helper `panel/lib/aws/aws-error.ts`:

- `describeAwsError(err)` returns **only** three fields: `aws_error` (the SDK
  error `name`, bounded to `[A-Za-z0-9_.:-]` and ≤100 chars — a generic or
  out-of-charset name collapses to `"unknown"`), `http` (`httpStatusCode`, kept
  only when it is an integer), and `request_id` (kept only when it is a
  bounded-charset string). A value is included **only** when present *and*
  matching its narrow shape; everything else is dropped. The error `message` is
  never read.
- It follows `cause` exactly **one level** (the panel wraps STS/invoke/SES
  failures in `CredentialsUnavailableError` / `InvocationFailedError` /
  `SesSendFailedError` with the original SDK error as `cause`, so the useful name
  lives one hop down), and it never throws.

The helper is wired into the `invoke.ts` error log lines and the `invoke_route`
/ `schedule_fire` `invocation_failed` and `notification_digest` `send_failed`
structured events.

**Explicitly unchanged:** the UI-facing run `error_message`, every HTTP response
body, and the 500-vs-502 error-code mapping. The allowlist is additive to the
**server log line only**.

The existing "no secrets logged" invariant is therefore preserved and tightened,
not relaxed: the new fields are a closed allowlist with bounded charsets, and
security-negative tests (a `SENTINEL-DO-NOT-LOG` message plus recipient/sender
sentinels) assert that no captured log line leaks any of them.

## Consequences

- A production AWS failure now names the AWS error, its HTTP status, and its
  request id in the logs — the #306 diagnosis goal — with no change to anything
  a user or an API consumer sees.
- The security contract in §5 is now accurate about what a failure log line
  contains. This ADR exists to satisfy the repository rule that **every
  modification to `docs/technical-guidelines.md` is accompanied by an ADR**
  (precedent: ADR-003), and to pin the allowlist as the enforceable control so a
  future change cannot quietly widen the logged surface to the message or the
  payload.
- No dependency changes; the helper is pure and unit-tested
  (`panel/tests/unit/aws-error.test.ts`) alongside wiring/security-negative
  tests on each consumer.
