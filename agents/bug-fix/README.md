# bug-fix Agent

An AgentCore agent that answers a `/bug-fix` comment on a GitHub issue: it claims the issue, runs headless Claude Code (`claude -p`) against the target repo inside a sandbox, validates the change with the repo's own gates, and opens a Draft PR for a human to review.

PRD: [`docs/requirements/prd-bug-fix-agent.md`](../../docs/requirements/prd-bug-fix-agent.md). Spec: `workstream/specification-prd-bug-fix-agent.md`.

## Status

**Skeleton (S-180) plus the sandbox spike code (S-182, phase 1).** `main.py` validates its config and payload, resolves the Supabase key, reports `started`, and ends `succeeded` / `not_applicable` with the summary "not yet implemented". It also has a probe mode for the S-182 spike, off unless the runtime sets `ALLOW_PROBE=1` (see "Probe mode"). A deploy of this image is harmless. The pipeline lands in later Wave A–C stories:

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
    ├── srt-settings.json          # sandbox-runtime policy for fixer scripts -> /etc/bug-fix/
    ├── sudoers-bug-fix            # the one sudo rule: wrapper -> fixer -> /etc/sudoers.d/bug-fix
    ├── pyproject.toml
    ├── main.py                    # AgentCore entrypoint (stub + probe-mode hook)
    ├── config.py                  # typed env config (ConfigError)
    ├── sandbox.py                 # starts fixer processes: uid switch, env, sandbox, timeout
    ├── fixer_exec.py              # runs as fixer after sudo; rebuilds the env from the allow-list
    ├── probe.py                   # S-182 spike checks (probe mode)
    ├── probe_inner.py             # the probe's fixer-side helper (stdlib only)
    ├── agent_reporter.py          # copied: runs / run_steps / run_events reporting
    ├── heartbeat.py               # copied: stream keep-alive
    ├── signal_backstop.py         # copied: SIGTERM terminal report
    ├── scrubber.py                # copied + extended: secret redaction
    ├── credentials.py             # copied + extended: Supabase key, App token, fetch_secret_string
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

- Python 3.13 (wrapper), Node 26 + pnpm 10.11.0, git, make, `bubblewrap`, `socat` and `ripgrep` (the Claude Code sandbox runtime on Linux), `procps` (`/usr/bin/kill` for the post-run sweep), and `sudo`.
- `@anthropic-ai/claude-code` pinned by `ARG CLAUDE_CODE_VERSION`, and `@anthropic-ai/sandbox-runtime` (`srt`) pinned by `ARG SANDBOX_RUNTIME_VERSION`, both installed root-owned; `DISABLE_AUTOUPDATER=1`.
- Users: `wrapper` (uid 10001, the default user; runs `main.py`) and `fixer` (uid 10002; runs the CLI and repo scripts). Separate groups, private homes.
- Directories: `/work/repo` and `/work/out` owned by `fixer`; `/work/wrapper` and `/work/secrets` owned by `wrapper`, mode 0700.
- `/etc/claude-code/managed-settings.json` and `/etc/bug-fix/srt-settings.json`, `root:root` 0644, directories 0755.
- `/etc/sudoers.d/bug-fix`, `root:root` 0440, checked with `visudo -cf` at build time (D-109).

### Starting processes as `fixer` (`sandbox.py`, D-51, D-109)

The wrapper never runs model output or repo code in its own process. `sandbox.py` starts every such process as:

```
sudo -n -u fixer --preserve-env=<names> -- python3 -I /app/fixer_exec.py <runtime> ...
```

- **uid switch.** One sudoers rule: `wrapper ALL=(fixer) NOPASSWD: ALL`, with `Defaults env_reset` and a fixed `secure_path`. `wrapper` can become `fixer` and nobody else; `fixer` can't run `sudo` at all.
- **Minimal env.** The spawn env is built from an allow-list, never from `os.environ`: `ANTHROPIC_API_KEY` (only when passed), `PATH`, `HOME=/home/fixer`, `LANG`, `CI=1`. Only those names cross `sudo`, and `fixer_exec.py` rebuilds the final env from the same allow-list, dropping what `sudo` adds. No value is put in argv.
- **Sandbox.** Two modes, and no bare exec. `SCRIPT` (install, gates, tests, probe helpers) runs under `srt --settings /etc/bug-fix/srt-settings.json`: bwrap with no network namespace, a fresh pid namespace and `/proc`, and srt's filtering proxy limited to the same four registries as the managed policy. `CLI` runs only the pinned `claude` binary, which enforces its own Bash sandbox from the managed policy. (Nesting `claude` in `srt` would cut it off from the Anthropic API.)
- **Timeout.** SIGTERM at the wall-clock deadline (`sudo` relays it). If the child is still alive 15 s later, every `fixer` process is swept and the child gets SIGKILL. The timeout outcome is distinct from a non-zero exit (srt itself exits 0 after a relayed SIGTERM).
- **No survivors (D-62).** After every run, `sudo -u fixer kill -9 -- -1` kills every `fixer` process, daemons included, and zombies are reaped.
- A missing `sudo`, `python3`, `fixer_exec.py`, `srt`, settings file or `claude` raises `SandboxUnavailable`.

### Managed Claude Code policy

`managed-settings.json` (spec §12, D-51 layer 2) takes precedence over a target repo's `.claude/`:

- Bash sandbox enabled, `allowUnsandboxedCommands: false`, `failIfUnavailable: true`, bypass-permissions mode disabled.
- Managed-only: `allowManagedPermissionRulesOnly` (repo, user and `--settings` permission rules are ignored, not just outranked), `sandbox.network.allowManagedDomainsOnly`, `allowManagedHooksOnly` and `allowManagedMcpServersOnly` (D-29).
- Network allow-list: exactly `registry.npmjs.org`, `registry.yarnpkg.com`, `pypi.org`, `files.pythonhosted.org`. No link-local, no GitHub, no wildcard.
- Deny: `Bash(git push:*)`, `Bash(gh:*)`, `Bash(curl:*)`, `Bash(wget:*)`, `WebFetch`, `WebSearch`, and Read/Edit of `/proc/**`, `/etc/claude-code/**` and `/work/secrets/**`.

Path rules use Claude Code's `//` prefix for an absolute path (`Read(//proc/**)`). A single leading `/` is resolved relative to the settings file, so `Read(/proc/**)` here would guard `/etc/claude-code/proc/**`.

**The key names are provisional until the S-182 IC run.** Phase 1 found every key above in the settings schema of the pinned CLI (2.1.309); the IC run on the deployed runtime confirms they take effect. See `workstream/spike-bug-fix-sandbox.md`. `tests/unit/test_managed_policy.py` pins them.

## Probe mode (S-182, D-70)

A top-level payload key `__probe: true` (the JSON boolean, outside `params`) runs the spike checks in `probe.py`, but only when the runtime sets `ALLOW_PROBE=1`. Without the flag the run fails with `PROBE_REFUSED` and no check runs. `params.__probe` and non-boolean values are ignored (the normal path runs). The panel can't send the key; `infra-engineer` invokes the runtime directly, and sets and unsets the flag (tasks 3.5 and 3.10).

Each check is one `run_event` `{check, verdict: PASS|FAIL, detail}`, scrubbed, and the run ends `succeeded` / `not_applicable` with a JSON summary. Check groups: `sandbox.*` (the sandbox runtime starts), `net.*` (credential and metadata endpoints and non-registry hosts blocked, registries reachable), `proc.*`, `env.*`, `sudo.*` (as `fixer`, inside the sandbox and with the uid switch alone), `policy.*` / `secrets.*`, `cli.*` (`claude -p` in a throwaway repo whose `.claude/settings.json` allows what the managed policy denies), and `board.*` (D-105: the linked board #5 of `llipe/dev-tasks`, with cleanup in a `finally`). The PAT check passes only a SHA-256 digest to `fixer`.

## Testing

From `app/bugFix/`:

```bash
make install        # pip install -e '.[dev]' (Python 3.13 venv)
make test           # unit + component
make validate       # lint, format-check, typecheck, test-cov (>= 90%), audit
make image          # docker build --platform linux/arm64 -t bug-fix:local .
make image-smoke    # build, then scripts/image-smoke.sh bug-fix:local
```

`scripts/image-smoke.sh [image]` asserts the toolchain versions (including `claude --version` and `srt --version` equal to the pinned versions), the users and their isolation, the sudo rule (`sudo -n -u fixer id -u` is 10002, `fixer` can't sudo, `wrapper` can't become root, the env is reset, the post-run sweep leaves no `fixer` process), the directory owners and modes, and that neither runtime user can modify either policy file. The repo-root `make validate` includes this package.

`tests/component/test_sandbox_proc.py` runs the real command chain with real processes; only `sudo` and `srt` are replaced by exec-through shims, and the sweep is scoped to a per-test marker (the production sweep would kill every process of the current user).

## Deployment

Not deployed by this story. The first deploy, the runtime role and its secret grants, and the panel invoke-policy entry are S-181, run by `infra-engineer`. The runbook is `docs/runbooks/bug-fix-agent.md` (stub in S-181, completed in Wave C).
