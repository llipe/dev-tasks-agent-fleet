# Implementation Plan — Issue #56 Deployment correctness fixes + GitHub App migration

Source: `workstream/pending-deployments.md` (defects D1, D2, D3) plus the PAT → GitHub App migration.
GitHub Issue: https://github.com/llipe/dev-tasks-agent-fleet/issues/56
Base branch: `integration/acp-v1-control-plane`

## Relevant Files

- `agents/dep-updater/agentcore/cdk/lib/fleet-iam-attributes.ts` — drift-guarded mirror of the `@fleet/shared` IAM allowlists for the vended CDK app
- `agents/dep-updater/agentcore/cdk/lib/cdk-stack.ts` — grants the AgentCore runtime execution role its data-plane permissions
- `agents/dep-updater/agentcore/cdk/test/cdk.test.ts` — CDK assertion tests for the runtime role policy
- `infra/test/vended-cdk-iam-drift.test.ts` — CI-enforced drift guard between the vended mirror and `@fleet/shared`
- `packages/shared/src/observability-config.ts` — `SPANS_LOG_GROUP` corrected to `aws/spans`
- `packages/shared/src/observability-config.test.ts` — regression test pinning the span log group
- `docs/runbook-observability-setup.md` — span destination, retention and verification commands
- `workstream/manual-validation-checklist.md` — log-group discovery instead of hardcoded names
- `apps/control-plane/src/app/agents/[name]/run-panel-data.ts` — `AGENT_LOG_GROUP` fallback default
- `agents/dep-updater/main.py` — configurable bot committer identity
- `agents/dep-updater/tests/test_github_auth.py` — PAT / GitHub App token tests
- `agents/dep-updater/agentcore/agentcore.json` — declarative `GITHUB_SECRET_ID` env var
- `infra/test/agentcore-config.test.ts` — asserts the env var contract
- `docs/runbook-github-app.md` — GitHub App creation, secret shape, cutover and rollback

## Tasks

- [x] 1.0 Implement Issue #56 — Task 1: grant the AgentCore runtime role its data-plane permissions (D1)

  - [x] 1.1 Investigate whether the vended CDK app can import `AGENT_EXEC_WRITE_ATTRIBUTES` from `@fleet/shared`; record the finding
  - [x] 1.2 Write failing CDK assertion tests for all five statements on the runtime execution role
  - [x] 1.3 Write the failing drift guard that fails when the vended allowlist diverges from `@fleet/shared`
  - [x] 1.4 Implement the allowlist source for the vended app
  - [x] 1.5 Implement the five policy statements in `cdk-stack.ts` following the existing `addToPrincipalPolicy` pattern
  - [x] 1.6 Verify Acceptance Criterion: `UpdateItem` is allowed only under `ForAllValues:StringEquals` on `dynamodb:Attributes`
  - [x] 1.7 Verify Acceptance Criterion: `PutItem` is denied and `enabled` / `params` writes are denied
  - [x] 1.8 Verify Acceptance Criterion: secret access is scoped to `secret:dep-agent/github-*` with a tighten-after-cutover comment
  - [x] 1.9 Run Tests: vended jest suite + `pnpm --filter @fleet/infra run test`

- [ ] 2.0 Implement Issue #56 — Task 2: fix `SPANS_LOG_GROUP` (D2)

  - [ ] 2.1 Write a failing regression test pinning `SPANS_LOG_GROUP` to `aws/spans`
  - [ ] 2.2 Change the constant and its doc comment
  - [ ] 2.3 Update `docs/runbook-observability-setup.md` §2 decision + config value, §3 retention command, §4 verification commands
  - [ ] 2.4 Grep the repo for the old string and fix every remaining occurrence
  - [ ] 2.5 Confirm `packages/shared/__fixtures__/` does not hardcode the old group name
  - [ ] 2.6 Verify Acceptance Criterion: no occurrence of `/aws/vendedlogs/agentcore/dep-updater/spans` remains outside historical notes
  - [ ] 2.7 Run Tests: `pnpm --filter @fleet/shared run test`, `pnpm --filter @fleet/control-plane run test`

- [ ] 3.0 Implement Issue #56 — Task 3: stop hardcoding the app log group name (D3)

  - [ ] 3.1 Replace hardcoded group names in `workstream/manual-validation-checklist.md` with discovery
  - [ ] 3.2 Fix the `AGENT_LOG_GROUP` fallback default in the control plane and document where the value comes from
  - [ ] 3.3 Verify Acceptance Criterion: no fictional `/aws/agentcore/dep-updater` reference remains
  - [ ] 3.4 Run Tests: `pnpm --filter @fleet/control-plane run test`

- [ ] 4.0 Implement Issue #56 — Task 4: PAT → GitHub App migration

  - [ ] 4.1 Write failing unit tests for the PAT branch, App branch, JWT claims, RS256, token extraction and HTTP error paths
  - [ ] 4.2 Write failing tests for the env-configurable committer identity
  - [ ] 4.3 Implement the configurable committer identity with current values as defaults
  - [ ] 4.4 Add `envVars: [{ name: "GITHUB_SECRET_ID", value: "dep-agent/github-app" }]` to the runtime entry
  - [ ] 4.5 Extend `infra/test/agentcore-config.test.ts` to assert the env var contract
  - [ ] 4.6 Write `docs/runbook-github-app.md` covering App creation, permissions, installation, key generation, secret command, cutover ordering and rollback
  - [ ] 4.7 Verify Acceptance Criterion: no key material or real credentials committed; no network calls in tests
  - [ ] 4.8 Run Tests: `cd agents/dep-updater && uv run pytest`, `pnpm --filter @fleet/infra run test`

- [ ] 5.0 Completion gate
  - [ ] 5.1 Run quality gates: `pnpm test`, `pnpm lint`, `pnpm format:check`, `pnpm typecheck`, `pnpm audit`, `pnpm check-boundaries`
  - [ ] 5.2 Run Python gates: `uv run pytest`, `uv run ruff check .`, `uv run mypy --strict .`
  - [ ] 5.3 Run the vended CDK jest suite
  - [ ] 5.4 Documentation pass and drift validation
  - [ ] 5.5 Post the verifier audit summary to the issue/PR
  - [ ] 5.6 Convert the PR to Ready for Review (base `integration/acp-v1-control-plane`, no merge)
