# ADR-001: Fly Machines OIDC is the only AWS credential path for the control plane

## Status

Accepted — 2026-08-25

## Context

`docs/technical-guidelines.md` §5 ("Machine identity") and §18 both recorded static AWS
access keys in Fly secrets as an approved fallback if OIDC "proves difficult":

> Static access keys in Fly secrets are the documented fallback, carrying the same minimal
> permissions.

Implementing [#60](https://github.com/llipe/dev-tasks-agent-fleet/issues/60) showed that
fallback cannot carry the same permissions, so the guideline was unsound as written.

The control plane's authority is not defined by its action list. It is defined by three
statements on `agent-fleet-control-plane-role` in `infra/lib/iam-stack.ts`:

- `dynamodb:UpdateItem` allowed only when every touched attribute is in
  `CONTROL_PLANE_WRITE_ATTRIBUTES` (`enabled`, `params`, plus keys)
- an explicit `Deny` on `bedrock-agentcore:InvokeAgentRuntime`
- an explicit `Deny` on writes to `last_*` attributes

Those are properties of a _role_. An IAM user with policies attached directly reproduces the
action list but not the conditions, unless every statement including both `Deny`s is
replicated by hand and kept in sync. §6 of the guidelines states that least privilege _is_
the scope boundary — PRD §3 exclusions are unreachable because the credential cannot express
them. A credential that can express them voids that boundary silently, with no test failing.

This is the same class of mistake already rejected once on this project, when granting the
agent runtime plain `dynamodb:UpdateItem` was proposed as a deployment shortcut
(`workstream/pending-deployments.md` Part 3).

Separately, `apps/control-plane/src/server/aws/credentials.ts` read `FLY_AWS_ROLE_ARN` and
`FLY_OIDC_TOKEN_PATH`. Neither is a real Fly variable, so the custom `fromWebToken` branch
never activated and the app fell through to a path labelled "local dev fallback" — meaning
the deployed application had no credentials at all while appearing to have a deliberate
OIDC implementation.

## Decision

**Fly Machines OIDC via `AssumeRoleWithWebIdentity` is the only supported AWS credential
path for the control plane. Static access keys are not an approved fallback.**

Three parts:

1. `infra/lib/iam-stack.ts` registers an `iam.OpenIdConnectProvider` for
   `https://oidc.fly.io/<org-slug>` with audience `sts.amazonaws.com`, and
   `agent-fleet-control-plane-role` is assumed by an `iam.WebIdentityPrincipal` conditioned
   on both `:aud` (`StringEquals`) and `:sub` (`StringLike`,
   `<org-slug>:<app-name>:*`). The prior `ecs-tasks.amazonaws.com` service principal — a
   leftover from an abandoned ECS design — is removed.

2. `AWS_ROLE_ARN` is set in `[env]` in `fly.toml`, not as a Fly secret. It is a role ARN,
   not a credential, and belongs where it is reviewable in git. Fly's `init` detects it and
   sets `AWS_WEB_IDENTITY_TOKEN_FILE` and `AWS_ROLE_SESSION_NAME`; these must never be set
   by hand.

3. `credentials.ts` delegates entirely to `fromNodeProviderChain()`. The custom provider is
   deleted rather than fixed.

The org slug in the provider URL **must** be the real slug from a live token's `iss` claim,
not the alias `fly orgs list` prints. `infra/test/iam-stack.test.ts` carries a regression
test asserting the alias never reappears in either the provider URL or the trust policy.

If a static-credential path is ever genuinely required, it is a new ADR, and its policy must
replicate every statement on the role — both `Deny`s included — and carry a removal ticket.

## Alternatives Considered

**Static IAM user access keys in Fly secrets** (the previously documented fallback).
Rejected: bypasses the `dynamodb:Attributes` conditions and the `InvokeAgentRuntime` deny,
which are the enforcement mechanism for PRD §3 scope exclusions. An inert IAM user
`fleet-control-plane-reader` was created during investigation with no policies and no access
keys, and was deleted as part of #60.

**Keep the custom `fromWebToken` provider, with corrected variable names.** Rejected: it
read the token file once at module import and passed the result as a string, so the token
was never re-read. Fly's OIDC tokens live roughly ten minutes and STS credentials expire in
fifteen. The default chain re-reads the token file on refresh, so deleting the code fixes a
second bug for free.

**Register the org slug reported by `fly orgs list` (`personal`).** Rejected on evidence:
that value is an alias. Tokens are issued by `https://oidc.fly.io/felipe-mallea`, so STS
found no provider matching the issuer and rejected every call with
`InvalidIdentityTokenException`. Discovery returns a valid document for _both_ slugs, so a
200 from the well-known endpoint does not confirm the choice.

## Consequences

**Positive.** The write-separation control in §6 of the guidelines is now enforced for the
control plane rather than assumed. No long-lived AWS credential exists for this app in any
system. Credential refresh is handled by the SDK. Deleting the custom provider removed the
dead code path that made the failure look like a permissions problem.

**Negative.** The credential path is now coupled to Fly's `init` behaviour, which is
documented but not contractual. Failures are hard to diagnose: `AssumeRoleWithWebIdentity`
failures are **not recorded in CloudTrail**, since there is no authenticated identity to
attribute them to, and `InvalidIdentityTokenException` names no cause. Mitigated by
`logCredentialDiagnostics()` in `credentials.ts`, which logs the token's `iss`, `aud`, `sub`,
`iat` and `exp` claims plus its length at startup — never the token itself.

**Follow-up actions.**

- Token refresh over long uptime is unverified. Fly's docs do not state whether `init`
  rewrites `/.fly/oidc_token` as the token ages; on a machine up longer than the token
  lifetime a refresh could read a stale token. Watch `fly logs` for `InvalidIdentityToken`
  after more than an hour of uptime. With `auto_stop_machines` enabled this may never
  surface.
- `AWS_WEB_IDENTITY_TOKEN_FILE` and `AWS_ROLE_SESSION_NAME` were confirmed present via the
  startup diagnostic, but not yet via `fly ssh console -C env`, which is blocked by
  corporate TLS interception on the operator's network. Re-run from an unproxied network to
  close #60 AC5 fully.

## Related

- Requirements: `docs/requirements/PRD-agent-control-plane-v1-en.md` §15
- Workstream: `workstream/tasks-issue-60-control-plane-iam.md`,
  `workstream/pending-deployments.md` (D7)
- Issue: [#60](https://github.com/llipe/dev-tasks-agent-fleet/issues/60)
- Code: `infra/lib/iam-stack.ts`, `infra/test/iam-stack.test.ts`,
  `apps/control-plane/src/server/aws/credentials.ts`, `fly.toml`
- Docs updated: `docs/technical-guidelines.md` §5, §18;
  `docs/runbook-deployment.md` §7
