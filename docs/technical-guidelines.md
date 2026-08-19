# Technical Guidelines — dev-tasks-agent-fleet

## Changelog

| Version | Date       | Summary                                                | Author           |
| ------- | ---------- | ------------------------------------------------------ | ---------------- |
| 1.1     | 2026-08-19 | IaC changed from Terraform to AWS CDK (TypeScript). Agent Python 3.13. Added the agent-liveness / non-blocking-entrypoint constraint. `stale` → `incomplete` bounded by `maxLifetime`. | product-engineer |
| 1.0     | 2026-08-19 | Initial version, derived from PRD v1.0 (scope closed)   | product-engineer |

---

## 1. Overview

This monorepo holds three kinds of software that share two contracts: a Next.js control plane deployed to Fly.io, a set of AI agents deployed to AWS Bedrock AgentCore, and the infrastructure that schedules and supports them. The two shared contracts are the **DynamoDB single-table schema** and the **`llipe.*` span attribute set**.

Guiding principles:

1. **The contract is code, in one place.** `packages/shared` is the only definition of the DynamoDB schema and the `llipe.*` attributes. Every other package consumes it. Two implementations of the same contract drift silently; that is the entire reason this is a monorepo.
2. **The IAM policy is the scope boundary.** PRD §3 lists what v1 does not do. That list is enforced by omitting permissions, not by omitting UI buttons.
3. **Server-first, no API layer.** AWS calls happen in React Server Components and Server Actions. An HTTP API between the browser and the server would be a second surface to authenticate and maintain for no gain.
4. **Stateless by design.** No database in the control plane. A container restart clears the in-memory cache and loses nothing.
5. **Test-first.** Tests and acceptance scenarios are designed before implementation. The contract test between emitted spans and `packages/shared` is the load-bearing one.
6. **Small and finished over general and open.** v1 scope is closed. Resist abstraction for requirements listed in the backlog.

---

## 2. Technology Stack

### Workspace

| Concern         | Choice                                                                 |
| --------------- | ---------------------------------------------------------------------- |
| Package manager | **pnpm** with workspaces (`pnpm-workspace.yaml`). Required, not preferred. |
| Node runtime    | Pinned exactly in `.nvmrc` and `engines`, matched to the container base image. |
| Language (JS)   | TypeScript, `strict: true`, no implicit `any`, `noUncheckedIndexedAccess`. |
| Monorepo tasks  | pnpm workspace scripts. Add a task runner only if build times justify it. |

### Control plane — `apps/control-plane`

| Concern     | Choice                                                    |
| ----------- | --------------------------------------------------------- |
| Framework   | Next.js App Router, `output: 'standalone'`                 |
| UI          | shadcn/ui + Tailwind CSS                                   |
| Tables      | TanStack Table                                             |
| AWS access  | AWS SDK for JavaScript v3, modular clients only            |
| Validation  | Zod — every external input and every AWS response boundary |
| State       | Server components plus an in-process TTL cache. No client store. |

### Agents — `agents/*`

| Concern      | Choice                                                                 |
| ------------ | ---------------------------------------------------------------------- |
| Language     | **Python 3.13**, matching the reference agent and where the AgentCore SDK ecosystem lives |
| Dependencies | `uv` with a committed lockfile, exact pins                             |
| Contract     | Generated Python module produced from `packages/shared` — never hand-written |
| Lint / types | `ruff` + `mypy --strict`                                               |
| Concurrency  | **The entrypoint must never block.** See "Agent liveness" below.        |

### Orchestrator and infrastructure

| Concern     | Choice                                                                     |
| ----------- | -------------------------------------------------------------------------- |
| Orchestrator | **TypeScript** Lambda. It reads GSI1 and builds `session_id` — both contract-bound, so native import of `packages/shared` matters more here than SDK breadth. |
| IaC         | **AWS CDK (TypeScript).** Same language as the orchestrator, the control plane, and `packages/shared`, so infrastructure imports the same constants it deploys — table name, GSI name, tag keys, agent names. Also what the reference agent already uses. |
| Hosting     | Fly.io, single machine, single container                                    |

### Cross-language contract flow

`packages/shared` (TypeScript, source of truth) → JSON Schema → generated Python module.

Generation is a build step with committed output and a CI check that fails when the generated artifact does not match the source. Hand-editing generated files is prohibited.

---

## 3. Architecture Patterns

Single container, server-rendered, reading four AWS services and writing one.

```
Browser
  │  (Cloudflare Access → JWT validated in middleware)
  ▼
Next.js on Fly.io  ── server components / server actions
  │
  ├─ tag:GetResources ................ agent inventory      (5 min cache)
  ├─ GetAgentRuntime ................. runtime detail       (5 min cache)
  ├─ Logs Insights (StartQuery/Get) .. runs from spans      (5 min cache)
  ├─ logs:FilterLogEvents ............ execution logs       (no cache)
  └─ DynamoDB ........................ configuration        (no cache)

EventBridge Scheduler (one schedule per agent)
  ▼
Orchestrator Lambda
  ├─ Query GSI1: AGENT#<name>, enabled=true → N repos
  └─ per repo, bounded pool of 3–5:
       session_id = "<agent>-<repo>-<yyyymmdd>-<hhmmss>"  (≥33 chars)
       UpdateItem: last_session_id, last_run_at, last_status="running"
       InvokeAgentRuntime(session_id, payload)   ← fire and forget
  ▼
Agent on AgentCore
  ├─ emits root-span llipe.* attributes + JSON logs with session_id
  └─ UpdateItem: last_status, last_outcome_url   (those two attributes only)
```

### Key decisions and rationale

| Decision                                    | Rationale                                                                                                  |
| ------------------------------------------- | ---------------------------------------------------------------------------------------------------------- |
| No database in the control plane            | Everything displayed already lives in an AWS API. A local store would be a cache with a consistency problem. |
| In-process memory cache, 5-minute TTL       | Logs Insights is slow and metered. The cache exists to make navigation tolerable, not to be a source of truth. |
| Server components instead of an HTTP API    | No second surface to authenticate, no client-side AWS credentials, no API contract to version.               |
| `session_id` generated by the orchestrator  | Fire-and-forget returns no identifier. Pre-generating it is the only way the DynamoDB row and the logs correlate. |
| DynamoDB single table + inverted GSI1       | Two access patterns, mirror images of each other. `GSI1: PK = SK, SK = PK` serves the second for free.       |
| `incomplete` derived at read time           | Nobody can write "I died." Comparing `last_run_at` against the agent's `maxLifetime` from `GetAgentRuntime` turns that silence into a determinate fact. |
| Bounded fan-out pool of 3–5                 | Serial stacks latency; unbounded hits GitHub and Bedrock rate limits.                                        |
| Monorepo, separate deploys                  | Shared contracts justify one repo. Different deploy targets and cadences justify path-gated CI.               |

### Agent liveness — the entrypoint must not block

AgentCore decides whether a session is still alive by polling the agent's `/ping` endpoint. Per the [AgentCore long-running agents guide](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-long-run.html), `/ping` must return `{"status": "HealthyBusy"}` while background work is in progress; a session reporting `Healthy` (idle) is terminated after the idle timeout, while one reporting `HealthyBusy` survives until `maxLifetime`.

**The trap:** `/ping` is served by the same process as the entrypoint. An entrypoint that runs a long pipeline synchronously — subprocess calls to `git`, `pnpm install`, a test suite — blocks the ping thread, so the platform sees a session that has stopped answering, concludes it is idle, and terminates it mid-work. AWS documents this as a known issue, and the failure is silent: no error, no exception, the logs simply stop.

Every agent in this repo therefore follows the same shape:

```python
@app.entrypoint
def handler(payload, context):
    task_id = app.add_async_task("pipeline")
    threading.Thread(target=lambda: _run(payload, task_id), daemon=True).start()
    return {"accepted": True, "session_id": payload["session_id"]}   # returns immediately
```

with `app.complete_async_task(task_id)` in a `finally` block. Two things fall out of this beyond staying alive: the entrypoint returning immediately is what makes the orchestrator's fire-and-forget invocation safe, and the SDK manages the ping status so no manual health bookkeeping is needed.

Do not set `time_of_last_update` by hand. The AWS guidance warns that a timestamp advancing on every ping reads as continuous status change, which stops the idle timeout from ever firing and can exhaust the session quota. Let the SDK handle it.

### Failure model

Each repository is an independent run. One repository failing must not prevent the others from being invoked. The orchestrator logs the failure and continues; there is no all-or-nothing batch.

A run's terminal state must be written from a `finally` block — both the DynamoDB outcome stamp and the `llipe.*` span attributes. An agent that crashes without writing is indistinguishable from one killed at `maxLifetime`, and both surface only as `incomplete`.

---

## 4. API Design Standards

**v1 exposes no public HTTP API.** No REST, no GraphQL, no route handlers for data access.

Writes use **Server Actions**, one per intent:

| Action                | Purpose                                    |
| --------------------- | ------------------------------------------ |
| `setSubjectEnabled`   | Toggle `enabled` on a `SUBJECT#…/AGENT#…` item |
| `setSubjectParams`    | Replace validated `params` on that item     |
| `addSubjectToAgent`   | `PutItem` a new subject/agent pair          |

Rules for Server Actions:

- Validate every argument with a Zod schema as the first statement. A Server Action is a public endpoint, regardless of how it looks in the source.
- Re-verify the Access JWT inside the action. Middleware protects navigation; it must not be the only check on a mutation.
- Return a discriminated result (`{ ok: true }` / `{ ok: false, error }`) rather than throwing across the boundary. Never surface raw AWS error text to the client — log it server-side, return something classified.
- Revalidate only the affected path.
- Writes are confined to `enabled` and `params`. Any action touching `last_*` attributes is a bug.

If an HTTP route ever becomes necessary (health check aside), it inherits the same JWT validation. There is no unauthenticated path.

---

## 5. Authentication & Authorization

Cloudflare Access sits in front of the app. **Both halves are mandatory** and neither is a follow-on to the other:

**1. Validate the JWT.** Middleware verifies `Cf-Access-Jwt-Assertion` on every request:

- Fetch and cache the team JWKS; key ID must resolve to a known key.
- Require `RS256`. Reject `none` and reject algorithm values taken from the token header without an allowlist check.
- Verify `iss` against the team domain and `aud` against the Access application AUD tag.
- Verify `exp` / `iat`.
- A missing or unverifiable header is a rejection, not a fallback to anonymous. **Fail closed** — if the JWKS fetch fails, deny rather than allow.

**2. Lock down the origin.** Cloudflare Tunnel (preferred) or a Cloudflare IP allowlist on the Fly service. Without this, the `.fly.dev` origin is directly reachable and step 1 is the only thing standing between the internet and the app.

These are two independent controls against the same threat, and the app must not ship with only one. Validation without origin lockdown means anyone who finds the origin bypasses Cloudflare entirely; origin lockdown without validation means anyone who can route through Cloudflare is trusted.

**Authorization:** none. Roles and permissions are out of scope, and a single-operator tool does not need them. That is a scope decision about *what distinctions exist among authenticated users* — it is not permission to skip authentication. Every request is still identified.

**Machine identity:** the control plane assumes an AWS role via Fly Machines OIDC (`AssumeRoleWithWebIdentity`). Static access keys in Fly secrets are the documented fallback, carrying the same minimal permissions. If the fallback is used, keys must be rotatable without a redeploy and must never appear in the repo, logs, or build output.

---

## 6. Security Requirements

**Least privilege, as the scope boundary.** The control-plane role carries exactly the permissions in PRD §15 and no more. Specifically: **no `bedrock-agentcore:InvokeAgentRuntime`, no write action on runtimes at all.** Everything PRD §3 excludes is unreachable because the credential cannot express it.

**Write separation, enforced by policy.** Three writers touch the DynamoDB table with disjoint attribute sets:

| Writer       | May write                                                | Mechanism                     |
| ------------ | -------------------------------------------------------- | ----------------------------- |
| Control plane | `enabled`, `params`                                       | `PutItem` / `UpdateItem`      |
| Orchestrator | `last_session_id`, `last_run_at`, `last_status="running"` | `UpdateItem`                  |
| Agent        | `last_status`, `last_outcome_url`                         | `UpdateExpression` only, **never `PutItem`** |

The agent execution role is constrained with `dynamodb:Attributes` to those two attributes. `PutItem` from an agent would silently erase `enabled` and `params`, which is why the policy forbids it rather than the code merely avoiding it.

**`params` is an injection boundary.** Operator-supplied JSON flows from a textarea into DynamoDB and then into the agent's invocation payload. Treat it as untrusted at both ends: validate against a Zod schema on write with an explicit key allowlist, and re-validate in the agent on read. Do not pass it to a shell, a template, or a prompt without escaping appropriate to the sink.

**Secrets.** The GitHub App private key lives in AWS Secrets Manager, never in the repo or an environment variable baked into an image. Application configuration lives in Fly secrets. No secret is logged, echoed in an error message, or included in a span attribute. GitHub installation tokens are requested per-repository, short-lived, and never persisted or logged.

**GitHub access.** A GitHub App installed on the org with `contents:write` and `pull_requests:write`. The repository allowlist is DynamoDB — agents must not discover repositories through the GitHub API. A repository enters scope only by explicit decision in the control plane.

**Transport and data.** HTTPS only, HSTS enabled. No PII beyond repository names and GitHub URLs; nothing requiring a data-retention policy.

**Dependencies.** Exact version pins, committed lockfiles, `pnpm audit` and `uv`-side scanning in CI.

---

## 7. Data & Database Guidelines

Single-table design, on-demand capacity, point-in-time recovery enabled.

### Key schema

```
PK                      SK                  Attributes
SUBJECT#fintrack-home   META                enabled
SUBJECT#fintrack-home   AGENT#dep-updater   enabled, params{},
                                            last_session_id, last_run_at,
                                            last_status, last_outcome_url
AGENT#dep-updater       CONFIG              global params

GSI1: PK = SK, SK = PK   (inverted)
```

### Access patterns

| Need                          | Query                                                    |
| ----------------------------- | -------------------------------------------------------- |
| Repositories for an agent     | `Query GSI1 PK = AGENT#<name>`, filter `enabled = true`   |
| Agents for a repository       | `Query PK = SUBJECT#<repo>`                               |
| Add a repository to scope     | Single `PutItem`                                          |

### Conventions

- Key prefixes are `SUBJECT#` and `AGENT#`, uppercase, defined once in `packages/shared`. Never build a key by string concatenation at a call site — use the shared key builders so a prefix change is one edit.
- **`Query` only. No `Scan`.** If a requirement seems to need a scan, the access pattern is wrong or the item needs a GSI.
- Use condition expressions to make writes intentional: `addSubjectToAgent` should fail rather than silently overwrite an existing pair.
- `last_status` persists only `running`, `success`, or `failed`. **`incomplete` is never written** — it is derived at read time from `last_status = running` and `last_run_at` older than the agent's `maxLifetime` plus a grace period. The grace and the service-default fallback are named constants in `packages/shared`; the lifetime itself is per-agent and comes from `GetAgentRuntime`.
- Timestamps are ISO 8601 UTC strings.
- Attribute names in the table are `snake_case`, matching the PRD. TypeScript-side field names may be camelCase, with the mapping confined to the repository layer.
- No TTL. Configuration is small and retained indefinitely.

---

## 8. Integration Methods

| Integration              | Surface                                                       | Notes                                                        |
| ------------------------ | ------------------------------------------------------------- | ------------------------------------------------------------ |
| Resource Groups Tagging  | `tag:GetResources`, filter `agent:managed=true`                | The only discovery filter. Untagged agents are invisible by design. |
| AgentCore Control        | `GetAgentRuntime`, `ListAgentRuntimes`                         | Read-only. Runtime detail, 5-minute cache.                    |
| CloudWatch Logs Insights | `StartQuery` → poll `GetQueryResults`                          | The run list. Async, seconds-scale, quota-limited.            |
| CloudWatch Logs          | `FilterLogEvents` by `session_id`                              | Execution logs. Uncached — read when something is wrong.      |
| DynamoDB                 | `GetItem`, `Query`, `PutItem`, `UpdateItem`, `DeleteItem`        | Table and GSI1 only.                                          |
| AgentCore Runtime        | `InvokeAgentRuntime`                                           | **Orchestrator role only.** Never the control plane.          |
| GitHub                   | GitHub App installation tokens                                 | Agent-side. Scoped per repository, short-lived.               |
| Cloudflare Access        | `Cf-Access-Jwt-Assertion` + team JWKS                          | Validated in middleware, fail closed.                         |

**Adapter pattern.** One thin module per external service, in the control plane's server layer. Adapters return typed domain objects; no AWS SDK type escapes into a component. This keeps the mapping logic — spans to `Run`, items to configuration — pure and directly testable.

**Retries.** Jittered exponential backoff on throttling and 5xx, with a bounded attempt count. Never retry a validation error. Logs Insights polling needs an explicit overall timeout and must surface "query timed out" as a distinct state rather than an empty result — an empty run list and a failed query must not look the same in the UI.

**Partial failure.** Fan-out failures are per-repository and isolated. A view that cannot load logs still renders run metadata.

---

## 9. Code Organization & Structure

```
dev-tasks-agent-fleet/
├── apps/
│   └── control-plane/            # Next.js, deploys to Fly.io
│       ├── src/app/              # App Router: routes, layouts, server components
│       ├── src/components/       # shadcn/ui compositions, tables, run panel
│       ├── src/server/
│       │   ├── aws/              # one adapter per service
│       │   ├── repository/       # DynamoDB access, key builders
│       │   ├── mappers/          # span → Run, item → config (pure)
│       │   ├── cache/            # in-process TTL cache
│       │   └── actions/          # Server Actions
│       ├── src/lib/              # cost estimation, formatting, status derivation
│       ├── pricing/              # versioned pricing table, indexed by model_id
│       └── middleware.ts         # Access JWT validation
├── agents/
│   └── dep-updater/              # Python, deploys to AgentCore
├── packages/
│   └── shared/                   # DynamoDB schema + llipe.* contract, key builders,
│                                 # status enums, thresholds; JSON Schema + generated Python
└── infra/
    ├── control-plane.fly.toml
    └── agents/                   # CDK: table, GSI1, scheduler, orchestrator, IAM, tags
```

### Dependency rules

- `packages/shared` imports **nothing** from `apps/` or `agents/`. It is a leaf.
- `apps/control-plane` and `agents/*` both depend on `shared`. They never depend on each other.
- Contract types, key prefixes, status values, and the stale threshold are defined **only** in `shared`. A duplicate definition elsewhere is the exact failure mode the monorepo exists to prevent, and CI should catch it.
- Generated artifacts (JSON Schema, Python module) are committed and verified in CI, never hand-edited.

### Naming

- TypeScript files `kebab-case.ts`; React components `PascalCase.tsx`.
- Python modules `snake_case.py`.
- Types describe the domain (`Run`, `AgentSummary`, `SubjectAgentItem`), not the transport.
- Server-only modules live under `src/server/` and are import-guarded so they cannot be pulled into a client bundle.

---

## 10. Design Patterns & Principles

- **Server-first composition.** Fetch in server components, pass plain data down. Client components only where interaction demands it: toggles, filters, the side panel.
- **Repository pattern** for DynamoDB. Callers express intent (`getAgentsForSubject`), not queries.
- **Adapter per service** with a typed boundary, so AWS shapes stay at the edge.
- **Pure mappers.** Span-to-`Run`, cost estimation, and status derivation are pure functions of their inputs. These hold the logic most likely to be subtly wrong, so they must be testable without AWS.
- **Contract-first.** Change `packages/shared`, regenerate, then update consumers. Never the reverse.
- **YAGNI, deliberately.** v1 scope is closed and the backlog is written down. Do not build extension points for Cost Explorer, webhooks, or prompt versioning now. When they arrive, they arrive with real requirements.
- **KISS over configurability.** One operator, one account, one region. Do not parameterize what has exactly one value.

---

## 11. Testing Strategy

**Test-first is the default.** Acceptance criteria and test scenarios are designed before implementation, per repository convention.

| Layer                | Tool                        | Scope                                                             |
| -------------------- | --------------------------- | ----------------------------------------------------------------- |
| Unit (TS)            | Vitest                      | Mappers, cost estimation, status derivation, key builders, `params` validation |
| Integration (TS)     | Vitest + `aws-sdk-client-mock` | Adapters and repository against mocked AWS clients                |
| E2E                  | Playwright                  | The four views, filters, toggle, side panel; stubbed auth header, fixture data |
| Unit (Python)        | pytest                      | Agent logic, payload parsing                                       |
| **Contract**         | pytest + Vitest             | Emitted root-span attributes and DynamoDB item shape match `packages/shared` |

The contract test is the one that earns its keep. It asserts that what an agent actually emits satisfies the schema the control plane reads, and that the generated Python module matches its TypeScript source. Everything else in the repo can be re-derived; a drifted contract fails silently and corrupts the repository axis with no error anywhere.

**Required coverage** — these must have tests before merge, regardless of aggregate percentage:

- Cost estimation, including an unknown `model_id` (must degrade visibly, not silently show zero).
- `incomplete` derivation at the `maxLifetime + grace` boundary in both directions, the fallback when `maxLifetime` is absent, and the distinction between `incomplete` and a genuinely running run.
- JWT validation: valid, expired, wrong `aud`, wrong `iss`, missing header, unknown `kid`, unexpected `alg`, JWKS unavailable. Each must deny.
- `params` validation: rejects unknown keys, rejects malformed JSON, round-trips valid input.
- Fan-out partial failure: one repository failing does not stop the rest.
- Write separation: an agent-shaped write cannot clear `enabled` or `params`.

Prefer meaningful assertions over a coverage number. No coverage threshold is mandated; the required list above is.

---

## 12. Code Quality & Standards

| Concern            | Tool                                                              |
| ------------------ | ----------------------------------------------------------------- |
| Lint (TS)          | ESLint, Next.js and TypeScript configs                            |
| Format             | Prettier, single shared config                                    |
| Types (TS)         | `tsc --noEmit`, `strict: true`                                     |
| Lint / format (Py) | `ruff`                                                            |
| Types (Py)         | `mypy --strict`                                                   |
| Vulnerabilities    | `pnpm audit`, plus Python dependency scanning                      |

### Canonical scripts

Every JS/TS package exposes the same names, and the root aggregates them:

```
lint            lint:fix
format          format:check
typecheck
test            test:unit    test:integration    test:e2e
audit
validate        # aggregate quality gate: lint + format:check + typecheck + test + audit
```

`validate` is what CI runs and what should pass locally before a PR.

### Review and documentation

- Human PR review is the actual gate. Automated checks are necessary, not sufficient.
- Comments explain *why*, not *what*. The non-obvious decisions here — orchestrator-generated `session_id`, read-time `incomplete`, agent `UpdateExpression`-only writes — each deserve a comment pointing at the PRD section, because all three look like mistakes to someone who doesn't know the constraint.
- Document at the module level: what an adapter is responsible for and what it deliberately does not do.

---

## 13. Deployment & DevOps

**Environments.** Production only. A single-operator tool with no persistent state does not justify a staging tier; preview deploys cover the pre-merge case if needed.

**Control plane.** Fly.io, single machine, `output: 'standalone'` in a minimal container. Config via Fly secrets. Origin locked to Cloudflare.

**Agents.** Deployed to AgentCore per agent, independently.

**Infrastructure.** AWS CDK in TypeScript. `cdk diff` on PR, `cdk deploy` gated on human approval. Everything in PRD §8, §9, §15 is CDK-managed: table and GSI1, EventBridge Scheduler rules, the orchestrator Lambda, the agent runtime and its `lifecycleConfiguration`, IAM roles including the `dynamodb:Attributes` constraint, discovery tags, and the OIDC trust policy.

Constants that both infrastructure and application code depend on — the table name, `GSI1`, the `agent:*` tag keys, agent names — are imported from `packages/shared` by the CDK stacks rather than duplicated as strings. A stack that hardcodes `"GSI1"` while the query layer imports it from `shared` is two definitions of one fact.

Bootstrap the CDK environment once per account/region. Stacks are split by deploy cadence: agent runtime, shared data (table + GSI1), and orchestration (scheduler + Lambda).

**Path-gated CI.** GitHub Actions, filtered so unrelated work does not trigger unrelated deploys:

| Path                     | Triggers                                    |
| ------------------------ | ------------------------------------------- |
| `apps/control-plane/**`  | validate → build → deploy to Fly            |
| `agents/<name>/**`       | validate → deploy that agent to AgentCore   |
| `infra/**`               | `cdk diff` → gated `cdk deploy`             |
| `packages/shared/**`     | validate **all** consumers, verify generated artifacts match |

A change to `packages/shared` must fan out to everything that depends on it. That is the one path where narrow gating would be wrong.

**CI credentials.** GitHub OIDC to AWS. No long-lived AWS keys in Actions secrets.

**Git discipline.** No agent pushes or merges to `main`. Conventional Commits. `gh issue`/`pr` bodies via `--body-file`, never inline `--body`.

---

## 14. Monitoring, Logging & Observability

**Prerequisites, without which the product has no data:**

1. CloudWatch Transaction Search enabled. 1% indexing is sufficient — all spans are ingested as logs, and the indexing rate affects only X-Ray trace summaries.
2. One unified span destination across the fleet. Two destinations means two queries in the read path.

**Structured logging is contractual.** Application logs are JSON, one object per line, with **`session_id` on every line**. With three to five repositories running in parallel, a time-window filter interleaves runs into something unreadable; `session_id` is the only thing that separates them. A log line without it is effectively lost.

Standard fields: `timestamp`, `level`, `session_id`, `agent`, `repo`, `message`, plus structured context. Never log secrets, tokens, or full payloads that might contain them.

**Levels.** `error` for failed runs and unexpected exceptions; `warn` for retries, throttling, and degraded reads; `info` for run lifecycle boundaries; `debug` off in production.

**Span attributes** on the root span of every run, from `packages/shared`:

```
llipe.subject.id    = "fintrack-home"
llipe.run.status    = "success" | "failed"
llipe.outcome.type  = "pr" | "report" | "none"
llipe.outcome.url   = "https://github.com/myorg/fintrack-home/pull/42"
```

Tokens, latency, and model come from AgentCore's automatic instrumentation and require no agent code.

**Alerting: none in v1.** Out of scope, and honestly so. The `incomplete` status is the manual substitute: it turns "an agent died quietly" into something visible on the next look. Nothing pages anyone. Missing-run detection against declared schedules is in the backlog.

**Control-plane logs** go to Fly's log stream, JSON-formatted for consistency.

---

## 15. Performance & Scalability

Scale is fixed and small: one operator, a handful of agents, a few dozen repositories.

| Path                       | Expectation                                                       |
| -------------------------- | ----------------------------------------------------------------- |
| Cached view render         | Fast enough to feel immediate — cache hit, no AWS round trip       |
| Cold run list              | Seconds. Logs Insights is start-query-and-poll; this is the floor. |
| Log fetch in the run panel | Uncached by design. Show a loading state, never a blank panel.     |
| DynamoDB reads             | Single-digit milliseconds                                          |

**Caching.** In-process TTL cache, 5 minutes, keyed by the full query shape including time range and filters. Uncached: execution logs and DynamoDB configuration reads — both are read precisely when the operator needs current truth. Cache misses after a container restart are expected and harmless.

**Because the cold path is seconds, streaming and skeleton states are functional requirements**, not polish. A view that blocks for four seconds with no feedback reads as broken.

**Fan-out concurrency** is a pool of 3–5. The bound protects GitHub and Bedrock rate limits.

**Not optimizing for:** horizontal scale, multi-user concurrency, sub-second cold queries, or run volumes beyond one operator's fleet. If those become real, they are new requirements with new architecture, not tuning.

---

## 16. Dependency Management

- **Exact version pins.** No `^`, no `~`, in either ecosystem. Lockfiles committed (`pnpm-lock.yaml`, `uv.lock`).
- `pnpm` is required for JS/TS. `npm` only if `pnpm` is genuinely unavailable.
- Prefer well-maintained, widely used packages. Scrutinize anything that looks like a typosquat, especially in the AWS and OTel namespaces where near-miss names are common.
- AWS SDK v3: import individual clients, never the umbrella package.
- Updates land as reviewed PRs with `validate` green. `pnpm audit` runs in CI.
- Dependency additions to `packages/shared` need justification — it is imported by everything and should stay near-dependency-free.

---

## 17. Development Workflow

**Branches.** `<type>/<short-description>`, e.g. `feat/run-side-panel`. Never commit to `main`; no agent pushes or merges to `main`.

**Commits.** [Conventional Commits](https://www.conventionalcommits.org/), scoped to the affected package: `feat(control-plane):`, `fix(shared):`, `chore(infra):`.

**Pull requests.**

- Titles under 70 characters; detail goes in the body.
- Bodies via `--body-file`, never inline `--body`.
- Body states what changed, what was tested, and anything deliberately deferred.
- `validate` green before review.
- **Human review is the gate.** Automated hooks are best-effort.

**Planning artifacts.** New PRDs go in `docs/requirements/`; specifications, user stories, and task lists in `/workstream/`. The v1 PRD sits at `docs/requirements/PRD-agent-control-plane-v1-en.md`. GitHub Issues and PRs are the source of truth for execution status.

**Documents carry changelogs.** Updating a PRD, spec, or foundation document means adding a changelog row with an incremented version, the date, a summary, and an author.

---

## 18. Known Constraints & Trade-offs

| Constraint                                                       | Consequence accepted                                                                                 |
| ---------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------- |
| No run ledger, no local database                                 | Run history is bounded by CloudWatch log retention. Once logs expire, those runs are gone. Chosen to keep cost under USD 10/month and to avoid a second source of truth. |
| 5-minute cache TTL                                               | The run list can be five minutes stale. Acceptable because nothing here is real-time.                  |
| Logs Insights as the read path                                   | Cold queries take seconds and are quota-limited. No front-end work changes this.                        |
| Token-derived cost estimate                                      | Excludes runtime compute. Displayed as an estimate. Reconciling a bill needs Cost Explorer, out of scope. |
| Hand-maintained pricing table                                    | Goes stale silently when a model's price changes. Versioned in-repo so at least the drift is auditable.  |
| Fire-and-forget invocation                                       | No completion signal except the agent's own write. An agent that dies before writing is only detectable via `incomplete`. |
| `incomplete` bounded by `maxLifetime` + grace                    | Depends on `GetAgentRuntime` being reachable; falls back to the 8 h service default, which over-waits for agents configured shorter. |
| Emission contract as a hard dependency                           | An agent that does not emit `llipe.subject.id` is invisible in the repository view, with no error to explain why. The contract test is the mitigation. |
| Tag-based opt-in discovery                                       | A new agent silently absent until tagged. Intentional, but a predictable source of "why isn't it showing up." |
| Single account, single region                                    | No failover story. Appropriate for a personal tool.                                                     |
| No authorization model                                           | Anyone past Cloudflare Access has full write capability over scope configuration. Bounded by the perimeter being the only control. |
| Static AWS keys as the OIDC fallback                             | Long-lived credentials in Fly secrets if OIDC proves difficult. Weaker; rotate deliberately if used.     |

---

## Reference

- PRD: [`docs/requirements/PRD-agent-control-plane-v1-en.md`](./requirements/PRD-agent-control-plane-v1-en.md) — v1.1, scope closed
- Product context: [`docs/product-context.md`](./product-context.md)
- Design contract: [`../DESIGN.md`](../DESIGN.md)
