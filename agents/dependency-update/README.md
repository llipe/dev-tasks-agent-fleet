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
10. Open PR (idempotent — skips if `deps/update-*` branch exists)
11. Report outcome to Supabase

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

> **Not yet wired (deferred):** recording the test-output tail as a
> `run_artifact` on budget exhaustion is deferred to issue #76 (PR/artifact
> plumbing); full persistence of `llm_used` / `fix_attempts` into `runs.metrics`
> is deferred to issues #76/#77. The values are computed and returned in the
> entrypoint payload today, but are not yet written to the `runs.metrics` column.

## Deployment

```bash
cd agents/dependency-update
agentcore deploy -y
agentcore status
```

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
| `idleRuntimeSessionTimeout` | 300s | `agentcore/agentcore.json` |
| `max_runtime_seconds` | 3600 | `002_seed.sql` (agents table) |

**Important:** `max_runtime_seconds` in the database seed MUST equal `maxLifetime` in `agentcore.json`. The database value drives the panel's reaper (stale execution detection), while the AgentCore value enforces the actual container kill. If they drift, the panel may show a run as "running" after AgentCore has already killed it, or vice versa.

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
