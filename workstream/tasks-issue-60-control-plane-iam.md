# Implementation Plan - Control-Plane IAM (Fly OIDC + CloudWatch Logs)

Source issue: [#60](https://github.com/llipe/dev-tasks-agent-fleet/issues/60)
Blocks: `workstream/pending-deployments.md` item 16 (Fly deploy)

## Resolved unknown — Fly OIDC mechanism

Confirmed from <https://fly.io/docs/security/openid-connect/> and
<https://fly.io/blog/oidc-cloud-roles/>. No application code is needed:

1. Fly's `init` sees `AWS_ROLE_ARN` at boot.
2. It fetches an OIDC token over the `/.fly/api` unix socket (`POST /v1/tokens/oidc`) with
   `aud: sts.amazonaws.com`.
3. It writes it to `/.fly/oidc_token`.
4. It sets `AWS_WEB_IDENTITY_TOKEN_FILE` and `AWS_ROLE_SESSION_NAME`.
5. The AWS SDK default credential chain does the `AssumeRoleWithWebIdentity` call.

Concrete values for this app (org slug confirmed with `fly orgs list`):

| Item          | Value                                                  |
| ------------- | ------------------------------------------------------ |
| Provider URL  | `https://oidc.fly.io/personal`                         |
| Audience      | `sts.amazonaws.com`                                    |
| `sub` pattern | `personal:dt-agent-fleet-control-plane:*` (StringLike) |

Consequence: `credentials.ts` is **deleted down**, not extended. `FLY_OIDC_TOKEN_PATH` and
`FLY_AWS_ROLE_ARN` are invented names Fly never sets; `fromNodeProviderChain()` replaces the
whole custom branch and fixes the token-refresh bug as a side effect.

## Relevant Files

- `infra/lib/iam-stack.ts` - Fly OIDC provider, control-plane role trust, `logs:` + `tag:` statements
- `infra/test/iam-stack.test.ts` - Assertions for trust policy and new grants, plus negative assertions
- `apps/control-plane/src/server/aws/credentials.ts` - Replace custom provider with `fromNodeProviderChain()`
- `apps/control-plane/src/server/aws/credentials.test.ts` - New; asserts the default chain is used
- `fly.toml` - Add `AWS_ROLE_ARN` to `[env]` (relocated from `infra/control-plane.fly.toml` so the Dockerfile build context resolves)
- `docs/runbook-deployment.md` - Remove the §7 blocking notice once deployed
- `workstream/pending-deployments.md` - Status board items 16 and 17 (D7)

## Tasks

- [ ] 1.0 Implement Issue [#60](https://github.com/llipe/dev-tasks-agent-fleet/issues/60): control-plane role needs Fly OIDC trust and CloudWatch Logs grants

  > Note: Write separation is the controlling constraint. DynamoDB writes must stay conditioned on `CONTROL_PLANE_WRITE_ATTRIBUTES` and `bedrock-agentcore:InvokeAgentRuntime` must stay explicitly denied. Granting anything broader repeats the mistake rejected in #56.

  - [x] 1.1 Write failing assertions in `infra/test/iam-stack.test.ts` for the Fly OIDC provider: URL `https://oidc.fly.io/personal`, client ID `sts.amazonaws.com`
  - [x] 1.2 Write failing assertions for the control-plane role trust policy: `Federated` principal on that provider, `sts:AssumeRoleWithWebIdentity`, `StringEquals` on `oidc.fly.io/personal:aud`, `StringLike` on `oidc.fly.io/personal:sub`
  - [x] 1.3 Write failing assertions for the `logs:` statement: exactly `StartQuery`, `GetQueryResults`, `StopQuery`, `FilterLogEvents`, scoped to the `aws/spans` and `/aws/bedrock-agentcore/runtimes/depupdater_dep_updater*` group ARNs
  - [x] 1.4 Write failing assertions for `tag:GetResources` on `Resource: "*"` (the API does not support resource-level permissions)
  - [x] 1.5 Write failing negative assertions: no `logs:DescribeLogGroups`, no unconditioned `dynamodb:UpdateItem`, `DenyInvokeAgentRuntime` still present, DynamoDB write condition still references `CONTROL_PLANE_WRITE_ATTRIBUTES`, and `ecs-tasks.amazonaws.com` no longer trusted
  - [x] 1.6 Implement in `infra/lib/iam-stack.ts`: add `iam.OpenIdConnectProvider`, change `assumedBy` to `iam.WebIdentityPrincipal` with both conditions, add the `logs:` and `tag:` statements. Run `pnpm run test` in `infra` until 1.1–1.5 pass
  - [x] 1.7 Write a failing test in `apps/control-plane/src/server/aws/credentials.test.ts` asserting the exported provider resolves via the SDK default chain (web-identity file honoured, no reference to `FLY_*` variables)
  - [x] 1.8 Replace `createCredentialsProvider()` in `credentials.ts` with `fromNodeProviderChain()`; delete the `readFileSync` import and the `FLY_OIDC_TOKEN_PATH` / `FLY_AWS_ROLE_ARN` reads
  - [x] 1.9 Add `AWS_ROLE_ARN = "arn:aws:iam::755641879575:role/agent-fleet-control-plane-role"` to `[env]` in `fly.toml`
  - [x] 1.10 Run `pnpm run cdk diff AgentFleetIamStack` and review: the diff must add one OIDC provider, replace the control-plane role trust, and add two policy statements — nothing else
  - [x] 1.11 Deploy: `cd infra && pnpm run cdk deploy AgentFleetIamStack`
  - [x] 1.12 Remove the staged static keys: `fly secrets unset AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY --app dt-agent-fleet-control-plane`
  - [x] 1.13 Delete the inert investigation artifact: IAM user `fleet-control-plane-reader` (no policies, no keys)
  - [x] 1.14 Verify Acceptance Criterion 1: `aws iam get-role --role-name agent-fleet-control-plane-role` shows the `Federated` principal for `oidc.fly.io/personal` with both claim conditions, and no `ecs-tasks` principal
  - [x] 1.15 Verify Acceptance Criterion 2: role grants exactly the four Logs actions on the two ARN patterns, plus `tag:GetResources`, and no `DescribeLogGroups`
  - [x] 1.16 Verify Acceptance Criterion 3: DynamoDB writes still attribute-conditioned; `InvokeAgentRuntime` still denied — confirm on the live role, not only in the template
  - [x] 1.17 Verify Acceptance Criterion 4: `pnpm run test` in `infra` passes and fails if any grant is reverted (mutate locally to confirm, then revert)
  - [x] 1.18 Verify Acceptance Criterion 5: **partial.** `AWS_ROLE_ARN` confirmed live in the deployed machine config (`fly machine status --display-config`). `AWS_WEB_IDENTITY_TOKEN_FILE` and `AWS_ROLE_SESSION_NAME` are injected by Fly's `init` inside the machine and are only observable via `fly ssh console`, which fails from this network with `websocket: failed to WebSocket dial: expected handshake response status code 101 but got 502` (corporate proxy). Re-run `fly ssh console --app dt-agent-fleet-control-plane -C env | grep AWS_` from an unproxied network to close this out
  - [ ] 1.19 Verify Acceptance Criterion 6: **needs a browser.** The `fleet.llipe.com` certificate was issued 2026-08-25 and Cloudflare Access now intercepts correctly (`/agents` → 302 to `round-mouse-afcf.cloudflareaccess.com`), so the path is open. Complete an Access login, load `https://fleet.llipe.com/agents`, and confirm the agents list renders with no `AccessDeniedException` in `fly logs` for `StartQuery`, `GetQueryResults`, `FilterLogEvents` or `GetResources`. Verifies authorization, not data presence — an empty-but-successful runs view passes. Expect `dep-updater` three times (#61) and an empty runs view (#62); neither is an IAM failure. If the login succeeds but the app returns 401, check that `CF_ACCESS_TEAM_NAME` is exactly `round-mouse-afcf`
  - [x] 1.20 Verify Acceptance Criterion 7: `fly secrets list` shows no `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY`
  - [x] 1.21 Run Tests: `pnpm run test` (unit + integration, workspace root)
  - [x] 1.22 Run quality gates and record results: `pnpm run lint`, `pnpm run format:check`, `pnpm run typecheck`, `pnpm run audit`, `pnpm run validate`
  - [ ] 1.23 Observe the machine for over an hour and check `fly logs` for `InvalidIdentityToken` — the docs do not state whether `init` rewrites `/.fly/oidc_token` as it ages. Record the finding; open a follow-up issue if refresh is needed
  - [ ] 1.24 Update `docs/runbook-deployment.md`: remove the §7 blocking notice, fold the resolved gaps into §15, update item 16 state in §1
  - [ ] 1.25 Update `workstream/pending-deployments.md` status board items 16 and 17
  - [ ] 1.26 Invoke `verifier` in audit mode and post the summary to #60
  - [ ] 1.27 Invoke `technical-writer` for the documentation pass and drift validation

## Notes

- No schema or data-model change, so no migration tasks. The only stateful resource touched is an IAM role.
- **Sibling issues, independent of this one:** #61 (agent inventory returns three duplicate entries per agent) and #62 (`aws/spans` is empty because no OTEL exporter is installed). Both become visible the moment this issue's grants land, and neither is an IAM failure. AC6 is deliberately scoped to authorization only for that reason.
- `tag:GetResources` is the grant that fails first: `listManagedAgents()` discovers agents by the `agent:managed=true` tag filter, so without it the agents list is empty and no other view has anything to render. The tags are already live on the runtime.
- `AGENT_LOG_GROUP` must be refreshed after any `agentcore deploy` that recreates the runtime. The wildcard in the logs ARN pattern means the IAM grant survives that; the Fly secret does not.
- Changing `assumedBy` on an existing role is an in-place trust-policy update, not a replacement — the role ARN is stable, so no dependent references break.
