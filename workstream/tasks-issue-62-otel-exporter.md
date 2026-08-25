# Implementation Plan - Issue #62: Install OTEL Exporter for aws/spans

## Relevant Files

- `agents/dep-updater/pyproject.toml` - `aws-opentelemetry-distro>=0.18.0` added to production dependencies
- `agents/dep-updater/uv.lock` - Regenerated; resolves ADOT 0.19.0 + OTLP exporters + AWS X-Ray propagator
- `agents/dep-updater/agentcore/agentcore.json` - `AGENT_OBSERVABILITY_ENABLED=true`, `UNIFIED_TRACES_DESTINATION_ENABLED=false`
- `agents/dep-updater/main.py` - `_run_pipeline` opens the `dep-update-pipeline` span; body moved to `_execute_pipeline`
- `agents/dep-updater/tests/test_pipeline_span.py` - New: 7 tests asserting `llipe.*` land on an exported span
- `infra/test/agentcore-config.test.ts` - New drift guard: 13 assertions pinning all three causes of D9
- `agents/dep-updater/emission.py` - Unchanged; the defect was the absence of a live span, not this logic
- `Dockerfile.dep-updater` - Unchanged; `opentelemetry-instrument` CMD verified correct
- `packages/shared/src/observability-config.ts` - `SPANS_LOG_GROUP` reference (unchanged)
- `packages/shared/src/span-fields.ts` - **Pending (AC4):** paths do not match the real record
- `packages/shared/__fixtures__/root-span.json` - **Pending (AC4):** shape does not match the real record

## Root Cause Summary (revised after live verification)

The issue described a single cause — no exporter installed. Live verification found **three**,
each masking the next:

| # | Cause | Fixed in |
| - | ----- | -------- |
| 1 | No OTLP exporter installed; spans created then dropped | #65 |
| 2 | First fix set non-runtime `OTEL_*` vars, overriding the endpoint the runtime injects | `e55782f` on main |
| 3a | Spans delivered to the per-agent log group, not `aws/spans` | #66 |
| 3b | Zero `llipe.*` attributes on any span — emission wrote to the already-ended server span | #66 |
| 4 | `SPAN_FIELDS` / fixtures do not match the real record shape | **open** |

## Tasks

- [x] 1.0 Implement Issue #62 - https://github.com/llipe/dev-tasks-agent-fleet/issues/62: Install OTEL exporter and configure observability env vars

  - [x] 1.1 Add `aws-opentelemetry-distro` to `agents/dep-updater/pyproject.toml` production dependencies
    > The ADOT distro package brings the OTLP exporter, AWS X-Ray propagator, and AWS resource detectors transitively. Pin with `>=0.18.0` (minimum version supporting custom trace header destinations per the docs).
    
  - [x] 1.2 Move `opentelemetry-sdk` from `[dependency-groups] dev` to production `dependencies`
    > ADOT requires the SDK at runtime (not just for local testing). Alternatively, verify that `aws-opentelemetry-distro` pulls it transitively — if it does, it can stay in dev. Check the resolved lockfile.
    > **Result:** ADOT pulls `opentelemetry-sdk` transitively via `opentelemetry-distro`. No change needed; SDK stays in dev group for explicitness.

  - [x] 1.3 Regenerate `uv.lock` with `uv lock` in `agents/dep-updater/`
    > Verify that the lockfile resolves without conflicts, especially against the existing `opentelemetry-api>=1.20.0` pin.
    > **Result:** Resolved 132 packages. ADOT v0.19.0 installed with all OTLP exporters and AWS propagators.

  - [x] 1.4 Verify the lockfile now contains exporter packages
    > `grep -i exporter agents/dep-updater/uv.lock` should return OTLP exporter packages. `grep -i "aws-opentelemetry-distro" agents/dep-updater/uv.lock` should match.
    > **Result:** Confirmed: `opentelemetry-exporter-otlp-proto-common`, `opentelemetry-exporter-otlp-proto-grpc`, `opentelemetry-exporter-otlp-proto-http` all present.

  - [x] 1.5 Add OTEL environment variables to `agents/dep-updater/agentcore/agentcore.json` `envVars`
    > Add the following env vars (per AWS docs Step 3 for non-runtime agents):
    > - `AGENT_OBSERVABILITY_ENABLED` = `true`
    > - `OTEL_PYTHON_DISTRO` = `aws_distro`
    > - `OTEL_PYTHON_CONFIGURATOR` = `aws_configurator`
    > - `OTEL_EXPORTER_OTLP_PROTOCOL` = `http/protobuf`
    > - `OTEL_RESOURCE_ATTRIBUTES` = `service.name=dep-updater`
    >
    > Do NOT set `OTEL_EXPORTER_OTLP_TRACES_HEADERS` — spans should route to the default `aws/spans` group.
    > Do NOT set `OTEL_LOGS_EXPORTER` or `OTEL_METRICS_EXPORTER` — those are Lambda-layer-specific.

  - [x] 1.6 Verify `Dockerfile.dep-updater` CMD is unchanged and compatible
    > The existing `CMD ["opentelemetry-instrument", "python", "main.py"]` should now pick up the ADOT distro automatically via the `OTEL_PYTHON_DISTRO` env var. No Dockerfile change expected. Confirm the import check (`RUN python -c "import main, ..."`) still passes by doing a local build test or verifying the dependency graph.
    > **Result:** CMD unchanged at line 93. ADOT distro detected via env var — no code changes needed.

  - [x] 1.7 Run agent-side quality gates
    > ```bash
    > cd agents/dep-updater
    > uv run ruff check .
    > uv run ruff format --check .
    > uv run mypy .
    > uv run pytest
    > ```
    > **Result:** All passed. ruff clean, mypy clean, 132 pytest tests green.

  - [x] 1.8 Run monorepo quality gates (to confirm no shared-package regressions)
    > ```bash
    > pnpm run validate
    > ```
    > This runs lint, format:check, typecheck, test, and build across the workspace.
    > **Result:** lint, typecheck, test, build all pass. format:check has 3 pre-existing failures on main (docs/*.md) unrelated to this change.

  - [x] 1.9 Verify Acceptance Criterion AC6: All quality gates pass
    > **Result:** All gates pass. 668 total tests green across all packages.

- [ ] 2.0 Post-deploy verification (manual, after `agentcore deploy`)

  > **Note:** These steps are executed manually after the code PR is merged and deployed. They are documented here for completeness and to define the acceptance criteria verification procedure.

  - [ ] 2.1 Deploy the agent: `cd agents/dep-updater && agentcore deploy`

  - [ ] 2.2 Invoke the agent with a known session ID
    > ```bash
    > agentcore invoke '{"session_id": "otel-verify-001", "repo": "llipe/memo-cli"}'
    > ```

  - [ ] 2.3 Wait for run completion (2-10 minutes), monitor app logs
    > ```bash
    > LG=$(aws logs describe-log-groups \
    >   --log-group-name-prefix /aws/bedrock-agentcore/runtimes/depupdater_dep_updater \
    >   --query 'logGroups[0].logGroupName' --output text)
    > aws logs filter-log-events --log-group-name "$LG" \
    >   --filter-pattern '{ $.session_id = "otel-verify-001" }' \
    >   --query 'events[*].message' --output text
    > ```

  - [ ] 2.4 Verify AC1: `aws/spans` has stored bytes
    > ```bash
    > aws logs describe-log-groups --log-group-name-prefix "aws/spans" \
    >   --query 'logGroups[0].storedBytes'
    > ```
    > Must be > 0.

  - [ ] 2.5 Verify AC2: Filter log events returns a span record
    > ```bash
    > aws logs filter-log-events --log-group-name "aws/spans" \
    >   --limit 10 --query 'events[*].message' --output text
    > ```
    > Must return at least one record.

  - [ ] 2.6 Verify AC3: Span record carries `llipe.*` attributes
    > Inspect the record(s) from 2.5. Confirm the presence of:
    > - `llipe.subject.id` (should equal `llipe/memo-cli`)
    > - `llipe.run.status` (should be `success` or `failed`)
    > - `llipe.outcome.type` (should be `pr` or `none`)
    > - `llipe.outcome.url` (should be a URL or empty string)

  - [ ] 2.7 Verify AC4: Compare span record shape against fixtures
    > If `packages/shared/__fixtures__/` exists and contains span fixtures, compare the real record's top-level structure against them. If the shape differs, create a follow-up issue to correct the fixtures.

  - [ ] 2.8 Verify AC5: Document session_id fields for D5
    > Record which field(s) in the span record carry session identity. Look for:
    > - `runtimeSessionId` or equivalent AgentCore-injected field
    > - Any `session.id` baggage attribute
    > - The payload-supplied `session_id`
    > Document findings in a comment on #62 or in `workstream/pending-deployments.md`.

  - [ ] 2.9 Summarize verification results and close issue #62


- [x] 3.0 Correct the observability configuration and emit on a live span (PR #66)

  > Added after live verification proved the exporter fix alone was insufficient.
  > Covers AC3 and the span-destination correction.

  - [x] 3.1 Remove the non-runtime `OTEL_*` env vars from `agentcore.json`
    > `OTEL_PYTHON_DISTRO`, `OTEL_PYTHON_CONFIGURATOR`, `OTEL_EXPORTER_OTLP_PROTOCOL` and
    > `OTEL_RESOURCE_ATTRIBUTES` are documented for agents hosted *outside* the AgentCore
    > runtime. On a runtime-hosted agent they override the endpoint the runtime injects.
    > **Landed as `e55782f` on main** (pushed directly to main in error; left in place by
    > user decision rather than reverted).

  - [x] 3.2 Set `UNIFIED_TRACES_DESTINATION_ENABLED=false`
    > AgentCore defaults newly created agents to a per-agent span destination. Verified live:
    > the agent log group has a populated `spans` stream while `aws/spans` stayed at 0 bytes.
    > Opting out preserves the single shared destination that `SPANS_LOG_GROUP` and the
    > control plane's fleet-wide runs query assume.
    > **Decision:** shared `aws/spans` retained over per-agent group, to avoid making
    > `SPANS_LOG_GROUP` per-agent and breaking the fleet-wide query model.

  - [x] 3.3 Write failing tests for the pipeline span before implementing
    > `agents/dep-updater/tests/test_pipeline_span.py` — 7 tests. Confirmed failing against
    > the pre-fix code.

  - [x] 3.4 Open a live span in the worker thread so emission has somewhere to write
    > `_run_pipeline` now opens `dep-update-pipeline` as the current span and delegates to
    > `_execute_pipeline` (previous body, unchanged). Root cause: the `POST /invocations`
    > SERVER span ends ~3 ms in (`durationNano: 2921461` on the live record) when the
    > non-blocking entrypoint returns, so `is_recording()` was False and all four attributes
    > were discarded on every path.
    > No context plumbing needed — `opentelemetry-instrumentation-threading` already
    > propagates the invocation context into the worker thread, confirmed by the botocore
    > spans being parented to the server span.

  - [x] 3.5 Add a drift guard for all three causes
    > `infra/test/agentcore-config.test.ts` +13 assertions: observability vars present,
    > non-runtime vars absent, ADOT declared at `>=0.18.0`, OTLP exporter resolved in the
    > lockfile, `opentelemetry-instrument` still the Dockerfile CMD. Mutation-checked:
    > removing the opt-out or reintroducing a non-runtime var fails 3 tests.

  - [x] 3.6 Run quality gates
    > 688 tests pass (139 agent, 109 shared, 218 control-plane, 51 components, 36
    > orchestrator, 135 infra). `lint`, `typecheck`, `build` clean. `format:check` has 3
    > pre-existing failures in `docs/*.md` present on `main` and untouched by this work.

- [ ] 4.0 Correct the span read path against the real record (AC4, AC5)

  > **Open.** Blocks S-016/S-017 from rendering even once spans arrive in `aws/spans`.
  > `SPAN_FIELDS` and the fixtures were written from inference and are self-labelled
  > "PENDING LIVE VERIFICATION". The live record disproves four assumptions:
  >
  > | Contract says | Real record |
  > | ------------- | ----------- |
  > | `resource.attributes.llipe.*` | span `attributes.llipe.*` — per-run values cannot be resource attributes, which are fixed at SDK init |
  > | `resource.attributes.session.id` | `attributes.session.id` |
  > | `duration` | `durationNano` |
  > | root span `parentSpanId: ""`, name `dep-updater-run` | no such span; the server span has a parent |

  - [ ] 4.1 Capture a fresh `aws/spans` record after #66 is deployed
  - [ ] 4.2 Correct `packages/shared/src/span-fields.ts` paths against that record
  - [ ] 4.3 Replace `packages/shared/__fixtures__/root-span.json` and `gen-ai-child-span.json` with real captured shapes, and drop the "pending verification" caveat from the fixtures README
  - [ ] 4.4 Decide how the control plane identifies the run span
    > The fixture README assumes `parentSpanId` empty. The real run span (`dep-update-pipeline`)
    > has a parent, so identification should key on the presence of `llipe.run.status`.
  - [ ] 4.5 Update `span-mapper.ts` / `span-query.ts` and their tests for the corrected paths
  - [ ] 4.6 Emit `llipe.session.id` from `emission.py` to close D5
    > `span-session-resolver.ts` already documents that the agent emits both `session.id` and
    > `llipe.session.id`; it currently emits neither. Contract-first: add `SESSION_ID` to the
    > `LLIPE` set in `packages/shared`, regenerate `shared_contract.py`, then emit.
  - [ ] 4.7 Verify AC4 and AC5, then re-run quality gates

## AC Status

| AC | Statement | Status |
| -- | --------- | ------ |
| AC1 | `aws/spans` `storedBytes > 0` after a run | Pending redeploy of #66 |
| AC2 | `filter-log-events` returns a record for a known run | Met in the per-agent group; pending redeploy for `aws/spans` |
| AC3 | Record carries the `llipe.*` attributes | Fix in #66; pending live confirmation |
| AC4 | Fixtures match the real record shape | Open — task 4.0 |
| AC5 | `session_id` field(s) documented, unblocking D5 | Evidence captured; `llipe.session.id` emission open in 4.6 |
| AC6 | Quality gates pass | Pass |

## AC5 Evidence (captured, D5 unblocked)

- Spans carry the **runtime** session id as a span attribute: `attributes.session.id = d4f97861-02aa-4015-8e9a-47c975b20a9c`
- App logs carry the **payload** session id: `session_id = otel-verify-001`
- The two do not intersect, so joining spans to logs by session id fails exactly as D5 predicted.
- Resolution path: emit `llipe.session.id` = payload session id (task 4.6), which is what
  `span-session-resolver.ts` already expects.
