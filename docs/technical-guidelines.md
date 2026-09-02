# Technical Guidelines — Agent Fleet Control Plane

## Changelog

| Version | Date       | Summary                                                                 | Author           |
| ------- | ---------- | ----------------------------------------------------------------------- | ---------------- |
| 1.0     | 2026-08-26 | Initial version. Reformatted from consolidated PRD, `001_schema.sql`, `002_seed.sql`, `agent_reporter.py`, and `credentials.ts` into foundation doc format. No scope or decision changes. | product-engineer |
| 1.1     | 2026-08-26 | Translated to English. Aligned with two-phase delivery model. | product-engineer |
| 1.2     | 2026-08-27 | Documented the implemented LLM fix-agent escape hatch (issue #75): added the sandbox + mandate-backstop security rule to §6, replaced the stale §11 Testing Strategy with the implemented pytest layer taxonomy, and recorded Strands/Bedrock as a committed agent runtime dependency in §16. See [ADR-001](adr/ADR-001-llm-fix-agent-escape-hatch.md). | technical-writer |
| 1.3     | 2026-08-27 | Documented the implemented `open_pr` step + `pull_request` run artifact (issue #76): updated the §9 `dependency-update` status line (PR-creation/artifact no longer deferred; only `runs.metrics` persistence + deploy/E2E remain, → #77) and refreshed the §11 test surface (PR-creation Layer 1 + Layer 2 tests; suite now 328 passing). Current-state status correction only — no new architectural decision or enforceable-rule change. See [ADR-002](adr/ADR-002-open-pr-step-and-pr-artifact.md). | technical-writer |
| 1.4     | 2026-08-27 | Documented the run-metric under-reporting fix (issue #90): refreshed the §9 `dependency-update` status line to record that `advisories_fixed` is now an audit ID-set diff and `packages_changed` a workspace-aware recursive lockfile snapshot (with a single fixed-advisory count feeding both the PR body Security Summary and `runs.metrics`), and updated the §11 test surface + suite count (now 362 passing). Current-state status correction only — no new architectural decision or enforceable-rule change. See [ADR-003](adr/ADR-003-run-metric-under-report-fix.md). | technical-writer |
| 1.5     | 2026-08-31 | Recorded the `pg_cron` reaper activation and its verification (issue #94): added §18 "Open defects discovered during reaper verification" registering #97/#98/#99/#100, the empirically verified reaper properties (fires 12.3 s after the 3720 s threshold, writes the explanatory event at `max(seq)+1`, two-layer convergence confirmed), and the accepted ~61-minute stale window from the D8 threshold choice. See [ADR-004](adr/ADR-004-schedule-pg-cron-reaper.md). | developer |
| 1.6     | 2026-08-31 | Documentation-gate pass for issue #94 (PR #96) under the same decision record, [ADR-004](adr/ADR-004-schedule-pg-cron-reaper.md) — no new decision taken. Corrected the sections written while the reaper was still unscheduled: §2 and §3 now state the job is registered `* * * * *` and empirically confirmed, §7 records the current scheduling state plus the `RUNTIME_TIMEOUT`/`START_TIMEOUT` event contract and the #99 orphan-step caveat, §14 adds the reaper observability surface (`cron.job_run_details` + the explanatory event), and §18 records the residual verification carried by #101 (AC5, AC6, AC4 `queued` half) and marks the 185.7 s cold-start figure invalid so it is not cited as a measurement. | technical-writer |
| 1.7     | 2026-09-01 | Documented the repeated `prompt`-wrapper unwrap + distinct double-wrap diagnostic (issue #97, PR #102): added a §8 "Invocation payload contract" subsection recording that `unwrap_payload` now unwraps lone-`prompt` wrappers repeatedly (bounded by `_MAX_UNWRAP_DEPTH=16`, guarded by `_is_lone_prompt_wrapper`) to tolerate the `agentcore` CLI ≥0.28.0 double-wrap, and that a still-wrapper-only payload emits an "appears double-wrapped" diagnostic via `classify_invalid_payload` while `error_code` stays `INVALID_PARAMS` (no new error code, no schema change, no migration); flipped the §18 #97 row from Open to Resolved. Current-state status correction only — no enforceable-rule change. See [ADR-005](adr/ADR-005-repeated-prompt-unwrap-and-diagnostic.md). | technical-writer |
| 1.8     | 2026-09-01 | Documented the `validate`-step keep-alive fix (issue #98, PR #103): added a §8 subsection recording the heartbeat keep-alive (`heartbeat.run_with_heartbeat` live-yields chunks during `validate`/`llm_fix`), the four-clock consistency invariant enforced by `config.assert_clock_invariant()` (`TOOL_COMMAND_TIMEOUT ≤ TEST_TIMEOUT ≤ IDLE_SESSION_TIMEOUT ≤ MAX_LIFETIME ≤ REAPER_THRESHOLD_SECONDS`, heartbeat ≤ idle/2), the `idleRuntimeSessionTimeout` 300 → 900 change (requires redeploy), and the best-effort SIGTERM backstop (`signal_backstop.py`; SIGKILL/OOM stays reaper-only); flipped the §18 #98 row to Resolved (code) with live AC2/AC3 verification pending. Introduces an enforceable clock-consistency rule (fail-fast at startup) plus the heartbeat keep-alive and SIGTERM-backstop mechanisms — recorded as a decision in [ADR-006](adr/ADR-006-long-step-keepalive-and-clock-invariant.md). | developer / technical-writer |
| 1.9     | 2026-09-01 | Documented the reaper orphan-`run_steps` fix (issue #99): `reap_stale_runs()` now closes any open `run_steps` (`status='failed'`, `finished_at=now()`, attributing `error_message`) on **both** its branches (`timed_out` and `failed_to_start`), in symmetry with the agent failure path (§8). Refreshed §7 (orphan-step caveat reworded from open-defect to resolved; one stale-window caveat remains), added the §8 "Reaper mirrors the agent's step-closure" note, and flipped the §18 #99 row Open → Resolved. Reuses the existing `step_status` enum value `failed` (no new enum value, no migration); the DDL change lives in `docs/reference/001_schema.sql` and is applied via `create or replace function`. | developer |
| 1.10    | 2026-09-01 | Documented the insert-then-invoke contract + defensive `start()` guard (issue #100): added the §8 behavioral-property row recording that `RunReporter.start()` now issues its `running` PATCH with `Prefer: count=exact`, reads `Content-Range`, and on a **confirmed** zero-row match (no `queued` row inserted — D1) logs a loud stderr warning naming #100 and continues (reporting never kills the agent; an unknown count does not warn). The change is mirrored byte-identically into both `agent_reporter.py` copies (D13). Agent-doc changes (README §Invocation prerequisite + silent-no-op diagnosis) are current-state only; the SDK guard is a small behavioral addition under the existing D1/D15 reporting-contract context, no new enforceable rule. | developer |
| 1.11    | 2026-09-02 | Documented the Phase 2 JS/TS kickoff (issue #114 / S-101): the previously-deferred front-end sections now describe the shipped reality. §12 replaced "no `package.json` at root" with the real pnpm workspace + `panel` ESLint/Prettier/TypeScript-strict toolchain and canonical scripts; §9 records the pnpm workspace, the `panel/` Next.js App Router package, and the two-branch `make validate`; §16 pins the `panel` render/validation dependency tree (`next` 15.5.25 backport line off the RCE-carrying 15.5.4, `react` 19.1.1, `ajv` 8.17.1, Vitest 3.2.4, Playwright 1.56.0; root `pnpm.overrides` for postcss/sharp; one sub-high `ajv` advisory noted; `@aws-sdk/*` + `@supabase/supabase-js` deferred to S-104/S-105/S-111); §11 flips the front-end test line from "no JS/TS test package yet" to the Vitest projects + Playwright stub; §13 notes the panel scaffold exists but is not yet deployed; §1/§2 Phase-2 markers refined to "scaffold exists, not yet deployed". Current-state status correction only — the pnpm/canonical-scripts standard, SD2 server-only Supabase, and the F7 aggregate-gate rule all trace to existing decisions (spec/PRD + §11/`TESTING.md`), so no new enforceable guideline changed and no ADR is required (precedent: rows 1.3/1.4/1.6/1.7). The `next` 15.5.4→15.5.x spec pin write-back is routed to `product-engineer`, not made here. | technical-writer |
| 1.12    | 2026-09-02 | Documented Supabase CLI migration adoption (issue #115 / S-102, PR #130): the canonical schema/seed moved to `supabase/migrations/20260902200101_initial_schema.sql` (byte-identical to the former reference DDL, incl. `pg_cron` + the `reap-stale-runs` schedule) and `supabase/seed.sql`, applied by `supabase db reset`; `supabase/config.toml` added. §7 header rewritten to name the migration + seed as canonical and `docs/reference/001_schema.sql`/`002_seed.sql` as non-canonical zero-DDL pointer stubs; §7 reaper current-state prose re-pointed from `001_schema.sql` to the migration; §8 GitHub App manual-seed link re-pointed to `supabase/seed.sql`; §9 artifact table split into canonical (migration/seed/config.toml) and stub rows. Current-state status correction only — migration adoption is the SD3 decision already recorded in the spec/story, no new architectural decision, so no ADR is required (precedent: rows 1.3/1.4/1.6/1.7/1.11). Layer 2.5 integration-harness/`TESTING.md`/`panel/README.md` changes were already made on-branch and are the `qa-engineer`/implementer surface, not re-authored here. PRD Phase-1 reference-file links left as historical requirements text. | technical-writer |

## 1. Overview

The system has three pieces with different languages and runtimes, joined by Supabase as the *system of record*:

1. **Front-end / panel** — Next.js in TypeScript, deployed on Fly.io (Phase 2).
2. **Agents** — containers in AWS Bedrock AgentCore, in Python, that report their own lifecycle (Phase 1).
3. **Database** — PostgreSQL via Supabase, with Realtime for live log tailing and `pg_cron` for stale-execution detection (Phase 1).

Guiding principle: **the agent reports state explicitly**; nothing is reconstructed by inference over logs (see Problem Statement in `product-context.md`). Every decision in this document upholds that rule or resolves a consequence of it (timeouts, buffering, credentials).

## 2. Technology Stack

| Layer | Technology | Notes |
|---|---|---|
| Front-end | Next.js (TypeScript) | Routes, JSON Schema-generated forms, live tail via Supabase Realtime (Phase 2). The `panel` package (Next.js 15 App Router, React 19, TS strict) is **scaffolded in the repo** as of issue #114 / S-101; routes/forms/live-tail land in later Phase 2 stories |
| Front-end hosting | Fly.io | Node process persists after responding — enables fire-and-forget invocation without a durable queue (D7). Panel **not yet deployed** — scaffold exists, Fly config lands in a later Phase 2 story |
| Agent runtime | AWS Bedrock AgentCore | Containers; AgentCore controls the lifecycle and enforces the real timeout |
| Agent SDK | Python, stdlib only (`urllib`, `logging`, `atexit`) | Single file [`agent_reporter.py`](reference/agent_reporter.py), copied per repo (D13), not a pip package |
| Database | PostgreSQL via Supabase | System of record for executions. RLS deny-all from the first migration (D11) |
| Realtime | Supabase Realtime on `run_events` and `runs` | Live log tail without polling |
| Cron | `pg_cron` inside Supabase | Reaper for stale executions — does not depend on the front-end being alive (D10). Job `reap-stale-runs`, `* * * * *`, **scheduled and verified as of issue #94** (ADR-004) |
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

**Two application layers for the reaper (see specification §6).** `pg_cron` materializes the state change and writes the explanatory `run_event` every minute (D10). The `v_runs` view computes `effective_status` at read time, so the UI never shows a run "running" that has already expired even if the reaper is one minute behind. The reaper materializes eventual truth; the view tells immediate truth. **Both layers are live and empirically confirmed** as of issue #94 ([ADR-004](adr/ADR-004-schedule-pg-cron-reaper.md)): the job is registered `* * * * *`, and on a real hung run the view read `running` pre-threshold and then agreed with `timed_out` after materialization. Note that the explanatory event exists **only** in layer 1 — an unscheduled reaper is therefore worse than a late one, because the view keeps the UI looking correct while `runs.status` stays wrong and the "why" is never written.

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

**Canonical schema and seed (issue #115 / S-102 — Supabase CLI migrations).** The schema is now a Supabase CLI migration: [`supabase/migrations/20260902200101_initial_schema.sql`](../supabase/migrations/20260902200101_initial_schema.sql) is the canonical, executed source of truth (full schema: tables, enums, indexes, view, reaper function, RLS — byte-identical to the former reference DDL, including `pg_cron` and the `reap-stale-runs` schedule), and the canonical seed is [`supabase/seed.sql`](../supabase/seed.sql) (idempotent via `on conflict`), applied by `supabase db reset`. Local project config lives in `supabase/config.toml`.

The former reference files [`docs/reference/001_schema.sql`](reference/001_schema.sql) and [`docs/reference/002_seed.sql`](reference/002_seed.sql) are **no longer canonical** — they are now zero-DDL pointer stubs kept only so existing Markdown links still resolve. Do not add DDL/seed SQL to them; edit the migration (or add a new timestamped migration) and `supabase/seed.sql` instead.

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

**Current state (issue #94, ADR-004).** The schedule is **active**, not pending: the canonical
migration ([`supabase/migrations/20260902200101_initial_schema.sql`](../supabase/migrations/20260902200101_initial_schema.sql))
carries `create extension if not exists pg_cron;` and
`select cron.schedule('reap-stale-runs', '* * * * *', $$select reap_stale_runs()$$);` uncommented at
its tail (the extension still has to be enabled with sufficient privilege, so the Supabase-dashboard
note is retained). Each reaped run gets `error_code = RUNTIME_TIMEOUT` or `START_TIMEOUT` plus one
`run_events` row at `max(seq)+1` with `level = error`, `data.reaped_by = reap_stale_runs`, and
`data.reason`. As of issue #99 the function also **closes any open `run_steps`** for a reaped run
(sets `status = 'failed'`, `finished_at = now()`, and an attributing `error_message`), in symmetry
with the agent's own failure path (§8) — so a reaped run no longer leaves an in-flight step pinned
`running`. One caveat remains: because the thresholds mirror AgentCore's own limits, a container that
dies early still reads `running` until its boundary (~61 minutes in the observed case — see §18).
Operator procedures and the verification
evidence are in [`runbooks/issue-94-reaper-verification.md`](runbooks/issue-94-reaper-verification.md).

`last_heartbeat_at` is declared in the schema but not used for detection in v1 — it comes into play only if agents appear that hang well below their timeout (backlog).

**Retention (declared risk, not resolved in v1 — R3).** `run_events` will be the largest table by two orders of magnitude. Policy pending: events older than 90 days get collapsed to an artifact in Supabase Storage and the rows are purged.

**Separate environments (R7).** Local development invokes real AgentCore; to avoid mixing test runs with production runs, the recommended exit is a second Supabase project for development (free tier is sufficient, same schema).

## 8. Integration Methods

**AWS Bedrock AgentCore.** The front-end invokes `InvokeAgentRuntime` in a fire-and-forget manner from the route handler (see §4). There is no automatic retry on the front-end side for startup failures — it marks `failed_to_start` and stops there; the reaper is the safety net for the case where the invocation was accepted but the container never reported.

**Invocation payload contract — repeated `prompt`-wrapper unwrapping (issue #97).** AgentCore delivers the JSON payload inside a `prompt` key as a JSON string. Historically this was a single wrap. As of `agentcore` CLI ≥ 0.28.0 the CLI treats its invoke argument *as* the prompt and wraps it itself, so an already-wrapped argument arrives **double-wrapped**. The agent entrypoint (`main.unwrap_payload`) therefore unwraps **repeatedly** rather than once: it keeps stripping while the current value is a dict whose *only* key is a string `prompt` that parses to a JSON dict (`_is_lone_prompt_wrapper`), bounded by `_MAX_UNWRAP_DEPTH = 16` as a defensive guard. Both the bare inner JSON and the pre-wrapped form are accepted. The loop never over-unwraps a legitimate inner payload that carries its own `prompt` field or sibling keys, and stops on a non-string `prompt` or a `prompt` string that does not parse to a JSON dict. This is a tolerance widening, not a contract change: the required fields (`run_id`, `repository_org`, `repository_name`) and the `INVALID_PARAMS` failure mode are unchanged. When a payload is still wrapper-only after unwrapping — the tell-tale of a double-wrap that could not be resolved — a pure `classify_invalid_payload` helper drives a distinct "appears double-wrapped" diagnostic log line while `error_code` remains `INVALID_PARAMS` (no new error code, no schema change). See [ADR-005](adr/ADR-005-repeated-prompt-unwrap-and-diagnostic.md).

**Agent reporting contract ([`agent_reporter.py`](reference/agent_reporter.py), D13).** Single file copied to each agent repo, no external dependencies (`urllib`, not `supabase-py` or `httpx`). Hybrid interface (D14):

- **Standard `logging.Handler`**, attached to the root logger — captures noise from third-party libraries (`boto3`, `httpx`), which is exactly what you want to see when something fails.
- **Explicit lifecycle API** (`RunReporter.from_env()`, `run.step(...)`, `run.succeed(...)`, `run.fail(...)`, `run.artifact(...)`) — the lifecycle does not fit naturally in a `logger.info()`.

**Long-step keep-alive + timeout-clock invariant (issue #98).** The `@app.entrypoint`
handler is an async generator that historically yielded only at terminal points, so during a
long blocking step (notably `pnpm test` inside `validate`) the AgentCore response stream was
idle. Once idle past `idleRuntimeSessionTimeout`, AgentCore reclaimed the container before the
agent could write a terminal status — the run sat `running` until the reaper marked it
`timed_out` (root cause confirmed from CloudWatch on run `f63ac9f3-…`; the container log ended
cleanly on the last `update`-step line with no exception/OOM/terminal line). The fix keeps the
stream alive: `validate` and `llm_fix` run under `heartbeat.run_with_heartbeat`, which executes
the blocking step in a worker thread and **live-yields lightweight heartbeat chunks** every
`HEARTBEAT_INTERVAL` seconds. Heartbeat chunks (`{"heartbeat": {...}}`) are structurally
distinct from the terminal result payload (the existing `event.contentBlockDelta.delta.text`
shape), the terminal payload is always the last chunk emitted, and a consumer reads it with
`heartbeat.read_terminal_payload` (heartbeats ignored). The reusable logic lives in
`heartbeat.py`, **not** in the vendored `agent_reporter.py` (D13 — the copy must not diverge).

The four timeout "clocks" MUST stay mutually consistent so no inner bound can outlive an outer
one; `config.assert_clock_invariant()` enforces this at entrypoint start (fail-fast with
`ClockConsistencyError` rather than a silent mid-step death — an enforceable rule recorded in
[ADR-006](adr/ADR-006-long-step-keepalive-and-clock-invariant.md)), and a unit test asserts the
shipped constants satisfy it:

```
TOOL_COMMAND_TIMEOUT (180)  <=  TEST_TIMEOUT (600)  <=  IDLE_SESSION_TIMEOUT (900)
                            <=  MAX_LIFETIME (3600)  <=  REAPER_THRESHOLD_SECONDS (3720)
    and   0 < HEARTBEAT_INTERVAL (120)  <=  IDLE_SESSION_TIMEOUT / 2
```

`IDLE_SESSION_TIMEOUT`/`MAX_LIFETIME` mirror `agentcore/agentcore.json`
`lifecycleConfiguration` (`idleRuntimeSessionTimeout` was raised 300 → 900 for this fix — a
runtime redeploy is required, see the pending-manual-config runbook), and
`REAPER_THRESHOLD_SECONDS` mirrors the Supabase run snapshot (`max_runtime_seconds` +
`grace_seconds`). The reaper remains the **outer** backstop, never a competitor to a
legitimately-running container.

**`start_timeout_seconds` is a queue clock, not `idleRuntimeSessionTimeout` (issue #116 / S-103).**
The seed formerly asserted that `agents.start_timeout_seconds (300)` "MUST equal
`idleRuntimeSessionTimeout`". That equivalence was never correct and is now removed. The two measure
different failures on different clocks: `start_timeout_seconds` is the **queue clock** (`queued_at`-based,
D9) — how long an *accepted* invocation may sit before the agent reports a *start*, after which the
reaper marks it `failed_to_start` (§7 table, row 2). `idleRuntimeSessionTimeout` is an **output-idle
clock** — how long AgentCore tolerates a *running* container producing no stream output before it
reclaims it (the issue #98 clock, raised 300 → 900). Issue #98 raising the idle clock to 900 exposed
the stale comment but did not create the mismatch. The resolution is **direction A: correct the
comment, keep the value at 300** — the queue clock has no reason to track the idle clock, so no value
change and therefore no change to the four-clock invariant above. Recorded in `supabase/seed.sql`
block 3.

**Abrupt-termination backstop (issue #98, AC6).** `RunReporter.__exit__` guarantees a terminal
write on any *normal* Python exit, but not on an abrupt kill. `signal_backstop.py` adds a
best-effort SIGTERM handler that marks the active run `failed / SIGNAL_TERMINATION` (message
secret-scrubbed, handler never raises) so an interceptable stop does not wait for the reaper. A
true **SIGKILL / OOM cannot be intercepted** by any process — that path is by design covered
only by the pg_cron reaper.

The agent authenticates to PostgREST directly (D15) using the Supabase service role key fetched from AWS Secrets Manager at startup — not from an env var.

Behavioral properties:

| Property | Behavior |
|---|---|
| Write buffer (D5) | Inline flush every 50 events or 2 seconds; forced at step boundary open/close and on termination. No background thread — async worker adds queue, `join`, and `atexit` for ~200 ms |
| Retries | 3 with exponential backoff. 4xx are not retried (contract error). If exhausted, the payload is written to stderr (lands in CloudWatch) and the agent continues — reporting never kills the agent |
| Agent failure | The context manager marks `failed` with full traceback before re-raising; open steps are closed as `failed` |
| Exit without `succeed()` | Closes with `outcome = not_applicable` to avoid leaving the run dangling |
| Zero-row `start()` (issue #100) | `start()` issues its `running` PATCH with `Prefer: count=exact` and reads `Content-Range`. A **confirmed** zero-row match (no `queued` row was inserted — D1) logs a loud stderr warning naming issue #100, then continues — reporting never kills the agent, and an unknown count (request failed / header absent) does **not** warn, to avoid false alarms |
| Truncation | Messages to 8 KB |
| Transport change | Isolated to the `_SupabaseClient` class (~40 lines) — no generic transport abstraction because today it does not pay for itself |

**Reaper mirrors the agent's step-closure (issue #99).** The "Agent failure" row above closes open
steps as `failed` from the *agent* side. The `pg_cron` reaper is the *database*-side counterpart for
runs the agent never closed itself: on both its branches (`timed_out` and `failed_to_start`),
`reap_stale_runs()` now runs `update run_steps set status='failed', finished_at=now(), error_message=<reaper attribution> where run_id=<run> and status in ('running','pending')`
after materializing the run-level terminal state. `failed` reuses the existing `step_status` enum
value (no new enum value, no migration), and the predicate leaves already-terminal steps
(`succeeded`/`failed`/`skipped`) untouched. A `failed_to_start` run normally has no steps; the update
is a safe 0-row no-op in that case. This closes the orphan-step defect from §7/§18 and removes the
"perpetually pulsing step inside a terminal run" the Phase 2 Run Detail panel (`DESIGN.md` §5.3) would
otherwise have to special-case.

**Per-execution write volume (R5, distinct from R3 which is growth over time).** Not actively mitigated in v1 — the chosen approach is "evaluate later" if an actual agent evidences the problem (e.g., one that tails builds or long test runs). First lever if it occurs: raise the minimum captured log level (`INFO+` instead of `DEBUG+`).

**GitHub App.** The agent reads the private key and `installation_id` from Secrets Manager and issues a short-lived installation token to clone the repo and open the PR. Automatic repo sync from the GitHub App is backlog — v1 uses the manual seed ([`supabase/seed.sql`](../supabase/seed.sql)).

## 9. Code Organization & Structure

Artifacts already defined at design level (see specification §14):

| File/directory | Role |
|---|---|
| [`supabase/migrations/20260902200101_initial_schema.sql`](../supabase/migrations/20260902200101_initial_schema.sql) | **Canonical** schema (Supabase CLI migration, issue #115 / S-102): full DDL — tables, enums, indexes, `v_runs` view, `reap_stale_runs()` function, RLS, `pg_cron` + `reap-stale-runs` schedule |
| [`supabase/seed.sql`](../supabase/seed.sql) | **Canonical** idempotent seed applied by `supabase db reset`: installation, repo list, `dependency-update` agent |
| `supabase/config.toml` | Local Supabase project config (issue #115 / S-102) |
| [`docs/reference/001_schema.sql`](reference/001_schema.sql) / [`docs/reference/002_seed.sql`](reference/002_seed.sql) | **Non-canonical pointer stubs** (issue #115 / S-102). Zero-DDL; kept only so existing Markdown links resolve — edit the migration + `supabase/seed.sql`, never these |
| [`agent_reporter.py`](reference/agent_reporter.py) | Reporting SDK, copied to each agent repo |
| [`credentials.ts`](reference/credentials.ts) | AWS credential provider with Fly OIDC / local branches |
| `panel/` front-end | Next.js 15 (App Router) package under `panel/`, the primary member of the repo-root pnpm workspace — scaffolded in Phase 2 (issue #114 / S-101). Placeholder `app/layout.tsx` (DESIGN §1.2 Inter `<link>`) + `app/page.tsx`; routes, schema-generated forms, and live tail land in later Phase 2 stories. React 19, TypeScript strict, ESLint + Prettier, Vitest (unit/component/integration projects) + Playwright config stub. |
| `dependency-update` agent | AgentCore runtime under `agents/dependency-update/` — implemented (Phase 1): deterministic audit→classify→update→validate pipeline, the bounded LLM fix loop (`fix_agent.py`, ADR-001), and the idempotent `open_pr` step with the `pull_request` run artifact (`pull_request.py`, issue #76). Run metrics are computed correctly as of issue #90: `advisories_fixed` is an advisory ID-set diff between the before/after audits (`audit.count_advisories_fixed`), and `packages_changed` is derived from a workspace-aware, recursive lockfile snapshot (`pnpm list -r --depth Infinity` / `npm list --all`) — the previous `in_range` bucket subtraction and `--depth 0` root-only listing both under-reported (0) on monorepos. A single fixed-advisory count feeds both the PR body Security Summary and `runs.metrics.advisories_fixed` so they cannot disagree. Deferred to issue #77: fix-budget test-output artifact, plus deploy + E2E. |

The repository is now a **pnpm workspace** (`pnpm-workspace.yaml`, members `panel` and
`agents/dependency-update/agentcore/cdk`) with a root `package.json` whose canonical scripts
delegate to `panel` via `pnpm --filter`. The front-end folder convention is settled for the
scaffold: the `panel` package follows the Next.js App Router layout (`app/`, with `lib/` and
route directories added as Phase 2 screens land). The repo-root `Makefile` `validate` runs a
Python branch and a JS/TS branch, both of which must pass.

## 10. Design Patterns & Principles

- **Explicitness over inference.** Every observable state in the panel is written explicitly by the agent or the reaper; nothing is derived by parsing free text.
- **YAGNI on transport and infrastructure abstractions.** No pip package for the SDK (D13), no durable queue for invocation (D7), no `agent_versions` table (snapshot in `runs` suffices). These decisions are explicitly revisable if the fleet grows (see backlog).
- **Auditability by snapshot, not by referenced version.** Each `run` is self-contained regarding the parameters and thresholds it ran with, even if the agent's configuration changes later.

## 11. Testing Strategy

The canonical testing contract lives in [`TESTING.md`](../TESTING.md) — this section summarizes the current state for the `dependency-update` agent (Phase 1) and points to it.

- **Framework and layers (Python agent).** `pytest 8.3.5` with branch coverage via `pytest-cov`. Layer markers are auto-applied by directory in `tests/conftest.py`: `tests/unit/` → Layer 1 (`unit`, no I/O/network — all `boto3`/`requests`/`jwt`/`subprocess` boundaries mocked), `tests/component/` → Layer 2 (`component`, mocked externals + temp-dir project fixtures). The aggregate gate is `make validate` (lint + format:check + typecheck + test-cov + audit), enforced in CI (`.github/workflows/ci.yml`) on a Python 3.13 + 3.14 matrix for every push/PR to `main`.
- **LLM fix agent test surface (issue #75).** The escape hatch adds a Layer 1 + Layer 2 surface exercised without invoking a real model: `tests/unit/test_safe_path.py` (workspace-escape guard — traversal, absolute, symlink, null-byte), `tests/unit/test_mandate_check.py` (`verify_no_mandate_violation` add/remove/change/malformed-JSON/missing-file), `tests/unit/test_fix_tools.py` (tool path-safety), and `tests/component/test_fix_agent.py` (5-tool surface, retry-budget exhaustion, early success, `max_attempts=0` → zero model calls, agent-exception resilience) with the Strands `Agent` mocked. `fix_agent.py` reports ~91% line coverage.
- **PR-creation test surface (issue #76).** The `open_pr` step adds a Layer 1 + Layer 2 surface with `git`/`gh` mocked: `tests/unit/test_pr_body.py` (branch naming + conditional PR-body sections, cap-at-30, AI-warning, validation table — 19 tests) and `tests/component/test_pr_creation.py` (idempotency short-circuit, `--body-file` never inline, never-push-to-default, credential-helper push, commit-message contract — 14 tests), plus additions to `tests/component/test_pipeline.py` (token-staleness re-mint). `pull_request.py` reports ~95% line coverage.
- **Run-metric under-report fix test surface (issue #90).** The metric-computation fix adds a Layer 1 + Layer 2 surface: `tests/unit/test_audit.py` gains `TestCountAdvisoriesFixed` (advisory ID-set diff — unknown-bucket fixtures, equal sets, all-fixed, empty-before, no-negative result, dedupe) and monorepo-recursion cases for `_parse_list_json` / `snapshot_lockfile_packages` (workspace + transitive capture, command-shape assertions), backed by new fixtures (`audit_pnpm_before.json`, `audit_pnpm_after.json`, `list_pnpm_monorepo.json`); `tests/component/test_pipeline.py` gains `test_security_summary_uses_id_set_diff_not_bucket_count` asserting the PR body Security Summary and Package Changes agree with the real diff (no contradictory `fixed: 0`). Full suite: **362 tests passing**.
- **Known gaps (tracked, non-blocking).** No Layer 3 product-evaluation/eval harness exists for the LLM path (semantic/groundedness) — the fix-agent *code path* is tested but its output *quality* is not. The `main.py` orchestrator is coverage-excluded, so the req-49→req-50→`open_pr` guard ordering, the PR-before-`MAJOR_UPDATE_REQUIRED` sequencing, and the `pull_request` artifact emission are verified by inspection, not by an automated test. `agent_reporter.py` (buffering/retry/`seq`) has no committed tests. Security-negative coverage of the GitHub App / Supabase auth path in `credentials.py` is largely absent because the token endpoint is mocked. See `TESTING.md` (Coverage, Security-Negative Tests) for the ranked gap analysis.
- **`validate`-step keep-alive test surface (issue #98).** The heartbeat fix adds a Layer 1 + Layer 2 surface exercised without a live runtime: `tests/unit/test_heartbeat.py` (chunk contract, `run_with_heartbeat` short/long/exception/bounded-count, terminal-last property RT-1, consumer parser + fuzz RT-3), `tests/unit/test_clock_invariant.py` (shipped-config consistency, rejection of each violated relation SC-4, heartbeat ≤ idle/2 EC-2, property RT-2), `tests/unit/test_signal_backstop.py` (best-effort SIGTERM report, already-terminal no-op, secret-scrub EC-7, never-raises), and `TestEntrypointHeartbeatWiring` in `tests/component/test_pipeline.py` (a slow mocked `validate` emits ≥1 heartbeat and a single terminal chunk last, SC-3). `heartbeat.py` ~94%, `config.py` ~96% line coverage; `signal_backstop.py`'s signal-registration path is not unit-covered (its reportable core is). Full suite: **416 tests passing**.
- **Front-end (`panel`, Phase 2).** The JS/TS application test package now exists (issue #114 / S-101): `panel` uses **Vitest 3.2.4** with config-level `projects` (unit / component / integration) + `@vitest/coverage-v8`, reachable from the repo-root `make validate` JS/TS branch. A **Playwright** config stub is committed (`panel/playwright.config.ts`, `test:e2e` wired) but the E2E scenario suite lands in S-114 — no committed scenarios yet. The `agentcore/cdk/` package still has its single CDK synth smoke test under `jest`. See `TESTING.md` for the per-package table.

## 12. Code Quality & Standards

The JS/TS quality toolchain is now real (Phase 2 has begun — issue #114 / S-101). A root
`package.json` exists (`packageManager: pnpm@10.11.0`, `engines.node >=22`) and a
`pnpm-workspace.yaml` declares the workspace members (`panel`, `agents/dependency-update/agentcore/cdk`).
The `panel` package uses **ESLint 9** (`next/core-web-vitals` + `next/typescript`, plus an SD2
restricted-import rule that forbids client-side import of `lib/supabase/server`), **Prettier 3**,
and **TypeScript 5.7 strict**. The canonical `package.json` scripts are wired on both the root
(delegating to `panel` via `pnpm --filter`) and the `panel` package itself: `lint`, `lint:fix`,
`format`, `format:check`, `typecheck`, `test`, `test:unit`, `test:integration`, `test:e2e`,
`test:coverage`, `audit`, `validate`. The `panel` `validate` aggregate runs
lint + format:check + typecheck + test + audit, and is reached from the repo-root `make validate`
JS/TS branch (F7 closed — the panel is inside the aggregate gate). The Python agent keeps its own
`ruff`/`mypy` toolchain (§11, `TESTING.md`); the two branches run independently under
`make validate` and both must pass.

## 13. Deployment & DevOps

- **Front-end:** Fly.io. A prior app existed (`dt-agent-fleet-control-plane`, torn down in the reset — see `RESET-PLAN.md` Phase 2). The `panel` Next.js package now exists in the repo as a scaffold (issue #114 / S-101), but is **not yet deployed** — Fly deployment and its config (`fly.toml`, Dockerfile) land in a later Phase 2 story.
- **Agents:** AWS Bedrock AgentCore. The prior deploy used a CloudFormation stack (`AgentCore-depupdater-default`) managed by the AgentCore CLI — also torn down in the reset. Re-deployment is Phase 1.
- **Supporting AWS infrastructure (IAM, OIDC provider, orchestration, config table):** the prior iteration used CDK (`AgentFleetIamStack`, `AgentFleetOrchestrationStack`, `AgentFleetDataStack` on DynamoDB). All destroyed in the reset. v2 replaces the DynamoDB config table with the Supabase tables described in §7 — no equivalent CDK stack is planned yet for v2; will be defined when the IAM setup from §5 is implemented (OIDC provider + role).
- **Known note:** `cdk destroy` does not work under Node.js v26 with `aws-cdk-lib@2.266.0` (incompatibility documented in `RESET-PLAN.md`). If CDK is reintroduced in v2, validate the `aws-cdk-lib` version against the Node version in use before depending on `cdk destroy`/`cdk deploy`.

## 14. Monitoring, Logging & Observability

- **CloudWatch** remains as infrastructure telemetry (container startup, crashes not captured by the SDK), outside the panel's functional scope (see §3). It also serves as a fallback destination when the agent SDK cannot reach the Supabase API — payloads are dumped to stderr, which lands in CloudWatch.
- **Supabase Realtime** on `run_events` and `runs` is the business observability mechanism — live log tail without polling (Phase 2 enables the UI for this; Phase 1 writes the data).
- **Captured log level** by the SDK's `logging.Handler` is configurable via `AGENT_LOG_LEVEL` (default `INFO`), first mitigation lever for R5 if an agent proves too verbose.
- **Reaper observability (issue #94).** The `pg_cron` job is its own telemetry surface: `cron.job` shows the registered `reap-stale-runs` entry and `cron.job_run_details` shows per-tick success/failure — the check to run when runs stop being reaped. Every materialized transition also writes one `run_events` row carrying `data.reaped_by` and `data.reason`, which is the only record of *why* a run ended when the agent itself never reported (product-context success metric 3). No alerting is wired on either surface in v1; detection is manual, per [`runbooks/issue-94-reaper-verification.md`](runbooks/issue-94-reaper-verification.md).

## 15. Performance & Scalability

- Indexes on `runs` are designed for the most frequent listing queries: by agent and by repo, both ordered by `created_at desc` (§7).
- The SDK write buffer (50 events / 2 seconds) is the only active performance lever in v1 for log write volume; see R5 for the analysis of why it is not adjusted preemptively.
- No formalized latency or throughput targets — the expected scale in v1 is few agents with non-continuous executions (see `product-context.md` §11, Assumptions).

## 16. Dependency Management

- **Agent — reporting SDK:** zero external dependencies — Python stdlib only (explicit decision, D13). [`agent_reporter.py`](reference/agent_reporter.py) is copied byte-identical into the agent repo; because that verbatim copy trips one mypy check (`exit-return`) on mypy 2.3.1, a per-module override in `pyproject.toml` suppresses that single error code for `agent_reporter` only — the file is not modified and the rest of the codebase keeps full strictness (ADR-001).
- **Agent — runtime (`dependency-update`):** pinned in `pyproject.toml`, `requires-python >=3.13`. Committed runtime dependencies: `bedrock-agentcore` (runtime harness), **`strands-agents` (the LLM fix agent, now activated by the issue #75 escape hatch — a real runtime dependency, no longer "outside scope")**, `boto3`, `requests`, `PyJWT`, `cryptography`. The Bedrock model is selected via `MODEL_ID` (default `us.anthropic.claude-sonnet-4-6`). Dev/quality tooling (also pinned, `[dev]` extra): `pytest`, `pytest-mock`, `pytest-cov`, `ruff`, `mypy`, `pip-audit`. The `audit` gate runs `pip-audit .` scoped to declared runtime deps, not the ambient venv.
- **Front-end (`panel`):** the render/validation dependency tree is now pinned (Phase 2 has begun — issue #114 / S-101). Runtime deps in `panel/package.json`: **`next` 15.5.25** and **`eslint-config-next` 15.5.25** (the 15.5 backport line — pinned off the spec's 15.5.4 because 15.5.4 carries a critical RCE advisory; the version write-back to the spec is routed to `product-engineer`, not made here), **`react`/`react-dom` 19.1.1**, **`ajv` 8.17.1** + **`ajv-formats` 3.0.1** (for `params_schema` validation in later stories), and **`@phosphor-icons/react` 2.1.10** (DESIGN §10 icon set). Dev/quality tooling (also pinned): **`vitest` 3.2.4** (config-level `projects` API) + **`@vitest/coverage-v8` 3.2.4**, **`@testing-library/react`/`jest-dom`**, **`jsdom`**, **`playwright`/`@playwright/test` 1.56.0**, **`eslint` 9.18.0**, **`prettier` 3.4.2**, **`typescript` 5.7.3**. Root `package.json` `pnpm.overrides` pin **`postcss>=8.5.18`** and **`sharp>=0.34.4`** transitively (audit-driven). One residual **moderate** `ajv` advisory sits below the `--audit-level=high` gate and does not fail `audit`. The `@aws-sdk/*` and `@supabase/supabase-js` clients are intentionally deferred to later stories (S-104/S-105/S-111) and are not yet in `panel`; the `@aws-sdk/*` set remains confirmed for [`credentials.ts`](reference/credentials.ts) when the invocation path lands.

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

### Open defects discovered during reaper verification (issue #94)

The `pg_cron` reaper was scheduled and its stale-run detection verified in issue #94 (see
[`runbooks/issue-94-reaper-verification.md`](runbooks/issue-94-reaper-verification.md)). The reaper
behaved correctly in every observed case, but the verification surfaced four defects elsewhere in
the stack. Each was tracked as its own issue; the **Status** column below records its current
resolution state:

| Issue | Defect | Impact | Status |
|---|---|---|---|
| [#97](https://github.com/llipe/dev-tasks-agent-fleet/issues/97) | `unwrap_payload()` strips exactly one `prompt` wrapper, but `agentcore` CLI ≥0.28.0 wraps the prompt argument itself — the documented pre-wrapped form arrives double-wrapped and dies with a generic `INVALID_PARAMS` | Any invocation using the README / #77-runbook examples fails; the error gives no hint of the real cause | **Resolved (PR #102):** `unwrap_payload()` now strips nested lone-`prompt` wrappers in a loop (bounded by `_MAX_UNWRAP_DEPTH=16`), and a still-wrapper-only payload emits a distinct "appears double-wrapped" diagnostic while `error_code` stays `INVALID_PARAMS`. See §8 and [ADR-005](adr/ADR-005-repeated-prompt-unwrap-and-diagnostic.md). |
| [#98](https://github.com/llipe/dev-tasks-agent-fleet/issues/98) | A run died during the `validate` step without reporting terminal status. The entrypoint yields only its final result, so a run streams nothing for its whole duration against `idleRuntimeSessionTimeout: 300`; `TEST_TIMEOUT` defaults to 600 s, twice that. Root cause unconfirmed (idle-timeout vs. OOM both fit) | If runs cannot survive ~5 min, `maxLifetime: 3600` is moot and no long `llm_fix` run completes. **Blocks issue #94 AC5** | **Resolved (code) / live-verify pending (PR #103):** root cause confirmed as output-idle reclamation from CloudWatch (clean silence on run `f63ac9f3-…`, no OOM signature). `validate`/`llm_fix` now live-yield heartbeat chunks (`heartbeat.py`), `idleRuntimeSessionTimeout` raised 300 → 900, and the four timeout clocks are enforced consistent by `config.assert_clock_invariant()`. Best-effort SIGTERM backstop added; SIGKILL/OOM stays reaper-only. See §8. AC2 (>5 min validate) and AC3 (>20 min llm_fix) require a runtime redeploy to verify live. |
| [#99](https://github.com/llipe/dev-tasks-agent-fleet/issues/99) | `reap_stale_runs()` transitions `runs` and writes the explanatory event but never closes open `run_steps` — unlike the agent's own failure path (§8), which closes them as `failed` | Every reaped run leaves an orphan step pinned `running`; the Phase 2 Run Detail panel (DESIGN.md §5.3) would render a perpetually pulsing step inside a terminal run | **Resolved:** `reap_stale_runs()` now closes open `run_steps` (`status='failed'`, `finished_at=now()`, attributing `error_message`) on **both** branches (`timed_out` and `failed_to_start`), mirroring the agent path (§8). Reuses the existing `step_status` enum value `failed` (no migration); leaves already-terminal steps untouched; safe 0-row no-op when a run has no steps. See §7/§8. |
| [#100](https://github.com/llipe/dev-tasks-agent-fleet/issues/100) | Per D1 the control plane inserts the `queued` `runs` row; the agent SDK only PATCHes it. A direct `agentcore invoke` therefore leaves the run invisible — PostgREST returns HTTP 200 on a zero-match UPDATE | Runs appear to vanish with no error anywhere; documented contract omits the insert requirement | **Resolved:** the insert-then-invoke prerequisite is now documented (README §Invocation, reaper-runbook §4.0), and `RunReporter.start()` issues its `running` PATCH with `Prefer: count=exact`, reads `Content-Range`, and on a **confirmed** zero-row match logs a loud stderr warning naming #100 before continuing (an unknown count does **not** warn). No schema/migration change; small behavioral addition under the existing D1/D15 reporting-contract context, no new enforceable rule. See §8 (Behavioral properties → *Zero-row `start()`*). |

**Verified-correct reaper behaviour worth recording** (from the same exercise, real run
`f63ac9f3-14b0-4157-9484-f2f6b062f846`): the reaper fired 12.3 s after the 3720 s threshold
(`max_runtime 3600 + grace 120`) — inside one cron tick, never early; its explanatory event took
`seq = max(seq)+1` without colliding with `uq_run_events_seq`; and `v_runs.effective_status`
reported `running` pre-threshold then agreed with `timed_out` after materialization, confirming the
two-layer design in §3.

**Accepted consequence of the D8 threshold choice.** Because `max_runtime_seconds` mirrors
AgentCore's `maxLifetime` (3600) plus `grace_seconds` (120), a container that dies early still reads
`running` until the 3720 s boundary. The run above died around 19:36 and was marked `timed_out` at
20:37 — a ~61-minute window of plausible-but-stale state. This is the accepted tradeoff, not a
reaper failure; `last_heartbeat_at` (declared, unused in v1) is the lever if it ever needs
tightening.

**Residual verification, not a defect.** Issue #94 closed with **5 of 7 acceptance criteria
verified** (AC1, AC2, AC3, AC4, AC7). Three checks remain and are carried by
[#101](https://github.com/llipe/dev-tasks-agent-fleet/issues/101): AC5 (a healthy long run is not
reaped early, plus a *valid* cold-start measurement), AC6 (the SDK's CloudWatch fallback when
PostgREST is unreachable), and the `queued` → `failed_to_start` read-time half of AC4 — `v_runs` has
two independent branches and only the `running` one was observed. Two consequences to respect until
#101 closes: the reaper's **must-not-reap** direction rests on one incidental observation rather than
a deliberate check, and the earlier cold-start figure of **185.7 s is invalid** (it includes human
delay between the row INSERT and the `agentcore invoke`; the agent's first log and `started_at` were
180 ms apart). It must not be cited as a measurement or used to justify a `grace_seconds` change.
`TESTING.md` (Database / reaper layer) ranks the corresponding structural test gaps.
