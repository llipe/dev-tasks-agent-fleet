# Implementation Plan - Issue #62: Install OTEL Exporter for aws/spans

## Relevant Files

- `agents/dep-updater/pyproject.toml` - Add `aws-opentelemetry-distro` to production dependencies
- `agents/dep-updater/uv.lock` - Regenerated lockfile with new dependency tree
- `agents/dep-updater/agentcore/agentcore.json` - Add OTEL env vars to `envVars` array
- `agents/dep-updater/emission.py` - Existing span attribute emission (verify compatibility, no changes expected)
- `Dockerfile.dep-updater` - Verify `opentelemetry-instrument` CMD still works with ADOT installed (no changes expected)
- `packages/shared/src/observability-config.ts` - Reference for `SPANS_LOG_GROUP` constant (no changes)

## Tasks

- [ ] 1.0 Implement Issue #62 - https://github.com/llipe/dev-tasks-agent-fleet/issues/62: Install OTEL exporter and configure observability env vars

  - [ ] 1.1 Add `aws-opentelemetry-distro` to `agents/dep-updater/pyproject.toml` production dependencies
    > The ADOT distro package brings the OTLP exporter, AWS X-Ray propagator, and AWS resource detectors transitively. Pin with `>=0.18.0` (minimum version supporting custom trace header destinations per the docs).
    
  - [ ] 1.2 Move `opentelemetry-sdk` from `[dependency-groups] dev` to production `dependencies`
    > ADOT requires the SDK at runtime (not just for local testing). Alternatively, verify that `aws-opentelemetry-distro` pulls it transitively — if it does, it can stay in dev. Check the resolved lockfile.

  - [ ] 1.3 Regenerate `uv.lock` with `uv lock` in `agents/dep-updater/`
    > Verify that the lockfile resolves without conflicts, especially against the existing `opentelemetry-api>=1.20.0` pin.

  - [ ] 1.4 Verify the lockfile now contains exporter packages
    > `grep -i exporter agents/dep-updater/uv.lock` should return OTLP exporter packages. `grep -i "aws-opentelemetry-distro" agents/dep-updater/uv.lock` should match.

  - [ ] 1.5 Add OTEL environment variables to `agents/dep-updater/agentcore/agentcore.json` `envVars`
    > Add the following env vars (per AWS docs Step 3 for non-runtime agents):
    > - `AGENT_OBSERVABILITY_ENABLED` = `true`
    > - `OTEL_PYTHON_DISTRO` = `aws_distro`
    > - `OTEL_PYTHON_CONFIGURATOR` = `aws_configurator`
    > - `OTEL_EXPORTER_OTLP_PROTOCOL` = `http/protobuf`
    > - `OTEL_RESOURCE_ATTRIBUTES` = `service.name=dep-updater`
    >
    > Do NOT set `OTEL_EXPORTER_OTLP_TRACES_HEADERS` — spans should route to the default `aws/spans` group.
    > Do NOT set `OTEL_LOGS_EXPORTER` or `OTEL_METRICS_EXPORTER` — those are Lambda-layer-specific.

  - [ ] 1.6 Verify `Dockerfile.dep-updater` CMD is unchanged and compatible
    > The existing `CMD ["opentelemetry-instrument", "python", "main.py"]` should now pick up the ADOT distro automatically via the `OTEL_PYTHON_DISTRO` env var. No Dockerfile change expected. Confirm the import check (`RUN python -c "import main, ..."`) still passes by doing a local build test or verifying the dependency graph.

  - [ ] 1.7 Run agent-side quality gates
    > ```bash
    > cd agents/dep-updater
    > uv run ruff check .
    > uv run ruff format --check .
    > uv run mypy .
    > uv run pytest
    > ```

  - [ ] 1.8 Run monorepo quality gates (to confirm no shared-package regressions)
    > ```bash
    > pnpm run validate
    > ```
    > This runs lint, format:check, typecheck, test, and build across the workspace.

  - [ ] 1.9 Verify Acceptance Criterion AC6: All quality gates pass

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
