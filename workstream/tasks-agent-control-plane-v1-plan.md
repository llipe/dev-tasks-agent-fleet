# Implementation Plan — Agent Control Plane v1

## Relevant Files

- `package.json`, `pnpm-workspace.yaml`, `tsconfig.base.json`, `.nvmrc` - Monorepo root config
- `eslint.config.js`, `.prettierrc`, `vitest.workspace.ts` - Quality tooling
- `.github/workflows/{control-plane,agent,infra,shared}.yml` - Path-gated CI
- `packages/shared/src/**` - Contract: keys, schemas, status, session-id, span fields, codegen, IAM attribute allowlists, agent tags, observability config
- `packages/shared/generated/**` - Generated Python module + JSON Schema
- `infra/bin/app.ts`, `infra/lib/{data-stack,iam-stack,agent-stack,orchestration-stack}.ts` - CDK
- `infra/test/agent-stack.test.ts` - CDK snapshot test for discovery tags
- `infra/test/discovery.integration-test.ts` - Integration tests for tag-based discovery
- `infra/seed/seed.ts` - Table seeder
- `infra/orchestrator/src/**` - Orchestrator Lambda
- `agents/dep-updater/{main.py,Dockerfile,pyproject.toml}` - Agent
- `agents/dep-updater/{agentcore.json,uv.lock,package.json,.gitignore}` - Agent config and deps
- `agents/dep-updater/tests/test_helpers.py` - Pytest coverage for pure helpers
- `agents/dep-updater/ca/.keep` - Corporate CA certificate directory
- `apps/control-plane/src/middleware.ts` - JWT validation
- `apps/control-plane/src/server/aws/**` - AWS adapters
- `apps/control-plane/src/server/cache/ttl-cache.ts` - In-process cache
- `apps/control-plane/src/server/repository/**` - DynamoDB repository layer
- `apps/control-plane/src/server/actions/scope.ts` - Server Actions (writes)
- `apps/control-plane/src/server/runs/**` - Run merge, projection, query
- `apps/control-plane/src/lib/cost.ts` - Cost estimation
- `apps/control-plane/src/components/**` - UI primitives and view components
- `apps/control-plane/src/app/**` - Routes and layouts
- `apps/control-plane/Dockerfile`, `infra/control-plane.fly.toml` - Deployment
- `apps/control-plane/pricing/pricing-v1.json` - Model pricing table
- `docs/runbook-observability-setup.md` - CloudWatch Transaction Search, span destination, retention setup

## Execution Plan

Integration branch: `integration/acp-v1-control-plane`
Repository: `llipe/dev-tasks-agent-fleet`
Test plan: `workstream/test-plan-agent-control-plane-v1.md`
Developer execution mode: pre-approved autonomous sequential

### Dependency Graph

```
S-001 (foundation)
├── S-002 (shared contract)
│   ├── S-003 (DynamoDB + seed) [depends: S-001, S-002]
│   │   ├── S-004 (IAM roles) [depends: S-003]
│   │   │   ├── S-005 (Observability + tags) [depends: S-003, S-004]
│   │   │   │   └── S-010 (Span attributes) [depends: S-005, S-009]
│   │   │   ├── S-011 (Agent DynamoDB stamps) [depends: S-004, S-010]
│   │   │   ├── S-013 (Orchestrator Lambda) [depends: S-002, S-004, S-011]
│   │   │   └── S-015 (AWS adapters) [depends: S-002, S-004, S-014]
│   │   └── S-009 (Payload envelope) [depends: S-002, S-008]
│   └── S-017 (Logs Insights query) [depends: S-012, S-015]
├── S-006 (Port agent) [depends: S-001, S-005]
│   └── S-007 (Non-blocking entrypoint) [depends: S-006]
│       └── S-008 (Structured logging) [depends: S-007]
├── S-014 (App shell + JWT) [depends: S-001]
│   ├── S-015 (AWS adapters) [depends: S-002, S-004, S-014]
│   └── S-016 (Design-system primitives) [depends: S-014]
├── S-012 (Verify telemetry) [depends: S-010, S-011]
├── S-018 (Run merge + cost) [depends: S-002, S-015, S-017]
│   ├── S-019 (Agents list view) [depends: S-016, S-018]
│   └── S-020 (Agent detail – Runs tab) [depends: S-016, S-018]
│       └── S-021 (Run side panel) [depends: S-017, S-020]
│           └── S-022 (Scope config – Repos tab) [depends: S-015, S-016, S-021]
│               └── S-023 (Repos list view) [depends: S-022]
└── S-024 (Fly deployment) [depends: all S-014–S-023]
```

### Sequential Execution Order

| Seq | Story | Title                                                       | Issue | Dependencies        |
| --- | ----- | ----------------------------------------------------------- | ----- | ------------------- |
| 1   | S-001 | Monorepo scaffold with quality gates and path-gated CI      | #1    | —                   |
| 2   | S-002 | `packages/shared` contract with Python code generation      | #2    | S-001               |
| 3   | S-003 | DynamoDB table, GSI1, and seed script via CDK               | #3    | S-001, S-002        |
| 4   | S-004 | IAM roles enforcing write separation                        | #6    | S-003               |
| 5   | S-005 | Observability prerequisites and discovery tags              | #7    | S-003, S-004        |
| 6   | S-006 | Port `dep-update-agent` into the monorepo                   | #8    | S-001, S-005        |
| 7   | S-007 | Non-blocking entrypoint so long runs survive                | #9    | S-006               |
| 8   | S-008 | Structured JSON logging keyed by `session_id`               | #10   | S-007               |
| 9   | S-009 | Accept the control-plane payload envelope                   | #11   | S-002, S-008        |
| 10  | S-010 | Emit the `llipe.*` span attributes                          | #12   | S-005, S-009        |
| 11  | S-011 | Agent stamps its outcome into DynamoDB                      | #13   | S-004, S-010        |
| 12  | S-012 | Verify telemetry assumptions and pin the span field mapping | #14   | S-010, S-011        |
| 13  | S-013 | Orchestrator Lambda driven by DynamoDB scope                | #15   | S-002, S-004, S-011 |
| 14  | S-014 | App shell with Cloudflare Access JWT validation             | #18   | S-001               |
| 15  | S-015 | AWS adapter layer, credentials, and TTL cache               | #22   | S-002, S-004, S-014 |
| 16  | S-016 | Design-system primitives — tokens, DataTable, StatusBadge   | #23   | S-014               |
| 17  | S-017 | Logs Insights run query and span-to-run mapping             | #24   | S-012, S-015        |
| 18  | S-018 | Run list merge, status derivation, and cost estimation      | #25   | S-002, S-015, S-017 |
| 19  | S-019 | Agents list view                                            | #26   | S-016, S-018        |
| 20  | S-020 | Agent detail — Runs tab with URL-persisted filters          | #27   | S-016, S-018        |
| 21  | S-021 | Run side panel with span timeline and logs                  | #28   | S-017, S-020        |
| 22  | S-022 | Scope configuration — Repos tab and write actions           | #29   | S-015, S-016, S-021 |
| 23  | S-023 | Repos list and per-repository run view                      | #30   | S-022               |
| 24  | S-024 | Fly deployment with Cloudflare Tunnel origin lockdown       | #31   | S-014–S-023         |

### Notes

- Sequences 6–12 (agent-compat track) and 14–16 (control-plane shell track) are logically independent but serialized here because S-017 requires both S-012 (from agent track) and S-015 (from control-plane track). The agent track is scheduled first because it feeds telemetry fixtures needed downstream.
- S-013 (Orchestrator) is independent of the control-plane UI track and is placed at sequence 13 after its last dependency (S-011) completes.
- S-024 (Deployment) is terminal — it depends on all control-plane stories being integrated.

## Tasks

- [x] 1.0 Implement Story S-001: Monorepo scaffold with quality gates and path-gated CI — #1 https://github.com/llipe/dev-tasks-agent-fleet/issues/1

  - [x] 1.1 Initialize pnpm workspace: `package.json`, `pnpm-workspace.yaml` covering `apps/*`, `agents/*`, `packages/*`, `infra`
  - [x] 1.2 Create `tsconfig.base.json` with `strict: true`, `noUncheckedIndexedAccess: true`; pin Node in `.nvmrc` and `engines`
  - [x] 1.3 Create placeholder packages for `apps/control-plane`, `agents/dep-updater`, `packages/shared`, `infra` with minimal `package.json` and `tsconfig.json` extending root
  - [x] 1.4 Configure ESLint (flat config, TS + Next.js rules), Prettier (single config), and shared formatting rules
  - [x] 1.5 Configure Vitest workspace with per-package projects; install Playwright (no specs yet)
  - [x] 1.6 Wire canonical scripts in root and every JS/TS package: `lint`, `lint:fix`, `format`, `format:check`, `typecheck`, `test`, `test:unit`, `test:integration`, `test:e2e`, `audit`, `validate`
  - [x] 1.7 Write `scripts/check-import-boundaries.ts`: asserts `apps/` never imports `agents/`, `agents/` never imports `apps/`, `shared` imports neither
  - [x] 1.8 Add one trivial passing test per package proving the runner is wired
  - [x] 1.9 Create four path-gated GitHub Actions workflows with OIDC role assumption
  - [x] 1.10 Verify `pnpm run validate` passes end to end on the empty scaffold
  - [x] 1.11 Verify a commit touching only `agents/dep-updater/**` does not trigger the control-plane workflow
  - [x] 1.12 Verify AC: deliberate lint error fails `lint`; deliberate type error fails `typecheck`; unformatted file fails `format:check`; cross-package import fails boundary check
  - [x] 1.13 Run Tests: `pnpm run validate` green

- [x] 2.0 Implement Story S-002: `packages/shared` contract with Python code generation — #2 https://github.com/llipe/dev-tasks-agent-fleet/issues/2

  - [x] 2.1 Implement key builders: `subjectPk(repo)`, `agentSk(name)`, `META`, `CONFIG` — prefixes defined once
  - [x] 2.2 Implement Zod schemas for `SubjectMetaItem`, `SubjectAgentItem`, `AgentConfigItem`
  - [x] 2.3 Implement `PARAMS_SCHEMAS` registry with `dep-updater` (`allow_fixes: boolean`, `max_fix_attempts: int 1–5`), `.strict()`; `paramsSchemaFor(unknown)` returns empty strict object
  - [x] 2.4 Implement `LLIPE` attribute-name constants (`SUBJECT_ID`, `RUN_STATUS`, `OUTCOME_TYPE`, `OUTCOME_URL`)
  - [x] 2.5 Implement `SPAN_FIELDS` mapping (single point of change for field paths, initially placeholder)
  - [x] 2.6 Implement `deriveStatus(lastStatus, lastRunAt, maxLifetimeMs, now)` with `DEFAULT_MAX_LIFETIME_MS = 28_800_000` and `TERMINATION_GRACE_MS = 300_000`
  - [x] 2.7 Implement `buildSessionId(agent, repo, scheduledAt)` with ≥33-char guarantee and determinism
  - [x] 2.8 Implement `normalizeSubjectId(input)` handling bare name, `owner/repo`, HTTPS clone URL, `.git` suffix, trailing slash
  - [x] 2.9 Write codegen script: Zod → JSON Schema → Python module; output committed under `generated/`
  - [x] 2.10 Add CI drift check: fails if `pnpm --filter shared run codegen` produces a diff
  - [x] 2.11 Unit test: key builders round-trip
  - [x] 2.12 Unit test: `deriveStatus` at boundary ±1 ms, absent-`maxLifetime` fallback, unparseable `lastRunAt`
  - [x] 2.13 Unit test: `buildSessionId` length floor with shortest agent+repo, determinism, charset
  - [x] 2.14 Unit test: `normalizeSubjectId` across all input forms incl. SSH remote edge case
  - [x] 2.15 Unit test: `PARAMS_SCHEMAS` rejects unknown keys and wrong types
  - [x] 2.16 Verify AC: `packages/shared` has no dependency on `apps/` or `agents/`
  - [x] 2.17 Run Tests: `pnpm --filter shared run test:unit && pnpm --filter shared run codegen && pnpm run validate`

- [x] 3.0 Implement Story S-003: DynamoDB table, GSI1, and seed script via CDK — #3 https://github.com/llipe/dev-tasks-agent-fleet/issues/3

  - [x] 3.1 Create CDK app skeleton in `infra/`: `bin/app.ts` with stack instantiation
  - [x] 3.2 Implement `data-stack.ts`: table `agent-fleet-config`, `pk`/`sk` string keys, on-demand, PITR, deletion protection, GSI1 (pk=sk, sk=pk, ALL projection)
  - [x] 3.3 Import table name, GSI name, key prefixes from `packages/shared` — no string literals
  - [x] 3.4 Wire `cdk diff` in the `infra/**` CI workflow; `cdk deploy` gated on approval
  - [x] 3.5 Implement `infra/seed/seed.ts`: reads `repos.json`, writes `SUBJECT#<repo>/META` + `SUBJECT#<repo>/AGENT#dep-updater` per repo using `TransactWriteItems` with `attribute_not_exists`
  - [x] 3.6 Create `infra/seed/repos.json` with the current repository list
  - [x] 3.7 Unit test: seed input parsing and normalization via `normalizeSubjectId`
  - [x] 3.8 Integration test: A1 (repos for agent), A3 (agents for repo), A4 (all subjects via GSI1 META)
  - [x] 3.9 Integration test: idempotent re-seed makes zero writes
  - [x] 3.10 Integration test: transaction rollback when agent item already exists
  - [x] 3.11 Verify AC: `Query GSI1 pk = "META"` returns every seeded subject
  - [x] 3.12 Verify AC: `Query GSI1 pk = "AGENT#dep-updater"` filtered `enabled = true` returns enabled subset
  - [x] 3.13 Request user confirmation, deploy table, run seed, verify — DEFERRED: deployment requires user confirmation, documented in PR
  - [x] 3.14 Run Tests: `pnpm --filter infra run test && pnpm --filter infra run test:integration`

- [x] 4.0 Implement Story S-004: IAM roles enforcing write separation — #6 https://github.com/llipe/dev-tasks-agent-fleet/issues/6

  - [x] 4.1 Implement `iam-stack.ts` with three role constructs: `control-plane-role`, `orchestrator-role`, `agent-exec-role`
  - [x] 4.2 Import attribute allowlists from `packages/shared` for `dynamodb:Attributes` conditions
  - [x] 4.3 CDK snapshot test: policy documents contain expected actions and do NOT contain forbidden ones
  - [x] 4.4 CDK snapshot test: agent role has no `PutItem` action
  - [x] 4.5 Integration test: assume control-plane role, assert `InvokeAgentRuntime` is denied
  - [x] 4.6 Integration test: assume agent role, assert `PutItem` is denied
  - [x] 4.7 Integration test: assume agent role, assert `UpdateItem` touching `enabled` is denied
  - [x] 4.8 Integration test: agent `UpdateItem` on `last_status` succeeds (targeted deny, not blanket)
  - [x] 4.9 Deploy via gated `cdk deploy` and verify — DEFERRED: deployment requires user confirmation
  - [x] 4.10 Run Tests: `pnpm --filter infra run test && pnpm --filter infra run test:integration -- iam`

- [x] 5.0 Implement Story S-005: Observability prerequisites and discovery tags — #7 https://github.com/llipe/dev-tasks-agent-fleet/issues/7

  - [x] 5.1 Enable CloudWatch Transaction Search (console); document the steps in `docs/runbook-observability-setup.md`
  - [x] 5.2 Choose and record the span destination; set `SPANS_LOG_GROUP` config; record in runbook
  - [x] 5.3 Record the log-group retention period, closing PRD open question #6
  - [x] 5.4 Add `agent:managed=true`, `agent:name=dep-updater`, `agent:domain=security` to the agent CDK stack
  - [x] 5.5 CDK snapshot test asserting all three tags on the runtime
  - [x] 5.6 Integration test: `tag:GetResources` filtered on `agent:managed=true` returns the agent
  - [x] 5.7 Integration test: an untagged control resource is absent from results
  - [x] 5.8 Consistency assertion: `agent:name` value equals the `AGENT#<name>` key
  - [x] 5.9 Verify AC: spans arrive at the chosen destination (may require one triggered run post-setup) — DEFERRED: requires deployed agent stack and one triggered run
  - [x] 5.10 Run Tests: `pnpm --filter infra run test && pnpm --filter infra run test:integration -- discovery`

- [x] 6.0 Implement Story S-006: Port `dep-update-agent` into the monorepo — #8 https://github.com/llipe/dev-tasks-agent-fleet/issues/8

  - [x] 6.1 Move `main.py`, `Dockerfile`, `pyproject.toml`, `uv.lock` to `agents/dep-updater/`
  - [x] 6.2 Rename to `dep-updater` throughout: `agentcore.json`, CDK stack, tag values
  - [x] 6.3 Align Python 3.13 in `pyproject.toml`, `Dockerfile`, and `agentcore.json`
  - [x] 6.4 Wire `ruff`, `mypy --strict`, `pytest` into package scripts
  - [x] 6.5 Port the agent CDK stack into `infra/lib/agent-stack.ts`
  - [x] 6.6 Write pytest coverage for pure helpers: `diff_packages`, `count_vulns`, `extract_advisories`, `_detect_pnpm_version`
  - [x] 6.7 Build container for `linux/arm64`; verify it passes locally
  - [x] 6.8 Deploy to AgentCore and trigger one run against a test repository — DEFER (requires manual deployment)
  - [x] 6.9 Verify AC: pipeline behaviour unchanged, run completes successfully — DEFER (requires deployment)
  - [x] 6.10 Record `lifecycleConfiguration` values (`maxLifetime`, `idleRuntimeSessionTimeout`)
  - [x] 6.11 Run Tests: `uv run ruff check && uv run mypy --strict . && uv run pytest && docker build --platform linux/arm64`

- [ ] 7.0 Implement Story S-007: Non-blocking entrypoint so long runs survive — #9 https://github.com/llipe/dev-tasks-agent-fleet/issues/9

  - [x] 7.1 Extract the pipeline body into `_run_pipeline(payload, task_id)`
  - [x] 7.2 Rewrite `@app.entrypoint` to register `app.add_async_task`, start a daemon thread, and return within 1 s
  - [x] 7.3 Wrap `_run_pipeline` in try/finally with `app.complete_async_task`
  - [x] 7.4 Verify `time_of_last_update` is not set manually anywhere
  - [x] 7.5 Unit test: entrypoint returns without running the pipeline
  - [x] 7.6 Unit test: `complete_async_task` invoked on both success and exception
  - [x] 7.7 Unit test: worker thread started as daemon
  - [x] 7.8 Local integration test: poll `/ping` during a simulated long task → assert `HealthyBusy`; assert `Healthy` after completion
  - [ ] 7.9 Deploy and run against a repo whose pipeline exceeds 10 minutes; confirm logs continue past 5 min and run completes — DEFERRED (requires deployment)
  - [x] 7.10 Run Tests: `uv run pytest`

- [ ] 8.0 Implement Story S-008: Structured JSON logging keyed by `session_id` — #10 https://github.com/llipe/dev-tasks-agent-fleet/issues/10

  - [ ] 8.1 Implement `logging_json.py`: JSON logging helper that binds `session_id`, `agent`, `repo` once; emits one JSON object per line
  - [ ] 8.2 Implement secret redaction helper stripping token-shaped values
  - [ ] 8.3 Choose and implement subprocess output handling (one JSON object per line with `stream` field, or captured block)
  - [ ] 8.4 Convert all `print()` calls in `main.py` to the structured logger, preserving messages
  - [ ] 8.5 Ensure log levels follow guidelines: `error` for failures, `warn` for retries, `info` for lifecycle
  - [ ] 8.6 Unit test: emitted line parses as JSON with required fields
  - [ ] 8.7 Unit test: redaction helper strips token-shaped values
  - [ ] 8.8 Unit test: message with quotes/newlines/non-UTF8 does not break JSON
  - [ ] 8.9 Post-deploy integration test: `FilterLogEvents` by `session_id` returns only that run
  - [ ] 8.10 Run Tests: `uv run pytest && uv run ruff check`

- [ ] 9.0 Implement Story S-009: Accept the control-plane payload envelope — #11 https://github.com/llipe/dev-tasks-agent-fleet/issues/11

  - [ ] 9.1 Implement `payload.py`: model from the generated Python contract; parse `{session_id, repo, params}`
  - [ ] 9.2 Normalize `subject_id` via generated `normalize_subject_id`; derive clone URL
  - [ ] 9.3 Validate `params` against generated schema; reject unknown keys
  - [ ] 9.4 Apply defaults (`allow_fixes=True`, `max_fix_attempts=3`)
  - [ ] 9.5 Preserve the `prompt`-unwrapping CLI shim
  - [ ] 9.6 Fail fast on missing `session_id` or `repo` with a clear logged error
  - [ ] 9.7 Create `packages/shared/fixtures/subject-ids.json` with test cases
  - [ ] 9.8 Unit test: envelope parsing; normalization equivalence with TS over shared fixture
  - [ ] 9.9 Unit test: params validation accept/reject; unknown key rejected not stripped
  - [ ] 9.10 Unit test: missing `session_id`; missing `repo`; `params` null vs `{}`
  - [ ] 9.11 Integration test: end-to-end invocation with control-plane-shaped payload
  - [ ] 9.12 Verify AC: CLI invocation still works via `prompt` shim
  - [ ] 9.13 Run Tests: `uv run pytest && pnpm --filter shared run test:unit`

- [ ] 10.0 Implement Story S-010: Emit the `llipe.*` span attributes — #12 https://github.com/llipe/dev-tasks-agent-fleet/issues/12

  - [ ] 10.1 Implement `emission.py`: import `LLIPE` from generated contract; result-to-attribute mapping function
  - [ ] 10.2 Map all five agent results: `success`→(success,pr,url); `no_updates`→(success,none,—); `pr_already_open`→(success,pr,existing); `tests_failing`→(failed,none,—); `error`→(failed,none,—)
  - [ ] 10.3 Set attributes on root span in `finally` block of `_run_pipeline`; verify span is the root from the worker thread
  - [ ] 10.4 Ensure `llipe.subject.id` equals normalized `subject_id`; `outcome.url` empty rather than absent when none
  - [ ] 10.5 Unit test: result-to-attribute mapping for all five results
  - [ ] 10.6 Unit test: attributes emitted on exception path
  - [ ] 10.7 Integration test: in-memory OTel exporter asserts four attributes on root span
  - [ ] 10.8 Integration test: confirm root span annotation from worker thread (not a child span)
  - [ ] 10.9 Post-deploy verification: query span destination, confirm attributes present
  - [ ] 10.10 Run Tests: `uv run pytest`

- [ ] 11.0 Implement Story S-011: Agent stamps its outcome into DynamoDB — #13 https://github.com/llipe/dev-tasks-agent-fleet/issues/13

  - [ ] 11.1 Implement `outcome_store.py`: `UpdateItem` on `last_status` and `last_outcome_url` only, `UpdateExpression`
  - [ ] 11.2 Add conditional expression `attribute_exists(pk)` so a missing item logs error, does not create one
  - [ ] 11.3 Call from `_run_pipeline`'s `finally` block alongside span attributes
  - [ ] 11.4 Ensure no `PutItem` exists anywhere in agent code
  - [ ] 11.5 Handle failed DynamoDB write: log `error`, do not mask the run's actual result
  - [ ] 11.6 Unit test: update expression contains only two attributes
  - [ ] 11.7 Unit test: called on both success and failure paths
  - [ ] 11.8 Integration test: real write under `agent-exec-role`; assert `enabled` and `params` unchanged
  - [ ] 11.9 Integration test: attempted write to `enabled` is denied
  - [ ] 11.10 Post-deploy: inspect item after a real run; confirm `enabled`/`params` untouched
  - [ ] 11.11 Run Tests: `uv run pytest && pnpm --filter infra run test:integration -- agent-writes`

- [ ] 12.0 Implement Story S-012: Verify telemetry assumptions and pin the span field mapping — #14 https://github.com/llipe/dev-tasks-agent-fleet/issues/14

  - [ ] 12.1 Trigger a run with a forced test failure to guarantee model spans (token-consuming run)
  - [ ] 12.2 Retrieve raw spans from `SPANS_LOG_GROUP`; commit one root span and one `gen_ai` child as `__fixtures__/`
  - [ ] 12.3 Confirm or refute `session.id` presence; implement `llipe.session.id` explicit fallback if absent
  - [ ] 12.4 Populate `SPAN_FIELDS` with verified paths (session id, subject, status, outcome, model, tokens, duration, service name, timestamp)
  - [ ] 12.5 Confirm `gen_ai.usage.*` is on child spans (not root) and root spans are identifiable by attribute presence
  - [ ] 12.6 Build and validate a working Logs Insights query returning at least one complete run row
  - [ ] 12.7 Confirm `HealthyBusy` observed during the run and run survived past 5 minutes
  - [ ] 12.8 Write `workstream/findings-telemetry-verification.md`: assumptions confirmed, refuted, newly surfaced
  - [ ] 12.9 Update spec §8.2: replace unverified-field warning with verified paths; add changelog row
  - [ ] 12.10 Unit test: mapper against committed fixture, asserting every field resolves
  - [ ] 12.11 Run Tests: `pnpm --filter control-plane run test:unit -- spans`

- [ ] 13.0 Implement Story S-013: Orchestrator Lambda driven by DynamoDB scope — #15 https://github.com/llipe/dev-tasks-agent-fleet/issues/15

  - [ ] 13.1 Create TypeScript Lambda scaffold in `infra/orchestrator/`
  - [ ] 13.2 Implement GSI1 query: `pk = "AGENT#<name>"`, filter `enabled = true`
  - [ ] 13.3 Implement params merge: global CONFIG + subject-level params, subject wins
  - [ ] 13.4 Stamp-then-invoke per repository: `UpdateItem` `last_session_id`, `last_run_at`, `last_status="running"` then `InvokeAgentRuntime` fire-and-forget (never read response body)
  - [ ] 13.5 Implement bounded concurrency pool of 4 (`ORCHESTRATOR_CONCURRENCY`), per-repo try/catch
  - [ ] 13.6 Implement failure walk-back: if invoke throws, `UpdateItem` `last_status="failed"` immediately
  - [ ] 13.7 Use `buildSessionId(agent, repo, scheduledAt)` — `scheduledAt` from EventBridge event
  - [ ] 13.8 Implement structured JSON logging: `session_id` per invocation, summary line with invoked/skipped counts
  - [ ] 13.9 Create `orchestration-stack.ts` in CDK: EventBridge Scheduler rule per agent, Lambda with 60 s timeout, orchestrator role
  - [ ] 13.10 Remove `REPOS` env var from any residual config; confirm scope comes from DynamoDB only
  - [ ] 13.11 Unit test: `buildSessionId` integration; params merge precedence
  - [ ] 13.12 Unit test: pool bounds concurrency to 4
  - [ ] 13.13 Integration test (mocked): full fan-out over N repos; one throwing while rest proceed; failure walk-back
  - [ ] 13.14 Integration test: disabled repos excluded; `scheduledAt` retry produces identical `session_id`
  - [ ] 13.15 Integration test: zero enabled repos produces zero invocations and a clean return
  - [ ] 13.16 Manual: trigger schedule manually; confirm N runs start and DynamoDB rows stamp
  - [ ] 13.17 Verify AC: adding a repo in DynamoDB (by S-022) causes the next schedule to invoke it without a deploy
  - [ ] 13.18 Run Tests: `pnpm --filter orchestrator run test && pnpm --filter infra run cdk diff`

- [ ] 14.0 Implement Story S-014: App shell with Cloudflare Access JWT validation — #18 https://github.com/llipe/dev-tasks-agent-fleet/issues/18

  - [ ] 14.1 Create Next.js app in `apps/control-plane` with `output: 'standalone'`, strict TS
  - [ ] 14.2 Implement verification helper using `jose`: JWKS fetch with caching, RS256 allowlist, iss/aud/exp/iat checks, fail closed
  - [ ] 14.3 Implement `middleware.ts`: verify `Cf-Access-Jwt-Assertion` on every request except `/healthz` and `_next/static`
  - [ ] 14.4 Implement `/healthz` route handler: returns 200 with no auth, no data access
  - [ ] 14.5 Implement app shell layout: slim top bar with Agents/Repos navigation; `/` redirects to `/agents`
  - [ ] 14.6 Set `export const dynamic = 'force-dynamic'` on all data routes
  - [ ] 14.7 Unit test: valid token → allowed
  - [ ] 14.8 Unit test: expired token → denied
  - [ ] 14.9 Unit test: wrong `aud` → denied
  - [ ] 14.10 Unit test: wrong `iss` → denied
  - [ ] 14.11 Unit test: missing header → denied
  - [ ] 14.12 Unit test: unknown `kid` → denied
  - [ ] 14.13 Unit test: `alg: none` → denied
  - [ ] 14.14 Unit test: JWKS unreachable → denied (fail closed)
  - [ ] 14.15 Unit test: malformed token → denied
  - [ ] 14.16 Integration test: middleware denies unauthenticated data route; allows `/healthz`
  - [ ] 14.17 Run Tests: `pnpm --filter control-plane run test:unit -- auth && pnpm run validate`

- [ ] 15.0 Implement Story S-015: AWS adapter layer, credentials, and TTL cache — #22 https://github.com/llipe/dev-tasks-agent-fleet/issues/22

  - [ ] 15.1 Implement credentials module: Fly OIDC `fromWebToken`, falling back to `fromEnv`; isolated in one file
  - [ ] 15.2 Implement TTL cache with 5 min expiry, single-flight de-dup, LRU cap 500
  - [ ] 15.3 Implement adapter: resource tagging (filter `agent:managed=true`) → domain type with name, domain, ARN
  - [ ] 15.4 Implement adapter: AgentCore control → `lifecycleConfiguration.maxLifetime` defaulting to 28800
  - [ ] 15.5 Implement adapter: CloudWatch Logs Insights → `StartQuery`/poll/`StopQuery` executor
  - [ ] 15.6 Implement adapter: `FilterLogEvents` by `session_id`
  - [ ] 15.7 Implement adapter: DynamoDB via `@aws-sdk/lib-dynamodb`
  - [ ] 15.8 Implement scope repository with intent-named methods; no `Scan` anywhere
  - [ ] 15.9 Implement `ReadOutcome<T>` union: `ok | empty | timeout | error` with correlation id
  - [ ] 15.10 Implement retry policy helper: jittered backoff on throttle/5xx, never retry validation errors
  - [ ] 15.11 Unit test: cache hit/miss/expiry; single-flight collapses concurrent calls; LRU eviction
  - [ ] 15.12 Unit test: `maxLifetime` default when absent
  - [ ] 15.13 Integration test (mocked): each adapter throttle-then-success; validation error not retried
  - [ ] 15.14 Integration test: assert no `ScanCommand` ever sent
  - [ ] 15.15 Run Tests: `pnpm --filter control-plane run test:unit && pnpm --filter control-plane run test:integration`

- [ ] 16.0 Implement Story S-016: Design-system primitives — tokens, DataTable, StatusBadge — #23 https://github.com/llipe/dev-tasks-agent-fleet/issues/23

  - [ ] 16.1 Configure Tailwind + shadcn/ui; define semantic tokens incl. four status pairs in CSS custom properties
  - [ ] 16.2 Implement light and dark colour schemes; verify and record contrast ratios (4.5:1 text, 3:1 UI)
  - [ ] 16.3 Implement `StatusBadge`: colour + text label always; `incomplete` amber, `failed` red
  - [ ] 16.4 Implement `DataTable` on TanStack Table: sorting, row click, keyboard nav (arrow/Enter/Space), real `<table>` semantics
  - [ ] 16.5 Implement four required states in `DataTable`: loading skeleton, empty, error, timed-out
  - [ ] 16.6 Numeric columns: tabular figures, right alignment
  - [ ] 16.7 Implement `RelativeTime`: relative text, absolute UTC in `title`
  - [ ] 16.8 Implement `CostEstimate`: exact, `≥` partial with marker, `unknown` — never `$0.00` for unpriced
  - [ ] 16.9 Handle `prefers-reduced-motion`; no animated status indicator
  - [ ] 16.10 Ensure no hardcoded colour, spacing, or radius value in any component
  - [ ] 16.11 Unit test: `StatusBadge` for all four statuses; `CostEstimate` across complete/partial/unknown incl. genuinely free run; `RelativeTime` formatting
  - [ ] 16.12 Component integration test: `DataTable` renders all four states; row click fires; sorting works; keyboard nav
  - [ ] 16.13 Manual: keyboard-only navigation; screen-reader pass; contrast check both schemes
  - [ ] 16.14 Run Tests: `pnpm --filter control-plane run test:unit -- components`

- [ ] 17.0 Implement Story S-017: Logs Insights run query and span-to-run mapping — #24 https://github.com/llipe/dev-tasks-agent-fleet/issues/24

  - [ ] 17.1 Implement query builder reading `SPAN_FIELDS` and `SPANS_LOG_GROUP` from config
  - [ ] 17.2 Implement `StartQuery`/poll/`StopQuery` executor with 25 s deadline and capped backoff
  - [ ] 17.3 Map `timeout`, `Failed`, `Cancelled` to their `QueryOutcome` variants; `timeout` calls `StopQuery`
  - [ ] 17.4 Implement pure span-to-`Run` mapper: fold per-model rows into one `Run` per `session_id`
  - [ ] 17.5 Implement single-run trace query for the run panel's span timeline
  - [ ] 17.6 Integrate results into the TTL cache, keyed by full filter shape
  - [ ] 17.7 Unit test: mapper against S-012's committed fixture; per-model folding; zero-token run; missing optional attribute; malformed row skipped with `warn`
  - [ ] 17.8 Integration test (mocked): `Complete` after several `Running` polls; `Failed`; `Cancelled`; deadline exceeded → `StopQuery` + `timeout`
  - [ ] 17.9 Integration test: concurrent identical queries collapse via single-flight
  - [ ] 17.10 Manual: query real data, compare a row against the AWS console
  - [ ] 17.11 Run Tests: `pnpm --filter control-plane run test:unit -- spans && pnpm --filter control-plane run test:integration -- insights`

- [ ] 18.0 Implement Story S-018: Run list merge, status derivation, and cost estimation — #25 https://github.com/llipe/dev-tasks-agent-fleet/issues/25

  - [ ] 18.1 Implement `mergeRuns(spanRuns, configRuns)`: keyed by `session_id`, span wins on conflict, config-only included regardless of `last_status`
  - [ ] 18.2 Implement config-row-to-`Run` projection with `deriveStatus` using per-agent `maxLifetime`
  - [ ] 18.3 Apply status filter and date-range filter after merge; sort `started_at` desc
  - [ ] 18.4 Implement pricing table loader from `pricing/pricing-v1.json`
  - [ ] 18.5 Implement `estimateRunCost(perModel, table)` returning `{ usd, complete, unpricedModels }`
  - [ ] 18.6 Implement 30-day per-agent cost aggregate; cache 5 min
  - [ ] 18.7 Log `warn` on any unpriced `model_id`
  - [ ] 18.8 Populate `pricing-v1.json` with placeholder values (test asserts every observed model has an entry)
  - [ ] 18.9 Unit test: `mergeRuns` — in-both, spans-only, config-only; sort order; filter application
  - [ ] 18.10 Unit test: `estimateRunCost` — complete, partial, unpriced; genuinely free run (usd=0, complete=true)
  - [ ] 18.11 Unit test: `deriveStatus` wired with per-agent `maxLifetime`; boundary case ±1 ms
  - [ ] 18.12 Integration test: full read path producing merged list with one completed, one running, one incomplete
  - [ ] 18.13 Run Tests: `pnpm --filter control-plane run test:unit -- runs && pnpm --filter control-plane run test:integration -- read-path`

- [ ] 19.0 Implement Story S-019: Agents list view — #26 https://github.com/llipe/dev-tasks-agent-fleet/issues/26

  - [ ] 19.1 Implement server component fetching inventory + config counts + 30d cost aggregate
  - [ ] 19.2 Implement row view-model: name, domain, last run (relative), status, active repo count, 30d cost
  - [ ] 19.3 Wire `DataTable` with column definitions; streaming boundary for cost column
  - [ ] 19.4 Row click navigates to `/agents/[name]`
  - [ ] 19.5 Implement all four async states (loading, empty, error, timeout)
  - [ ] 19.6 Integration test: renders with mocked adapters; untagged agent excluded
  - [ ] 19.7 Integration test: zero agents (empty state); agent with zero repos; agent never run; cost unknown; timeout
  - [ ] 19.8 Manual: load against real data; confirm counts and costs match DynamoDB/console
  - [ ] 19.9 Run Tests: `pnpm --filter control-plane run test:integration -- agents`

- [ ] 20.0 Implement Story S-020: Agent detail — Runs tab with URL-persisted filters — #27 https://github.com/llipe/dev-tasks-agent-fleet/issues/27

  - [ ] 20.1 Implement `/agents/[name]` route reading `searchParams` for `tab`, `status`, `from`, `to`, `run`
  - [ ] 20.2 Implement tab shell switching Runs / Repos via `tab` param
  - [ ] 20.3 Implement Runs `DataTable` columns: date, repo, status, duration, tokens, cost, output
  - [ ] 20.4 Implement filter controls writing to URL; range defaults to 7d, capped 30d
  - [ ] 20.5 Implement row click setting `run=<session_id>`
  - [ ] 20.6 Duration in human units; tokens as labelled `in / out`; outcome as type-labelled link, `none` → dash
  - [ ] 20.7 All four async states; timeout suggests narrower range
  - [ ] 20.8 Unit test: filter parsing/validation; range clamping; column formatters
  - [ ] 20.9 Integration test: page renders with filters; invalid params fall back to defaults
  - [ ] 20.10 E2E: apply filters, reload, confirm URL restoration; copy URL into new tab
  - [ ] 20.11 Run Tests: `pnpm --filter control-plane run test:integration -- agent-runs && pnpm --filter control-plane run test:e2e -- filters`

- [ ] 21.0 Implement Story S-021: Run side panel with span timeline and logs — #28 https://github.com/llipe/dev-tasks-agent-fleet/issues/28

  - [ ] 21.1 Implement `RunPanel` sheet driven by `run` URL param
  - [ ] 21.2 Metadata section: agent, repo, session_id (monospace, truncated, copy), status, duration, tokens, cost, outcome link — paints immediately from row data
  - [ ] 21.3 `SpanTimeline` in its own `Suspense`: per-call horizontal bars with latency and tokens
  - [ ] 21.4 `LogViewer` in its own `Suspense`: `FilterLogEvents` by `session_id`, monospace, scrollable
  - [ ] 21.5 Dismissal: `Esc`, backdrop click, explicit close; focus trapped while open, restored on close
  - [ ] 21.6 Browser back closes the panel
  - [ ] 21.7 Each section: loading, empty, error, timeout states independently
  - [ ] 21.8 `incomplete` run shows logs up to cut-off point without an error
  - [ ] 21.9 Unit test: log line parsing; timeline bar geometry; `session_id` truncation
  - [ ] 21.10 Integration test: panel renders with mocked timeline and logs; each async state per section
  - [ ] 21.11 E2E: open panel, assert table scroll preserved; count clicks from list to logs (≤3); keyboard open/close; focus restoration
  - [ ] 21.12 Run Tests: `pnpm --filter control-plane run test:integration -- run-panel && pnpm --filter control-plane run test:e2e -- run-panel`

- [ ] 22.0 Implement Story S-022: Scope configuration — Repos tab and write actions — #29 https://github.com/llipe/dev-tasks-agent-fleet/issues/29

  - [ ] 22.1 Implement `/agents/[name]?tab=repos` DataTable: repo, enabled toggle, last run, last status, output
  - [ ] 22.2 Implement `setSubjectEnabled` Server Action: re-verify JWT, Zod parse from `unknown`, conditional `UpdateItem`, `revalidatePath`
  - [ ] 22.3 Implement `EnabledToggle`: optimistic flip, rollback on failure with error naming the repo
  - [ ] 22.4 Implement `setSubjectParams` Server Action: re-verify JWT, Zod parse, `paramsSchemaFor(agent).strict()`, update
  - [ ] 22.5 Implement `ParamsEditor`: client-side JSON validation before enabling save; inline error naming the failing key
  - [ ] 22.6 Implement `addSubjectToAgent` Server Action: re-verify JWT, normalize repo, `TransactWriteItems` (META + AGENT# items), `attribute_not_exists` on AGENT#, `conflict` if exists
  - [ ] 22.7 Implement `AddRepoForm`: single input, validated repo name
  - [ ] 22.8 All actions return discriminated result `{ ok: true } | { ok: false, error: ActionError }`; raw AWS error never returned
  - [ ] 22.9 All actions parse input from `unknown` via Zod as the first statement
  - [ ] 22.10 Assert no action ever touches `last_*` attributes
  - [ ] 22.11 Log scope writes at `info` with before/after values
  - [ ] 22.12 Unit test: input schemas for all three actions; params accept/reject
  - [ ] 22.13 Integration test: each action success + failure modes (not_found, conflict, unauthorized, upstream)
  - [ ] 22.14 Integration test: transactional add writes both items; assert written attrs exactly `enabled` or `params`
  - [ ] 22.15 E2E: toggle, verify immediate reflection; add repo timed under 30 s; toggle failure → revert visible
  - [ ] 22.16 Run Tests: `pnpm --filter control-plane run test:unit -- actions && pnpm --filter control-plane run test:integration -- actions && pnpm --filter control-plane run test:e2e -- scope`

- [ ] 23.0 Implement Story S-023: Repos list and per-repository run view — #30 https://github.com/llipe/dev-tasks-agent-fleet/issues/30

  - [ ] 23.1 Implement subject list service: `Query GSI1 pk = "META"` — no Scan
  - [ ] 23.2 Implement coverage aggregation: per-agent GSI1 queries for agent count per subject
  - [ ] 23.3 Implement `/repos` table: repo, agents covering it, last activity, status; row click → `/repos/[repo]`
  - [ ] 23.4 Implement `/repos/[repo]` reusing `RunsTable` with agent column added
  - [ ] 23.5 Wire filters and run panel identically to S-020/S-021
  - [ ] 23.6 Subject with META only and no agents appears showing zero
  - [ ] 23.7 All four async states
  - [ ] 23.8 Integration test: no `ScanCommand` issued; subject with no agents appears; renders with mocks
  - [ ] 23.9 E2E: navigate, filter, open panel from this view
  - [ ] 23.10 Run Tests: `pnpm --filter control-plane run test:integration -- repos && pnpm --filter control-plane run test:e2e -- repos`

- [ ] 24.0 Implement Story S-024: Fly deployment with Cloudflare Tunnel origin lockdown — #31 https://github.com/llipe/dev-tasks-agent-fleet/issues/31

  - [ ] 24.1 Create multi-stage Dockerfile for standalone Next.js; target <512 MB memory
  - [ ] 24.2 Create `fly.toml` with single machine, `/healthz` health check
  - [ ] 24.3 Configure Fly Machines OIDC → AWS role; document fallback if unworkable
  - [ ] 24.4 Configure Cloudflare Access application in front of the app
  - [ ] 24.5 Configure Cloudflare Tunnel; verify direct `.fly.dev` request is refused
  - [ ] 24.6 Enable HTTPS only + HSTS header
  - [ ] 24.7 All secrets via `fly secrets`; none in image, repo, or build output
  - [ ] 24.8 Wire deploy into `apps/control-plane/**` CI workflow after `validate`
  - [ ] 24.9 Exercise rollback to previous image once; verify stateless recovery
  - [ ] 24.10 Record monthly cost; confirm under USD 10
  - [ ] 24.11 Update `docs/runbook-deployment.md` with deploy and rollback steps
  - [ ] 24.12 Verify AC: direct origin access refused (documented with evidence)
  - [ ] 24.13 Run Tests: `pnpm --filter control-plane run build`, deploy, verify
