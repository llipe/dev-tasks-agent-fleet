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
- `apps/control-plane/src/app/agents/[name]/run-panel-data.ts` — `AGENT_LOG_GROUP` is now required, resolved per call, with no fictional default
- `apps/control-plane/src/app/agents/[name]/run-panel-data.test.ts` — log-group resolution tests
- `apps/control-plane/src/server/runs/insights-query.integration-test.ts` — uses `SPANS_LOG_GROUP` instead of a literal
- `docs/runbook-deployment.md` — documents `AGENT_LOG_GROUP` discovery and when to refresh it
- `agents/dep-updater/main.py` — `resolve_committer_identity()` reads `GIT_COMMITTER_NAME` / `GIT_COMMITTER_EMAIL` with the PAT-era values as defaults
- `agents/dep-updater/tests/test_github_auth.py` — PAT / GitHub App token tests and committer-identity tests (in-fixture RSA key, no network)
- `agents/dep-updater/agentcore/agentcore.json` — declarative `GITHUB_SECRET_ID` env var
- `infra/test/agentcore-config.test.ts` — asserts the env var contract
- `docs/runbook-github-app.md` — GitHub App creation, secret shape, cutover and rollback
- `workstream/pending-deployments.md` — D1/D2/D3 reconciled to fixed-in-code / pending-deploy, live-state evidence retained
- `infra/test/vended-cdk-iam-drift.test.ts` — regex capture handling reworked to satisfy `no-non-null-assertion`
- `apps/control-plane/src/app/agents/[name]/run-panel-data.test.ts` — env access by literal key to satisfy `no-dynamic-delete`
- `.github/workflows/agent.yml` — installs the `uv` toolchain so the Python lint/format/typecheck/test steps can run
- `.github/workflows/shared.yml` — installs the same `uv` toolchain so `pnpm -r run typecheck` can validate the `agents/dep-updater` consumer

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

- [x] 2.0 Implement Issue #56 — Task 2: fix `SPANS_LOG_GROUP` (D2)

  - [x] 2.1 Write a failing regression test pinning `SPANS_LOG_GROUP` to `aws/spans`
  - [x] 2.2 Change the constant and its doc comment
  - [x] 2.3 Update `docs/runbook-observability-setup.md` §2 decision + config value, §3 retention command, §4 verification commands
  - [x] 2.4 Grep the repo for the old string and fix every remaining occurrence
  - [x] 2.5 Confirm `packages/shared/__fixtures__/` does not hardcode the old group name
  - [x] 2.6 Verify Acceptance Criterion: no occurrence of `/aws/vendedlogs/agentcore/dep-updater/spans` remains outside historical notes
  - [x] 2.7 Run Tests: `pnpm --filter @fleet/shared run test`, `pnpm --filter @fleet/control-plane run test`

- [x] 3.0 Implement Issue #56 — Task 3: stop hardcoding the app log group name (D3)

  - [x] 3.1 Replace hardcoded group names in `workstream/manual-validation-checklist.md` with discovery
  - [x] 3.2 Fix the `AGENT_LOG_GROUP` fallback default in the control plane and document where the value comes from
  - [x] 3.3 Verify Acceptance Criterion: no fictional `/aws/agentcore/dep-updater` reference remains
  - [x] 3.4 Run Tests: `pnpm --filter @fleet/control-plane run test`

- [x] 4.0 Implement Issue #56 — Task 4: PAT → GitHub App migration

  - [x] 4.1 Write failing unit tests for the PAT branch, App branch, JWT claims, RS256, token extraction and HTTP error paths
  - [x] 4.2 Write failing tests for the env-configurable committer identity
  - [x] 4.3 Implement the configurable committer identity with current values as defaults
  - [x] 4.4 Add `envVars: [{ name: "GITHUB_SECRET_ID", value: "dep-agent/github-app" }]` to the runtime entry
  - [x] 4.5 Extend `infra/test/agentcore-config.test.ts` to assert the env var contract
  - [x] 4.6 Write `docs/runbook-github-app.md` covering App creation, permissions, installation, key generation, secret command, cutover ordering and rollback
  - [x] 4.7 Verify Acceptance Criterion: no key material or real credentials committed; no network calls in tests
  - [x] 4.8 Run Tests: `cd agents/dep-updater && uv run pytest`, `pnpm --filter @fleet/infra run test`

- [x] 5.0 Completion gate
  - [x] 5.1 Run quality gates: `pnpm test`, `pnpm lint`, `pnpm format:check`, `pnpm typecheck`, `pnpm audit`, `pnpm check-boundaries`
  - [x] 5.2 Run Python gates: `uv run pytest`, `uv run ruff check .`, `uv run mypy --strict .`
  - [x] 5.3 Run the vended CDK jest suite
  - [x] 5.4 Documentation pass and drift validation
  - [x] 5.5 Post the verifier audit summary to the issue/PR
  - [x] 5.6 Convert the PR to Ready for Review (base `integration/acp-v1-control-plane`, no merge)

- [ ] 6.0 Fix the missing `uv` toolchain in CI (discovered during planner review of PR #57)

  > Note: `CI — Agent` and `CI — Shared` both failed on PR #57 because no workflow installs `uv`, while every `agents/dep-updater` script runs through it. Pre-existing and latent since S-006 — `git diff integration/acp-v1-control-plane...HEAD -- agents/dep-updater/package.json .github/` is empty. Issue #56 is simply the first change to touch `packages/shared/**` and `agents/**` in a way that surfaced it, so the Python CI gates have effectively never executed in CI.

  - [ ] 6.1 Add `astral-sh/setup-uv` (exact pinned version, caching enabled) to `.github/workflows/agent.yml` after the pnpm/Node setup
  - [ ] 6.2 Add the same block to `.github/workflows/shared.yml`, keeping the two workflows consistent
  - [ ] 6.3 Provision Python 3.13 explicitly and sync the locked environment from `uv.lock` (`uv python install` + `uv sync --locked`)
  - [ ] 6.4 Verify Acceptance Criterion: `agents/dep-updater` stays in `shared.yml`'s "Validate all consumers" scope — the toolchain is fixed, not the validation surface
  - [ ] 6.5 Verify Acceptance Criterion: the AWS OIDC step and all trigger `paths:` filters are unchanged
  - [ ] 6.6 Verify Acceptance Criterion: `CI — Agent` and `CI — Shared` are both green on PR #57
  - [ ] 6.7 Run Tests: full local gate set (`pnpm test`, `lint`, `format:check`, `typecheck`, `audit`, `check-boundaries`, Python suite, vended CDK jest)
  - [ ] 6.8 Update the PR #57 body with the toolchain fix and the "Python CI never executed before this change" fact
  - [ ] 6.9 Open a follow-up issue for the 13 pre-existing `pnpm audit` advisories and reference it from PR #57

## Gate Results

| Gate                      | Result                                                             |
| ------------------------- | ------------------------------------------------------------------ |
| `pnpm test`               | PASS — 524 tests (109 shared, 132 python, 36 orchestrator, 265 control-plane, 114 infra) |
| `pnpm lint`               | PASS — after fixing 2 eslint errors in tests added by this issue    |
| `pnpm format:check`       | PASS — after prettier-formatting `docs/runbook-github-app.md`       |
| `pnpm typecheck`          | PASS — 5 projects, including `mypy --strict`                        |
| `pnpm audit`              | **FAIL — pre-existing, not introduced here** (see note below)       |
| `pnpm check-boundaries`   | PASS                                                                |
| `uv run pytest`           | PASS — 132 passed                                                   |
| `uv run ruff check .`     | PASS                                                                |
| `uv run mypy --strict .`  | PASS — 14 source files                                              |
| Vended CDK `npm test`     | PASS — 17 assertions                                                |

### `pnpm audit` note

13 advisories (1 critical, 5 high, 5 moderate, 1 low) across four **transitive** packages:
`fast-xml-parser` (via `@aws-sdk/client-dynamodb@3.750.0` → `@aws-sdk/core`), plus `postcss`,
`sharp` and `uuid` (via Next.js). This branch changes no `package.json` and no
`pnpm-lock.yaml` — `git diff integration/acp-v1-control-plane...HEAD` over those paths is
empty — so the finding is identical on the base branch and is not a regression from issue
#56. Clearing it means bumping the AWS SDK and Next.js across the workspace, which is a
dependency-upgrade change with its own blast radius and belongs in a separate issue rather
than in a deployment-correctness PR. Flagged for follow-up; not silently passed.
