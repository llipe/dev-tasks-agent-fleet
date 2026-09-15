# security-analyst Agent

Five-tool security scanner agent (semgrep, gitleaks, trivy, checkov, CodeQL) for the Agent Fleet
Control Plane. Runs as an AWS Bedrock AgentCore Container runtime.

> **Status (S-125-S-126):** project scaffold, deploy, and reporting pipe (S-125), plus per-tool
> severity normalization (S-126). The entrypoint validates the invocation payload and runs a
> placeholder pipeline (`resolve_credentials` -> `checkout` -> `succeeded`/`no_findings`) —
> **no scanners run yet**. `severity.py`'s five `severity_from_<tool>()` functions are pure,
> unit-tested, and not yet wired into the pipeline (no `normalize_<tool>()` caller exists until
> S-128+). This is a deliberate bring-up milestone, not a shortcut: it proves the
> deploy/credential/reporting pipe end-to-end (mirroring how `agents/dependency-update/` proved its
> own pipe first) before scanner integrations land in later stories (S-128-S-141).

## Layout

```
agents/security-analyst/
├── agentcore/
│   ├── agentcore.json     # Runtime configuration (Container, HTTP, lifecycle)
│   ├── aws-targets.json   # Deployment target (us-east-1)
│   └── cdk/                # CDK infrastructure (managed by agentcore CLI)
├── app/securityAnalyst/
│   ├── main.py              # Pipeline orchestrator entrypoint (placeholder pipeline, S-125)
│   ├── severity.py          # Per-tool severity normalization, pure functions (S-126)
│   ├── agent_reporter.py    # Reporting SDK (byte-identical copy, docs/reference/)
│   ├── config.py            # Environment variable reads, this agent's own clock constants
│   ├── credentials.py       # Supabase key + GitHub App token resolution (unmodified copy)
│   ├── scrubber.py          # Token scrubbing for output/errors (unmodified copy)
│   ├── heartbeat.py         # Long-step keep-alive: live-yield heartbeat chunks (unmodified copy)
│   ├── signal_backstop.py   # Best-effort SIGTERM terminal-report backstop (unmodified copy)
│   ├── Dockerfile           # ARM64 container: Python 3.13 + git + gh (scanner toolchains land S-128+)
│   ├── pyproject.toml       # Python dependencies (pinned)
│   ├── Makefile              # install/lint/format-check/typecheck/test-unit/test-component/test-cov/audit/validate
│   └── tests/
│       ├── unit/            # Pure unit tests (no I/O), incl. test_severity.py (S-126)
│       └── component/       # Component tests (mocked externals) — empty until S-128+
└── README.md                 # This file
```

## Pipeline (this story's subset)

1. Validate payload (reject with `INVALID_PARAMS` on bad input — no clone attempted)
2. Resolve credentials (Supabase service role key, GitHub App token — reuses the sibling agent's
   `credentials.py` unmodified against the shared `github_installations` row)
3. Clone repository (depth 1)
4. Report `succeeded` / `no_findings` (placeholder — no scanner ran)

Later stories replace step 4 with the real `scan -> classify -> fix -> rescan -> open_pr` pipeline
(spec `workstream/specification-prd-security-analyst-agent.md` S8.8).

## Invocation payload (spec S6.1)

```json
{
  "run_id": "<uuid>",
  "repository_org": "my-org",
  "repository_name": "checkout-api",
  "params": {
    "mode": "audit_only",
    "fail_on_findings": true,
    "min_severity": "low",
    "max_fix_attempts": 3,
    "scanners": ["semgrep", "gitleaks", "trivy", "checkov", "codeql"]
  }
}
```

`run_id`, `repository_org`, `repository_name` are required. `params` is optional and defaulted
(`mode=audit_only`, `fail_on_findings=true`, `min_severity=low`, `max_fix_attempts=3` clamped
0-5, `scanners=` all five). `min_severity` must be one of `low`/`medium`/`high`/`critical`;
`scanners` must be a non-empty subset of `semgrep`/`gitleaks`/`trivy`/`checkov`/`codeql`. An
invalid payload terminates `failed` / `not_applicable` / `INVALID_PARAMS` before any clone
(PRD AC28). The entrypoint tolerates the AgentCore `prompt` wrapper (single or double-wrapped,
identical mechanism to the sibling agent), and requires an existing `queued` `runs` row before
invoking — see the sibling agent's README for the full prerequisite/troubleshooting flow (shared
`RunReporter` contract).

## Deployment

```bash
cd agents/security-analyst
agentcore deploy -y      # non-interactive build + deploy
agentcore status         # confirm runtime ready; copy the runtime ARN
```

After a successful deploy, the `runtime_arn` is recorded in `supabase/seed.sql` as part of
**S-141** (this story does not touch the seed file — no `security-analyst` `agents` row exists
until then).

## Local Development

```bash
cd agents/security-analyst
agentcore dev
# In another terminal:
curl http://localhost:8080/ping
```

## Configuration

### Runtime Timeouts (spec S9.2, PRD S12.3)

| Setting | Value | Location |
|---------|-------|----------|
| `maxLifetime` | 5400s | `agentcore/agentcore.json` |
| `idleRuntimeSessionTimeout` | 900s | `agentcore/agentcore.json` |

This agent recomputes ADR-006's clock-invariant chain for its own, higher bounds — a five-scanner
step (CodeQL's database-build phase especially) can legitimately run far longer than the sibling
agent's `pnpm test`. At entrypoint start `config.assert_clock_invariant()` fails fast
(`ClockConsistencyError`) unless
`FIX_COMMAND_TIMEOUT <= SCANNER_TIMEOUT <= IDLE_SESSION_TIMEOUT <= MAX_LIFETIME <= REAPER_THRESHOLD_SECONDS`
and `HEARTBEAT_INTERVAL <= IDLE_SESSION_TIMEOUT / 2`. `IDLE_SESSION_TIMEOUT` / `MAX_LIFETIME` MUST
mirror `agentcore.json` `lifecycleConfiguration`, and `REAPER_THRESHOLD_SECONDS` (default
`MAX_LIFETIME + 120`) MUST equal the database `max_runtime_seconds` + `grace_seconds` set for this
agent's row in `supabase/seed.sql` (S-141). See `docs/technical-guidelines.md` S7/S8 and
[ADR-006](../../docs/adr/ADR-006-long-step-keepalive-and-clock-invariant.md).

### Environment Variables (set by AgentCore / Secrets Manager)

| Variable | Required | Description |
|----------|----------|-------------|
| `SUPABASE_URL` | Yes | Supabase project URL |
| `SUPABASE_KEY_SECRET_ID` | Yes | Secrets Manager ID for Supabase service role key |
| `RUN_ID` | Yes | Execution ID (passed by control plane at invocation) |
| `RUN_PARAMS` | Yes | JSON payload with invocation parameters |
| `AGENT_LOG_LEVEL` | No | Minimum log level captured (default: INFO) |
| `MODEL_ID` | No | Bedrock model for the LLM fix loop, wired in a later story (default: `us.anthropic.claude-sonnet-4-6`) |
| `SCANNER_TIMEOUT` | No | Per-scanner subprocess timeout, in seconds (default: 600) |
| `FIX_COMMAND_TIMEOUT` | No | Per-LLM-shell-call timeout in the fix agent, in seconds (default: 180) |
| `IDLE_SESSION_TIMEOUT` | No | Mirror of `agentcore.json` `idleRuntimeSessionTimeout` (default: 900) |
| `MAX_LIFETIME` | No | Mirror of `agentcore.json` `maxLifetime` (default: 5400) |
| `REAPER_THRESHOLD_SECONDS` | No | Mirror of the DB `max_runtime_seconds` + `grace_seconds` (default: `MAX_LIFETIME + 120`) |
| `HEARTBEAT_INTERVAL` | No | Keep-alive cadence during long steps, in seconds; must be `<= IDLE_SESSION_TIMEOUT / 2` (default: 120) |

## Testing

Quality gates run through the `Makefile` (canonical command contract, mirrors `TESTING.md`). Run
from `app/securityAnalyst/`:

```bash
cd agents/security-analyst/app/securityAnalyst
make install         # pip install -e '.[dev]'
make test            # python -m pytest (all layers)
make test-unit       # python -m pytest -m unit
make test-component  # python -m pytest -m component
make test-cov        # python -m pytest --cov --cov-report=term-missing
make validate        # aggregate gate: lint + format-check + typecheck + test-cov + audit
```

Layer markers (`unit` / `component`) are applied automatically by `tests/conftest.py` based on the
test's directory, mirroring the sibling agent's convention.
