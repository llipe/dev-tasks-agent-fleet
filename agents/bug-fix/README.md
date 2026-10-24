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
    ├── pyproject.toml
    ├── main.py                    # AgentCore entrypoint (stub + probe-mode hook)
    ├── config.py                  # typed env config (ConfigError)
    ├── sandbox.py                 # starts fixer processes: setpriv drop, env, sandbox, timeout
    ├── fixer_exec.py              # runs as fixer after setpriv; rebuilds the env, refuses root
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

- Python 3.13 (wrapper), Node 26 + pnpm 10.11.0, git, make, `bubblewrap`, `socat` and `ripgrep` (the Claude Code sandbox runtime on Linux), `util-linux` (`setpriv`, the drop to `fixer`), and `procps` (`kill` and `pkill` for the post-run sweep). No `sudo`: the build fails if it is present.
- `@anthropic-ai/claude-code` pinned by `ARG CLAUDE_CODE_VERSION`, and `@anthropic-ai/sandbox-runtime` (`srt`) pinned by `ARG SANDBOX_RUNTIME_VERSION`, both installed root-owned; `DISABLE_AUTOUPDATER=1`.
- Users: the wrapper (`main.py`) runs as **root**, the image's default user (D-110). `fixer` (uid/gid 10002, in no other group, private home) runs the CLI and repo scripts. There is no other runtime user.
- Directories: `/work/repo` and `/work/out` owned by `fixer`; `/work/wrapper` and `/work/secrets` `root:root` 0700.
- `/etc/claude-code/managed-settings.json` and `/etc/bug-fix/srt-settings.json`, `root:root` 0644, directories 0755.

### Starting processes as `fixer` (`sandbox.py`, D-51, D-110)

The wrapper never runs model output or repo code in its own process. `sandbox.py` starts every such process as:

```
setpriv --reuid=10002 --regid=10002 --clear-groups --inh-caps=-all --no-new-privs -- \
  python3 -I /app/fixer_exec.py <runtime> ...
```

- **Why root, not sudo.** AgentCore starts the container with `no_new_privs` set, so a setuid helper such as `sudo` can't run (S-182 probe run 1, which retired D-109's sudo rule). A root process can still drop privileges under `no_new_privs`, so the wrapper runs as root and drops per process.
- **The drop.** The child has uid and gid 10002 (real, effective, saved and filesystem), no supplementary groups, no capabilities (inheritable cleared; permitted, effective and ambient are cleared by the uid change), and `no_new_privs` set. A setuid-root binary therefore can't take it back to root, and `setuid(0)`, `su` and `setpriv --reuid=0` fail. A process with another uid can't read the root wrapper's `/proc/<pid>/environ` or `/proc/<pid>/mem`.
- **Mitigations for a root wrapper (D-110).** There is one microVM per AgentCore session. The wrapper never runs model output or repo scripts in its own process. Nothing but wrapper code runs as root. `fixer_exec.py` refuses to exec while its uid or euid is 0, so a failed drop never runs a command as root.
- **Minimal env.** The spawn env is built from an allow-list, never from `os.environ`: `ANTHROPIC_API_KEY` (only when passed), `PATH`, `HOME=/home/fixer`, `LANG`, `CI=1`. `setpriv` passes it through unchanged, and `fixer_exec.py` rebuilds the final env from the same allow-list. No value is put in argv.
- **Sandbox.** Two modes, and no bare exec. `SCRIPT` (install, gates, tests, probe helpers) runs under `srt --settings /etc/bug-fix/srt-settings.json`: bwrap with no network namespace, a fresh pid namespace and `/proc`, and srt's filtering proxy limited to the same four registries as the managed policy. `CLI` runs only the pinned `claude` binary, which enforces its own Bash sandbox from the managed policy. (Nesting `claude` in `srt` would cut it off from the Anthropic API.)
- **Timeout.** SIGTERM at the wall-clock deadline. `setpriv` and `fixer_exec.py` exec, so the child pid is the runtime itself. If the child is still alive 15 s later, every `fixer` process is swept and the child gets SIGKILL. The timeout outcome is distinct from a non-zero exit (srt itself exits 0 after a relayed SIGTERM).
- **No survivors (D-62).** After every run the sweep kills every `fixer` process, daemons included, in two passes. First, `kill -9 -- -1` as `fixer`: one kernel pass over every process `fixer` may signal, which a fork loop can't outrun. Second, `pkill -KILL -u 10002` as root. Then zombies are reaped.
- A missing `setpriv`, `python3`, `fixer_exec.py`, `srt`, settings file or `claude` raises `SandboxUnavailable`.

### Managed Claude Code policy

`managed-settings.json` (spec §12, D-51 layer 2) takes precedence over a target repo's `.claude/`:

- Bash sandbox enabled, `allowUnsandboxedCommands: false`, `failIfUnavailable: true`, bypass-permissions mode disabled.
- Managed-only: `allowManagedPermissionRulesOnly` (repo, user and `--settings` permission rules are ignored, not just outranked), `sandbox.network.allowManagedDomainsOnly`, `allowManagedHooksOnly` and `allowManagedMcpServersOnly` (D-29).
- Network allow-list: exactly `registry.npmjs.org`, `registry.yarnpkg.com`, `pypi.org`, `files.pythonhosted.org`. No link-local, no GitHub, no wildcard.
- Deny: `Bash(git push:*)`, `Bash(gh:*)`, `Bash(curl:*)`, `Bash(wget:*)`, `WebFetch`, `WebSearch`, and Read/Edit of `/proc/**`, `/etc/claude-code/**` and `/work/secrets/**`.

Path rules use Claude Code's `//` prefix for an absolute path (`Read(//proc/**)`). A single leading `/` is resolved relative to the settings file, so `Read(/proc/**)` here would guard `/etc/claude-code/proc/**`.

**The key names are provisional until the S-182 IC run.** Phase 1 found every key above in the settings schema of the pinned CLI (2.1.309); the IC run on the deployed runtime confirms they take effect. See `workstream/spike-bug-fix-sandbox.md`. `tests/unit/test_managed_policy.py` pins them.

## Probe mode (S-182, D-70)

A top-level payload key `__probe: true` (the JSON boolean, outside `params`) runs the spike checks in `probe.py`, but only when the runtime sets `ALLOW_PROBE=1`. Without the flag the run fails with `PROBE_REFUSED` and no check runs. `params.__probe` and non-boolean values are ignored (the normal path runs). The panel can't send the key; `infra-engineer` invokes the runtime directly, and sets and unsets the flag (tasks 3.5 and 3.10). The procedure is in `docs/runbooks/bug-fix-agent.md`, section "Run the sandbox probe".

Each check is one `run_event` `{check, verdict: PASS|FAIL, detail}`, scrubbed, and the run ends `succeeded` / `not_applicable` with a JSON summary. Check groups:
- `setpriv.*`: the wrapper is root with `CAP_SETUID`/`CAP_SETGID`, and a dropped process has uid/gid 10002, no groups, no capabilities and `NoNewPrivs: 1`.
- `sandbox.*`: the sandbox runtime starts.
- `userns.available`: reported on its own. Can `fixer`'s `bwrap` create the user, pid and net namespaces under AgentCore's `no_new_privs`? The detail adds `unshare`, the sysctls and the same measurement as root.
- `net.*`: credential and metadata endpoints and non-registry hosts are blocked; registries are reachable.
- `proc.*`, `env.*` and `noescalate.*`: as `fixer`, inside the sandbox and with the drop alone. `noescalate.*` covers `setuid(0)`, `su` and `setpriv --reuid=0`, and checks that no `sudo` is present.
- `policy.*` / `secrets.*`.
- `cli.version`: exit code, outcome and stderr are always in the detail.
- `cli.*`: `claude -p` in a throwaway repo whose `.claude/settings.json` allows what the managed policy denies.
- `board.*` (D-105: the linked board #5 of `llipe/dev-tasks`, with cleanup in a `finally`). The PAT check passes only a SHA-256 digest to `fixer`.

## Testing

From `app/bugFix/`:

```bash
make install        # pip install -e '.[dev]' (Python 3.13 venv)
make test           # unit + component
make validate       # lint, format-check, typecheck, test-cov (>= 90%), audit
make image          # docker build --platform linux/arm64 -t bug-fix:local .
make image-smoke    # build, then scripts/image-smoke.sh bug-fix:local
```

`scripts/image-smoke.sh [image]` runs the privilege checks with `--security-opt no-new-privileges`, which emulates AgentCore. It asserts:
- the toolchain versions, including `claude --version` (run through `setpriv` and `fixer_exec.py`) and `srt --version` equal to the pinned versions;
- the default user is root, and there is no `sudo` or sudoers file;
- the `setpriv` drop: uid/gid 10002, no groups, no capabilities, `NoNewPrivs: 1`;
- no way back to root: a setuid-root binary stays at euid 10002, with a control run without `no_new_privs` that does reach 0;
- `fixer` can't read the root wrapper's `/proc/<pid>/environ` or `mem`;
- `fixer_exec.py`'s env rebuild and its refusal to run as root;
- `sandbox.py`'s own paths, prefix and sweep;
- the directory owners and modes, and that `fixer` can't modify either policy file.

The repo-root `make validate` includes this package.

`tests/component/test_sandbox_proc.py` runs the real command chain with real processes. Only `setpriv` and `srt` are replaced by exec-through shims, and the sweep is scoped to a per-test marker (the production sweep would kill every process of the current user).

## Deployment

Not deployed by this story. The first deploy, the runtime role and its secret grants, and the panel invoke-policy entry are S-181, run by `infra-engineer`. The runbook is `docs/runbooks/bug-fix-agent.md` (stub in S-181, completed in Wave C).
