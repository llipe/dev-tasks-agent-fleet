# bug-fix Agent

An AgentCore agent that answers a `/bug-fix` comment on a GitHub issue: it claims the issue, runs headless Claude Code (`claude -p`) against the target repo inside a sandbox, validates the change with the repo's own gates, and opens a Draft PR for a human to review.

PRD: [`docs/requirements/prd-bug-fix-agent.md`](../../docs/requirements/prd-bug-fix-agent.md). Spec: `workstream/specification-prd-bug-fix-agent.md`.

## Status

**Skeleton only (S-180).** `main.py` validates its config and payload, resolves the Supabase key, reports `started`, and ends `succeeded` / `not_applicable` with the summary "not yet implemented". A deploy of this image is harmless. The pipeline lands in later Wave A–C stories:

| Piece | Story |
| ----- | ----- |
| Runtime, role, secrets, panel invoke policy | S-181 (`infra-engineer`) |
| Sandbox spike; pins the managed-settings key names | S-182 |
| `agents` seed row and params | S-184 |
| Refusal checks, markers, claim, checkout, orchestration | S-185, S-186, S-188, S-189, S-190 |
| Fix runner, validation, red-to-green, Draft PR, confinement | Wave B (S-191–S-195) |

## Layout

```
agents/bug-fix/
├── AGENTS.md                      # AgentCore CLI project guide (generic)
├── README.md
├── agentcore/
│   ├── agentcore.json             # runtime `bug_fix`: env, lifecycle
│   ├── .llm-context/              # AgentCore schema types (read-only)
│   └── cdk/                       # generic AgentCore CDK app used by `agentcore deploy`
└── app/bugFix/
    ├── Dockerfile                 # ARM64 image (see "Image")
    ├── Makefile                   # quality gates + `image`, `image-smoke`
    ├── managed-settings.json      # managed Claude Code policy -> /etc/claude-code/
    ├── pyproject.toml
    ├── main.py                    # AgentCore entrypoint (stub)
    ├── config.py                  # typed env config (ConfigError)
    ├── agent_reporter.py          # copied: runs / run_steps / run_events reporting
    ├── heartbeat.py               # copied: stream keep-alive
    ├── signal_backstop.py         # copied: SIGTERM terminal report
    ├── scrubber.py                # copied + extended: secret redaction
    ├── credentials.py             # copied: Supabase key, GitHub App token
    ├── scripts/image-smoke.sh     # image assertions
    └── tests/{unit,component}/
```

Copied modules follow the sibling convention (copy, don't share; D-03). Each starts with a header naming its source path in `agents/security-analyst/app/securityAnalyst/` and the source commit.

## Configuration

Set in `agentcore/agentcore.json`. Only secret **IDs** are configured; the wrapper reads the values from Secrets Manager and keeps them in memory. Nothing is exported to `os.environ`.

| Variable | Required | Value |
| -------- | -------- | ----- |
| `SUPABASE_URL` | yes | Supabase project URL |
| `SUPABASE_KEY_SECRET_ID` | yes | `agent-fleet/prod/SUPABASE_SERVICE_ROLE_KEY` |
| `ANTHROPIC_KEY_SECRET_ID` | yes | `agent-fleet/prod/ANTHROPIC_API_KEY` (D-50) |
| `MODEL_ID` | yes | An Anthropic API model id, default `claude-sonnet-5-5` (D-43). A cloud inference-profile id is rejected. |
| `PROJECTS_TOKEN_SECRET_ID` | no | `agent-fleet/prod/GITHUB_PROJECTS_TOKEN` (D-99). Absent: the board is disabled (`no_token_secret_id`); the run continues. |
| `BOARD_UPDATES_ENABLED` | no | `1` or `0`. Absent or `0`: the board is disabled (`flag_off`). Any other value is a config error. |

`config.load_config()` raises `ConfigError(variable, reason)` for a missing, blank or invalid required variable. The message names the variable, never its value. The entrypoint maps it to `failed` / `CONFIG_INVALID`.

Lifecycle: `maxLifetime` 3600 s, `idleRuntimeSessionTimeout` 900 s. `config.MAX_LIFETIME` and `config.IDLE_SESSION_TIMEOUT` must match, and the seed's `max_runtime_seconds` (S-184) must equal `maxLifetime`. Unit tests pin the first two.

## Image

`Dockerfile`, built for `linux/arm64`:

- Python 3.13 (wrapper), Node 26 + pnpm 10.11.0, git, make, `bubblewrap` and `socat` (the Claude Code sandbox runtime on Linux).
- `@anthropic-ai/claude-code` pinned by `ARG CLAUDE_CODE_VERSION`, installed root-owned; `DISABLE_AUTOUPDATER=1`.
- Users: `wrapper` (uid 10001, the default user; runs `main.py`) and `fixer` (uid 10002; will run the CLI and repo scripts). Separate groups, no sudo, private homes.
- Directories: `/work/repo` and `/work/out` owned by `fixer`; `/work/wrapper` and `/work/secrets` owned by `wrapper`, mode 0700.
- `/etc/claude-code/managed-settings.json`, `root:root` 0644, directory 0755.

How the wrapper starts processes as `fixer` (for example a sudoers rule limited to `fixer`, or `setpriv` with a capability) is not in the image yet. `sandbox.py` (S-182/S-191) decides it.

### Managed Claude Code policy

`managed-settings.json` (spec §12, D-51 layer 2) takes precedence over a target repo's `.claude/`:

- Bash sandbox enabled, `allowUnsandboxedCommands: false`, bypass-permissions mode disabled.
- Network allow-list: exactly `registry.npmjs.org`, `registry.yarnpkg.com`, `pypi.org`, `files.pythonhosted.org`. No link-local, no GitHub, no wildcard.
- Deny: `Bash(git push:*)`, `Bash(gh:*)`, `Bash(curl:*)`, `Bash(wget:*)`, `WebFetch`, `WebSearch`, and Read/Edit of `/proc/**`, `/etc/claude-code/**` and `/work/secrets/**`.

Path rules use Claude Code's `//` prefix for an absolute path (`Read(//proc/**)`). A single leading `/` is resolved relative to the settings file, so `Read(/proc/**)` here would guard `/etc/claude-code/proc/**`.

**The key names are provisional.** The S-182 spike pins them against the installed CLI version on the deployed runtime; `tests/unit/test_managed_policy.py` re-runs against the spike's keys.

## Testing

From `app/bugFix/`:

```bash
make install        # pip install -e '.[dev]' (Python 3.13 venv)
make test           # unit + component
make validate       # lint, format-check, typecheck, test-cov (>= 90%), audit
make image          # docker build --platform linux/arm64 -t bug-fix:local .
make image-smoke    # build, then scripts/image-smoke.sh bug-fix:local
```

`scripts/image-smoke.sh [image]` asserts the toolchain versions (including `claude --version` equal to the pinned version), the users and their isolation, the directory owners and modes, and that neither runtime user can modify the policy. The repo-root `make validate` includes this package.

## Deployment

Not deployed by this story. The first deploy, the runtime role and its secret grants, and the panel invoke-policy entry are S-181, run by `infra-engineer`. The runbook is `docs/runbooks/bug-fix-agent.md` (stub in S-181, completed in Wave C).
