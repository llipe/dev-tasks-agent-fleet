# dependency-update Agent

Automated dependency auditing and updating agent for the Agent Fleet Control Plane. Runs as an AWS Bedrock AgentCore Container runtime.

## Layout

```
agents/dependency-update/
├── agentcore/
│   ├── agentcore.json     # Runtime configuration (Container, HTTP, lifecycle)
│   ├── aws-targets.json   # Deployment target (us-east-1)
│   └── cdk/               # CDK infrastructure (managed by agentcore CLI)
├── app/dependencyUpdate/
│   ├── main.py            # Pipeline orchestrator entrypoint
│   ├── agent_reporter.py  # Reporting SDK (copy from docs/reference/)
│   ├── config.py          # Environment variable reads, constants
│   ├── credentials.py     # Supabase key + GitHub App token resolution
│   ├── scrubber.py        # Token scrubbing for output/errors
│   ├── toolchain.py       # PM detection (D19), pnpm version mapping, script contract
│   ├── validator.py       # Lint→format→typecheck→test runner (fix-and-retry)
│   ├── audit.py           # Audit runner + JSON parsing
│   ├── eligibility.py     # Semver version eligibility (D26)
│   ├── classifier.py      # Advisory classification (D25)
│   ├── updater.py         # Apply updates + reconcile lockfile
│   ├── fix_agent.py       # Strands LLM fix agent + tools
│   ├── pull_request.py    # Branch, PR creation, body builder
│   ├── heartbeat.py       # Long-step keep-alive: live-yield heartbeat chunks (#98)
│   ├── signal_backstop.py # Best-effort SIGTERM terminal-report backstop (#98)
│   ├── Dockerfile         # ARM64 container: Python 3.13 + Node 26 + pnpm + npm + gh
│   ├── pyproject.toml     # Python dependencies (pinned)
│   └── tests/
│       ├── unit/          # Pure unit tests (no I/O)
│       ├── component/     # Component tests (mocked externals)
│       └── fixtures/      # Test fixture data
└── README.md              # This file
```

## Pipeline

1. Validate payload (reject with `INVALID_PARAMS` on bad input)
2. Resolve credentials (Supabase service role key, GitHub App token)
3. Clone repository (depth 1)
4. Detect toolchain (pnpm/npm, scripts)
5. Run audit (`pnpm audit --json` / `npm audit --json`)
6. Classify advisories (eligible / major_required / unknown)
7. Apply eligible updates + reconcile lockfile
8. Run validation (lint → format → typecheck → test)
9. [Optional] LLM fix loop (`llm_fix` mode only — see below)
10. Open PR (idempotent — skips if a `deps/update-*` PR already exists)
11. Report outcome to Supabase

### Open PR step

After a successful update (and validation), the agent opens a pull request
against the base branch (default `main`; overridable via the `base_branch`
param). The step is deterministic and idempotent:

- **Branch:** a fresh `deps/update-YYYYMMDD-HHMMSS` branch (UTC). The agent
  **never** commits to or pushes the default branch. Commit message is fixed:
  `chore(deps): automated dependency update`.
- **Idempotency:** before doing any work the agent runs `gh pr list` and, if an
  open PR whose head branch starts with `deps/update-` already exists, it
  short-circuits to `succeeded / not_applicable` and records the **existing** PR
  URL as the artifact — no new branch, push, or PR.
- **Token freshness:** the GitHub installation token is re-minted if it has aged
  past 45 minutes before the push (`refresh_token_if_stale`), so long runs do
  not push with an expired token.
- **Secure push:** the token is supplied to `git push` via an ephemeral
  credential helper for the duration of that single call — it never lands in the
  remote URL or `.git/config`.
- **PR body:** assembled from pipeline state and passed via `gh pr create
  --body-file` (never inline `--body`). Sections: security summary (always),
  fixed advisories, major-version-required advisories, unresolved advisories,
  non-semver version changes, package changes (capped at 30 rows), validation
  results (always), and — only when the LLM fix agent ran — an AI-assisted
  modifications warning.
- **Artifact:** the PR is recorded as a `run_artifacts` row of type
  `pull_request` (for both newly created and pre-existing PRs).
- **Major bump sequencing:** when an advisory can only be closed by a major
  version bump, the PR carrying the fixed subset is opened **before** the run
  terminates `failed / needs_review / MAJOR_UPDATE_REQUIRED`, so the reviewer
  always has the partial fix in hand.
- **Failure mapping:** a push or `gh` failure raises `PullRequestError`, which
  the orchestrator maps to `failed / needs_review` with the specific error code
  (`PR_LIST_FAILED`, `PUSH_FAILED`, `PR_CREATE_FAILED`, or `GIT_FAILED`) — the
  update itself succeeded, only the PR handoff failed.

### LLM fix loop (escape hatch)

The LLM sits **outside** the deterministic path and is reachable from exactly
one edge: when the validation suite fails after a dependency update, and only in
`llm_fix` mode with `max_fix_attempts > 0`. It never judges vulnerabilities,
picks versions, or writes the PR body — those stay deterministic.

- **Runtime:** a Strands agent on Amazon Bedrock (`fix_agent.py`). The model is
  configurable via `MODEL_ID` (default `us.anthropic.claude-sonnet-4-6`).
- **Tool surface — exactly five, no more:** `shell`, `read_file`, `write_file`,
  `find_files`, `grep_code`. Every path-taking tool resolves against the
  workspace root through `_safe_path`, which refuses absolute paths, `../`
  traversal, and symlink escapes; `shell`/`find_files`/`grep_code` are confined
  to the workspace cwd.
- **Mandate (system prompt):** the agent is instructed to adapt **source code
  only**. It must not weaken/skip/disable tests, roll back the dependency
  update, widen a semver range, perform a major bump, add/remove dependencies,
  or edit lockfiles.
- **Bounded loop:** up to `max_fix_attempts` (0–5, default 3). The full
  validation suite is re-run after each attempt; the loop stops on the first
  pass or when the budget is exhausted.
- **Post-success re-check:** on success, lint/format/typecheck are re-run
  (`rerun_static_checks_after_fix`) because the model may have edited files after
  those checks last passed; the original `test` result is preserved.
- **Deterministic backstop:** after the loop, `verify_no_mandate_violation`
  compares `package.json` dependency specifiers against the post-update
  snapshot. Any widened range, major bump, or added/removed dependency
  terminates the run `failed` / `needs_review` / `MANDATE_VIOLATION` and **blocks
  PR creation** — the prompt is guidance, this check is enforcement.

> **Wired as of issue #76:** the `open_pr` step, the `pull_request` run
> artifact, and the PR body builder are implemented (see *Open PR step* above).
>
> **Wired as of issue #77:** run metrics (`llm_used`, `fix_attempts`, and the
> vulnerability / advisory / package counts) are now persisted to the
> `runs.metrics` jsonb column at every terminal report — the entrypoint return
> payload and the stored metrics are built from the same source
> (`build_metrics`). The fix-budget test-output artifact on budget exhaustion
> remains a tracked, non-blocking gap (see `TESTING.md`).
>
> **Corrected as of issue #90:** two run-metric under-reporting bugs are fixed.
> `advisories_fixed` is now the count of advisory IDs present in the
> before-update audit but absent from the after-update audit
> (`audit.count_advisories_fixed`), replacing an `in_range` bucket subtraction
> that reported 0 whenever no advisory was classified `in_range` (common on
> monorepos). `packages_changed` is now derived from a workspace-aware,
> recursive lockfile snapshot (`pnpm list -r --depth Infinity --json` /
> `npm list --all --json`, walking nested `dependencies`), replacing the
> root-only `--depth 0` listing that saw no workspace-package or transitive
> changes in a monorepo. The fixed-advisory count is computed once and feeds
> **both** the PR body Security Summary and `runs.metrics.advisories_fixed`, so
> the two can no longer disagree. (The npm advisory `id` is normalized to a
> source-or-url fallback so npm advisories lacking a numeric source are not
> collapsed in the ID-set diff.)

## Deployment

```bash
cd agents/dependency-update
agentcore deploy -y      # non-interactive build + deploy
agentcore status         # confirm runtime ready; copy the runtime ARN
```

After a successful deploy:

1. Copy the `runtime_arn` reported by `agentcore status`.
2. Paste it into `docs/reference/002_seed.sql` (block 3, `runtime_arn` column),
   replacing the `...000000000000...` placeholder.
3. Apply the seed to Supabase (SQL Editor). The seed is idempotent
   (`ON CONFLICT (slug) DO UPDATE`), so re-running is safe.
4. Ensure the AgentCore execution role has `secretsmanager:GetSecretValue` on
   `agent-fleet/prod/*` and `bedrock:InvokeModel` on the configured `MODEL_ID`.

The full step-by-step operator runbook for deploy, IAM, seed apply, and the
end-to-end invocation checks lives in
[`docs/runbooks/issue-77-deployment-e2e.md`](../../docs/runbooks/issue-77-deployment-e2e.md).

## Invocation

Invoke the deployed runtime with `agentcore invoke`. The runtime contract is a payload
wrapped in a `prompt` key (a JSON string); the agent unwraps nested `prompt` wrappers
transparently (see the CLI-version note below).

### Prerequisite — insert the `queued` row before invoking (D1)

**The caller must INSERT the `runs` row before invoking; the agent only updates it.** Per D1 and
specification §14 the control plane generates `run_id` and inserts the `runs` row in `queued`
*before* calling AgentCore. The agent SDK **never inserts** — `RunReporter.start()` issues a PATCH
(`UPDATE runs SET status='running', started_at=… WHERE id=<run_id>`). The Phase 2 panel does this
automatically; when you invoke by hand (`agentcore invoke`), **you** must insert the row first.

Ready-to-paste insert (mirrors operator runbook
[`issue-94-reaper-verification.md`](../../docs/runbooks/issue-94-reaper-verification.md) §4.0;
lists every NOT-NULL column and returns the `id` to use as `run_id`):

```sql
insert into runs (
  id, agent_id, agent_version, repository_id, installation_id,
  status, queued_at, max_runtime_seconds, grace_seconds, start_timeout_seconds
)
select gen_random_uuid(), a.id, a.version, r.id, r.installation_id,
       'queued', now(), 3600, 120, 300
from agents a
join repositories r on r.full_name = 'my-org/checkout-api'
where a.slug = 'dependency-update'
returning id;   -- use this UUID as run_id in the invoke payload below
```

The `returning id` value is the `run_id` you put in the invoke payload. (You may instead generate
the UUID yourself and pass the same literal to both the `INSERT` and the payload — either way the
row must exist first and the two `run_id`s must match exactly.)

#### Failure mode — run invisible (silent no-op)

If you invoke **without** inserting the row, the agent's `start()` PATCH matches **zero** rows.
PostgREST returns **HTTP 200 on a zero-match UPDATE** (a silent no-op), so:

- **Symptom:** the run never appears in `runs` or `v_runs`, the agent produces no error, and there
  is no failure anywhere — the run simply seems to vanish. (This cost real debugging time during
  #94 verification.)
- **Cause:** no `queued` row existed for the PATCH to match.
- **Fix:** insert the `queued` row first (above), then invoke with the matching `run_id`.

**Secondary symptom (not a bug):** if a `queued` row *is* pre-inserted but the agent never starts
(e.g. a rejected payload), the reaper marks it `failed_to_start` with `started_at = null` and zero
agent-written events. That is correct reaper behavior on an orphan
([#99](https://github.com/llipe/dev-tasks-agent-fleet/issues/99) also closes any open steps), not a
reaper defect — see runbook §2 / §4.0.

**Quick diagnosis — "my run is invisible":**

1. Did you `INSERT` the `queued` row before invoking? (the #1 cause)
2. Does the invoke payload `run_id` match the inserted row's `id` **exactly**?
3. Is `SUPABASE_URL` reachable from the runtime? (an unreachable URL also drops the write — see
   runbook §5)

> **`agentcore` CLI ≥ 0.28.0 — the CLI wraps the prompt argument itself.**
> The CLI treats its invoke argument *as* the prompt and wraps it as `{"prompt": "<arg>"}`.
> Passing an already-wrapped `'{"prompt": "{...}"}'` therefore arrives **double-wrapped**. As of
> [#97](https://github.com/llipe/dev-tasks-agent-fleet/issues/97), `unwrap_payload()` strips nested
> `prompt` wrappers in a loop, so **both** the bare inner JSON and the pre-wrapped form work. If a
> payload is still wrapper-only after unwrapping, the run fails `INVALID_PARAMS` with a specific
> "appears double-wrapped" log line (not the generic missing-fields message).
>
> The examples below were validated against **`agentcore` CLI 0.28.x**. Two equivalent forms:
>
> ```bash
> # (a) bare inner JSON via --prompt-file (recommended for hand-invocation)
> cat > /tmp/invoke.json <<'JSON'
> {"run_id":"<uuid>","repository_org":"my-org","repository_name":"checkout-api","params":{"fix_mode":"audit_only"}}
> JSON
> agentcore invoke --prompt-file /tmp/invoke.json
> ```
>
> Reminder: this still requires the `queued` row to exist first (see *Prerequisite* above) — a
> direct CLI invoke does not create it.

The wrapped form below is the contract the Phase 2 control plane will send over
`InvokeAgentRuntime`, and (since #97) is also accepted verbatim from the CLI ≥ 0.28.0:

```bash
# audit_only (default) — report findings, no PR
agentcore invoke '{"prompt": "{\"run_id\":\"<uuid>\",\"repository_org\":\"my-org\",\"repository_name\":\"checkout-api\",\"params\":{\"fix_mode\":\"audit_only\"}}"}'

# llm_fix — attempt fixes and open a PR (max_fix_attempts 0..5, default 3)
agentcore invoke '{"prompt": "{\"run_id\":\"<uuid>\",\"repository_org\":\"my-org\",\"repository_name\":\"checkout-api\",\"params\":{\"fix_mode\":\"llm_fix\",\"max_fix_attempts\":3}}"}'
```

`run_id` MUST be a caller-generated UUID that already exists as a `queued` `runs` row (see
*Prerequisite — insert the `queued` row before invoking* above). `repository_org` and
`repository_name` are required; `params` is validated against the agent's `params_schema` and
defaulted (`fix_mode=audit_only`, `fail_on_findings=true`, `max_fix_attempts=3`).
An invalid payload terminates `failed / not_applicable / INVALID_PARAMS` before
any clone.

Verify a run in Supabase by querying `runs`, `run_steps`, `run_events`, and
`run_artifacts` for the `run_id`. The `runs.metrics` column carries `llm_used`,
`fix_attempts`, and the vulnerability / advisory / package counts for the run.

## Local Development

```bash
cd agents/dependency-update
agentcore dev
# In another terminal:
curl http://localhost:8080/ping
```

## Configuration

### Runtime Timeouts

| Setting | Value | Location |
|---------|-------|----------|
| `maxLifetime` | 3600s | `agentcore/agentcore.json` |
| `idleRuntimeSessionTimeout` | 900s | `agentcore/agentcore.json` |
| `max_runtime_seconds` | 3600 | `002_seed.sql` (agents table) |
| `grace_seconds` | 120 | `002_seed.sql` (agents table) |
| `start_timeout_seconds` | 300 | `002_seed.sql` (agents table) |

**Important:** these clocks are cross-checked in code. `idleRuntimeSessionTimeout` was raised
300 → 900 (issue #98) so a bounded `TEST_TIMEOUT` (600s) validation, kept alive by a 120s
heartbeat, cannot trip idle reclamation mid-`validate`; the change requires an AgentCore
redeploy to take effect. At entrypoint start `config.assert_clock_invariant()` fails fast
(`ClockConsistencyError`) unless
`TOOL_COMMAND_TIMEOUT ≤ TEST_TIMEOUT ≤ IDLE_SESSION_TIMEOUT ≤ MAX_LIFETIME ≤ REAPER_THRESHOLD_SECONDS`
and `HEARTBEAT_INTERVAL ≤ IDLE_SESSION_TIMEOUT / 2`. The `IDLE_SESSION_TIMEOUT` / `MAX_LIFETIME`
constants MUST mirror `agentcore.json` `lifecycleConfiguration`, and `REAPER_THRESHOLD_SECONDS`
(default 3720) MUST equal the database `max_runtime_seconds` (3600) + `grace_seconds` (120) — the
values that drive the panel's reaper. `start_timeout_seconds` (300) is the independent
`queued → failed_to_start` clock and is **not** tied to `idleRuntimeSessionTimeout`. If the
container and database clocks drift, the panel may show a run as "running" after AgentCore has
already killed it, or vice versa. See `docs/technical-guidelines.md` §7/§8 and
[ADR-006](../../docs/adr/ADR-006-long-step-keepalive-and-clock-invariant.md).

### Environment Variables (set by AgentCore / Secrets Manager)

| Variable | Required | Description |
|----------|----------|-------------|
| `SUPABASE_URL` | Yes | Supabase project URL |
| `SUPABASE_KEY_SECRET_ID` | Yes | Secrets Manager ID for Supabase service role key |
| `RUN_ID` | Yes | Execution ID (passed by control plane at invocation) |
| `RUN_PARAMS` | Yes | JSON payload with invocation parameters |
| `AGENT_LOG_LEVEL` | No | Minimum log level captured (default: INFO) |
| `MODEL_ID` | No | Bedrock model for the LLM fix loop (default: `us.anthropic.claude-sonnet-4-6`) |
| `TOOL_COMMAND_TIMEOUT` | No | Per-command timeout for the fix agent's `shell` tool, in seconds (default: 180) |
| `TEST_TIMEOUT` | No | Timeout for the validation test run, in seconds (default: 600) |
| `IDLE_SESSION_TIMEOUT` | No | Mirror of `agentcore.json` `idleRuntimeSessionTimeout`; used by the clock-consistency check (default: 900) |
| `MAX_LIFETIME` | No | Mirror of `agentcore.json` `maxLifetime`; used by the clock-consistency check (default: 3600) |
| `REAPER_THRESHOLD_SECONDS` | No | Mirror of the DB `max_runtime_seconds` (3600) + `grace_seconds` (120); reaper backstop bound (default: 3720) |
| `HEARTBEAT_INTERVAL` | No | Keep-alive cadence during long steps, in seconds; must be `≤ IDLE_SESSION_TIMEOUT / 2` (default: 120) |

## Testing

Quality gates run through the `Makefile` (canonical command contract, mirrors
`TESTING.md`). Run from `app/dependencyUpdate/`:

```bash
cd agents/dependency-update/app/dependencyUpdate
make install         # pip install -e '.[dev]'
make test            # python -m pytest (all layers)
make test-unit       # python -m pytest -m unit
make test-component  # python -m pytest -m component
make test-cov        # python -m pytest --cov --cov-report=term-missing
make validate        # aggregate gate: lint + format-check + typecheck + test-cov + audit
```

Layer markers (`unit` / `component`) are applied automatically by
`tests/conftest.py` based on the test's directory, so tests do not declare them
by hand. Shared temp-dir project fixtures (pnpm/npm/no-lockfile/no-test/minimal)
also live in `tests/conftest.py`.
