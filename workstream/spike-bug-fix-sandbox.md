# Spike report — bug-fix sandbox on the deployed runtime (S-182, #364)

> **Status: skeleton (phase 1).** This holds the phase 1 local evidence, the
> sandbox-runtime choice, the installed versions and the provisional
> managed-settings keys. Every IC row reads **pending (IC)** until the probe runs
> on the deployed AgentCore runtime (tasks 3.5–3.8, 3.15). The PASS / FAIL verdict
> (task 3.9) is written after the IC run, not here.
>
> **Local is not IC.** The LOCAL rows come from Docker Desktop on an arm64 Mac.
> It isn't AgentCore (a Firecracker microVM), and its kernel, seccomp and
> AppArmor defaults differ. A LOCAL PASS proves the code and image behave as
> designed. It does not satisfy any spike exit criterion (spec §12).

## Changelog

| Version | Date       | Summary                                                         | Author    |
| ------- | ---------- | --------------------------------------------------------------- | --------- |
| 0.1     | 2026-10-23 | Skeleton: phase 1 local evidence, runtime choice, versions, keys | developer |

## 1. Versions (image `bug-fix:local`, linux/arm64)

| Component | Version | Pinned by |
| --------- | ------- | --------- |
| Claude Code CLI | `2.1.309 (Claude Code)`, native binary `claude.exe`, commit `1ce7e4ff2da8` | `ARG CLAUDE_CODE_VERSION` |
| Sandbox runtime (`srt`) | `@anthropic-ai/sandbox-runtime` `0.0.81` | `ARG SANDBOX_RUNTIME_VERSION` |
| bubblewrap | `0.12.0` (Debian 13 package, not setuid) | apt |
| sudo | `1.9.16p2` | apt |
| ripgrep | `14.1.1` (an `srt` dependency) | apt |
| procps | `4.0.4` (`/usr/bin/kill` for the sweep) | apt |
| Base | Debian 13 (trixie), Python 3.13.17, Node v26.12.1 | `python:3.13-slim` |

The IC run records the same table from the deployed image (`cli.version` check).

## 2. Sandbox-runtime choice

**Decision (phase 1): use Claude Code's own sandbox runtime, not a hand-built `bwrap` command line.**

- **`claude -p`** (`Mode.CLI`) runs as `fixer` and enforces its own Bash sandbox from `/etc/claude-code/managed-settings.json`. It is never nested inside `srt`: a registry-only proxy would cut the CLI off from `api.anthropic.com`.
- **Wrapper-run scripts** (`Mode.SCRIPT`: install, gates, changed tests, probe helpers) run under `srt` (`@anthropic-ai/sandbox-runtime`), the library Claude Code's sandbox is built on, packaged as a CLI, with `/etc/bug-fix/srt-settings.json`. It holds the same four registries as the managed policy.

Why not `bwrap` directly:

- `bwrap` alone offers only "no network" (`--unshare-net`). A registry allow-list then needs a filtering proxy plus a socket bridge into the namespace. That is what `srt` already does (bwrap + socat + an HTTP/SOCKS proxy), including the resolved-address check: it refuses link-local, loopback and the cloud-metadata addresses even when an allowed name resolves to them.
- One runtime for both paths means one set of IC results covers both, and D-51 layer 3 ("the same sandbox for repo scripts") holds by construction.

The uid switch is the same for both modes (D-109): `sudo -n -u fixer --preserve-env=<allow-listed names> -- python3 -I /app/fixer_exec.py …`. `fixer_exec.py` rebuilds the env from the allow-list and drops what `sudo` adds.

Caveats for the IC run:

- `bwrap` needs unprivileged user namespaces. If AgentCore blocks them, both modes are affected, and Wave B stays blocked (exit rule, §6).
- `sudo` is setuid. A runtime that sets `no_new_privs` would break the uid switch (`sudo: effective uid is not 0`). The `sudo.*` and `proc.wrapper.uid` checks would show it.

## 3. Managed-settings keys (provisional until IC)

Phase 1 found each key below in the settings schema compiled into CLI 2.1.309 (string search of the binary for the key and its schema description), and added it to `managed-settings.json`. **IC must confirm each takes effect.**

| Key | Where | Purpose | Status |
| --- | ----- | ------- | ------ |
| `permissions.deny` (`Bash(git push:*)`, `Bash(gh:*)`, `Bash(curl:*)`, `Bash(wget:*)`, `WebFetch`, `WebSearch`, Read/Edit `//proc/**`, `//etc/claude-code/**`, `//work/secrets/**`) | `permissions` | D-51 deny rules | present in schema; IC pending (`cli.deny.*`) |
| `permissions.disableBypassPermissionsMode: "disable"` | `permissions` | no bypass mode from a repo | present in schema; IC pending |
| `allowManagedPermissionRulesOnly: true` | top level (next to `disablePluginDirectory`) | repo, user, local and `--settings` permission rules are **ignored**, not just outranked | **added in phase 1**; IC pending |
| `allowManagedHooksOnly: true` | top level | D-29: only managed hooks run | **added in phase 1**; IC pending |
| `allowManagedMcpServersOnly: true` | top level | D-29: only managed MCP servers | **added in phase 1**; IC pending |
| `sandbox.enabled: true` | `sandbox` | Bash sandbox on | present; IC pending |
| `sandbox.allowUnsandboxedCommands: false` | `sandbox` | no escape hatch | present; IC pending |
| `sandbox.failIfUnavailable: true` | `sandbox` | "exit with an error at startup if the sandbox can't start"; without it the CLI warns and **runs Bash unsandboxed** | **added in phase 1**; see LOCAL-07; IC pending |
| `sandbox.network.allowedDomains` (4 registries) | `sandbox.network` | registry-only network | present; IC pending |
| `sandbox.network.allowManagedDomainsOnly: true` | `sandbox.network` | repo domains ignored | **added in phase 1**; IC pending |
| `sandbox.network.allowLocalBinding: false` | `sandbox.network` | no local ports | present; IC pending |

Also seen in the schema, **not adopted** (no decision covers them): `sandbox.enableWeakerNestedSandbox` (would weaken the sandbox for Docker; must stay off), `sandbox.excludedCommands`, `autoAllowBashIfSandboxed`, `permissions.blockReadsOutsideWorkingDirectories`, `sandbox.filesystem.allowManagedReadPathsOnly`.

## 4. Local evidence (LOCAL, not IC)

Two Docker profiles, both running the built image as `wrapper` with the real chain `sudo → fixer_exec.py → srt → bwrap`:

- **default** — Docker Desktop's default seccomp, AppArmor and masked `/proc` paths;
- **permissive** — `--security-opt seccomp=unconfined --security-opt apparmor=unconfined --security-opt systempaths=unconfined`. It stands in for a runtime that allows unprivileged user namespaces. Whether AgentCore does is the question the IC run answers.

| ID | Check | default | permissive | Detail |
| -- | ----- | ------- | ---------- | ------ |
| LOCAL-01 | `image-smoke.sh` (38 assertions incl. D-109) | PASS | n/a | `sudo -n -u fixer id -u` = 10002; `fixer` `sudo -n true` fails; `wrapper` `sudo -n -u root true` fails; sudoers `root:root 440`, `visudo -cf` OK; env reset; `kill -9 -- -1` as `fixer` leaves no process |
| LOCAL-02 | `sandbox.starts` (srt/bwrap) | **FAIL** | PASS | default: `bwrap: No permissions to create a new namespace` |
| LOCAL-03 | `net.blocked.*`: `169.254.170.2`, `169.254.169.254`, `169.254.170.23`, `example.com`, `api.github.com`, `api.anthropic.com` | FAIL (no sandbox) | PASS ×6 | link-local: proxy `403 blocked-by-allowlist`; hosts: `Tunnel connection failed: 403 host is not on the allow list`; raw TCP blocked (no network namespace) |
| LOCAL-04 | `net.reachable.*`: `npm view left-pad version`, `pip download --no-deps six` | FAIL (no sandbox) | PASS ×2 | `1.3.0`; `six-1.17.0` downloaded through the proxy |
| LOCAL-05 | `proc.wrapper.{sandbox,uid}`: `/proc/<wrapper>/environ`, `/mem` | uid PASS, sandbox FAIL (no sandbox) | PASS ×2 | `EACCES` for both; `cmdline` is readable (world-readable by design; no secret is ever in argv) |
| LOCAL-06 | `env.fixer.{sandbox,uid}`; `sudo.*`; `policy.tamper`; `secrets.dir.*` (wrapper-written canary); `board.pat_absent.*` (dummy PAT digest) | uid-only checks PASS | PASS (all) | uid env: `CI HOME LANG PATH`; in srt, plus srt's proxy variables only; policy write `EACCES`; canary `EACCES` (uid) / `ENOENT` (srt `denyRead`) |
| LOCAL-07 | `claude -p` with `failIfUnavailable: true`, default profile (bwrap can't start) | the CLI **started** (it reached the API and failed on the dummy key) | n/a | Locally, `failIfUnavailable` looks like a dependency check only: bwrap, socat and rg are installed. **IC must show that a Bash tool call really runs sandboxed**, or that the CLI refuses. |
| LOCAL-08 | Real chain, daemon and timeout | n/a | PASS | a `setsid`-style daemon leaves no `fixer` process; a SIGTERM-ignoring child is stopped at the deadline (srt honours the relayed SIGTERM and exits 0; the wrapper still reports `timeout`); child uid 10002 |
| LOCAL-09 | `board.disabled_without_pat` | PASS | PASS | `board_updates_enabled=False reason=no_token_secret_id` |
| LOCAL-10 | `cli.version` | PASS | PASS | `2.1.309 (Claude Code)` = pin |

Overall: default profile 10 PASS / 15 FAIL, all failures caused by bwrap's namespace refusal; permissive profile 25 PASS / 0 FAIL. Not run locally: `cli.deny.*` (needs the Anthropic key, read from Secrets Manager on the runtime) and `board.detect` / `add_idempotent` / `status.*` / `cleanup` (need the Projects PAT and the App token).

## 5. IC results (deployed runtime)

Run by `infra-engineer` with `ALLOW_PROBE=1` (task 3.5) and the payload `{"run_id": …, "__probe": true, …}`. One row per `run_event`.

| Check | Spec / test | Verdict | Detail |
| ----- | ----------- | ------- | ------ |
| `sandbox.available.script`, `sandbox.available.cli`, `sandbox.starts` | §12 "bwrap starts on AgentCore ARM64" | pending (IC) | |
| `net.blocked.169.254.170.2` | 3.6, SC-IC-01 | pending (IC) | |
| `net.blocked.169.254.169.254` | 3.6, SC-IC-01 | pending (IC) | |
| `net.blocked.169.254.170.23` | SC-IC-01 | pending (IC) | |
| `net.blocked.example.com` | 3.6, SC-IC-02 | pending (IC) | |
| `net.blocked.api.github.com`, `net.blocked.api.anthropic.com` | SC-IC-02 | pending (IC) | |
| `net.reachable.registry.npmjs.org` | 3.6, SC-IC-02 | pending (IC) | |
| `net.reachable.pypi.org` | 3.6, SC-IC-02 | pending (IC) | |
| `proc.wrapper.sandbox`, `proc.wrapper.uid` | 3.7, 3.16, SC-IC-03 | pending (IC) | |
| `env.fixer.sandbox`, `env.fixer.uid` | 3.7, SC-IC-03 | pending (IC) | |
| `sudo.fixer.uid`, `sudo.fixer.sandbox`, `sudo.wrapper.root` | 3.16, D-109 | pending (IC) | |
| `policy.tamper`, `secrets.dir.sandbox`, `secrets.dir.uid` | SC-IC-05 (part) | pending (IC) | |
| `cli.version` | 3.9 | pending (IC) | |
| `cli.deny.git_push` (denial **and** no ref on the bare remote) | 3.8, SC-IC-04 | pending (IC) | |
| `cli.deny.webfetch` | 3.8, SC-IC-04 | pending (IC) | |
| `board.detect` | 3.15 (1), SC-IC-11 | pending (IC) | |
| `board.add_idempotent` | 3.15 (2), SC-IC-11 | pending (IC) | |
| `board.status.in_progress`, `.in_review`, `.ready` | 3.15 (3), SC-IC-11 | pending (IC) | |
| `board.pat_absent.sandbox`, `board.pat_absent.uid` | 3.15 (4), SC-IC-13 | pending (IC) | |
| `board.disabled_without_pat` | 3.15 (5), SC-IC-14 | pending (IC) | Checks the config contract; `projects.py` lands with S-199 and re-runs this |
| `board.cleanup` (card deleted, probe issue closed) | 3.15, SC-IC-12 | pending (IC) | |

## 6. Verdict

pending (IC). Task 3.9 writes it after the IC run.

- **Sandbox exit rule (spec §12, AC8):** any FAIL among `sandbox.starts`, `net.*`, `proc.wrapper.*` or `cli.deny.*` keeps Wave B (#373–#377) blocked and routes to `product-engineer` drift reconciliation.
- **Board (D-105, AC7):** a FAIL of `board.detect`, `board.add_idempotent` or `board.status.*` sets `BOARD_UPDATES_ENABLED=0` and routes to drift. It does not block Wave B.
- After the run: unset `ALLOW_PROBE` and redeploy (task 3.10). `test_agentcore_config.py` pins `agentcore.json` without it.

## 7. Open questions for the IC run

1. Does AgentCore allow unprivileged user namespaces (bwrap)? Default Docker does not (LOCAL-02).
2. Does `sudo` work there? It needs setuid, so no `no_new_privs`.
3. Does the CLI's own Bash sandbox start, and does `failIfUnavailable` refuse when it can't (LOCAL-07)? The `cli.*` checks show denials but not whether an allowed Bash command was sandboxed. If unclear, add a follow-up probe item: a Bash call that writes outside the cwd must fail.
4. Is the wrapper pid 1 in the AgentCore container? If not, orphans are reaped by whatever is pid 1 there, not by `sandbox.reap_zombies`.
