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
│   ├── toolchain.py       # Package manager detection (pnpm/npm)
│   ├── validator.py       # Lint/format/typecheck/test runner
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
9. [Optional] LLM fix loop (bounded by `max_fix_attempts`)
10. Open PR (idempotent — skips if `deps/update-*` branch exists)
11. Report outcome to Supabase

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
| `MODEL_ID` | No | Bedrock model for LLM fix loop (default: Claude Sonnet) |

## Testing

```bash
cd agents/dependency-update/app/dependencyUpdate
pip install -e ".[dev]"
pytest -m unit tests/unit/
pytest -m component tests/component/
pytest tests/
```
