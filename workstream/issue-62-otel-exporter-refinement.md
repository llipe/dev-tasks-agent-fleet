# Issue Refinement: #62 - fix(agent): no OTEL exporter installed — aws/spans is empty, runs views have no data

## Changelog

| Version | Date       | Summary            | Author           |
| ------- | ---------- | ------------------ | ---------------- |
| 1.0     | 2026-08-26 | Initial refinement | product-engineer |

## Summary

- **Goal:** Install the ADOT (AWS Distro for OpenTelemetry) SDK so that the `dep-updater` agent exports spans to the `aws/spans` CloudWatch Logs group, enabling the control plane's runs views and validating S-010's `llipe.*` attribute emission.
- **Primary user impact:** Once resolved, the runs list and run detail views in the control plane will have real data, and the `llipe.*` span attributes emitted by `emission.py` become observable in CloudWatch.
- **Non-goals:** The D5 canonical `session_id` decision itself (this issue only produces the evidence it needs); control-plane rendering work; fixture correction beyond shape validation.

## Acceptance Criteria

- [ ] AC1: After a run, `aws logs describe-log-groups --log-group-name-prefix "aws/spans"` reports `storedBytes > 0`.
- [ ] AC2: `filter-log-events` against `aws/spans` returns at least one record for a known run's session.
- [ ] AC3: The span record carries the `llipe.*` attributes emitted by `emission.py` (`llipe.subject.id`, `llipe.run.status`, `llipe.outcome.type`, `llipe.outcome.url`).
- [ ] AC4: Span fixtures in `packages/shared/` (if present) match the real record's shape, or are corrected to match.
- [ ] AC5: The record's `session_id` field(s) are documented (stdout or committed note), unblocking D5.
- [ ] AC6: Quality gates pass: `pnpm run test`, `pnpm run lint`, `pnpm run format:check`, `pnpm run typecheck`, agent-side `ruff`, `mypy`, `pytest`.

## Constraints

- **No env-var guessing.** The docs are ambiguous on whether runtime-hosted agents need `AGENT_OBSERVABILITY_ENABLED` or any `OTEL_*` variables. The empirical evidence (zero spans despite Transaction Search being active) proves that the auto-instrumentation built into AgentCore Runtime is not sufficient for this agent's Docker-based deployment. The fix must install `aws-opentelemetry-distro` and configure the env vars documented for non-runtime agents (Step 3 of the observability guide).
- **Minimal dependency footprint.** Only add what is needed for export — `aws-opentelemetry-distro` (which pulls the OTLP exporter and AWS configurator transitively).
- **`opentelemetry-sdk` stays in dev deps.** It is needed for local testing but not in production — ADOT brings its own SDK fork.
- **Lockfile must be regenerated.** `uv.lock` must reflect the new dependency.
- **Deployment is manual and out of scope for the code PR.** The PR delivers the code change; `agentcore deploy` is a separate manual step documented in the task list but not automated in CI.

## Risks and Edge Cases

- **ADOT version compatibility:** `aws-opentelemetry-distro` must be compatible with `opentelemetry-api>=1.20.0`. The latest ADOT releases track upstream OTel closely, so conflict is unlikely but must be verified by lockfile resolution.
- **AgentCore runtime injection:** AgentCore may inject `OTEL_*` env vars at runtime. If it does, the ones set in `agentcore.json` `envVars` should not conflict. The `OTEL_EXPORTER_OTLP_TRACES_HEADERS` var is only needed for custom destinations — spans should go to the default `aws/spans` without it.
- **Image size increase:** ADOT adds several transitive packages. The Docker image may grow by 20-40MB. Acceptable for an ephemeral container.
- **`opentelemetry-instrument` behavior change:** With ADOT installed, the auto-instrumentor will pick up the AWS distro and configurator, changing the span export path. This is the desired outcome, but could surface unexpected instrumentation of boto3/requests calls as child spans.

## Dependencies

- Transaction Search already enabled (confirmed active with 100% sampling).
- `aws/spans` log group exists with 30-day retention (confirmed).
- Runtime execution role has the necessary permissions (delivered in #56, deployed).
- Agent pipeline works end-to-end (verified by PR llipe/memo-cli#49).
- Issue #60 (control-plane IAM) is resolved — the control plane can read `aws/spans` once data arrives.

## Testing Notes

- **Unit tests:** No new unit tests needed for the dependency addition itself. Existing `emission.py` tests validate attribute setting logic.
- **Integration tests:** Post-deploy manual verification against live AWS (invoke agent, query `aws/spans`).
- **Manual checks:** `agentcore invoke`, then query `aws/spans` with `filter-log-events`.
- **Edge-case checks:** Verify that a run producing "no_updates" (no PR created) still emits a span with `llipe.run.status=success` and `llipe.outcome.type=none`.
- **Acceptance-criteria-to-test mapping:**
  - AC1-AC2: Manual post-deploy verification
  - AC3: Manual post-deploy verification + comparison against `emission.py` attribute names
  - AC4: Compare real record shape against fixtures (if fixtures exist)
  - AC5: Document observed fields in the span record
  - AC6: `pnpm run validate` + agent-side linting

## Open Questions

- **Q1 (resolved by docs review):** Does AgentCore Runtime inject OTEL config automatically for Docker-based agents? **Answer: The docs explicitly state runtime-hosted agents get automatic instrumentation, but empirically this is not working for this agent. The fix path is to install ADOT and set the env vars as documented for "non-runtime" agents, since this agent uses `opentelemetry-instrument` explicitly in its CMD.**
- **Q2:** Should `OTEL_PYTHON_DISTRO` and `OTEL_PYTHON_CONFIGURATOR` be set in `agentcore.json` envVars, or is it sufficient to have the package installed (the auto-instrumentor detects it)? **Working hypothesis: Set them explicitly for deterministic behavior.**
- **Q3:** Does setting `OTEL_EXPORTER_OTLP_TRACES_HEADERS` with `x-aws-log-group=aws/spans` risk duplicating span delivery if the runtime also routes to `aws/spans` by default? **Working hypothesis: Omit it — the default destination is already `aws/spans`.**
