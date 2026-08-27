# Technical Guidelines — Agent Fleet Control Plane

## Changelog

| Version | Date       | Summary                                                                 | Author           |
| ------- | ---------- | ----------------------------------------------------------------------- | ---------------- |
| 1.0     | 2026-08-26 | Initial version. Reformatted from consolidated PRD, `001_schema.sql`, `002_seed.sql`, `agent_reporter.py`, and `credentials.ts` into foundation doc format. No scope or decision changes. | product-engineer |
| 1.1     | 2026-08-26 | Translated to English. Aligned with two-phase delivery model. | product-engineer |
| 1.2     | 2026-08-27 | Documented the implemented LLM fix-agent escape hatch (issue #75): added the sandbox + mandate-backstop security rule to §6, replaced the stale §11 Testing Strategy with the implemented pytest layer taxonomy, and recorded Strands/Bedrock as a committed agent runtime dependency in §16. See [ADR-001](adr/ADR-001-llm-fix-agent-escape-hatch.md). | technical-writer |
| 1.3     | 2026-08-27 | Documented the implemented `open_pr` step + `pull_request` run artifact (issue #76): updated the §9 `dependency-update` status line (PR-creation/artifact no longer deferred; only `runs.metrics` persistence + deploy/E2E remain, → #77) and refreshed the §11 test surface (PR-creation Layer 1 + Layer 2 tests; suite now 328 passing). Current-state status correction only — no new architectural decision or enforceable-rule change. See [ADR-002](adr/ADR-002-open-pr-step-and-pr-artifact.md). | technical-writer |

## 1. Overview

The system has three pieces with different languages and runtimes, joined by Supabase as the *system of record*:

1. **Front-end / panel** — Next.js in TypeScript, deployed on Fly.io (Phase 2).
2. **Agents** — containers in AWS Bedrock AgentCore, in Python, that report their own lifecycle (Phase 1).
3. **Database** — PostgreSQL via Supabase, with Realtime for live log tailing and `pg_cron` for stale-execution detection (Phase 1).

Guiding principle: **the agent reports state explicitly**; nothing is reconstructed by inference over logs (see Problem Statement in `product-context.md`). Every decision in this document upholds that rule or resolves a consequence of it (timeouts, buffering, credentials).

## 2. Technology Stack

| Layer | Technology | Notes |
|---|---|---|
| Front-end | Next.js (TypeScript) | Routes, JSON Schema-generated forms, live tail via Supabase Realtime (Phase 2) |
| Front-end hosting | Fly.io | Node process persists after responding — enables fire-and-forget invocation without a durable queue (D7) |
| Agent runtime | AWS Bedrock AgentCore | Containers; AgentCore controls the lifecycle and enforces the real timeout |
| Agent SDK | Python, stdlib only (`urllib`, `logging`, `atexit`) | Single file [`agent_reporter.py`](reference/agent_reporter.py), copied per repo (D13), not a pip package |
| Database | PostgreSQL via Supabase | System of record for executions. RLS deny-all from the first migration (D11) |
| Realtime | Supabase Realtime on `run_events` and `runs` | Live log tail without polling |
| Cron | `pg_cron` inside Supabase | Reaper for stale executions — does not depend on the front-end being alive (D10) |
| Front-end AWS auth | Fly OIDC + STS `AssumeRoleWithWebIdentity` | No static keys in `fly secrets` (D12) |
| GitHub App secrets | AWS Secrets Manager | Only the ARN lives in `github_installations`, never the key |

## 3. Architecture Patterns

**Supabase as system of record, CloudWatch as infrastructure telemetry.** CloudWatch remains outside the panel's scope — it is an AgentCore implementation detail, not a source of business truth. However, if the API layer (PostgREST) is unreachable during Phase 1, the agent SDK falls back to writing payloads to stderr, which lands in CloudWatch as a safety net.

**Separation of `status` / `outcome` (D3).** The lifecycle of an execution (`queued → running → succeeded|failed|canceled`, plus `timed_out` and `failed_to_start` injected by the reaper) is one column. The business result (`fixed`, `partial`, `no_vulnerabilities`, `needs_review`, `not_applicable`) is another. An execution that finishes successfully and finds no issues is not a failure.

**Structured log, not blob (D4).** `run_events` is a table of rows, not a text field. Enables filtering by level and live tail via Realtime.

**Snapshot over live reference.** Each `run` copies `agent_version`, `params`, `max_runtime_seconds`, `grace_seconds`, and `start_timeout_seconds` at dispatch time. If the configured timeout of an agent changes later, historical runs are not re-evaluated against the new value. There is no `agent_versions` table in v1 — the per-run snapshot covers auditability without the extra table.

**Repositories as a first-class entity (D6).** Not a string inside `params`: the GitHub App token is issued per `installation`, and modeling `repositories` separately enables queries like "all runs for repo X" and honors `is_enabled`/`archived_at`.

**Fire-and-forget from the route handler (D7).** The invocation to AgentCore happens directly from the Next.js handler on Fly, without a durable queue hop (SQS/Lambda). Justified because the Fly Node process does not die after responding. If this assumption stops holding, this pattern must be revisited.

**Two clocks for two distinct failures (D8, D9).** `timed_out` (agent hung, clock = `started_at`) and `failed_to_start` (invocation that never started, clock = `queued_at`) are separate states and runbooks. They do not collapse into a single "did not respond."

**Two application layers for the reaper (see specification §6).** `pg_cron` materializes the state change and writes the explanatory `run_event` every minute (D10). The `v_runs` view computes `effective_status` at read time, so the UI never shows a run "running" that has already expired even if the reaper is one minute behind. The reaper materializes eventual truth; the view tells immediate truth.

## 4. API Design Standards

**A single invocation endpoint per agent:** `POST /api/agents/{slug}/invoke`. Full flow (see specification §8):

1. The front-end validates `params` against `agents.params_schema` (JSON Schema) before calling AgentCore.
2. The front-end, not the database or the agent, generates the `run_id` (uuid) and inserts the `runs` row in `queued` (D1) — so an invocation where the agent never starts still leaves a record of the failure.
3. The front-end obtains/refreshes AWS credentials (see §5) and invokes `InvokeAgentRuntime` in a fire-and-forget manner.
4. If the invocation throws, the server marks the run `failed_to_start` immediately — that detection is not delegated to the reaper.
5. The server responds `202` with `run_id`; the front-end navigates to the detail view without waiting for the agent to finish.

**The invocation form is not hand-coded per agent (D2).** It is rendered from `agents.params_schema`. Adding a new agent is a row in `agents`, not a front-end deploy (v1 acceptance criterion #5).

**The repository does not live inside `params_schema`.** It is a first-class field that the front-end renders separately when `agents.requires_repository = true`. The agent's schema covers only its own parameters.

## 5. Authentication & Authorization

**No user authentication in v1** (explicit scope decision, not an accidental gap — see Risk R1 in the specification). The panel runs without login. Minimal mitigation required before exposing the app publicly: shared-secret header on `/api/agents/[slug]/invoke`, or keeping the app private on Fly.

**Front-end authentication against AWS — no static keys (D12).**

- **On Fly:** OIDC token issued by the Machine's local socket (`/.fly/api`, `aud=sts.amazonaws.com`) → `AssumeRoleWithWebIdentity` against an IAM Role with a trust policy scoped to the app's wildcard `sub` (`<org>:panel-agentes:*`) → 15-minute credentials, cached in memory with a 60-second refresh margin.
- **Locally:** `fromNodeProviderChain()` — SSO profile, `~/.aws/credentials`, or environment variables. The SDK handles its own refresh.
- Both branches live in a single module ([`credentials.ts`](reference/credentials.ts)), detected by `FLY_APP_NAME` + socket existence. Invocation code receives the credentials provider and does not know which branch it is on.
- The IAM permission is scoped to `bedrock-agentcore:InvokeAgentRuntime` on the runtimes ARN, never `*`.
- **Pending verification against the real Fly endpoint** (not yet validated): exact JSON response shape from the OIDC socket, literal claim name `sub` as normalized by AWS in the trust policy, and that `DurationSeconds: 900` is compatible with the role's `MaxSessionDuration`.

**Agent credentials against Supabase — service role key from Secrets Manager (D15, R2).** The agent authenticates to PostgREST with the Supabase service role key, which grants full database access (bypasses RLS). The key is **not** stored as a plaintext environment variable in the AgentCore runtime config — the agent fetches it from AWS Secrets Manager at startup, alongside the GitHub App private key. This keeps the credential out of the runtime configuration visible in the AgentCore console and applies Secrets Manager's access controls (IAM policy on the agent's execution role) and audit trail (CloudTrail). The scope risk (full DB access vs. scoped writes) remains accepted for a single-tenant system (R2). The exit path is unchanged: when the fleet grows or untrusted code enters, mint a scoped JWT per run instead.

**GitHub App secrets.** The private key never lives in the database — only its ARN in Secrets Manager (`github_installations.private_key_secret_arn`). The agent reads it at runtime to issue a short-lived installation token.

## 6. Security Requirements

- **RLS enabled and deny-all from the first migration (D11).** Without explicit policies, only `service_role` can read/write (it bypasses RLS). Enabling RLS after having data is a more costly and risky migration — hence the rule to do it from day one.
- **No long-lived AWS keys.** No IAM user with static keys in `fly secrets` (see §5).
- **Param validation at two points.** The front-end validates against `params_schema` before invoking; the agent validates its own payload at startup and fails fast with `error_code = INVALID_PARAMS` if it does not match (mitigation for R4 — drift between the schema in the database and what the agent expects).
- **Log messages truncated to 8 KB** (`run_events.message`) to bound row size and the risk of a malformed message degrading the table.
- **4xx errors from the reporting SDK are not retried.** A contract error (invalid payload) does not improve with waiting; only transient errors (5xx, network) use 3-retry backoff.
- **LLM fix agent — sandboxed tools + deterministic mandate backstop (ADR-001).** The `dependency-update` agent's optional LLM fix loop (`fix_agent.py`, reached only when validation fails after a dependency update in `llm_fix` mode) runs a Strands/Bedrock agent with **exactly five** tools (`shell`, `read_file`, `write_file`, `find_files`, `grep_code`). Every path-taking tool resolves against the workspace root via `_safe_path`, which rejects absolute paths, `../` traversal, and symlink escapes; `shell`/`find_files`/`grep_code` are confined to the workspace cwd. The system prompt forbids weakening tests, rolling back the update, widening semver ranges, major bumps, and dependency add/remove/lockfile edits — but the prompt is guidance, not the control. The enforceable control is `verify_no_mandate_violation`: after the loop, any change to a `package.json` dependency specifier (widened range, major bump, added/removed dependency) terminates the run `failed` / `needs_review` / `MANDATE_VIOLATION` and **blocks PR creation**. This mirrors the fleet's "explicitness over inference" and "human review is the real gate" posture — the model may propose, but a deterministic check disposes.

## 7. Data & Database Guidelines

Reference DDL: [`001_schema.sql`](reference/001_schema.sql) (full schema: tables, enums, indexes, view, reaper function, RLS). Reference seed: [`002_seed.sql`](reference/002_seed.sql) (idempotent via `on conflict`).

**Entities and relationships:**

```
github_installations 1──n repositories
                     1──n runs
agents               1──n runs
repositories         1──n runs
runs                 1──n run_steps
                     1──n run_events
                     1──n run_artifacts
run_steps            1──n run_events
```

**Main tables:**

| Table | Purpose | Design notes |
|---|---|---|
| `github_installations` | One row in v1. Not multi-tenancy — it is a requirement of the GitHub App token flow (token is issued per installation) | `private_key_secret_arn`, never the key |
| `repositories` | Repos enabled to run agents | Unique `(installation_id, full_name)`; `archived_at` is soft delete that preserves historical runs |
| `agents` | Catalog of configured agents | `params_schema` (JSON Schema) does not include the repo; `max_runtime_seconds` **must** reflect the real timeout configured in AgentCore |
| `runs` | One row per execution, `id` generated by the front-end (D1) | Snapshot of timeouts and params; constraint `chk_runs_terminal_outcome` requires non-null `outcome` when `status = succeeded` |
| `run_steps` | Named phases within an execution (`checkout`, `npm_audit`, `llm_fix`, `test`, `open_pr`) | `id` generated by the agent SDK (uuid4), not the database — avoids a read round-trip to associate events to the step |
| `run_events` | The log, as rows, not a blob (D4) | `seq` is monotonic, assigned by the agent, not the database — with buffering, arrival order is not emission order; Realtime enabled, filtered by `run_id` |
| `run_artifacts` | Execution artifacts (`pull_request`, `audit_report`, `diff`, `file`) | The generated PR lives here, not buried in `result jsonb`, so it can be rendered in the list without parsing JSON |

**State machine for `runs.status`:**

```
queued ──▶ running ──▶ succeeded | failed | canceled
   │                       ▲
   │                       └── timed_out        (reaper)
   └────────────────────────── failed_to_start  (reaper)
```

**Key indexes:** `(agent_id, created_at desc)`, `(repository_id, created_at desc)`, partial on `status in ('queued','running')` for the reaper, partial unique on `idempotency_key`.

**Stale execution detection** (see also §3 — two layers): two thresholds on two clocks.

| Condition | New status |
|---|---|
| `status = running` and `now() > started_at + max_runtime_seconds + grace_seconds` | `timed_out` |
| `status = queued` and `now() > queued_at + start_timeout_seconds` | `failed_to_start` |

`last_heartbeat_at` is declared in the schema but not used for detection in v1 — it comes into play only if agents appear that hang well below their timeout (backlog).

**Retention (declared risk, not resolved in v1 — R3).** `run_events` will be the largest table by two orders of magnitude. Policy pending: events older than 90 days get collapsed to an artifact in Supabase Storage and the rows are purged.

**Separate environments (R7).** Local development invokes real AgentCore; to avoid mixing test runs with production runs, the recommended exit is a second Supabase project for development (free tier is sufficient, same schema).

## 8. Integration Methods

**AWS Bedrock AgentCore.** The front-end invokes `InvokeAgentRuntime` in a fire-and-forget manner from the route handler (see §4). There is no automatic retry on the front-end side for startup failures — it marks `failed_to_start` and stops there; the reaper is the safety net for the case where the invocation was accepted but the container never reported.

**Agent reporting contract ([`agent_reporter.py`](reference/agent_reporter.py), D13).** Single file copied to each agent repo, no external dependencies (`urllib`, not `supabase-py` or `httpx`). Hybrid interface (D14):

- **Standard `logging.Handler`**, attached to the root logger — captures noise from third-party libraries (`boto3`, `httpx`), which is exactly what you want to see when something fails.
- **Explicit lifecycle API** (`RunReporter.from_env()`, `run.step(...)`, `run.succeed(...)`, `run.fail(...)`, `run.artifact(...)`) — the lifecycle does not fit naturally in a `logger.info()`.

The agent authenticates to PostgREST directly (D15) using the Supabase service role key fetched from AWS Secrets Manager at startup — not from an env var.

Behavioral properties:

| Property | Behavior |
|---|---|
| Write buffer (D5) | Inline flush every 50 events or 2 seconds; forced at step boundary open/close and on termination. No background thread — async worker adds queue, `join`, and `atexit` for ~200 ms |
| Retries | 3 with exponential backoff. 4xx are not retried (contract error). If exhausted, the payload is written to stderr (lands in CloudWatch) and the agent continues — reporting never kills the agent |
| Agent failure | The context manager marks `failed` with full traceback before re-raising; open steps are closed as `failed` |
| Exit without `succeed()` | Closes with `outcome = not_applicable` to avoid leaving the run dangling |
| Truncation | Messages to 8 KB |
| Transport change | Isolated to the `_SupabaseClient` class (~40 lines) — no generic transport abstraction because today it does not pay for itself |

**Per-execution write volume (R5, distinct from R3 which is growth over time).** Not actively mitigated in v1 — the chosen approach is "evaluate later" if an actual agent evidences the problem (e.g., one that tails builds or long test runs). First lever if it occurs: raise the minimum captured log level (`INFO+` instead of `DEBUG+`).

**GitHub App.** The agent reads the private key and `installation_id` from Secrets Manager and issues a short-lived installation token to clone the repo and open the PR. Automatic repo sync from the GitHub App is backlog — v1 uses manual seed ([`002_seed.sql`](reference/002_seed.sql)).

## 9. Code Organization & Structure

Artifacts already defined at design level (see specification §14):

| File/directory | Role |
|---|---|
| [`001_schema.sql`](reference/001_schema.sql) | Full DDL: tables, enums, indexes, `v_runs` view, `reap_stale_runs()` function, RLS |
| [`002_seed.sql`](reference/002_seed.sql) | Idempotent seed: installation, repo list, `dependency-update` agent |
| [`agent_reporter.py`](reference/agent_reporter.py) | Reporting SDK, copied to each agent repo |
| [`credentials.ts`](reference/credentials.ts) | AWS credential provider with Fly OIDC / local branches |
| Next.js front-end | Routes, schema-generated forms, live tail — pending implementation (Phase 2) |
| `dependency-update` agent | AgentCore runtime under `agents/dependency-update/` — implemented (Phase 1): deterministic audit→classify→update→validate pipeline, the bounded LLM fix loop (`fix_agent.py`, ADR-001), and the idempotent `open_pr` step with the `pull_request` run artifact (`pull_request.py`, issue #76). Deferred to issue #77: fix-budget test-output artifact and full `runs.metrics` persistence (`llm_used` / `fix_attempts`), plus deploy + E2E. |

The exact folder convention for the front-end (`app/`, `lib/`, etc.) is defined when Phase 2 implementation begins, not in this document — v1 does not impose a monorepo structure yet.

## 10. Design Patterns & Principles

- **Explicitness over inference.** Every observable state in the panel is written explicitly by the agent or the reaper; nothing is derived by parsing free text.
- **YAGNI on transport and infrastructure abstractions.** No pip package for the SDK (D13), no durable queue for invocation (D7), no `agent_versions` table (snapshot in `runs` suffices). These decisions are explicitly revisable if the fleet grows (see backlog).
- **Auditability by snapshot, not by referenced version.** Each `run` is self-contained regarding the parameters and thresholds it ran with, even if the agent's configuration changes later.

## 11. Testing Strategy

The canonical testing contract lives in [`TESTING.md`](../TESTING.md) — this section summarizes the current state for the `dependency-update` agent (Phase 1) and points to it.

- **Framework and layers (Python agent).** `pytest 8.3.5` with branch coverage via `pytest-cov`. Layer markers are auto-applied by directory in `tests/conftest.py`: `tests/unit/` → Layer 1 (`unit`, no I/O/network — all `boto3`/`requests`/`jwt`/`subprocess` boundaries mocked), `tests/component/` → Layer 2 (`component`, mocked externals + temp-dir project fixtures). The aggregate gate is `make validate` (lint + format:check + typecheck + test-cov + audit), enforced in CI (`.github/workflows/ci.yml`) on a Python 3.13 + 3.14 matrix for every push/PR to `main`.
- **LLM fix agent test surface (issue #75).** The escape hatch adds a Layer 1 + Layer 2 surface exercised without invoking a real model: `tests/unit/test_safe_path.py` (workspace-escape guard — traversal, absolute, symlink, null-byte), `tests/unit/test_mandate_check.py` (`verify_no_mandate_violation` add/remove/change/malformed-JSON/missing-file), `tests/unit/test_fix_tools.py` (tool path-safety), and `tests/component/test_fix_agent.py` (5-tool surface, retry-budget exhaustion, early success, `max_attempts=0` → zero model calls, agent-exception resilience) with the Strands `Agent` mocked. `fix_agent.py` reports ~91% line coverage.
- **PR-creation test surface (issue #76).** The `open_pr` step adds a Layer 1 + Layer 2 surface with `git`/`gh` mocked: `tests/unit/test_pr_body.py` (branch naming + conditional PR-body sections, cap-at-30, AI-warning, validation table — 19 tests) and `tests/component/test_pr_creation.py` (idempotency short-circuit, `--body-file` never inline, never-push-to-default, credential-helper push, commit-message contract — 14 tests), plus additions to `tests/component/test_pipeline.py` (token-staleness re-mint). `pull_request.py` reports ~95% line coverage. Full suite: **328 tests passing**.
- **Known gaps (tracked, non-blocking).** No Layer 3 product-evaluation/eval harness exists for the LLM path (semantic/groundedness) — the fix-agent *code path* is tested but its output *quality* is not. The `main.py` orchestrator is coverage-excluded, so the req-49→req-50→`open_pr` guard ordering, the PR-before-`MAJOR_UPDATE_REQUIRED` sequencing, and the `pull_request` artifact emission are verified by inspection, not by an automated test. `agent_reporter.py` (buffering/retry/`seq`) has no committed tests. Security-negative coverage of the GitHub App / Supabase auth path in `credentials.py` is largely absent because the token endpoint is mocked. See `TESTING.md` (Coverage, Security-Negative Tests) for the ranked gap analysis.
- **Front-end (Phase 2).** No JS/TS application test package exists yet (Next.js is Phase 2). The `agentcore/cdk/` package has a single CDK synth smoke test under `jest`. Framework and coverage strategy for the front-end are defined when Phase 2 implementation begins.

## 12. Code Quality & Standards

No linter/formatter configured yet in the repo (no `package.json` at root at the time of this document). Will be defined when front-end implementation starts (Phase 2), following the standard of `pnpm` + canonical scripts (`lint`, `format:check`, `typecheck`, `test`, `audit`, `validate`) once there is TypeScript code to manage.

## 13. Deployment & DevOps

- **Front-end:** Fly.io. A prior app existed (`dt-agent-fleet-control-plane`, torn down in the reset — see `RESET-PLAN.md` Phase 2). Deployment is Phase 2.
- **Agents:** AWS Bedrock AgentCore. The prior deploy used a CloudFormation stack (`AgentCore-depupdater-default`) managed by the AgentCore CLI — also torn down in the reset. Re-deployment is Phase 1.
- **Supporting AWS infrastructure (IAM, OIDC provider, orchestration, config table):** the prior iteration used CDK (`AgentFleetIamStack`, `AgentFleetOrchestrationStack`, `AgentFleetDataStack` on DynamoDB). All destroyed in the reset. v2 replaces the DynamoDB config table with the Supabase tables described in §7 — no equivalent CDK stack is planned yet for v2; will be defined when the IAM setup from §5 is implemented (OIDC provider + role).
- **Known note:** `cdk destroy` does not work under Node.js v26 with `aws-cdk-lib@2.266.0` (incompatibility documented in `RESET-PLAN.md`). If CDK is reintroduced in v2, validate the `aws-cdk-lib` version against the Node version in use before depending on `cdk destroy`/`cdk deploy`.

## 14. Monitoring, Logging & Observability

- **CloudWatch** remains as infrastructure telemetry (container startup, crashes not captured by the SDK), outside the panel's functional scope (see §3). It also serves as a fallback destination when the agent SDK cannot reach the Supabase API — payloads are dumped to stderr, which lands in CloudWatch.
- **Supabase Realtime** on `run_events` and `runs` is the business observability mechanism — live log tail without polling (Phase 2 enables the UI for this; Phase 1 writes the data).
- **Captured log level** by the SDK's `logging.Handler` is configurable via `AGENT_LOG_LEVEL` (default `INFO`), first mitigation lever for R5 if an agent proves too verbose.

## 15. Performance & Scalability

- Indexes on `runs` are designed for the most frequent listing queries: by agent and by repo, both ordered by `created_at desc` (§7).
- The SDK write buffer (50 events / 2 seconds) is the only active performance lever in v1 for log write volume; see R5 for the analysis of why it is not adjusted preemptively.
- No formalized latency or throughput targets — the expected scale in v1 is few agents with non-continuous executions (see `product-context.md` §11, Assumptions).

## 16. Dependency Management

- **Agent — reporting SDK:** zero external dependencies — Python stdlib only (explicit decision, D13). [`agent_reporter.py`](reference/agent_reporter.py) is copied byte-identical into the agent repo; because that verbatim copy trips one mypy check (`exit-return`) on mypy 2.3.1, a per-module override in `pyproject.toml` suppresses that single error code for `agent_reporter` only — the file is not modified and the rest of the codebase keeps full strictness (ADR-001).
- **Agent — runtime (`dependency-update`):** pinned in `pyproject.toml`, `requires-python >=3.13`. Committed runtime dependencies: `bedrock-agentcore` (runtime harness), **`strands-agents` (the LLM fix agent, now activated by the issue #75 escape hatch — a real runtime dependency, no longer "outside scope")**, `boto3`, `requests`, `PyJWT`, `cryptography`. The Bedrock model is selected via `MODEL_ID` (default `us.anthropic.claude-sonnet-4-6`). Dev/quality tooling (also pinned, `[dev]` extra): `pytest`, `pytest-mock`, `pytest-cov`, `ruff`, `mypy`, `pip-audit`. The `audit` gate runs `pip-audit .` scoped to declared runtime deps, not the ambient venv.
- **Front-end:** `@aws-sdk/client-sts`, `@aws-sdk/credential-providers`, `@aws-sdk/types` confirmed as dependencies of [`credentials.ts`](reference/credentials.ts). The rest of the front-end dependency tree is defined when Phase 2 implementation starts (Next.js, Supabase client, etc.), following this repository's `pnpm` standard.

## 17. Development Workflow

- **Active branch for this reset:** `chore/project-reset`, on `origin/main` without fast-forward pending merge as documented in `RESET-PLAN.md` Phase 3.
- **Branch convention for new work:** `story/*` for user stories, `issue/*` for individual issues (naming observed in the repo's commit history, e.g., `issue/62-*`).
- **Commits:** Conventional Commits (active repository rule, see git-guard notice). The history already follows this pattern (`fix(agent): ...`, `docs: ...`, `chore(workstream): ...`).
- **PRs:** require `--body-file`, never inline `--body`, for GitHub issues and PRs (active repository rule).
- **No agent may push or merge directly to `main`.**

## 18. Known Constraints & Trade-offs

Risks explicitly accepted in v1, with their declared exit path (full detail in the technical specification):

| Risk | Accepted trade-off | Future exit |
|---|---|---|
| R1 — No authentication | The panel can invoke agents without login | Shared-secret header, or keep the app private, until Supabase Auth exists |
| R2 — Agent uses Supabase `service role key` | Full database access from the agent container. Key stored in Secrets Manager, not in env vars (D15). | Dedicated Postgres role with scoped grants + signed JWT per run |
| R3 — `run_events` growth | Largest table by two orders of magnitude, no active retention policy | Collapse to Storage + purge at 90 days |
| R4 — `params_schema` without strong cross-validation | Drift between the schema in the database and what the agent expects is only detected at runtime | Agent validates its own payload at startup and fails with `INVALID_PARAMS` |
| R5 — Write volume within a verbose execution | No preventive mitigation | Raise minimum captured level, logger allowlist, truncate per step, or increase batch — "evaluate later" is the chosen option today |
| R6 — Drift between local and Fly environments (SSO permissions vs. scoped OIDC role) | Something that works locally may fail on Fly due to a missing permission | Assume the same role locally with a profile pointing to the Fly `role_arn` |
| R7 — Test runs against the production database | Local development invokes real AgentCore and can write to the configured Supabase | Second Supabase project dedicated to development |
