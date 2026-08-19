# User Stories — Agent Control Plane v1

## Changelog

| Version | Date       | Summary                                                        | Author           |
| ------- | ---------- | -------------------------------------------------------------- | ---------------- |
| 1.0     | 2026-08-19 | Initial stories, derived from spec v1.2 and PRD v1.3            | product-engineer |

---

## Source Documents

| Document | Version |
| --- | --- |
| [PRD](../docs/requirements/PRD-agent-control-plane-v1-en.md) | 1.3 |
| [Specification](./specification-agent-control-plane-v1.md) | 1.2 |
| [Technical guidelines](../docs/technical-guidelines.md) | 1.1 |
| [Design contract](../DESIGN.md) | 1.1 |
| [Product context](../docs/product-context.md) | 1.1 |

## Sequencing Rationale

Four constraints shape the order, and they are not negotiable:

1. **Data before surface.** PRD §Implementation Order: building views first yields empty tables and no way to distinguish an integration bug from an absence of data.
2. **Contract before both sides.** `packages/shared` (S-002) precedes every consumer, because the whole point of the monorepo is that neither side restates the contract.
3. **Risk first.** S-012 verifies span field paths, `session.id` presence, and the liveness fix on one real deployed run. Three design assumptions ride on it, and it gates the orchestrator (S-013) and the entire read path (S-017).
4. **Liveness before telemetry.** S-007 precedes S-012 because verifying span emission on a run that gets reaped at five minutes proves nothing.

Sizes assume a capable developer: **XS** ≤ half day, **S** ~1 day, **M** ~2 days, **L** ~3 days.

Definition of done for every story is the checklist at the end of each; `pnpm run validate` green and human PR review are non-negotiable per technical guidelines §12.

---

# Phase 1 — Foundation

### Story S-001: Monorepo scaffold with quality gates and path-gated CI

**Priority:** Critical
**Estimated Size:** M
**Dependencies:** None

#### User Story

As the operator,
I want a monorepo with working build, lint, type, and test tooling plus path-gated CI,
So that every later story lands in a repo that can verify itself instead of accumulating unverified code.

#### Context

Greenfield. PRD §12.3 fixes the layout; technical guidelines §2 fix the toolchain. Path gating matters immediately: a change to one agent must not redeploy the front end, and a change to `packages/shared` must fan out to everything.

#### Acceptance Criteria

- [ ] `pnpm install` succeeds from a clean clone with `pnpm-workspace.yaml` covering `apps/*`, `agents/*`, `packages/*`, `infra`.
- [ ] Canonical scripts exist at root and in every JS/TS package: `lint`, `lint:fix`, `format`, `format:check`, `typecheck`, `test`, `test:unit`, `test:integration`, `test:e2e`, `audit`, `validate`.
- [ ] `pnpm run validate` passes on the empty scaffold and aggregates lint + format:check + typecheck + test + audit.
- [ ] TypeScript is `strict: true` with `noUncheckedIndexedAccess`; a deliberate type error fails `typecheck`.
- [ ] Node version pinned identically in `.nvmrc` and `engines`.
- [ ] CI workflows trigger by path: `apps/control-plane/**`, `agents/<name>/**`, `infra/**`, and `packages/shared/**` (which validates **all** consumers).
- [ ] CI authenticates to AWS via GitHub OIDC; no long-lived AWS keys in Actions secrets.
- [ ] A commit touching only `agents/dep-updater/**` does not trigger the control-plane workflow.

#### Business Rules

- pnpm is required; npm only if pnpm is genuinely unavailable (technical guidelines §2).
- Exact version pins, no `^` or `~`, lockfiles committed (§16).
- No agent pushes or merges to `main`; Conventional Commits; PR bodies via `--body-file`.

#### Technical Notes

- Directory layout exactly per technical guidelines §9.
- `packages/shared` must be a dependency leaf — it imports nothing from `apps/` or `agents/`.
- Add a CI check that fails if `apps/` or `agents/` import from each other.
- Vitest at root with workspace projects; Playwright installed but no specs yet.

#### Testing Requirements

- **Unit Tests:** A trivial passing test per package to prove the runner is wired.
- **Integration Tests:** None.
- **Manual/UI Testing:** Clean clone → `pnpm install && pnpm run validate`.
- **Edge-Case Matrix:** Deliberate lint error fails `lint`; deliberate type error fails `typecheck`; unformatted file fails `format:check`; cross-package import fails the boundary check.
- **Acceptance-Criteria Mapping:** AC1–5 → `pnpm run validate` locally; AC6–8 → CI dry-run on a branch touching one path only.
- **Execution Commands:** `pnpm install`, `pnpm run validate`

#### Migration Requirements

Not applicable — no data model.

#### Implementation Steps

1. `pnpm init`, `pnpm-workspace.yaml`, root `tsconfig.base.json`.
2. Create `apps/control-plane`, `agents/`, `packages/shared`, `infra/` with placeholder packages.
3. Shared ESLint + Prettier config; strict TS config.
4. Vitest workspace + Playwright install.
5. Root `validate` script aggregating the gates.
6. Four path-gated GitHub Actions workflows + OIDC role assumption.
7. Import-boundary CI check.
8. README with setup instructions.

#### Files to Create/Modify

- `package.json`, `pnpm-workspace.yaml`, `tsconfig.base.json`, `.nvmrc`
- `eslint.config.js`, `.prettierrc`, `vitest.workspace.ts`
- `.github/workflows/{control-plane,agent,infra,shared}.yml`
- `scripts/check-import-boundaries.ts`
- `README.md`

#### Definition of Done Checklist

- [ ] Code implemented per technical guidelines
- [ ] Unit/integration/manual/edge-case tests written and passing
- [ ] Quality gates passing (`lint`, `format:check`, `typecheck`, `test`, `audit`)
- [ ] Code reviewed and approved
- [ ] Acceptance criteria verified and mapped to evidence
- [ ] Migration lifecycle complete or documented opt-out
- [ ] Pull Request created and merged

---

### Story S-002: `packages/shared` contract with Python code generation

**Priority:** Critical
**Estimated Size:** M
**Dependencies:** S-001

#### User Story

As the operator,
I want the DynamoDB schema and `llipe.*` span attributes defined once in TypeScript and generated into Python,
So that the control plane and the agents cannot drift apart without CI noticing.

#### Context

This is the reason the monorepo exists (PRD §12.3). Spec §14.2 calls the contract test the load-bearing one: everything else can be re-derived from source, but a drifted contract fails silently and corrupts the repository axis with no error anywhere.

#### Acceptance Criteria

- [ ] Key builders for `SUBJECT#<repo>`, `AGENT#<name>`, `META`, `CONFIG` — prefixes defined once, never concatenated at call sites.
- [ ] Zod schemas for `SubjectMetaItem`, `SubjectAgentItem`, `AgentConfigItem`.
- [ ] `PARAMS_SCHEMAS` registry with `dep-updater` (`allow_fixes`, `max_fix_attempts`), `.strict()`; `paramsSchemaFor(unknown agent)` returns an empty strict object.
- [ ] `LLIPE` attribute-name constants and `SPAN_FIELDS` mapping (single point of change for S-012).
- [ ] `deriveStatus(lastStatus, lastRunAt, maxLifetimeMs, now)` returning `running | success | failed | incomplete`, with `DEFAULT_MAX_LIFETIME_MS = 28_800_000` and `TERMINATION_GRACE_MS = 300_000`.
- [ ] `buildSessionId(agent, repo, scheduledAt)` producing ≥33 chars for the shortest plausible input and deterministic for a given `scheduledAt`.
- [ ] `normalizeSubjectId(input)` yielding one canonical `owner/repo` form from a repo name or clone URL.
- [ ] `pnpm --filter shared run codegen` emits JSON Schema + a Python module; CI fails if committed output differs from freshly generated output.
- [ ] `packages/shared` has no dependency on `apps/` or `agents/`.

#### Business Rules

- Generated files are committed and never hand-edited.
- Persisted statuses are only `running`, `success`, `failed`. `incomplete` is derived and never written.
- Table attribute names are `snake_case`; camelCase mapping is confined to the repository layer.

#### Technical Notes

- Zod as the single source; derive JSON Schema from it rather than maintaining both.
- Python emission targets 3.13 with type hints; `mypy --strict` clean.
- `SPAN_FIELDS` exists specifically because span field paths are unverified until S-012.

#### Testing Requirements

- **Unit Tests:** Key builders round-trip; `deriveStatus` at `maxLifetime + grace` ±1 ms both directions, plus absent-`maxLifetime` fallback; `buildSessionId` length floor with shortest agent+repo, determinism, charset; `normalizeSubjectId` across bare name, `owner/repo`, HTTPS clone URL, `.git` suffix, trailing slash; `PARAMS_SCHEMAS` rejects unknown keys and malformed types.
- **Integration Tests:** Codegen output matches committed artifacts.
- **Manual/UI Testing:** None.
- **Edge-Case Matrix:** `deriveStatus` with unparseable `lastRunAt`; `buildSessionId` with a repo name containing characters outside the allowed set; params with a valid key but wrong type; `normalizeSubjectId` with an SSH remote.
- **Acceptance-Criteria Mapping:** AC1–7 → `pnpm --filter shared run test:unit`; AC8 → CI codegen drift check; AC9 → import-boundary check from S-001.
- **Execution Commands:** `pnpm --filter shared run test:unit`, `pnpm --filter shared run codegen`, `pnpm run validate`

#### Migration Requirements

Not applicable — defines schema, does not deploy it (S-003).

#### Implementation Steps

1. Zod schemas for the three item types + key builders.
2. Status enums, thresholds, `deriveStatus`.
3. `buildSessionId`, `normalizeSubjectId`.
4. `LLIPE` constants and `SPAN_FIELDS`.
5. `PARAMS_SCHEMAS` registry and accessor.
6. Codegen script: Zod → JSON Schema → Python module.
7. Unit tests for every pure function.
8. CI drift check for generated artifacts.

#### Files to Create/Modify

- `packages/shared/src/{keys,schema/scope,schema/items,run/status,run/session-id,run/subject,span/fields,index}.ts`
- `packages/shared/src/**/*.test.ts`
- `packages/shared/scripts/codegen.ts`
- `packages/shared/generated/{contract.schema.json,shared_contract.py}`

#### Definition of Done Checklist

- [ ] Code implemented per technical guidelines
- [ ] Unit/integration/manual/edge-case tests written and passing
- [ ] Quality gates passing
- [ ] Code reviewed and approved
- [ ] Acceptance criteria verified and mapped to evidence
- [ ] Generated artifacts committed and drift-checked
- [ ] Pull Request created and merged

---

# Phase 2 — Infrastructure and Data

### Story S-003: DynamoDB table, GSI1, and seed script via CDK

**Priority:** Critical
**Estimated Size:** M
**Dependencies:** S-001, S-002

#### User Story

As the operator,
I want the configuration table with its inverted GSI deployed and seeded with my current repositories,
So that scope lives in data rather than in an environment variable.

#### Context

PRD §8.1. The inverted GSI is what makes both access directions cheap, and spec §5.3 A4 depends on it for listing all subjects without a `Scan`.

#### Acceptance Criteria

- [ ] Table `agent-fleet-config` with `pk`/`sk` string keys, on-demand billing, PITR enabled, deletion protection enabled.
- [ ] `GSI1` projecting `ALL` with `pk = sk`, `sk = pk`.
- [ ] CDK stack imports table and index names from `packages/shared`, not string literals.
- [ ] `cdk diff` runs clean in CI; `cdk deploy` gated on human approval.
- [ ] Seed script writes one `SUBJECT#<repo>/META` plus one `SUBJECT#<repo>/AGENT#dep-updater` per repository, transactionally.
- [ ] Seed script is idempotent — a second run makes no changes and reports zero writes.
- [ ] `Query GSI1 pk = "META"` returns every seeded subject.
- [ ] `Query GSI1 pk = "AGENT#dep-updater"` filtered `enabled = true` returns the enabled subset.

#### Business Rules

- Every subject **must** have a `META` item, or it becomes invisible to the Repos list while still being in an agent's scope (spec §8.5).
- `Query` only; a `Scan` anywhere is a defect.
- Additive schema changes only.

#### Technical Notes

- `TransactWriteItems` for the subject pair, `attribute_not_exists(sk)` on the agent item.
- Stack split by cadence: this is the shared-data stack.
- ISO 8601 UTC strings for timestamps.

#### Testing Requirements

- **Unit Tests:** Seed input parsing and normalization via `normalizeSubjectId`.
- **Integration Tests:** Against a real deployed table — A1, A3, A4 access patterns; idempotent re-seed; transaction rollback when the agent item already exists.
- **Manual/UI Testing:** `cdk diff` output reviewed before apply.
- **Edge-Case Matrix:** Duplicate repo in the seed list; repo name needing normalization; empty seed list; partial pre-existing state (META present, agent item absent).
- **Acceptance-Criteria Mapping:** AC1–3 → `cdk diff` + snapshot test; AC5–8 → `pnpm --filter infra run test:integration` post-deploy.
- **Execution Commands:** `pnpm --filter infra run cdk diff`, `pnpm --filter infra run seed`, `pnpm --filter infra run test:integration`

#### Migration Requirements (Data Model Change)

- **Migration artifact:** CDK stack defining table + GSI1, plus `infra/seed/seed.ts`. Required.
- **Rollback/impact notes:** Greenfield with no existing data, so table creation is non-destructive. PITR enabled from creation. Deletion protection prevents accidental teardown; removing the stack requires disabling it first, which must be explicit. Seed is additive and idempotent.
- **Apply step:** `cdk deploy` and `seed` both require explicit operator confirmation. Do not auto-apply in CI.
- **Verification after apply:** Run the integration suite against the deployed table and confirm all four access patterns plus idempotent re-seed.

#### Implementation Steps

1. CDK app skeleton in `infra/`, importing shared constants.
2. Shared-data stack: table + GSI1 + PITR + deletion protection.
3. `cdk diff` in the `infra/**` CI workflow.
4. Seed script with transactional writes and idempotency.
5. Integration tests for the access patterns.
6. Request confirmation, deploy, seed, verify.

#### Files to Create/Modify

- `infra/bin/app.ts`, `infra/lib/data-stack.ts`
- `infra/seed/seed.ts`, `infra/seed/repos.json`
- `infra/test/data-stack.test.ts`, `infra/test/access-patterns.integration.test.ts`

#### Definition of Done Checklist

- [ ] Code implemented per technical guidelines
- [ ] Unit/integration/manual/edge-case tests written and passing
- [ ] Quality gates passing
- [ ] Code reviewed and approved
- [ ] Acceptance criteria verified and mapped to evidence
- [ ] Migration lifecycle complete: artifact, rollback notes, confirmed apply, post-apply verification
- [ ] Pull Request created and merged

---

### Story S-004: IAM roles enforcing write separation

**Priority:** Critical
**Estimated Size:** S
**Dependencies:** S-003

#### User Story

As the operator,
I want three least-privilege roles whose permissions make out-of-scope actions impossible,
So that PRD §10's exclusions are enforced by the credential rather than by the absence of a button.

#### Context

PRD §12.2 and spec §12.1–12.2. The agent's `PutItem` denial is the sharp edge: an attribute-constrained `PutItem` would still replace the whole item and erase `enabled` and `params`, so the action has to be withheld entirely rather than conditioned.

#### Acceptance Criteria

- [ ] `control-plane-role` carries exactly the read actions in PRD §12.2 plus DynamoDB read/write on table and GSI1, and **no** `bedrock-agentcore:InvokeAgentRuntime` and no runtime write action.
- [ ] `orchestrator-role` carries `InvokeAgentRuntime`, DynamoDB `UpdateItem` constrained to `last_session_id`, `last_run_at`, `last_status`, and `Query` on GSI1.
- [ ] `agent-exec-role` carries DynamoDB `UpdateItem` constrained to `last_status` and `last_outcome_url` only, **no `PutItem`**, plus Secrets Manager read for the GitHub App key.
- [ ] An integration test proves the control-plane role is denied `InvokeAgentRuntime`.
- [ ] An integration test proves the agent role is denied `PutItem`.
- [ ] An integration test proves the agent role is denied an `UpdateItem` touching `enabled`.
- [ ] Roles are defined in CDK importing attribute lists from `packages/shared`.

#### Business Rules

- Three distinct roles. The control plane and the orchestrator must not share one, so a front-end compromise cannot invoke an agent.
- Least privilege is the scope boundary, not a hardening pass.

#### Technical Notes

- `ForAllValues:StringEquals` on `dynamodb:Attributes`, with `dynamodb:Select` guarded via `StringEqualsIfExists`.
- Condition-key semantics are easy to get subtly wrong and fail open, which is why AC4–6 are live assertions rather than a policy review (spec R4).

#### Testing Requirements

- **Unit Tests:** CDK snapshot assertions that the policy documents contain the expected actions and, critically, do not contain the forbidden ones.
- **Integration Tests:** Assume each role and assert the three denials actually deny.
- **Manual/UI Testing:** None.
- **Edge-Case Matrix:** Agent `UpdateItem` on an allowed attribute succeeds (proving the deny is targeted, not blanket); agent `UpdateItem` mixing an allowed and a forbidden attribute is denied; control-plane role can still read logs.
- **Acceptance-Criteria Mapping:** AC1–3, AC7 → snapshot tests; AC4–6 → `pnpm --filter infra run test:integration -- iam`.
- **Execution Commands:** `pnpm --filter infra run test`, `pnpm --filter infra run test:integration -- iam`

#### Migration Requirements

Not applicable — no data model change. Policy changes are applied via gated `cdk deploy`.

#### Implementation Steps

1. Three role constructs in an IAM stack.
2. Attribute allowlists imported from `shared`.
3. CDK snapshot tests including negative assertions.
4. Integration tests asserting real denials.
5. Gated deploy and verification.

#### Files to Create/Modify

- `infra/lib/iam-stack.ts`
- `infra/test/iam-stack.test.ts`, `infra/test/iam-denials.integration.test.ts`

#### Definition of Done Checklist

- [ ] Code implemented per technical guidelines
- [ ] Unit/integration/manual/edge-case tests written and passing
- [ ] Quality gates passing
- [ ] Code reviewed and approved
- [ ] Acceptance criteria verified, including the three live denial assertions
- [ ] Pull Request created and merged

---

### Story S-005: Observability prerequisites and discovery tags

**Priority:** Critical
**Estimated Size:** S
**Dependencies:** S-001

#### User Story

As the operator,
I want Transaction Search on, one span destination, and `agent:managed=true` tags applied,
So that runs exist as queryable data and agents opt into the control plane.

#### Context

PRD §12.4. Without these there are no spans, no tokens, and no agent inventory. Tag-based discovery is deliberately opt-in, which also makes a missing tag a confusing silent absence with no error (product-context §9).

#### Acceptance Criteria

- [ ] CloudWatch Transaction Search enabled; 1% indexing documented as sufficient with the reason.
- [ ] One span destination chosen and recorded; `SPANS_LOG_GROUP` config value set from it.
- [ ] Log-group retention period recorded, closing PRD open question 6, and noted as the real bound on how far back any view can look.
- [ ] `agent:managed=true`, `agent:name=dep-updater`, `agent:domain=security` applied to the agent runtime resource via CDK.
- [ ] `tag:GetResources` filtered on `agent:managed=true` returns the agent.
- [ ] A runtime without the tag is confirmed absent from that result.
- [ ] `agent:name` value matches the `AGENT#<name>` key in DynamoDB exactly.

#### Business Rules

- `agent:managed=true` is the only discovery filter the front end uses.
- Two span destinations would mean two queries; exactly one is permitted.
- `agent:name` is a join key, so a mismatch silently fragments the data.

#### Technical Notes

- Tags belong in the agent CDK stack so they cannot be forgotten on redeploy.
- Some of this is console/CLI setup; record what was done and where in `docs/` so it is reproducible.

#### Testing Requirements

- **Unit Tests:** CDK snapshot asserting all three tags on the runtime.
- **Integration Tests:** `tag:GetResources` returns the agent; an untagged control resource is absent.
- **Manual/UI Testing:** Confirm Transaction Search is on and spans are arriving at the chosen destination.
- **Edge-Case Matrix:** Tag present with wrong value (`"false"`) excludes the agent; `agent:name` mismatched against the DynamoDB key is caught by a consistency assertion.
- **Acceptance-Criteria Mapping:** AC4, AC7 → snapshot + consistency test; AC5–6 → integration test; AC1–3 → documented manual verification.
- **Execution Commands:** `pnpm --filter infra run test`, `pnpm --filter infra run test:integration -- discovery`

#### Migration Requirements

Not applicable.

#### Implementation Steps

1. Enable Transaction Search; record the steps.
2. Choose and record the span destination; wire `SPANS_LOG_GROUP`.
3. Record retention period.
4. Add the three tags in CDK.
5. Integration test for discovery inclusion and exclusion.
6. Consistency assertion tying `agent:name` to the `AGENT#` key.

#### Files to Create/Modify

- `infra/lib/agent-stack.ts` (tags)
- `infra/test/discovery.integration.test.ts`
- `docs/runbook-observability-setup.md`

#### Definition of Done Checklist

- [ ] Code implemented per technical guidelines
- [ ] Tests written and passing
- [ ] Quality gates passing
- [ ] Code reviewed and approved
- [ ] Acceptance criteria verified
- [ ] Setup steps documented for reproducibility
- [ ] Pull Request created and merged

---

# Phase 3 — Agent Compatibility

### Story S-006: Port `dep-update-agent` into the monorepo

**Priority:** High
**Estimated Size:** M
**Dependencies:** S-001

#### User Story

As the operator,
I want the existing dependency-update agent living at `agents/dep-updater/` with consistent naming and one Python version,
So that later compatibility work happens in the monorepo against shared contracts.

#### Context

Spec §19.2 C14. The reference repo declares Python three different ways (`PYTHON_3_14` in `agentcore.json`, `python:3.13-slim` in the Dockerfile, `>=3.13` in `pyproject.toml`) and names the agent two more (`dependencyUpdateAgent`, `depUpdateAgent`). The version disagreement may be harmless under `build: Container`, but three declarations of one fact becomes load-bearing at the worst moment.

#### Acceptance Criteria

- [ ] Agent code at `agents/dep-updater/`, pipeline logic unchanged from the reference.
- [ ] Canonical name `dep-updater` used in `agentcore.json`, the CDK stack, the `agent:name` tag, and the DynamoDB `AGENT#` key.
- [ ] Python 3.13 declared consistently across `pyproject.toml`, Dockerfile, and `agentcore.json`.
- [ ] `uv` with committed `uv.lock`, exact pins.
- [ ] `ruff` and `mypy --strict` pass; wired into `agents/dep-updater` scripts and the agent CI workflow.
- [ ] Container builds for `linux/arm64`.
- [ ] Agent deploys to AgentCore and completes one run against a test repository, proving the port did not break the pipeline.
- [ ] `lifecycleConfiguration` values recorded and referenced by the spec's `incomplete` derivation.

#### Business Rules

- Pipeline behaviour must not change in this story. Compatibility changes are S-007 to S-011.
- `agent:name` and `AGENT#<name>` must match exactly.

#### Technical Notes

- Keep the existing `/ping` and `/invocations` contract; keep the corporate-CA Dockerfile step.
- Do not fix the blocking entrypoint here — that is S-007, kept separate so the port is reviewable on its own.
- Existing `print()` logging stays until S-008.

#### Testing Requirements

- **Unit Tests:** Existing pure helpers (`diff_packages`, `count_vulns`, `extract_advisories`, `_detect_pnpm_version`) get pytest coverage as they move.
- **Integration Tests:** Container builds; agent responds on `/ping`.
- **Manual/UI Testing:** One deployed run against a test repo produces the expected PR.
- **Edge-Case Matrix:** Repo with no updates available; repo whose pnpm version differs from the container's; missing `package.json` scripts (lint/typecheck skipped paths).
- **Acceptance-Criteria Mapping:** AC1–6 → `pnpm --filter dep-updater run validate` and CI build; AC7–8 → documented deployed run.
- **Execution Commands:** `uv run ruff check`, `uv run mypy --strict .`, `uv run pytest`, `docker build --platform linux/arm64`

#### Migration Requirements

Not applicable.

#### Implementation Steps

1. Move `main.py`, `Dockerfile`, `pyproject.toml`, `uv.lock` to `agents/dep-updater/`.
2. Rename to `dep-updater` throughout.
3. Align Python to 3.13 in all three places.
4. Wire ruff, mypy, pytest; add package scripts.
5. Port the agent CDK stack into `infra/`.
6. Add pytest coverage for the pure helpers.
7. Build, deploy, run once, record `lifecycleConfiguration`.

#### Files to Create/Modify

- `agents/dep-updater/{main.py,Dockerfile,pyproject.toml,uv.lock,agentcore.json,package.json}`
- `agents/dep-updater/tests/test_helpers.py`
- `infra/lib/agent-stack.ts`

#### Definition of Done Checklist

- [ ] Code implemented per technical guidelines
- [ ] Tests written and passing
- [ ] Quality gates passing
- [ ] Code reviewed and approved
- [ ] Acceptance criteria verified, including one successful deployed run
- [ ] Pull Request created and merged

---

### Story S-007: Non-blocking entrypoint so long runs survive

**Priority:** Critical
**Estimated Size:** S
**Dependencies:** S-006

#### User Story

As the operator,
I want the agent to return from its entrypoint immediately and run the pipeline on a worker thread,
So that AgentCore does not reap the session mid-work and my runs actually finish.

#### Context

Spec §2.4 and §19.2 C16. AgentCore polls `/ping` to decide whether a session is alive, and `/ping` is served by the same process as the entrypoint. The reference agent runs its whole pipeline inline — `git clone`, `pnpm install`, test suites, Claude fix attempts — blocking the health check. With `idleRuntimeSessionTimeout: 300`, the session is reclaimed five minutes in.

The failure is silent and misleading: the run shows `incomplete`, the logs stop partway through `pnpm install`, and everything points at a pipeline bug that does not exist. Fixing this before the telemetry work in S-012 avoids verifying span emission on runs that get killed.

#### Acceptance Criteria

- [ ] `@app.entrypoint` returns within one second, acknowledging with the `session_id`.
- [ ] Pipeline runs on a daemon worker thread tracked by `app.add_async_task`.
- [ ] `app.complete_async_task` is called in a `finally` block, so a crash still releases the task.
- [ ] `/ping` returns `{"status": "HealthyBusy"}` while the pipeline runs and `Healthy` once complete.
- [ ] `time_of_last_update` is **not** set manually anywhere.
- [ ] A run exceeding 10 minutes completes successfully, proving the session is not reaped at 300 s.
- [ ] No blocking call remains on the entrypoint's own thread.

#### Business Rules

- Every agent in this repo follows this shape (technical guidelines §3, "Agent liveness").
- A manually advancing `time_of_last_update` prevents the idle timeout ever firing and can exhaust the session quota — so it is prohibited, not merely discouraged.

#### Technical Notes

- Pipeline logic moves wholesale into `_run_pipeline`; do not refactor it in this story.
- Terminal writes (S-010, S-011) will attach to the same `finally` block.
- Consider raising `idleRuntimeSessionTimeout` as defence in depth (spec S-013), but `HealthyBusy` is the actual fix.

#### Testing Requirements

- **Unit Tests:** Entrypoint returns without running the pipeline; `complete_async_task` invoked on both success and raised exception; worker thread started as daemon.
- **Integration Tests:** Local agent server — poll `/ping` during a simulated long task and assert `HealthyBusy`, then `Healthy` after completion.
- **Manual/UI Testing:** Deployed run against a repo whose pipeline exceeds 10 minutes; confirm logs continue past the 5-minute mark and the run completes.
- **Edge-Case Matrix:** Pipeline raises immediately; pipeline raises after 6 minutes; two concurrent invocations on one runtime; pipeline exceeding `maxLifetime` (expected to be cut off and surface as `incomplete`).
- **Acceptance-Criteria Mapping:** AC1–5, AC7 → `uv run pytest`; AC4 → local `/ping` integration test; AC6 → documented deployed long run.
- **Execution Commands:** `uv run pytest`, local `curl http://localhost:8080/ping`

#### Migration Requirements

Not applicable.

#### Implementation Steps

1. Extract the pipeline body into `_run_pipeline(payload, task_id)`.
2. Rewrite the entrypoint to register an async task, start a daemon thread, and return.
3. Wrap `_run_pipeline` in try/finally with `complete_async_task`.
4. Add pytest coverage for the entrypoint contract.
5. Local `/ping` status integration test.
6. Deploy and verify a >10-minute run.

#### Files to Create/Modify

- `agents/dep-updater/main.py`
- `agents/dep-updater/tests/test_entrypoint.py`, `tests/test_ping_status.py`

#### Definition of Done Checklist

- [ ] Code implemented per technical guidelines
- [ ] Unit/integration/manual/edge-case tests written and passing
- [ ] Quality gates passing
- [ ] Code reviewed and approved
- [ ] Acceptance criteria verified, including a deployed run past 10 minutes
- [ ] Pull Request created and merged

---

### Story S-008: Structured JSON logging keyed by `session_id`

**Priority:** High
**Estimated Size:** S
**Dependencies:** S-006

#### User Story

As the operator,
I want every agent log line to be JSON carrying `session_id`,
So that the run panel can show one run's logs instead of several runs interleaved.

#### Context

PRD §7.3. With 3–5 repositories running in parallel, a time-window filter mixes runs into noise; `session_id` is the only thing that separates them. The reference agent's `print(f"[dep-agent] ...")` lines are good narration but unparseable and uncorrelated.

#### Acceptance Criteria

- [ ] A logging helper binds `session_id`, `agent`, and `repo` once at entry.
- [ ] Every log line is a single JSON object with `timestamp`, `level`, `session_id`, `agent`, `repo`, `message`.
- [ ] All existing `print()` narration is converted, messages preserved.
- [ ] Levels follow technical guidelines §14: `error` for failures, `warn` for retries and throttling, `info` for lifecycle boundaries.
- [ ] No secret, token, or GitHub App key appears in any log line.
- [ ] `logs:FilterLogEvents` filtered by one `session_id` returns only that run's lines.
- [ ] Multi-line subprocess output is emitted so it stays attributable to the run rather than breaking JSON parsing.

#### Business Rules

- A log line without `session_id` is effectively lost.
- Tokens are never logged, including on failure paths.

#### Technical Notes

- Bind context once rather than passing `session_id` to every call site.
- Subprocess stdout/stderr needs a deliberate decision: either one JSON object per line with a `stream` field, or a single object with the captured block. Pick one and apply it consistently.

#### Testing Requirements

- **Unit Tests:** Emitted line parses as JSON and contains required fields; redaction helper strips token-shaped values; level mapping.
- **Integration Tests:** `FilterLogEvents` by `session_id` against a real run returns only that run.
- **Manual/UI Testing:** Inspect a real run's logs for readability and completeness.
- **Edge-Case Matrix:** Message containing quotes/newlines/non-UTF8; very large subprocess output; exception traceback; two runs logging concurrently.
- **Acceptance-Criteria Mapping:** AC1–5, AC7 → `uv run pytest`; AC6 → integration test post-deploy.
- **Execution Commands:** `uv run pytest`, `uv run ruff check`

#### Migration Requirements

Not applicable.

#### Implementation Steps

1. JSON logging helper with bound context and redaction.
2. Bind at entrypoint from the payload's `session_id`.
3. Convert all `print()` calls, preserving messages.
4. Decide and implement subprocess output handling.
5. Unit tests including redaction and awkward payloads.
6. Post-deploy `FilterLogEvents` verification.

#### Files to Create/Modify

- `agents/dep-updater/logging_json.py`
- `agents/dep-updater/main.py`
- `agents/dep-updater/tests/test_logging.py`

#### Definition of Done Checklist

- [ ] Code implemented per technical guidelines
- [ ] Tests written and passing
- [ ] Quality gates passing
- [ ] Code reviewed and approved
- [ ] Acceptance criteria verified
- [ ] No secrets present in sampled log output
- [ ] Pull Request created and merged

---

### Story S-009: Accept the control-plane payload envelope

**Priority:** High
**Estimated Size:** S
**Dependencies:** S-002, S-006

#### User Story

As the operator,
I want the agent to accept `{session_id, repo, params}` and normalize the subject identifier,
So that configuration set in the control plane reaches the agent and joins correctly to telemetry.

#### Context

Spec §19.2 C5. The reference agent reads `payload["repo_url"]` with flat `allow_fixes` / `max_fix_attempts`. The control plane sends the PRD §8.3 envelope. More importantly, `subject_id` must be byte-identical to the DynamoDB `SUBJECT#<repo>` key — `fintrack-home` versus `myorg/fintrack-home` versus a clone URL produces three different subjects and a Repos view that fragments with no error anywhere.

#### Acceptance Criteria

- [ ] Entrypoint reads `session_id`, `repo`, and `params` from the payload.
- [ ] `subject_id` is normalized through the generated `normalize_subject_id`, matching the TypeScript implementation.
- [ ] Clone URL is derived from `subject_id` rather than accepted from the payload.
- [ ] `params` is re-validated against the generated schema on receipt; unknown keys are rejected.
- [ ] `allow_fixes` and `max_fix_attempts` are read from `params` with the previous defaults (`true`, `3`).
- [ ] The existing `prompt`-unwrapping shim still works for CLI invocation.
- [ ] A payload missing `session_id` or `repo` fails fast with a clear logged error.
- [ ] `params` never reaches a shell command, prompt, or URL without sink-appropriate escaping.

#### Business Rules

- `params` is an injection boundary and is validated at both ends (technical guidelines §6).
- Unknown keys are rejected rather than stripped, so a typo cannot look accepted while doing nothing.

#### Technical Notes

- Reuse the generated Python contract, not a hand-written parser.
- A cross-language test asserting TS and Python normalization agree is worth more than either side's unit tests.

#### Testing Requirements

- **Unit Tests:** Envelope parsing; normalization equivalence with the TS implementation over a shared fixture set; params validation accept/reject; default application.
- **Integration Tests:** End-to-end invocation with a control-plane-shaped payload.
- **Manual/UI Testing:** CLI invocation still works via the `prompt` shim.
- **Edge-Case Matrix:** Missing `session_id`; missing `repo`; `params` null vs `{}`; unknown param key; `max_fix_attempts` out of range; `repo` as clone URL, `owner/repo`, or bare name.
- **Acceptance-Criteria Mapping:** AC1–7 → `uv run pytest`; AC2 → shared-fixture cross-language test; AC8 → code review plus a test asserting no shell interpolation of params.
- **Execution Commands:** `uv run pytest`, `pnpm --filter shared run test:unit`

#### Migration Requirements

Not applicable.

#### Implementation Steps

1. Payload model from the generated contract.
2. Normalize `subject_id`; derive the clone URL.
3. Validate `params`, apply defaults.
4. Preserve the CLI shim.
5. Fail fast on missing required fields.
6. Cross-language normalization fixture test.

#### Files to Create/Modify

- `agents/dep-updater/main.py`, `agents/dep-updater/payload.py`
- `agents/dep-updater/tests/test_payload.py`
- `packages/shared/fixtures/subject-ids.json`

#### Definition of Done Checklist

- [ ] Code implemented per technical guidelines
- [ ] Tests written and passing, including cross-language normalization
- [ ] Quality gates passing
- [ ] Code reviewed and approved
- [ ] Acceptance criteria verified
- [ ] Pull Request created and merged

---

### Story S-010: Emit the `llipe.*` span attributes

**Priority:** Critical
**Estimated Size:** S
**Dependencies:** S-002, S-008, S-009

#### User Story

As the operator,
I want every run's root span to carry the subject, status, and outcome,
So that the per-repository view exists at all.

#### Context

PRD §7.3. Without `llipe.subject.id` there is no repository axis and view C does not exist. Spec §19.2 C15 also settles how the agent's five internal results project onto the contract's two statuses — a judgement call, since two of the five are successful runs that produced no pull request.

#### Acceptance Criteria

- [ ] All four attributes set on the root span using constants from the generated contract, never string literals.
- [ ] Attributes are set in a `finally` block, so failed and crashed runs still emit.
- [ ] Result mapping implemented exactly: `success`→(`success`,`pr`,url); `no_updates`→(`success`,`none`,—); `pr_already_open`→(`success`,`pr`,existing url); `tests_failing`→(`failed`,`none`,—); `error`→(`failed`,`none`,—).
- [ ] `llipe.subject.id` equals the normalized `subject_id`, matching the `SUBJECT#` key.
- [ ] `llipe.outcome.url` is empty rather than absent when there is no outcome.
- [ ] A completed run's span is retrievable from the span destination with all four attributes.
- [ ] Token, latency, and model attributes are present from ADOT auto-instrumentation without agent code.

#### Business Rules

- `no_updates` is a **successful** run with nothing to do. Mapping it to `failed` would make a healthy fleet look broken most weeks.
- `pr_already_open` is a correct no-op and the PR is still the useful artefact.

#### Technical Notes

- `trace.get_current_span()` inside the worker thread — confirm the root span is the one being annotated, not a thread-local child.
- If the span is not the root, propagate the root span reference into the worker explicitly.

#### Testing Requirements

- **Unit Tests:** Result-to-attribute mapping for all five results; attributes emitted on the exception path; attribute names sourced from generated constants.
- **Integration Tests:** In-memory OTel span exporter asserting the four attributes on the root span.
- **Manual/UI Testing:** Query the span destination after a real run and confirm all four attributes plus `gen_ai.usage.*`.
- **Edge-Case Matrix:** Run failing before `subject_id` is known; run with no model invocation (deterministic happy path, zero tokens); `pr_url` unexpectedly `None` on a `success` result; run cut off at `maxLifetime` (no terminal attributes expected).
- **Acceptance-Criteria Mapping:** AC1–5 → `uv run pytest` with the in-memory exporter; AC6–7 → documented post-deploy span query.
- **Execution Commands:** `uv run pytest`, Logs Insights query against `SPANS_LOG_GROUP`

#### Migration Requirements

Not applicable.

#### Implementation Steps

1. Import `LLIPE` constants from the generated contract.
2. Result-to-contract mapping function, unit tested standalone.
3. Set attributes in `finally`.
4. Verify the annotated span is the root span from the worker thread.
5. In-memory exporter integration test.
6. Post-deploy verification query.

#### Files to Create/Modify

- `agents/dep-updater/emission.py`, `agents/dep-updater/main.py`
- `agents/dep-updater/tests/test_emission.py`

#### Definition of Done Checklist

- [ ] Code implemented per technical guidelines
- [ ] Tests written and passing
- [ ] Quality gates passing
- [ ] Code reviewed and approved
- [ ] Acceptance criteria verified, including a real span carrying all four attributes
- [ ] Pull Request created and merged

---

### Story S-011: Agent stamps its outcome into DynamoDB

**Priority:** Critical
**Estimated Size:** S
**Dependencies:** S-003, S-004, S-009

#### User Story

As the operator,
I want the agent to write `last_status` and `last_outcome_url` when it finishes,
So that runs close out instead of every run eventually reading as `incomplete`.

#### Context

PRD §8.2. This is the only completion signal in a fire-and-forget model. The write is deliberately narrow: `UpdateExpression` on two attributes, never `PutItem`, because a `PutItem` would replace the item and erase the operator's `enabled` and `params`.

#### Acceptance Criteria

- [ ] On completion the agent issues `UpdateItem` on `last_status` and `last_outcome_url` only.
- [ ] The write happens in a `finally` block, so failures close out too.
- [ ] No `PutItem` call exists anywhere in agent code.
- [ ] The target item is addressed by normalized `subject_id` and canonical agent name.
- [ ] A conditional expression ensures the item exists; a missing item logs an error rather than creating one.
- [ ] A failed DynamoDB write is logged at `error` and does not mask the run's actual result.
- [ ] After a real run, the item shows the correct `last_status` while `enabled` and `params` are untouched.

#### Business Rules

- Agents write exactly two attributes. Anything else is a policy violation and should fail against the S-004 role.
- Terminal writes belong in `finally` alongside the span attributes.

#### Technical Notes

- Uses `agent-exec-role` from S-004, so the narrow permission is exercised in practice, not just tested.
- Do not retry blindly on `ConditionalCheckFailed` — it means the item is genuinely gone.

#### Testing Requirements

- **Unit Tests:** Update expression contains only the two attributes; called on success and failure paths; conditional expression present.
- **Integration Tests:** Real write under `agent-exec-role`; assert `enabled` and `params` unchanged; assert an attempted write to `enabled` is denied.
- **Manual/UI Testing:** Inspect the item after a real run.
- **Edge-Case Matrix:** Item deleted mid-run; DynamoDB throttling; concurrent orchestrator write to `last_status`; outcome URL absent.
- **Acceptance-Criteria Mapping:** AC1–6 → `uv run pytest`; AC7 → integration test plus manual inspection.
- **Execution Commands:** `uv run pytest`, `pnpm --filter infra run test:integration -- agent-writes`

#### Migration Requirements

No schema change — writes to existing attributes defined in S-003. Opt-out rationale: the attributes are part of the item shape created by the seed script, so no migration artifact is required.

#### Implementation Steps

1. DynamoDB client scoped to the two-attribute update.
2. Call from the pipeline's `finally` block.
3. Conditional expression on item existence.
4. Error handling that preserves the run result.
5. Integration tests including the denial case.

#### Files to Create/Modify

- `agents/dep-updater/outcome_store.py`, `agents/dep-updater/main.py`
- `agents/dep-updater/tests/test_outcome_store.py`

#### Definition of Done Checklist

- [ ] Code implemented per technical guidelines
- [ ] Tests written and passing
- [ ] Quality gates passing
- [ ] Code reviewed and approved
- [ ] Acceptance criteria verified, including that config attributes are untouched
- [ ] Pull Request created and merged

---

### Story S-012: Verify telemetry assumptions and pin the span field mapping

**Priority:** Critical
**Estimated Size:** S
**Dependencies:** S-005, S-007, S-010, S-011

#### User Story

As the operator,
I want the actual shape of emitted spans confirmed and encoded in one file,
So that the read path is built against verified field paths instead of guesses.

#### Context

Spec §8.2 states plainly that the Logs Insights field paths are **unverified**: whether `attributes.` is the right prefix, how nesting works, the real duration field name, and whether AgentCore's automatic `session.id` injection is actually present. Three design assumptions ride on this, and spec §19.3 puts it before the orchestrator and the read path deliberately — one deployed run answers all of it, and discovering a wrong assumption later means rewriting the query layer.

This story is a spike with a concrete deliverable: `SPAN_FIELDS` populated with verified paths and a fixture captured from real output.

#### Acceptance Criteria

- [ ] A real run's spans are retrieved from `SPANS_LOG_GROUP` and one raw span is committed as a test fixture.
- [ ] `session.id` presence is confirmed or refuted. If absent, `llipe.session.id` is added to agent emission and the contract, and the change is recorded in the PRD changelog.
- [ ] Verified field paths for subject, status, outcome type, outcome URL, session id, model id, input/output tokens, duration, service name, and timestamp are recorded in `SPAN_FIELDS`.
- [ ] Confirmed whether `gen_ai.usage.*` sits on child spans as expected (spec F2) and whether root spans can be identified by attribute presence.
- [ ] A working Logs Insights query returns at least one complete run row end to end.
- [ ] `HealthyBusy` was observed during the run and the run survived past 5 minutes, confirming S-007 in the deployed environment.
- [ ] Findings written up: assumptions confirmed, refuted, and any newly surfaced.
- [ ] Spec §8.2's unverified-field warning is replaced with verified paths, and the spec changelog updated.

#### Business Rules

- No read-path story starts before this completes.
- If `session.id` is absent, the explicit fallback ships in this story rather than being deferred.

#### Technical Notes

- Capture the raw span JSON verbatim; it becomes the fixture every mapper test runs against.
- Run against a repository whose pipeline exceeds 10 minutes so the liveness confirmation is meaningful.
- Expect the deterministic happy path to produce zero model spans; verify a token-consuming run separately by forcing a test failure.

#### Testing Requirements

- **Unit Tests:** Mapper against the committed fixture, asserting every field resolves.
- **Integration Tests:** Live Logs Insights query returning a complete row.
- **Manual/UI Testing:** Inspect raw span output; poll `/ping` during the run.
- **Edge-Case Matrix:** Run with zero model invocations (no `gen_ai.*` spans); run with multiple model invocations; failed run's span; run cut off at `maxLifetime`.
- **Acceptance-Criteria Mapping:** AC1–5 → fixture + integration query; AC6 → observed ping status and run duration; AC7–8 → committed findings document and updated spec.
- **Execution Commands:** `pnpm --filter control-plane run test:unit -- spans`, ad-hoc Logs Insights query

#### Migration Requirements

Not applicable.

#### Implementation Steps

1. Trigger a long run with a forced test failure to guarantee model spans.
2. Retrieve raw spans; commit one as a fixture.
3. Confirm or refute `session.id`; implement the fallback if needed.
4. Populate `SPAN_FIELDS` with verified paths.
5. Build and validate the run-list query against real data.
6. Confirm `HealthyBusy` and survival past 5 minutes.
7. Write findings; update spec §8.2 and its changelog.

#### Files to Create/Modify

- `packages/shared/src/span/fields.ts`
- `apps/control-plane/src/server/aws/spans/__fixtures__/root-span.json`
- `workstream/findings-telemetry-verification.md`
- `workstream/specification-agent-control-plane-v1.md` (§8.2 + changelog)

#### Definition of Done Checklist

- [ ] Verified field paths committed
- [ ] Fixture captured from real output
- [ ] `session.id` question answered and, if needed, fallback shipped
- [ ] Liveness fix confirmed in the deployed environment
- [ ] Findings documented; spec updated with changelog row
- [ ] Code reviewed and approved
- [ ] Pull Request created and merged

---

# Phase 4 — Orchestration

### Story S-013: Orchestrator Lambda driven by DynamoDB scope

**Priority:** Critical
**Estimated Size:** L
**Dependencies:** S-002, S-003, S-012

#### User Story

As the operator,
I want a scheduled orchestrator that reads the enabled repository list from DynamoDB and fans out with a unique session per run,
So that changing an agent's scope is a data change rather than a deploy.

#### Context

This story delivers PRD §1's first problem directly: the reference implementation reads `REPOS` from an environment variable set in the CDK stack, so adding a repository is a code change and a deploy. It also fixes three defects in the reference fan-out (spec §19.2 C1, C7, C8) that would each independently break the product.

#### Acceptance Criteria

- [ ] Lambda queries `GSI1 pk = "AGENT#<name>"` filtered `enabled = true`; no `REPOS` env var remains.
- [ ] `session_id` comes from `buildSessionId(agent, repo, scheduledAt)` — unique per run, ≥33 chars, deterministic for a given scheduled occurrence.
- [ ] Before each invocation, `UpdateItem` stamps `last_session_id`, `last_run_at`, `last_status="running"`.
- [ ] Invocation is fire-and-forget; the response body is never read.
- [ ] Bounded concurrency pool of 4, configurable via `ORCHESTRATOR_CONCURRENCY`.
- [ ] One repository failing does not prevent the others being invoked.
- [ ] A synchronous invocation failure walks the row back to `last_status="failed"` rather than leaving it `running`.
- [ ] Global agent params from `AGENT#<name>/CONFIG` merge with per-subject `params`, subject-level winning.
- [ ] EventBridge Scheduler rule per agent, cron-configured, passing the agent name and `scheduledAt`.
- [ ] Lambda timeout 60 s; it invokes and returns rather than waiting.
- [ ] Written in TypeScript, importing `buildSessionId` and the schema from `packages/shared`.
- [ ] Structured JSON logs with `session_id` per invocation, and a summary line with invoked/skipped counts.

#### Business Rules

- The DynamoDB stamp happens **before** invocation. Reversing the order loses the run entirely if the Lambda dies between the two calls — an agent running with no row pointing at it, and no `incomplete` detection possible because that derivation reads a row that would not exist.
- Never blind-retry `InvokeAgentRuntime`: a retry after an ambiguous timeout can double-invoke an agent that already started, producing two runs against one repository under one `session_id`.
- Each repository is an independent run.

#### Technical Notes

- Replaces `lambda/trigger/handler.py`; the reference logic is largely superseded by these changes.
- `scheduledAt` from the EventBridge event, not `Date.now()`, so a Lambda retry of the same occurrence is idempotent.
- Uses `orchestrator-role` from S-004.

#### Testing Requirements

- **Unit Tests:** `buildSessionId` integration; params merge precedence; pool bounds concurrency to 4; ordering of stamp-then-invoke.
- **Integration Tests:** With `aws-sdk-client-mock` — full fan-out over N repositories; one repository throwing while the rest proceed; failure walk-back to `failed`; disabled repositories excluded; `scheduledAt` retry produces the identical `session_id`.
- **Manual/UI Testing:** Trigger the schedule manually; confirm N runs start and DynamoDB rows stamp correctly.
- **Edge-Case Matrix:** Zero enabled repositories; a single repository; more repositories than pool size; DynamoDB stamp failing (skip and continue); invocation timing out ambiguously (no retry); malformed `params` in a row.
- **Acceptance-Criteria Mapping:** AC1–8, AC11–12 → `pnpm --filter orchestrator run test`; AC9–10 → CDK snapshot; end-to-end → manual trigger.
- **Execution Commands:** `pnpm --filter orchestrator run test`, `pnpm --filter infra run cdk diff`

#### Migration Requirements

No schema change. Operational migration: the reference `REPOS` env var is removed and its contents must already be seeded into DynamoDB by S-003. Verify parity between the old list and the seeded rows before deleting the variable, and record that comparison in the PR.

#### Implementation Steps

1. TypeScript Lambda scaffold in `infra/orchestrator/`.
2. GSI1 query with the `enabled` filter.
3. Params merge from global CONFIG + subject row.
4. Stamp-then-invoke per repository, fire-and-forget.
5. Bounded concurrency pool with per-repo try/catch.
6. Failure walk-back path.
7. Structured logging.
8. EventBridge Scheduler rule in CDK.
9. Unit and mocked-integration tests.
10. Manual trigger; verify parity with the old `REPOS` list.

#### Files to Create/Modify

- `infra/orchestrator/src/{handler,scope-query,params,pool,session}.ts`
- `infra/orchestrator/test/*.test.ts`
- `infra/lib/orchestration-stack.ts`

#### Definition of Done Checklist

- [ ] Code implemented per technical guidelines
- [ ] Unit/integration/manual/edge-case tests written and passing
- [ ] Quality gates passing
- [ ] Code reviewed and approved
- [ ] Acceptance criteria verified
- [ ] Parity with the previous `REPOS` list confirmed and recorded
- [ ] Pull Request created and merged

---

# Phase 5 — Control Plane Foundation

### Story S-014: App shell with Cloudflare Access JWT validation

**Priority:** Critical
**Estimated Size:** M
**Dependencies:** S-001

#### User Story

As the operator,
I want the application to reject every request without a valid Cloudflare Access token,
So that the tool is not readable by anyone who finds its hostname.

#### Context

PRD §12.1 and spec §7. Authentication comes first because everything else sits behind it, and because a data view shipped before the gate is a data view that was briefly public. Validation and origin lockdown are two independent controls against the same threat; this story delivers the first, S-024 the second.

#### Acceptance Criteria

- [ ] Next.js App Router app with `output: 'standalone'`.
- [ ] Middleware verifies `Cf-Access-Jwt-Assertion` on every request except `/healthz` and static assets.
- [ ] JWKS fetched from the team domain and cached; unknown `kid` triggers at most one refetch.
- [ ] `algorithms: ['RS256']` as an explicit allowlist — the token's own `alg` is never trusted.
- [ ] `iss` verified against the team domain, `aud` against the Access AUD tag, `exp`/`iat` enforced.
- [ ] Missing header → denied. Invalid signature → denied. JWKS unreachable → **denied** (fail closed).
- [ ] `/healthz` returns 200 without auth and touches no AWS service or data.
- [ ] `jose` is used rather than `jsonwebtoken`, for Edge-runtime compatibility.
- [ ] App shell renders a slim top bar with Agents and Repos navigation; `/` redirects to `/agents`.
- [ ] All data routes set `export const dynamic = 'force-dynamic'`.

#### Business Rules

- Fail closed on every path, including infrastructure failure. A JWKS outage must not become an open door.
- One authenticated role; no authorization model (PRD §10). That is a decision about distinctions among authenticated users, not permission to skip authentication.
- Static prerendering of a data route would bake one operator's data into the build and serve it stale forever.

#### Technical Notes

- Middleware runs in the Edge runtime, which has Web Crypto but not Node's `crypto`.
- Extract verification into a helper so S-022's Server Actions can re-verify without duplicating logic.

#### Testing Requirements

- **Unit Tests:** Verification helper across valid, expired, wrong `aud`, wrong `iss`, missing header, unknown `kid`, `alg: none`, `alg` mismatch, malformed token, and JWKS-unreachable — **each must deny**.
- **Integration Tests:** Middleware denies an unauthenticated request to a data route and allows `/healthz`.
- **Manual/UI Testing:** Deployed behind Access, confirm redirect to login; confirm direct request without the header is rejected.
- **Edge-Case Matrix:** Token valid but expired by one second; clock skew within tolerance; two concurrent requests during a JWKS refetch; header present but empty.
- **Acceptance-Criteria Mapping:** AC2–8 → `pnpm --filter control-plane run test:unit -- auth`; AC1, AC9–10 → build output plus E2E smoke.
- **Execution Commands:** `pnpm --filter control-plane run test:unit -- auth`, `pnpm run validate`

#### Migration Requirements

Not applicable.

#### Implementation Steps

1. Next.js app with standalone output and strict TS.
2. `jose` JWKS setup with caching.
3. Verification helper with the full claim and algorithm checks.
4. Middleware with matcher excluding `/healthz` and static assets.
5. `/healthz` route handler.
6. App shell layout, top bar, `/` redirect.
7. Exhaustive negative unit tests.

#### Files to Create/Modify

- `apps/control-plane/{next.config.ts,src/middleware.ts}`
- `apps/control-plane/src/server/auth/{verify-access-jwt.ts,verify-access-jwt.test.ts}`
- `apps/control-plane/src/app/{layout.tsx,page.tsx,healthz/route.ts}`

#### Definition of Done Checklist

- [ ] Code implemented per technical guidelines
- [ ] All negative auth cases tested and denying
- [ ] Quality gates passing
- [ ] Code reviewed and approved
- [ ] Acceptance criteria verified
- [ ] Pull Request created and merged

---

### Story S-015: AWS adapter layer, credentials, and TTL cache

**Priority:** Critical
**Estimated Size:** M
**Dependencies:** S-002, S-014

#### User Story

As the operator,
I want typed adapters over each AWS service behind a single-flight TTL cache,
So that views are fast, quota-safe, and testable without AWS.

#### Context

Spec §4.2, §9, §11.1. Single-flight matters more than the TTL: without it, four server components requesting the same 30-day cost aggregate fire four Logs Insights queries against a quota-limited API on every cold load.

#### Acceptance Criteria

- [ ] Credentials module resolving Fly OIDC `AssumeRoleWithWebIdentity`, falling back to env credentials, isolated so the choice touches one file.
- [ ] Adapters for resource tagging, AgentCore control, CloudWatch Logs (Insights and `FilterLogEvents`), and DynamoDB.
- [ ] Adapters return domain types; no AWS SDK type escapes `src/server/aws/`.
- [ ] Agent inventory adapter filters `agent:managed=true` and returns name, domain, and runtime ARN.
- [ ] Runtime adapter returns `lifecycleConfiguration.maxLifetime`, defaulting to 28800 s when absent.
- [ ] TTL cache with 5-minute expiry, single-flight de-duplication, and an LRU cap of 500 entries.
- [ ] Cached: inventory, runtime detail, run queries, 30-day cost. Uncached: execution logs and DynamoDB configuration reads.
- [ ] Retries use jittered exponential backoff on throttling and 5xx only; validation errors are never retried.
- [ ] Repository layer exposes intent-named methods (`getAgentsForSubject`, `getEnabledSubjects`) rather than queries, and issues no `Scan`.
- [ ] `ReadOutcome<T>` union with `ok | empty | timeout | error` including a correlation id.

#### Business Rules

- Logs and configuration reads stay uncached — they are read precisely when the operator needs current truth.
- `Query` only. A `Scan` is a defect.
- Raw AWS error text never reaches the client; it leaks ARNs and account ids.

#### Technical Notes

- Cache key must include the full query shape: agent or repo, time range, status filter.
- Use `@aws-sdk/lib-dynamodb` for marshalling; never interpolate expression strings.
- Modular SDK client imports only, never the umbrella package.

#### Testing Requirements

- **Unit Tests:** Cache hit/miss/expiry; single-flight collapses N concurrent calls into one upstream call; LRU eviction; correlation id generation; `maxLifetime` default.
- **Integration Tests:** Each adapter against `aws-sdk-client-mock`, including throttling-then-success retry and non-retry of validation errors.
- **Manual/UI Testing:** None directly.
- **Edge-Case Matrix:** Concurrent identical requests; cache expiry mid-flight; adapter throwing after retries exhausted; empty tag result; runtime missing `lifecycleConfiguration`; DynamoDB pagination beyond one page.
- **Acceptance-Criteria Mapping:** AC1–10 → `pnpm --filter control-plane run test:unit` and `test:integration`; AC9 no-Scan → test asserting no `ScanCommand` is ever sent.
- **Execution Commands:** `pnpm --filter control-plane run test:unit`, `pnpm --filter control-plane run test:integration`

#### Migration Requirements

Not applicable.

#### Implementation Steps

1. Credentials provider module.
2. TTL cache with single-flight and LRU.
3. Adapter per service returning domain types.
4. Repository layer over DynamoDB with key builders from `shared`.
5. `ReadOutcome` type and error classification.
6. Retry policy helper.
7. Unit and mocked-integration tests including a no-`Scan` assertion.

#### Files to Create/Modify

- `apps/control-plane/src/server/aws/{credentials,tagging,agentcore,logs,dynamodb}.ts`
- `apps/control-plane/src/server/cache/ttl-cache.ts`
- `apps/control-plane/src/server/repository/scope-repository.ts`
- `apps/control-plane/src/server/types/read-outcome.ts`
- corresponding `*.test.ts`

#### Definition of Done Checklist

- [ ] Code implemented per technical guidelines
- [ ] Unit/integration/edge-case tests written and passing
- [ ] Quality gates passing
- [ ] Code reviewed and approved
- [ ] Acceptance criteria verified, including single-flight and no-`Scan`
- [ ] Pull Request created and merged

---

### Story S-016: Design-system primitives — tokens, `DataTable`, `StatusBadge`

**Priority:** High
**Estimated Size:** M
**Dependencies:** S-014

#### User Story

As the operator,
I want one table implementation and one status indicator built on design tokens,
So that four views stay consistent and status is never communicated by colour alone.

#### Context

DESIGN.md §2–3. One shared `DataTable` is a stated rule: a second table implementation is a defect. `StatusBadge` is the single place status maps to visuals, which is what makes the accessibility guarantee enforceable in one file rather than four.

#### Acceptance Criteria

- [ ] Tailwind + shadcn/ui configured with semantic tokens; light and dark both legible.
- [ ] Four status tokens defined: `--status-running`, `--status-success`, `--status-failed`, `--status-incomplete`.
- [ ] `StatusBadge` renders colour **and** a text label always; `incomplete` is amber, distinct from `failed` red.
- [ ] Status token contrast verified at 4.5:1 for text and 3:1 for UI boundaries, in both schemes.
- [ ] `DataTable` built on TanStack Table with sorting, row click, and built-in loading/empty/error/timed-out states.
- [ ] `DataTable` supports keyboard navigation: arrow keys move between rows, `Enter`/`Space` activates.
- [ ] Real `<table>` semantics with proper headers, not a grid of divs.
- [ ] Numeric columns use tabular figures and right alignment.
- [ ] `RelativeTime` shows relative text with absolute UTC in `title`.
- [ ] `CostEstimate` renders exact, `≥` partial with marker, or `unknown` — never `$0.00` for an unpriced run.
- [ ] `prefers-reduced-motion` respected; no animated status indicator.
- [ ] No hardcoded colour, spacing, or radius value in any component.

#### Business Rules

- Status visuals come from `StatusBadge`, nowhere else.
- All four tables use `DataTable`.
- Status is never colour-only — roughly one in twelve men has a colour vision deficiency, red/green being the common axis, which is exactly the pair doing the most work here.

#### Technical Notes

- Four required states live in `DataTable` rather than in each view, so no view can forget one.
- `timed-out` is a distinct state from `empty` by design; the component must accept it as such.

#### Testing Requirements

- **Unit Tests:** `StatusBadge` renders a label for all four statuses; `CostEstimate` across complete/partial/unknown; `RelativeTime` formatting and title attribute.
- **Integration Tests:** `DataTable` renders each of the four states; row click fires; sorting works.
- **Manual/UI Testing:** Keyboard-only navigation through a table and into a row; screen-reader pass over table semantics; contrast check in both schemes.
- **Edge-Case Matrix:** Zero rows; single row; very long repo name; unknown status value; `CostEstimate` with `usd: 0` and `complete: true` (a genuinely free run — must render `$0.00`, unlike the unpriced case).
- **Acceptance-Criteria Mapping:** AC2–3, AC9–10 → unit tests; AC5–8, AC11 → component integration tests; AC4 → documented contrast measurements; AC12 → lint rule or review.
- **Execution Commands:** `pnpm --filter control-plane run test:unit -- components`, `pnpm --filter control-plane run test:e2e -- a11y`

#### Migration Requirements

Not applicable.

#### Implementation Steps

1. Tailwind + shadcn/ui setup; token definitions including the four status pairs.
2. Verify and record contrast ratios.
3. `StatusBadge` with mandatory label.
4. `DataTable` with the four states, keyboard nav, table semantics.
5. `RelativeTime`, `CostEstimate`.
6. Reduced-motion handling.
7. Component tests and an accessibility smoke test.

#### Files to Create/Modify

- `apps/control-plane/{tailwind.config.ts,src/app/globals.css}`
- `apps/control-plane/src/components/{DataTable,StatusBadge,RelativeTime,CostEstimate}.tsx`
- corresponding `*.test.tsx`

#### Definition of Done Checklist

- [ ] Code implemented per DESIGN.md
- [ ] Tests written and passing
- [ ] Quality gates passing
- [ ] Contrast measured and recorded for both schemes
- [ ] Keyboard-only path verified manually
- [ ] Code reviewed and approved
- [ ] Pull Request created and merged

---

# Phase 6 — Read Path

### Story S-017: Logs Insights run query and span-to-run mapping

**Priority:** Critical
**Estimated Size:** L
**Dependencies:** S-012, S-015

#### User Story

As the operator,
I want completed runs read out of CloudWatch spans with tokens aggregated per model,
So that run history exists as data the views can render.

#### Context

Spec §8.2. Tokens live on child spans, not the root (F2), so this is an aggregation grouped by `(session_id, model_id)` rather than a row projection. Field paths come from S-012's verified `SPAN_FIELDS`, not from assumption.

#### Acceptance Criteria

- [ ] Run-list query aggregates by `session_id` and `model_id`, summing input and output tokens.
- [ ] Query reads its log group from `SPANS_LOG_GROUP` config, with no hardcoded group name.
- [ ] `StartQuery` → poll `GetQueryResults` with capped exponential backoff and a 25-second overall deadline.
- [ ] Timeout returns `{ kind: 'timeout' }` and calls `StopQuery`; it is never conflated with an empty result.
- [ ] `Failed` and `Cancelled` statuses map to `{ kind: 'error' }` with a correlation id.
- [ ] Mapper folds per-model rows into one `Run` per `session_id` with a per-model usage breakdown retained.
- [ ] Mapper is a pure function tested against S-012's committed fixture.
- [ ] Date range capped at 30 days; query `limit 5000`.
- [ ] A single-run trace query supports the run panel's span timeline, returning per-call latency and tokens.
- [ ] Results cached 5 minutes keyed by the full filter shape.

#### Business Rules

- `timeout` and `empty` are different facts and must stay distinguishable to the UI — the operator needs to know which question to ask.
- All field access goes through `SPAN_FIELDS`, so a future span-format change is one edit.

#### Technical Notes

- Poll with backoff rather than a tight loop; Logs Insights is metered.
- Runs with zero model spans are normal for this agent's deterministic happy path, so zero tokens is valid data, not a mapping failure.

#### Testing Requirements

- **Unit Tests:** Mapper against the fixture; per-model folding for single and multi-model runs; zero-token run; missing optional attribute; malformed row skipped with a `warn`.
- **Integration Tests:** With `aws-sdk-client-mock` — `Complete` after several `Running` polls; `Failed`; `Cancelled`; deadline exceeded triggering `StopQuery` and `timeout`.
- **Manual/UI Testing:** Query real data and compare a row against the AWS console.
- **Edge-Case Matrix:** Empty result set; 5000-row cap reached; range exceeding 30 days rejected; concurrent identical queries collapsing via single-flight; span missing `session.id`.
- **Acceptance-Criteria Mapping:** AC1–8, AC10 → unit and mocked-integration tests; AC9 → trace query test; real-data check → manual.
- **Execution Commands:** `pnpm --filter control-plane run test:unit -- spans`, `pnpm --filter control-plane run test:integration -- insights`

#### Migration Requirements

Not applicable.

#### Implementation Steps

1. Query builder reading `SPAN_FIELDS` and config.
2. `StartQuery`/poll/`StopQuery` executor with deadline and backoff.
3. `QueryOutcome` mapping including the distinct `timeout`.
4. Pure span-to-`Run` mapper with per-model folding.
5. Single-run trace query for the timeline.
6. Cache integration.
7. Tests against the fixture and mocked clients.

#### Files to Create/Modify

- `apps/control-plane/src/server/aws/spans/{query,executor,mapper}.ts`
- `apps/control-plane/src/server/aws/spans/*.test.ts`

#### Definition of Done Checklist

- [ ] Code implemented per technical guidelines
- [ ] Unit/integration/edge-case tests written and passing
- [ ] Quality gates passing
- [ ] Code reviewed and approved
- [ ] Acceptance criteria verified, including `timeout` distinct from `empty`
- [ ] Pull Request created and merged

---

### Story S-018: Run list merge, status derivation, and cost estimation

**Priority:** Critical
**Estimated Size:** M
**Dependencies:** S-015, S-017

#### User Story

As the operator,
I want in-flight and cut-off runs shown alongside completed ones, with an honest cost estimate,
So that a dead agent is visible instead of missing.

#### Context

Spec §8.3 (F3). Spans only contain completed runs; `running` and `incomplete` exist solely in DynamoDB. A span-only implementation would silently never display two of the four statuses. Cost is best-effort per PRD v1.2, with gaps flagged rather than hidden.

#### Acceptance Criteria

- [ ] Run list merges span-derived runs with DynamoDB configuration rows, keyed by `session_id`.
- [ ] Span rows win on conflict, because they carry tokens and duration.
- [ ] Config-only rows are included **regardless** of `last_status`, not only `running`.
- [ ] Status derived via `deriveStatus` using the agent's per-agent `maxLifetime` from S-015.
- [ ] Config-only rows show tokens and cost as unknown rather than zero.
- [ ] Merged list sorted by start time descending; status and date-range filters applied after merge.
- [ ] `estimateRunCost` sums priced models, returns `usd: null` when nothing is priced, and sets `complete: false` when any model lacks pricing.
- [ ] Pricing table is a versioned JSON file keyed by `model_id`, loaded once.
- [ ] An unpriced `model_id` logs at `warn` and never renders as `$0.00`.
- [ ] 30-day per-agent cost aggregate available for the Agents list, cached.

#### Business Rules

- Including config-only rows regardless of status covers two real cases: span ingestion lag, where a run would otherwise vanish from history and reappear; and death before emission, where the run exists nowhere else.
- Only the latest run per `(subject, agent)` pair is visible as in-flight. That is sufficient because one schedule per agent means at most one concurrent run per pair — an assumption that breaks if an agent ever gets multiple schedules.
- `incomplete` is never persisted.

#### Technical Notes

- `mergeRuns` and `estimateRunCost` are pure and tested without AWS.
- Pricing values must be populated from AWS Bedrock pricing; the committed file ships with placeholders and a test asserting every observed `model_id` has an entry.

#### Testing Requirements

- **Unit Tests:** `mergeRuns` across in-both, spans-only, and config-only cases; sort order; filter application after merge; `estimateRunCost` for complete, partial, and unpriced; `deriveStatus` wired with per-agent `maxLifetime`.
- **Integration Tests:** Full read path with mocked Insights and DynamoDB producing a merged list containing one completed, one running, and one `incomplete` run.
- **Manual/UI Testing:** Compare a merged list against DynamoDB and the console for one agent.
- **Edge-Case Matrix:** Duplicate `session_id` in both sources; config row with null `last_session_id`; run whose `last_run_at` sits exactly on the `maxLifetime + grace` boundary; genuinely free run (`usd: 0`, `complete: true`) rendering `$0.00`; all models unpriced.
- **Acceptance-Criteria Mapping:** AC1–7, AC9 → `pnpm --filter control-plane run test:unit -- runs`; AC8, AC10 → integration tests; pricing completeness → dedicated test.
- **Execution Commands:** `pnpm --filter control-plane run test:unit -- runs`, `pnpm --filter control-plane run test:integration -- read-path`

#### Migration Requirements

Not applicable.

#### Implementation Steps

1. `mergeRuns` pure function.
2. Config-row-to-`Run` projection with `deriveStatus` and per-agent `maxLifetime`.
3. Filter and sort applied post-merge.
4. Pricing table file and loader.
5. `estimateRunCost` with the completeness flag.
6. 30-day aggregate query and cache entry.
7. `warn` logging for unpriced models.
8. Unit and integration tests.

#### Files to Create/Modify

- `apps/control-plane/src/server/runs/{merge,project-config-row,run-service}.ts`
- `apps/control-plane/src/lib/cost.ts`
- `apps/control-plane/pricing/pricing-v1.json`
- corresponding `*.test.ts`

#### Definition of Done Checklist

- [ ] Code implemented per technical guidelines
- [ ] Unit/integration/edge-case tests written and passing
- [ ] Quality gates passing
- [ ] Code reviewed and approved
- [ ] Acceptance criteria verified, including `running` and `incomplete` both appearing
- [ ] Pull Request created and merged

---

# Phase 7 — Views

### Story S-019: Agents list view

**Priority:** High
**Estimated Size:** M
**Dependencies:** S-016, S-018

#### User Story

As the operator,
I want one table of all managed agents with last run and 30-day cost,
So that I can assess the fleet at a glance without the AWS console.

#### Context

PRD §7.5 A. This is the landing view and the first place the whole read path is visible end to end.

#### Acceptance Criteria

- [ ] `/agents` lists one row per agent tagged `agent:managed=true`.
- [ ] Columns: name, domain, last run (relative), last run status, active repo count, estimated 30-day cost.
- [ ] Untagged agents are absent.
- [ ] Last run status uses `StatusBadge` and can show `incomplete`.
- [ ] Active repo count reflects `enabled = true` rows for that agent.
- [ ] 30-day cost renders per `CostEstimate` rules with an "estimated" column header.
- [ ] Row click navigates to `/agents/[name]`.
- [ ] Loading, empty, error, and timed-out states all render distinctly.
- [ ] Page is server-rendered and dynamic.

#### Business Rules

- Discovery is opt-in by tag; an untagged agent is invisible by design.
- Cost is labelled as an estimate and excludes runtime compute.

#### Technical Notes

- Uses `DataTable` from S-016 — no bespoke table.
- Streams so the table shell paints before the cost aggregate resolves.

#### Testing Requirements

- **Unit Tests:** Row view-model assembly from inventory plus config plus cost.
- **Integration Tests:** Page renders with mocked adapters; untagged agent excluded.
- **Manual/UI Testing:** Load against real data; confirm counts and costs against DynamoDB and the console.
- **Edge-Case Matrix:** Zero agents; agent with zero enabled repos; agent that has never run (no last run); cost unknown; Insights timeout.
- **Acceptance-Criteria Mapping:** AC1–7 → integration tests; AC8 → per-state E2E; AC9 → build output.
- **Execution Commands:** `pnpm --filter control-plane run test:integration -- agents`, `pnpm --filter control-plane run test:e2e -- agents`

#### Migration Requirements

Not applicable.

#### Implementation Steps

1. Server component fetching inventory, config counts, cost aggregate.
2. Row view-model assembly.
3. `DataTable` column definitions.
4. Streaming boundary for the cost column.
5. Row-click navigation.
6. Tests for all four async states.

#### Files to Create/Modify

- `apps/control-plane/src/app/agents/page.tsx`
- `apps/control-plane/src/components/agents/{AgentsTable.tsx,columns.tsx}`
- `apps/control-plane/src/server/agents/agent-summary-service.ts`
- corresponding tests

#### Definition of Done Checklist

- [ ] Code implemented per technical guidelines and DESIGN.md
- [ ] Tests written and passing, including all four async states
- [ ] Quality gates passing
- [ ] Code reviewed and approved
- [ ] Acceptance criteria verified
- [ ] Pull Request created and merged

---

### Story S-020: Agent detail — Runs tab with URL-persisted filters

**Priority:** High
**Estimated Size:** M
**Dependencies:** S-016, S-018

#### User Story

As the operator,
I want an agent's runs listed newest first and filterable by status and date range,
So that I can find recent failures quickly and share a link to what I found.

#### Context

PRD §7.5 B. Filters live in the URL (DESIGN.md §4) so reload restores the view and a specific failed run is a shareable link — and so server components read filters as props rather than the client re-fetching.

#### Acceptance Criteria

- [ ] `/agents/[name]?tab=runs` lists that agent's runs, date descending.
- [ ] Columns: date, repo, status, duration, tokens, estimated cost, output.
- [ ] Status filter and date-range filter serialize to `status`, `from`, `to` query params.
- [ ] Reloading restores filters exactly.
- [ ] Tabs switch between Runs and Repos via the `tab` param.
- [ ] Row click sets `run=<session_id>`, opening the panel from S-021.
- [ ] Duration renders in human units; tokens as a labelled `in / out` pair.
- [ ] Outcome renders as a type-labelled link; `outcome.type = "none"` shows a dash, not an empty cell.
- [ ] Date range defaults to 7 days and is capped at 30.
- [ ] All four async states render distinctly, with the timeout state suggesting a narrower range.

#### Business Rules

- Range cap of 30 days protects the query; the real ceiling is log retention.
- `running` and `incomplete` runs appear in this list, not just completed ones.

#### Technical Notes

- Read `searchParams` in the server component; no client fetching.
- Client-side pagination in TanStack over the fetched window — server-side pagination would re-run the query per page and burn quota.

#### Testing Requirements

- **Unit Tests:** Filter parsing and validation from search params; range clamping; column formatters.
- **Integration Tests:** Page renders with filters applied; invalid params fall back to defaults.
- **Manual/UI Testing:** Apply filters, reload, confirm restoration; copy the URL into a new tab.
- **Edge-Case Matrix:** `from` after `to`; range beyond 30 days; unknown status value; zero runs in range; timeout with a wide range.
- **Acceptance-Criteria Mapping:** AC1–2, AC7–9 → unit and integration; AC3–6 → E2E asserting URL state; AC10 → per-state E2E.
- **Execution Commands:** `pnpm --filter control-plane run test:integration -- agent-runs`, `pnpm --filter control-plane run test:e2e -- filters`

#### Migration Requirements

Not applicable.

#### Implementation Steps

1. Route with `searchParams`-driven filters and Zod validation.
2. Tab shell for Runs/Repos.
3. Runs `DataTable` columns and formatters.
4. Filter controls writing to the URL.
5. Row click setting `run`.
6. Tests including invalid-param fallbacks.

#### Files to Create/Modify

- `apps/control-plane/src/app/agents/[name]/page.tsx`
- `apps/control-plane/src/components/runs/{RunsTable.tsx,columns.tsx,RunFilters.tsx}`
- `apps/control-plane/src/lib/run-filters.ts`
- corresponding tests

#### Definition of Done Checklist

- [ ] Code implemented per technical guidelines and DESIGN.md
- [ ] Tests written and passing
- [ ] Quality gates passing
- [ ] Code reviewed and approved
- [ ] Acceptance criteria verified, including URL round-trip
- [ ] Pull Request created and merged

---

### Story S-021: Run side panel with span timeline and logs

**Priority:** High
**Estimated Size:** M
**Dependencies:** S-020

#### User Story

As the operator,
I want a run's metadata, span timeline, and logs in a panel that opens over the table,
So that I can reach a failure's cause without losing my place in the list.

#### Context

PRD §7.5 D and spec §10.3. This story is what delivers the "under 3 clicks to a failed run's logs" metric — a navigation that unmounted the list would cost a click coming back and lose the scroll position.

#### Acceptance Criteria

- [ ] Panel opens as a right-side sheet from any run row, driven by the `run` URL param.
- [ ] The table stays mounted with scroll position and filters intact.
- [ ] Metadata section shows agent, repo, `session_id`, status, duration, tokens, estimated cost, and outcome link, painting immediately from data already in hand.
- [ ] Span timeline shows model and tool calls with per-call latency and tokens, streamed in its own `Suspense` boundary.
- [ ] Logs come from `FilterLogEvents` filtered by `session_id`, uncached, in a separate `Suspense` boundary.
- [ ] `session_id` renders monospace, truncated, with a copy affordance and full value on hover.
- [ ] `Esc`, backdrop click, and explicit close all dismiss; focus returns to the originating row.
- [ ] Focus is trapped in the panel while open.
- [ ] Timeline and log sections each render their own loading, empty, error, and timeout states.
- [ ] Browser back closes the panel.
- [ ] Logs for a run whose agent died mid-way display up to the cut-off point without an error.

#### Business Rules

- Metadata must not wait on the two slow reads; awaiting all three produces a blank panel that reads as broken.
- Logs stay uncached because they are read mid-incident.

#### Technical Notes

- Panel state is a URL param, so first paint is server-rendered and history integration is free.
- Reaching logs from the list must be ≤3 clicks; verify by counting in the E2E test.

#### Testing Requirements

- **Unit Tests:** Log line parsing and rendering; timeline bar geometry from span durations; `session_id` truncation.
- **Integration Tests:** Panel renders with mocked timeline and log adapters; each async state per section.
- **Manual/UI Testing:** Keyboard-only open, navigate, close; screen-reader pass; confirm focus restoration.
- **Edge-Case Matrix:** Run with no child spans; run with 500 log lines; log fetch failing while metadata succeeds; `run` param referencing a nonexistent `session_id`; `incomplete` run with truncated logs.
- **Acceptance-Criteria Mapping:** AC1–6, AC9–11 → integration tests; AC7–8 → E2E accessibility test; ≤3 clicks → explicit E2E click count.
- **Execution Commands:** `pnpm --filter control-plane run test:integration -- run-panel`, `pnpm --filter control-plane run test:e2e -- run-panel`

#### Migration Requirements

Not applicable.

#### Implementation Steps

1. Sheet-based `RunPanel` driven by the `run` param.
2. Metadata section from row data.
3. `SpanTimeline` with its own Suspense boundary.
4. `LogViewer` with its own Suspense boundary.
5. Focus trap, restoration, and dismissal paths.
6. Per-section state handling.
7. E2E including the click count and scroll-preservation assertions.

#### Files to Create/Modify

- `apps/control-plane/src/components/runs/{RunPanel,SpanTimeline,LogViewer}.tsx`
- `apps/control-plane/src/server/runs/{trace-service,log-service}.ts`
- corresponding tests

#### Definition of Done Checklist

- [ ] Code implemented per technical guidelines and DESIGN.md
- [ ] Tests written and passing
- [ ] Quality gates passing
- [ ] Keyboard and focus behaviour verified manually
- [ ] ≤3 clicks from run list to logs demonstrated
- [ ] Code reviewed and approved
- [ ] Pull Request created and merged

---

### Story S-022: Scope configuration — Repos tab and write actions

**Priority:** Critical
**Estimated Size:** L
**Dependencies:** S-004, S-015, S-016

#### User Story

As the operator,
I want to toggle a repository's `enabled` state, edit its `params`, and add a repository by name,
So that changing an agent's scope takes seconds instead of a deploy.

#### Context

This story delivers PRD §1's first problem and the product's only write path. Spec §6 covers the three Server Actions; every one is a public endpoint regardless of how it looks in source.

#### Acceptance Criteria

- [ ] `/agents/[name]?tab=repos` lists that agent's repositories with columns: repo, `enabled` toggle, last run, last status, output.
- [ ] Toggling `enabled` writes to DynamoDB and reflects immediately, optimistically.
- [ ] A failed toggle reverts the optimistic state and shows an error naming the repository.
- [ ] `params` editor validates JSON client-side before enabling save; invalid JSON never reaches the server.
- [ ] Server re-validates `params` with `paramsSchemaFor(agent)`; unknown keys are **rejected**, not stripped.
- [ ] Adding a repository validates the name, normalizes it, and writes `META` plus `AGENT#` items transactionally.
- [ ] Adding a repository that is already in scope returns a `conflict` error rather than overwriting.
- [ ] All three actions re-verify the Access JWT before doing anything.
- [ ] All three actions parse input from an `unknown` parameter via Zod as their first statement.
- [ ] Actions return a discriminated result; raw AWS error text never reaches the client.
- [ ] Only `enabled` and `params` are ever written; no action touches any `last_*` attribute.
- [ ] `revalidatePath` targets only the affected route.
- [ ] Adding a repository end to end completes in under 30 seconds with no deploy.
- [ ] Scope writes log at `info` with before and after values.

#### Business Rules

- A silently failed toggle is worse than one that blocks: a repository the operator believes is enabled will simply never run, and nothing reports it.
- Unknown `params` keys are rejected so a typo cannot look accepted while doing nothing.
- Writing `last_*` from the front end is a bug — those belong to the orchestrator and the agent.

#### Technical Notes

- `TransactWriteItems` for the add path, per spec §8.5, so a subject can never exist without its `META` item.
- Scope changes are the only mutable state in the system and the only history not otherwise recoverable, which is why they are logged with values.

#### Testing Requirements

- **Unit Tests:** Input schemas for all three actions; params accept/reject; repo-name normalization and validation.
- **Integration Tests:** Each action against mocked DynamoDB — success, `not_found`, `conflict`, `unauthorized`; assert written attributes are exactly `enabled` or `params`; assert transactional add writes both items.
- **Manual/UI Testing:** Toggle a repo and confirm the next scheduled run honours it; add a repo and time the operation.
- **Edge-Case Matrix:** Toggle while another write is in flight; invalid JSON; valid JSON with unknown key; wrong-typed value; duplicate add; repo name needing normalization; action called without the auth header; DynamoDB throttling mid-write.
- **Acceptance-Criteria Mapping:** AC2–3 → E2E including the failure path; AC4–5, AC7, AC9–11 → unit and integration; AC8 → auth negative tests; AC13 → timed E2E; AC14 → log assertion.
- **Execution Commands:** `pnpm --filter control-plane run test:unit -- actions`, `pnpm --filter control-plane run test:integration -- actions`, `pnpm --filter control-plane run test:e2e -- scope`

#### Migration Requirements

No schema change — writes to attributes defined in S-003. Opt-out rationale: the add path creates new items using the shape the seed script already established, so no migration artifact is needed. The transactional write is covered by integration tests rather than a migration step.

#### Implementation Steps

1. Repos `DataTable` columns.
2. `setSubjectEnabled` action with JWT re-verification, Zod parse, conditional update.
3. `EnabledToggle` with optimistic update and rollback.
4. `setSubjectParams` action and `ParamsEditor` with client-side validation.
5. `addSubjectToAgent` action with transactional write and conflict handling.
6. `AddRepoForm`.
7. Structured `info` logging of before/after.
8. Unit, integration, and E2E tests including failure paths.

#### Files to Create/Modify

- `apps/control-plane/src/server/actions/scope.ts`
- `apps/control-plane/src/components/repos/{ReposTable,EnabledToggle,ParamsEditor,AddRepoForm}.tsx`
- corresponding tests

#### Definition of Done Checklist

- [ ] Code implemented per technical guidelines
- [ ] Unit/integration/manual/edge-case tests written and passing
- [ ] Quality gates passing
- [ ] Code reviewed and approved
- [ ] Acceptance criteria verified, including the sub-30-second add and the failed-toggle revert
- [ ] Pull Request created and merged

---

### Story S-023: Repos list and per-repository run view

**Priority:** Medium
**Estimated Size:** M
**Dependencies:** S-020, S-022

#### User Story

As the operator,
I want a list of repositories and the runs for any one of them,
So that I can ask what all agents did to a given repository.

#### Context

PRD §7.5 C. This is the axis AWS cannot provide and the reason the emission contract exists. Spec §5.3 A4 lists all subjects via `Query GSI1 pk = "META"` — no `Scan`.

#### Acceptance Criteria

- [ ] `/repos` lists one row per subject: repo, agents covering it, last activity, status.
- [ ] Subject list comes from `Query GSI1 pk = "META"`; no `Scan` is issued.
- [ ] Coverage is derived from per-agent GSI1 queries, agent count small.
- [ ] Row click navigates to `/repos/[repo]`.
- [ ] `/repos/[repo]` shows the same runs table as the agent view, filtered by repo, with an added agent column.
- [ ] Status and date-range filters behave identically and persist to the URL.
- [ ] Run panel opens from this table too, with the same behaviour.
- [ ] A subject with a `META` item but no agent pairs still appears, showing zero agents.
- [ ] All four async states render distinctly.

#### Business Rules

- Every subject must have a `META` item for this view to be complete, which is why S-003 and S-022 write it transactionally.
- The runs table implementation is shared with S-020, not duplicated.

#### Technical Notes

- Repo names appear as `org/repo` where ambiguity is possible, short form otherwise (DESIGN.md §5).
- Reuse `RunsTable` with a column-set flag rather than forking the component.

#### Testing Requirements

- **Unit Tests:** Coverage aggregation from per-agent query results; subject list assembly.
- **Integration Tests:** Page renders with mocked DynamoDB; assert no `ScanCommand` sent; subject with no agents appears.
- **Manual/UI Testing:** Cross-check one repository's agents and runs against DynamoDB.
- **Edge-Case Matrix:** Zero subjects; subject covered by multiple agents; subject with `META` only; repo name containing a slash in the route param; runs from two agents interleaved.
- **Acceptance-Criteria Mapping:** AC1–4, AC8 → integration; AC5–7 → E2E reusing the filter and panel specs; AC9 → per-state E2E.
- **Execution Commands:** `pnpm --filter control-plane run test:integration -- repos`, `pnpm --filter control-plane run test:e2e -- repos`

#### Migration Requirements

Not applicable.

#### Implementation Steps

1. Subject list service using the GSI1 `META` query.
2. Coverage aggregation across agents.
3. `/repos` table and row navigation.
4. `/repos/[repo]` reusing `RunsTable` with the agent column.
5. Filters and panel wiring.
6. Tests including the no-`Scan` assertion.

#### Files to Create/Modify

- `apps/control-plane/src/app/repos/{page.tsx,[repo]/page.tsx}`
- `apps/control-plane/src/components/repos/ReposListTable.tsx`
- `apps/control-plane/src/server/repos/subject-service.ts`
- corresponding tests

#### Definition of Done Checklist

- [ ] Code implemented per technical guidelines and DESIGN.md
- [ ] Tests written and passing, including no-`Scan`
- [ ] Quality gates passing
- [ ] Code reviewed and approved
- [ ] Acceptance criteria verified
- [ ] Pull Request created and merged

---

# Phase 8 — Deployment

### Story S-024: Fly deployment with Cloudflare Tunnel origin lockdown

**Priority:** Critical
**Estimated Size:** M
**Dependencies:** S-014, S-022

#### User Story

As the operator,
I want the app deployed to Fly behind Cloudflare Access with the origin unreachable directly,
So that JWT validation is not the only thing standing between the internet and my fleet.

#### Context

PRD §12.1. Validation (S-014) and origin lockdown are two independent controls against the same threat, and shipping with only one leaves a bypass: anyone who finds the `.fly.dev` hostname would otherwise reach the origin directly and Cloudflare Access would accomplish nothing.

#### Acceptance Criteria

- [ ] Multi-stage Dockerfile producing a standalone Next.js image; container under 512 MB memory in normal operation.
- [ ] `fly.toml` with a single machine and `/healthz` health check.
- [ ] Fly Machines OIDC assumes the control-plane role; no static AWS keys, or the fallback documented if OIDC proves unworkable.
- [ ] Cloudflare Access application configured in front of the app.
- [ ] Cloudflare Tunnel configured; **a direct request to the `.fly.dev` origin is refused**, verified explicitly.
- [ ] HTTPS only with HSTS enabled.
- [ ] All secrets via `fly secrets`; none in the image, repo, or build output.
- [ ] Deploy runs from the `apps/control-plane/**` CI workflow after `validate` passes.
- [ ] Rollback to a previous image verified once.
- [ ] Monthly infrastructure cost recorded and confirmed under USD 10.
- [ ] Observability runbook updated with deploy and rollback steps.

#### Business Rules

- Origin lockdown is not optional and not a follow-up.
- Rollback is cheap because the control plane is stateless — that property should be verified, not assumed.

#### Technical Notes

- Static-key fallback touches only the credentials module from S-015.
- Cost check is manual; there is no billing integration in v1.

#### Testing Requirements

- **Unit Tests:** None specific.
- **Integration Tests:** `/healthz` reachable unauthenticated; a data route unauthenticated is refused.
- **Manual/UI Testing:** Full login flow through Access; direct-origin request refused; rollback exercised; HSTS header confirmed.
- **Edge-Case Matrix:** Direct origin access attempt; expired Access session; container restart clearing cache with no data loss; OIDC token refresh after one hour; deploy during an in-flight request.
- **Acceptance-Criteria Mapping:** AC1–3, AC8 → CI deploy logs; AC4–6 → documented manual verification with evidence; AC9 → rollback record; AC10 → cost screenshot; AC11 → runbook diff.
- **Execution Commands:** `pnpm --filter control-plane run build`, `fly deploy`, `curl -I https://<app>.fly.dev` (expect refusal)

#### Migration Requirements

Not applicable.

#### Implementation Steps

1. Multi-stage Dockerfile for standalone output.
2. `fly.toml` with health check.
3. Fly OIDC → AWS role trust configuration.
4. Cloudflare Access application.
5. Cloudflare Tunnel; verify the origin is refused.
6. HSTS headers.
7. Secrets via `fly secrets`.
8. CI deploy step gated on `validate`.
9. Exercise rollback.
10. Record cost; update the runbook.

#### Files to Create/Modify

- `apps/control-plane/Dockerfile`
- `infra/control-plane.fly.toml`
- `.github/workflows/control-plane.yml`
- `docs/runbook-deployment.md`

#### Definition of Done Checklist

- [ ] Code implemented per technical guidelines
- [ ] Integration and manual verification complete
- [ ] Quality gates passing
- [ ] Direct-origin request demonstrated as refused
- [ ] Rollback exercised once
- [ ] Cost recorded under USD 10
- [ ] Code reviewed and approved
- [ ] Pull Request created and merged

---

## Execution Plan

| Phase | Stories | Sizes | Gate |
| --- | --- | --- | --- |
| 1 — Foundation | S-001, S-002 | M, M | Contract exists and CI enforces it |
| 2 — Infrastructure & data | S-003, S-004, S-005 | M, S, S | Table live, denials proven, spans arriving |
| 3 — Agent compatibility | S-006 … S-012 | M, S, S, S, S, S, S | **S-012 verifies telemetry assumptions** |
| 4 — Orchestration | S-013 | L | Scope changes need no deploy |
| 5 — Control plane foundation | S-014, S-015, S-016 | M, M, M | Auth closed, adapters cached, primitives ready |
| 6 — Read path | S-017, S-018 | L, M | All four statuses visible |
| 7 — Views | S-019 … S-023 | M, M, M, L, M | Both axes navigable, writes working |
| 8 — Deployment | S-024 | M | Two auth controls live |

**Total: 24 stories.** Roughly 44 developer-days at the stated sizes.

Two hard gates. **S-012** blocks S-013 and S-017 because span field paths, `session.id` presence, and the liveness fix are all unverified until one real run confirms them, and discovering a wrong assumption after the read path is written means rewriting it. **S-002** blocks nearly everything, since both sides consume the contract.

Only S-013 delivers PRD §1's zero-deploy scope change; only S-023 delivers the repository axis. If scope has to be cut, those two are the product.

---

## Coverage Validation

### Summary

- **Total PRD requirements traced:** 61 (10 user stories, 18 functional, 12 business rules, 12 acceptance criteria, 9 security)
- **Total user stories:** 24
- **Coverage:** 100%
- **Status:** Complete — no gaps

### Requirement Mapping

#### PRD §6 User Stories

| PRD user story | Story ID(s) | Status |
| --- | --- | --- |
| 1. All managed agents in one table | S-019 | Covered |
| 2. Runs for an agent, date descending | S-020 | Covered |
| 3. Agents and runs for a repository | S-023 | Covered |
| 4. Run detail without losing position | S-021 | Covered |
| 5. Toggle `enabled` instantly | S-022 | Covered |
| 6. Add repository by name | S-022 | Covered |
| 7. Edit `params` JSON | S-022 | Covered |
| 8. Estimated 30-day cost per agent | S-018, S-019 | Covered |
| 9. Cut-off runs visually distinct from failures | S-016, S-018 | Covered |
| 10. Filter runs by status and date range | S-020, S-023 | Covered |

#### PRD §7 Functional Requirements

| Requirement | Story ID(s) | Status |
| --- | --- | --- |
| 7.1 Run entity fields | S-002, S-017, S-018 | Covered |
| 7.1 Four statuses incl. `incomplete` | S-002, S-018 | Covered |
| 7.2 Agent inventory, 5 min cache | S-015 | Covered |
| 7.2 Runtime detail + `lifecycleConfiguration` | S-015 | Covered |
| 7.2 Runs via Logs Insights, 5 min cache | S-017 | Covered |
| 7.2 Execution logs uncached | S-021 | Covered |
| 7.2 Configuration uncached | S-015 | Covered |
| 7.3 Four `llipe.*` attributes | S-010 | Covered |
| 7.3 `session.id` availability | S-012 | Covered |
| 7.3 JSON logs with `session_id` | S-008 | Covered |
| 7.4 Discovery tags, opt-in | S-005 | Covered |
| 7.5 A Agents view | S-019 | Covered |
| 7.5 B Agent view, Runs tab | S-020 | Covered |
| 7.5 B Agent view, Repos tab | S-022 | Covered |
| 7.5 C Repos view | S-023 | Covered |
| 7.5 D Run side panel | S-021 | Covered |
| 7.6 Estimated cost formula + pricing table | S-018 | Covered |
| 7.6 Labelled as estimate | S-016, S-018 | Covered |

#### PRD §8 Business Rules

| Rule | Story ID(s) | Status |
| --- | --- | --- |
| 8.1 Single table + inverted GSI1 | S-003 | Covered |
| 8.1 Access pattern: repos for agent | S-003, S-015 | Covered |
| 8.1 Access pattern: agents for repo | S-003, S-023 | Covered |
| 8.1 Add repo as single write | S-022 | Covered |
| 8.2 Front end writes `enabled`, `params` | S-022 | Covered |
| 8.2 Orchestrator writes `last_*` | S-013 | Covered |
| 8.2 Agent writes two attributes via `UpdateExpression` | S-011 | Covered |
| 8.2 `dynamodb:Attributes` constraint | S-004 | Covered |
| 8.3 One schedule per agent, Lambda fan-out | S-013 | Covered |
| 8.3 Orchestrator-generated `session_id`, ≥33 chars | S-002, S-013 | Covered |
| 8.3 Concurrency pool 3–5 | S-013 | Covered |
| 8.3 Partial failures isolated | S-013 | Covered |
| 8.3 `incomplete` derived from `maxLifetime` | S-002, S-018 | Covered |
| 8.4 GitHub App, Secrets Manager key | S-006 (inherited) | Covered |
| 8.4 DynamoDB allowlist, no API discovery | S-009, S-013 | Covered |
| 8.5 Agent liveness / non-blocking entrypoint | S-007 | Covered |

#### PRD §13 Acceptance Criteria

| Criterion | Story ID(s) | Status |
| --- | --- | --- |
| Agents list with all columns | S-019 | Covered |
| Runs + Repos tabs, filterable | S-020, S-022 | Covered |
| Repos view with coverage | S-023 | Covered |
| Panel opens without unmounting table | S-021 | Covered |
| Toggle writes and reflects | S-022 | Covered |
| Add repo under 30 s, zero deploys | S-013, S-022 | Covered |
| `params` validated, bad JSON never stored | S-022 | Covered |
| JWT validated, invalid returns 401 | S-014 | Covered |
| Origin locked down | S-024 | Covered |
| Unknown `model_id` shows unknown | S-016, S-018 | Covered |
| `incomplete` derived at read | S-018 | Covered |
| Cost under USD 10/month | S-024 | Covered |

#### PRD §17 Security & Compliance

| Requirement | Story ID(s) | Status |
| --- | --- | --- |
| IAM least privilege, no `InvokeAgentRuntime` | S-004 | Covered |
| Write separation by policy | S-004, S-011 | Covered |
| JWT validation, fail closed | S-014 | Covered |
| Origin lockdown not optional | S-024 | Covered |
| `params` injection boundary, both ends | S-009, S-022 | Covered |
| GitHub App key in Secrets Manager, tokens unlogged | S-006, S-008 | Covered |
| No PII beyond repo names | S-008 | Covered |
| HTTPS + HSTS | S-024 | Covered |
| Exact pins, lockfiles, CI scanning | S-001 | Covered |

#### Prerequisites (PRD §12.4)

| Prerequisite | Story ID(s) | Status |
| --- | --- | --- |
| Transaction Search enabled | S-005 | Covered |
| Unified span destination | S-005 | Covered |
| Tags applied | S-005 | Covered |
| Emission contract implemented | S-010 | Covered |

### Gaps

None. Two requirements needed a story boundary adjustment to avoid one:

- **PRD §7.3 `session.id`** is not implementable as a plain coding task, since presence is unverified. It is covered by S-012 as an explicit verification story with a conditional fallback deliverable, rather than assumed inside S-010.
- **PRD §8.5 agent liveness** was added in PRD v1.3 after the original spec. S-007 covers it, sequenced before S-012 so telemetry is verified on runs that survive.

### Non-Goals Validation

Confirmed **not** present in any story:

- [x] Creating, deploying, modifying, or deleting agent runtimes — no story grants runtime write permission; S-004 explicitly withholds it
- [x] Invoking agents on-demand from the front end — `InvokeAgentRuntime` exists only in `orchestrator-role` (S-004, S-013)
- [x] Cost Explorer, allocation tags, actual billed cost — S-018 is token-derived only
- [x] Local database, materialization job, run ledger — S-015 is an in-memory cache with no persistence
- [x] Configuration Bundles, prompt versioning — absent
- [x] Schema-driven forms — S-022 uses a plain JSON textarea
- [x] Quality evaluation, prompt optimization, tool-usage analysis — absent
- [x] Missing-run detection against schedule — absent
- [x] Aggregate health metrics, outcome distributions, trends — S-019 shows per-agent last run only
- [x] Alerts via Slack, email, or any channel — absent; `incomplete` is the manual substitute
- [x] Differentiated roles and permissions — S-014 implements one authenticated role
- [x] Multi-account, multi-region — single account and region throughout

One note on scope discipline: S-019's "estimated 30-day cost" is a per-agent sum, deliberately not a trend, distribution, or health metric. The boundary is that it aggregates one number over a window rather than characterising change over time.
