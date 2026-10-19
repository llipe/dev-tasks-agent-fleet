# Implementation Plan - Issue #306: log the AWS error name on panel AWS failures

> Source: issue #306 body (ACs). One scope addition (2026-10-19): the **SES digest** path (`SES_SEND_FAILED`) gets the same treatment. Today's (2026-10-19 11:00Z) digest failure can't be diagnosed for the same reason. Single issue, so it runs through `developer` Execute Mode against `main`.

## Relevant Files

- `panel/lib/aws/aws-error.ts` - new: a pure helper that extracts `{ aws_error, http, request_id }` from an unknown error
- `panel/lib/aws/invoke.ts` - `[invoke] … failed` / `credentials unavailable` log lines
- `panel/lib/aws/credentials.ts` - STS / OIDC failure → `CredentialsUnavailableError` (keep the cause, so it is loggable)
- `panel/lib/aws/ses.ts` - `SesSendFailedError` (keep the cause)
- `panel/app/api/agents/[slug]/invoke/route.ts` - `invocation_failed` structured event
- `panel/app/api/internal/schedules/[id]/fire/route.ts` - `invocation_failed` structured event
- `panel/app/api/internal/notifications/digest/route.ts` - `send_failed` structured event
- `panel/tests/unit/aws-error.test.ts` - new
- existing tests: `invoke-route*.test.ts`, `credentials.test.ts`, `ses.test.ts`, digest/fire route tests

## Tasks

- [ ] 1.0 Implement Issue #306 - https://github.com/llipe/dev-tasks-agent-fleet/issues/306: log the AWS error name on INVOCATION_FAILED / CREDENTIALS_UNAVAILABLE / SES_SEND_FAILED

  - [ ] 1.1 [panel] Test-first: `tests/unit/aws-error.test.ts` for a pure `describeAwsError(err)`. An SDK-shaped error `{ name: "AccessDeniedException", $metadata: { httpStatusCode: 403, requestId: "r-1" } }` → `{ aws_error: "AccessDeniedException", http: 403, request_id: "r-1" }`. A plain `Error` or non-object → `{ aws_error: "unknown" }`, and the helper never throws. It follows `cause` one level (for errors the panel wraps). The output never contains `message`
  - [ ] 1.2 [panel] Implement `panel/lib/aws/aws-error.ts`. Allowlist only: the `name` string (bounded to `[A-Za-z0-9_.:-]`, max 100 chars), an integer `httpStatusCode`, and the `requestId` string (bounded charset)
  - [ ] 1.3 [panel] `invoke.ts`: append `aws_error=… http=… request_id=…` to both error log lines, using the cause for `CredentialsUnavailableError`
  - [ ] 1.4 [panel] `credentials.ts`: make every `CredentialsUnavailableError` thrown from STS or the OIDC socket carry the original error as `cause` (`FlyOidcShapeError` key names are already safe)
  - [ ] 1.5 [panel] `ses.ts`: confirm `SesSendFailedError` keeps `cause` (it does today)
  - [ ] 1.6 [panel] Add `aws_error`, `http`, `request_id` to the structured JSON events: `invoke_route` / `schedule_fire` `invocation_failed`, and `notification_digest` `send_failed`. The UI-facing `error_message` on the run and every HTTP response body stay **unchanged**
  - [ ] 1.7 [panel] Security-negative tests: in the invoke, fire, and digest route tests, throw an SDK-shaped error whose `message` contains a sentinel (`SENTINEL-DO-NOT-LOG`) and whose payload, token, or recipient contain sentinels. Assert that **no** captured log line contains any sentinel, and that `aws_error=` is present
  - [ ] 1.8 [panel] Unit test: a non-AWS error logs `aws_error=unknown` and the log path does not throw
  - [ ] 1.9 Verify AC1–AC6 of #306 (plus the SES addition): map each AC to a test in the PR body
  - [ ] 1.10 Run Tests: `source ~/.nvm/nvm.sh && nvm use 26`, then `pnpm --filter panel run validate` and `make validate`

## Decisions Consumed

| ID | Decision (short form) |
| -- | --------------------- |
