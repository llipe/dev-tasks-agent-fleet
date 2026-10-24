# Spike report — bug-fix sandbox on the deployed runtime (S-182, #364)

> **Status: PASS (2026-10-24).** IC probe run 1 (D-109 image)
> failed on `no_new_privs` (§5.1), which led to D-110. **Re-probe 2b** (runtime
> v3, D-110 image) gave **34 PASS / 3 FAIL** (§5.2): user namespaces, the
> setpriv drop, `/proc` isolation, no-escalation, `git push` deny and the board
> pass; `localhost`, srt's proxy host, didn't resolve inside the sandbox, and
> `cli.deny.webfetch` misread a working deny. Fix round 2 (§4.3) appended
> `127.0.0.1 localhost` to `/etc/hosts` at run time. **Re-probe 2c** (runtime
> v4) gave **18 PASS / 19 FAIL**, all for one reason: AgentCore's `/etc/hosts`
> is empty **and read-only**, so the append failed and `sandbox.py` refused
> every sandboxed run (fail-closed, nothing ran unsandboxed). **Fix round 3**
> (§4.4, D-111) resolves `localhost` in the image through
> `libnss-myhostname`, with IPv4 first, and the wrapper only checks it. **Re-probe 2d**
> (runtime v5) gave **39 PASS / 0 FAIL** (§5.2): `localhost` resolves via
> nss-myhostname with `127.0.0.1` first. **Verdict: PASS** (§6). Runtime v6 has
> `ALLOW_PROBE` removed and refuses probe payloads (`PROBE_REFUSED`).
>
> **Local is not IC.** The LOCAL rows come from Docker Desktop on an arm64 Mac.
> It isn't AgentCore (a Firecracker microVM), and its kernel, seccomp and
> AppArmor defaults differ. A LOCAL PASS proves the code and image behave as
> designed. It does not satisfy any spike exit criterion (spec §12).

## Changelog

| Version | Date       | Summary                                                         | Author    |
| ------- | ---------- | --------------------------------------------------------------- | --------- |
| 0.1     | 2026-10-23 | Skeleton: phase 1 local evidence, runtime choice, versions, keys | developer |
| 0.2     | 2026-10-24 | Phase 1b (D-110): IC run 1 summary (FAIL, `no_new_privs`; board PASS); setpriv drop; local evidence with `no-new-privileges` emulated; `setpriv.*`, `noescalate.*`, `userns.available` rows | developer |
| 0.3     | 2026-10-24 | Re-probe 2b results (34/37). Fix round 2: `/etc/hosts` loopback entry (registries), `cli.deny.*` reads the offered tool list, `--disallowedTools=WebFetch,WebSearch`; §4.3 local evidence; `net.localhost`, `cli.deny.websearch` rows | developer |
| 0.4     | 2026-10-24 | Re-probe 2c results (18/37: AgentCore's `/etc/hosts` is empty and read-only). Fix round 3 (D-111): `localhost` through `libnss-myhostname` and `/etc/gai.conf` in the image; `sandbox.py` preflight is read-only (`check_localhost_resolution`, `localhost_via`); `net.localhost` reports `via=` and needs `127.0.0.1` first; §4.4 local evidence; 2d column | developer |
| 0.5     | 2026-10-24 | Re-probe 2d: 39/39 PASS on runtime v5; 2d column; verdict PASS (§6); open question 5 answered; question 3 narrowed to a follow-up; `ALLOW_PROBE` removed (runtime v6, `PROBE_REFUSED`) | planner (infra-engineer) |

## 1. Versions (image `bug-fix:local`, linux/arm64)

| Component | Version | Pinned by |
| --------- | ------- | --------- |
| Claude Code CLI | `2.1.309 (Claude Code)`, native binary `claude.exe`, commit `1ce7e4ff2da8` | `ARG CLAUDE_CODE_VERSION` |
| Sandbox runtime (`srt`) | `@anthropic-ai/sandbox-runtime` `0.0.81` | `ARG SANDBOX_RUNTIME_VERSION` |
| bubblewrap | `0.12.0` (Debian 13 package, not setuid) | apt |
| util-linux (`setpriv`) | `2.41.5` (the root → `fixer` drop, D-110; `sudo` removed) | apt |
| ripgrep | `14.1.1` (an `srt` dependency) | apt |
| procps | `4.0.4` (`kill` and `pkill` for the sweep) | apt |
| Base | Debian 13 (trixie), Python 3.13.17, Node v26.12.1 | `python:3.13-slim` |

The IC run records the same table from the deployed image (`cli.version` check).

## 2. Sandbox-runtime choice

**Decision (phase 1): use Claude Code's own sandbox runtime, not a hand-built `bwrap` command line.**

- **`claude -p`** (`Mode.CLI`) runs as `fixer` and enforces its own Bash sandbox from `/etc/claude-code/managed-settings.json`. It is never nested inside `srt`: a registry-only proxy would cut the CLI off from `api.anthropic.com`.
- **Wrapper-run scripts** (`Mode.SCRIPT`: install, gates, changed tests, probe helpers) run under `srt` (`@anthropic-ai/sandbox-runtime`), the library Claude Code's sandbox is built on, packaged as a CLI, with `/etc/bug-fix/srt-settings.json`. It holds the same four registries as the managed policy.

Why not `bwrap` directly:

- `bwrap` alone offers only "no network" (`--unshare-net`). A registry allow-list then needs a filtering proxy plus a socket bridge into the namespace. That is what `srt` already does (bwrap + socat + an HTTP/SOCKS proxy), including the resolved-address check: it refuses link-local, loopback and the cloud-metadata addresses even when an allowed name resolves to them.
- One runtime for both paths means one set of IC results covers both, and D-51 layer 3 ("the same sandbox for repo scripts") holds by construction.

The uid drop is the same for both modes (D-110, which replaces D-109's sudo rule):

```
setpriv --reuid=10002 --regid=10002 --clear-groups --inh-caps=-all --no-new-privs -- python3 -I /app/fixer_exec.py …
```

The wrapper runs as root. `setpriv` passes the allow-list env through, and `fixer_exec.py` rebuilds it and refuses to run as root.

Caveats for the re-probe:

- `bwrap` needs unprivileged user namespaces. If AgentCore blocks them, both modes are affected, and Wave B stays blocked (exit rule, §6). D-110 then reopens the fallback (a separate CLI runtime). `userns.available` answers this directly.
- ~~`sudo` is setuid. A runtime that sets `no_new_privs` would break the uid switch.~~ **Confirmed by run 1** (§5.1), which is why D-110 replaces the switch. `setpriv` needs only `CAP_SETUID`/`CAP_SETGID` in the root wrapper, and `setpriv.wrapper.root` checks that.

## 3. Managed-settings keys (provisional until IC)

Phase 1 found each key below in the settings schema compiled into CLI 2.1.309 (string search of the binary for the key and its schema description), and added it to `managed-settings.json`. **IC must confirm each takes effect.**

| Key | Where | Purpose | Status |
| --- | ----- | ------- | ------ |
| `permissions.deny` (`Bash(git push:*)`, `Bash(gh:*)`, `Bash(curl:*)`, `Bash(wget:*)`, `WebFetch`, `WebSearch`, Read/Edit `//proc/**`, `//etc/claude-code/**`, `//work/secrets/**`) | `permissions` | D-51 deny rules | IC 2b: `git push` denied, no ref. The bare `WebFetch`/`WebSearch` form is a **tool-wide deny: the CLI removes the tool from the list offered to the model** (LOCAL-2-04), so no denial is ever recorded; 2c checks the offered list |
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

### 4.1 Phase 1 (D-109 image, superseded)

Kept for the record; the sudo chain it exercised no longer exists. Two Docker profiles, both running the built image as `wrapper` with the real chain `sudo → fixer_exec.py → srt → bwrap`. **Neither emulated `no_new_privs`, which is why this passed locally and failed on AgentCore.**

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

### 4.2 Phase 1b (D-110 image, `no-new-privileges` emulated) — LOCAL, 2026-10-24

The image `bug-fix:local` runs as its default user, **root**, with `--security-opt no-new-privileges` in both profiles to emulate AgentCore. The root wrapper's own `/proc/self/status` shows `NoNewPrivs: 1`. The real chain is `setpriv → fixer_exec.py → srt → bwrap`.

The harness calls the real `probe.py` check groups with the production `Sandbox()` and `Inner()`. It is not committed: it is the probe minus the groups that need secrets. It runs with dummy config env and a dummy PAT digest.

- **default + NNP:** Docker Desktop's default seccomp, AppArmor and masked paths.
- **permissive + NNP:** adds `seccomp=unconfined`, `apparmor=unconfined` and `systempaths=unconfined`.

| ID | Check | default + NNP | permissive + NNP | Detail |
| -- | ----- | ------------- | ---------------- | ------ |
| LOCAL-1b-01 | `image-smoke.sh` (41 assertions, D-110) | PASS | n/a | under NNP: default user root; no `sudo`/sudoers; drop gives `Uid`/`Gid` 10002 ×4, no `Groups`, `CapInh/Prm/Eff/Amb` 0, `NoNewPrivs` 1 (also without the container flag); `setuid(0)`, `setgid(0)`, `su root`, `setpriv --reuid=0` fail; a setuid-root `id` copy stays euid 10002 (control without NNP: euid 0); `/proc/<root pid>/environ` and `mem` and `/proc/1/environ` denied; `fixer_exec.py` env `CI HOME LANG PATH` and exit 3 as root; `Sandbox().sweep()` leaves no fixer process and spares root's; `claude --version` through setpriv = pin |
| LOCAL-1b-02 | `setpriv.wrapper.root` | PASS | PASS | `uid=0/0/0/0`, `CapEff=00000000a80425fb` (has SETUID/SETGID), `NoNewPrivs=1` |
| LOCAL-1b-03 | `setpriv.drop.uid` | PASS | PASS | `uid=10002/10002/10002/10002 gid=… groups=` caps all 0, `NoNewPrivs=1` |
| LOCAL-1b-04 | `setpriv.drop.sandbox` | FAIL (bwrap) | PASS | permissive: same identity inside srt/bwrap, `CapBnd=000001ffffffffff` (user namespace) |
| LOCAL-1b-05 | `userns.available` | **FAIL** | PASS | default: fixer `bwrap rc=1` "No permissions to create a new namespace", `unshare rc=1` EPERM, `max_user_namespaces=31879 unprivileged_userns_clone=1`; root also refused (Docker's default seccomp). Permissive: fixer and root `bwrap rc=0`, `unshare rc=0`. **`no_new_privs` alone does not block user namespaces;** the seccomp profile does. |
| LOCAL-1b-06 | `sandbox.available.*`, `sandbox.starts` | available PASS, starts FAIL (bwrap) | PASS ×3 | |
| LOCAL-1b-07 | `net.blocked.*` (6), `net.reachable.*` (2) | FAIL (bwrap) | PASS ×8 | link-local: proxy `403 blocked-by-allowlist`; hosts: `Tunnel connection failed: 403 host is not on the allow list`; raw TCP blocked; `npm view left-pad` = `1.3.0`; `pip download six` OK |
| LOCAL-1b-08 | `proc.wrapper.uid`, `proc.wrapper.sandbox` | uid PASS, sandbox FAIL (bwrap) | PASS ×2 | the root wrapper (pid 1): `environ` and `mem` `EACCES`; `cmdline` readable by design |
| LOCAL-1b-09 | `env.fixer.uid`, `env.fixer.sandbox` | uid PASS, sandbox FAIL (bwrap) | PASS ×2 | uid: `CI HOME LANG PATH`; srt adds its proxy variables only |
| LOCAL-1b-10 | `noescalate.fixer.uid`, `.sandbox`, `noescalate.no_sudo` | uid PASS, sandbox FAIL (bwrap), no_sudo PASS | PASS ×3 | `setuid(0)=EPERM` (`EINVAL` inside the user namespace), `su rc=1`, `setpriv --reuid=0 rc=1`, `NoNewPrivs=1`; no `sudo` on PATH, no sudoers files |
| LOCAL-1b-11 | `policy.tamper`, `secrets.dir.uid`, `secrets.dir.sandbox` | uid PASS, others FAIL (bwrap) | PASS ×3 | policy write `EACCES`; canary `EACCES` (uid) / `ENOENT` (srt `denyRead`) |
| LOCAL-1b-12 | `cli.version` | PASS | PASS | `claude --version rc=0 outcome=ok stdout='2.1.309 (Claude Code)'`, run as fixer through setpriv |
| LOCAL-1b-13 | `board.pat_absent.uid`, `.sandbox` (dummy PAT digest) | uid PASS, sandbox FAIL (bwrap) | PASS ×2 | `matches=0` |
| LOCAL-1b-14 | `board.disabled_without_pat` | PASS | PASS | `reason=no_token_secret_id` |

Overall: **default + NNP 12 PASS / 17 FAIL.** All 17 failures are bwrap's namespace refusal, which `userns.available` names. **Permissive + NNP: 29 PASS / 0 FAIL.** The setpriv drop, the `/proc` isolation from a root wrapper and the no-escalation checks pass in both profiles. Whether AgentCore allows user namespaces is the open question for the re-probe. Not run locally, as before: `cli.deny.*` and the live `board.*` checks.

### 4.3 Fix round 2 (after re-probe 2b) — LOCAL, 2026-10-24

Profile: the image's default user (root), `--security-opt no-new-privileges`, plus `seccomp=unconfined`, `apparmor=unconfined` and `systempaths=unconfined` (re-probe 2b showed AgentCore allows user namespaces; Docker's masked `/proc` paths otherwise stop bwrap mounting a fresh procfs). The chain is the production one: `Sandbox().run` → `setpriv` → `fixer_exec.py` → `srt` → `bwrap`.

**Root cause 1 — registries (`net.reachable.*`).** srt 0.0.81 hard-codes `localhost` in every proxy variable (`dist/sandbox/sandbox-utils.js`: `HTTP_PROXY=http://${auth}localhost:${httpProxyPort}`, and the same for HTTPS/ALL/FTP/GRPC/Docker/`GIT_SSH_COMMAND`). No setting changes it. The CLI's native binary embeds the same strings (`HTTP_PROXY=http://${i}localhost:${e}`, `TCP6-LISTEN:${D},ipv6only=0`), so its Bash sandbox uses the same mechanism. Inside the sandbox's network namespace there is no DNS, so `localhost` must come from `/etc/hosts` (`nsswitch`: `files dns`). The image's `/etc/hosts` is **0 bytes**: BuildKit bind-mounts it during the build, so even a `COPY hosts /etc/hosts` doesn't persist (tested). Docker writes its own at run time, which hid the problem in §4.1/§4.2. AgentCore evidently doesn't. The in-namespace relay listens dual-stack (`TCP6-LISTEN … ipv6only=0`, falling back to `TCP4-LISTEN`), so an IPv4 entry is enough.

**Fix 1.** Before every run (both modes), `sandbox.py` makes sure `/etc/hosts` maps `localhost` to a loopback address (`ensure_loopback_hosts`). If no such line exists, it appends `127.0.0.1\tlocalhost` once, in place. If it can't, it refuses the run (`SandboxUnavailable`). `Sandbox.hosts_status` records `added` or `present`, and the probe's new first check, `net.localhost`, reports it. One system-level fix covers srt and the CLI's Bash sandbox.

**Root cause 2 — `cli.deny.webfetch`.** Not a fail-open. In 2b, `turns=4` and the denials were three `Bash` calls (`git push`, `gh`, `curl`); the model never called WebFetch. A tool-wide deny removes the tool from the list the CLI offers the model, so no `permission_denials` entry can appear, and the check only looked for one.

**Fix 2.** `cli_checks` runs `--output-format stream-json --verbose` and reads the `system/init` event's `tools`. `cli.deny.webfetch` and the new `cli.deny.websearch` pass when the tool is **not offered**, or is offered and denied. Defence in depth: `Sandbox.build_command` adds `--disallowedTools=WebFetch,WebSearch` (one token, because the option is variadic) straight after the binary on every `-p`/`--print` run. The probe and the S-190 agent go through it, so IC 2c measures policy and flag together; LOCAL-2-04 isolates the policy.

| ID | Check | Before (D-110 image) | After (fix round 2) | Detail |
| -- | ----- | -------------------- | ------------------- | ------ |
| LOCAL-2-01 | Reproduce 2b: `npm view left-pad version`, `pip download six` as fixer in srt with an **empty** `/etc/hosts` mounted | FAIL ×2 | PASS ×2 | before: `getaddrinfo EAI_AGAIN localhost` and pip `Failed to resolve 'localhost' ([Errno -3] Temporary failure in name resolution)`, matching 2b's strings. After: the wrapper added `127.0.0.1\tlocalhost`; `1.3.0`, `six-1.17.0` saved |
| LOCAL-2-02 | probe `net_checks` (real `Inner` + `Sandbox`), empty `/etc/hosts` | n/a | PASS ×9 | `net.localhost`: `etc_hosts=added addrs=['127.0.0.1']`. Link-local ×3: proxy `HTTP 403 blocked-by-allowlist`. `example.com`, `api.github.com`, `api.anthropic.com`: `Tunnel connection failed: 403 host is not on the allow list`. Raw TCP blocked ×6. Registries ×2 PASS |
| LOCAL-2-03 | Control: same image with Docker's own `/etc/hosts` | PASS (npm, pip; `curl example.com` → `CONNECT tunnel failed, response 403`) | PASS | why §4.1/§4.2 never saw it |
| LOCAL-2-04 | `claude -p` init tool list as fixer, fake key, repo settings allowing `WebFetch`/`WebSearch` and asking for bypass | managed policy: **22 tools, WebFetch/WebSearch absent**; same policy with the two denies removed: 24, both present | with the flag (`--disallowedTools=WebFetch,WebSearch` or the space form) and the denies removed: 22, both absent; production argv through `Sandbox.run`: 22, both absent | `permissionMode=default` (bypass refused). The run then stops at `authentication_failed`: the Bash-tool network path through the CLI's own sandbox needs the key and is **IC-only** |
| LOCAL-2-05 | `image-smoke.sh` | 41 | **44** PASS | new: image `/etc/hosts` is empty; `Sandbox().ensure_hosts()` on an empty, writable `/etc/hosts` gives `added`, then `present`, and fixer resolves `localhost` to `127.0.0.1`; the pinned CLI accepts `--disallowedTools=WebFetch,WebSearch` |

Re-probe 2c showed that fix 1 can't work on AgentCore: its `/etc/hosts` is read-only. Fix round 3 (§4.4) replaces it.

Note on 2b's `net.blocked.*` PASS ×6: every detail reads `Temporary failure in name resolution`. Those targets were blocked because the proxy host itself didn't resolve, not by the allow-list. The verdict was right (fail-closed), but the evidence was weak. With fix 1, a 2c PASS must show the proxy's 403, as LOCAL-2-02 does.

### 4.4 Fix round 3 (after re-probe 2c) — LOCAL, 2026-10-24

**Root cause.** On AgentCore `/etc/hosts` is empty **and read-only** ("Read-only file system", 2c). Fix 1 couldn't append, so `sandbox.py` failed closed on every sandboxed run (19 FAIL, all `SandboxUnavailable: sandbox cannot resolve localhost`). The proxy host can't be changed: srt 0.0.81 sets `http://…@localhost:<port>` with `--setenv` inside bwrap, and the CLI's Bash sandbox does the same.

**Fix 3 (D-111).** `localhost` resolves in the image, without `/etc/hosts` and without DNS:

- The Dockerfile installs `libnss-myhostname` and writes `hosts: files myhostname dns` to `/etc/nsswitch.conf`. A `grep -qx` fails the build if the line didn't take. Debian's postinst already writes that line; the explicit write pins it.
- `/etc/gai.conf` holds `precedence ::ffff:0:0/96 100`. Without it, nss-myhostname makes `getaddrinfo("localhost")` return `::1` before `127.0.0.1` (measured: `['::1', …, '127.0.0.1', …]` without, `['127.0.0.1', …, '::1', …]` with). srt's in-namespace bridge may listen on IPv4 only.
- `sandbox.py` no longer writes anything. `check_localhost_resolution` returns `hosts` when `/etc/hosts` maps `localhost` to loopback. It returns `nss` when the nsswitch `hosts:` line lists `myhostname` before `dns` (with no `[…=return]` action ahead of it) and `libnss_myhostname.so.2` is in a lib dir. Otherwise it raises `SandboxUnavailable` with both reasons. `Sandbox.localhost_via` records `hosts`, `nss` or `none`.
- `net.localhost` reports `via=…`, the sandbox's `/etc/hosts` lines and its nsswitch `hosts:` line. It now passes only when every address is loopback **and `127.0.0.1` is first**.

Note: `getent hosts localhost` prints `::1` even with gai.conf, because it asks for `AF_INET6` first. The smoke script checks `getent ahostsv4` and the `getaddrinfo` order instead, which is what Python, Node and pip use.

Profile for LOCAL-3-02: the §4.3 profile, plus an empty, **read-only** `/etc/hosts` bind-mounted (`--mount type=bind,…,dst=/etc/hosts,readonly`) to emulate AgentCore.

| ID | Check | Before (fix round 2 image) | After (fix round 3) | Detail |
| -- | ----- | -------------------------- | ------------------- | ------ |
| LOCAL-3-01 | Append to an empty, read-only `/etc/hosts` | `SandboxUnavailable` on 2c | n/a: nothing is written | locally, the read-only mount gives the same `Read-only file system` on a write |
| LOCAL-3-02 | `Sandbox().run` through `srt` as fixer, empty read-only `/etc/hosts`: `probe_inner resolve localhost`, `npm view left-pad version`, `pip download six`, `net example.com` | FAIL (refused) | PASS ×4 | `localhost_via=nss`; `addrs=['127.0.0.1', '::1']`, `hosts=[]`, `nsswitch='files myhostname dns'`; npm `1.3.0`; pip saved `six-1.17.0`; example.com `HTTP 403 blocked-by-allowlist`, TCP blocked |
| LOCAL-3-03 | `image-smoke.sh` | 44 | **47** PASS | new: nsswitch `files myhostname dns`; gai.conf precedence line; with the read-only mount: `getent ahostsv4 localhost` = `127.0.0.1`, `Sandbox().check_localhost()` = `nss` with `/etc/hosts` left at 0 bytes, fixer's `getaddrinfo` gives `127.0.0.1` first. Replaced: the round-2 append check |
| LOCAL-3-04 | pytest (unit + component) | 518 | **543** PASS | `TestLocalhostResolution`, `TestLocalhostCheck`, `TestResolve`, `test_image_localhost.py` |

Open for 2d: whether AgentCore keeps the image's `/etc/nsswitch.conf` and `/etc/gai.conf` (it replaces `/etc/hosts`; nothing so far shows it touches the others). `net.localhost`'s detail answers it: `via=nss` and `nsswitch='files myhostname dns'`. If 2d fails, the fallback is to run srt in a private mount namespace with its own `/etc/hosts` (D-111).

## 5. IC results (deployed runtime)

Run by `infra-engineer` with `ALLOW_PROBE=1` (task 3.5) and the payload `{"run_id": …, "__probe": true, …}` (procedure: `docs/runbooks/bug-fix-agent.md`, "Run the sandbox probe"). One row per `run_event`.

### 5.1 Probe run 1 (2026-10-24, runtime v2, D-109 image) — FAIL

Raw evidence: `infra/changes/20261024-bug-fix-spike-probe/backup/probe-run-1.sse` (leak scan 0 hits); summary in that change record's `result.md`, step 2.

- **10 PASS / 22 FAIL.** All 22 failures had the same cause. AgentCore runs the container with **`no_new_privs` set**, so `sudo` (setuid) refused to run: "The 'no new privileges' flag is set, which prevents sudo from running as root". Nothing behind the wrapper → fixer switch could be exercised: sandbox start, network, `/proc`, env, policy, secrets, `claude -p` and the PAT scan.
- `cli.version` read `claude --version=''`. It ran through the same failing `sudo`, and the old check didn't report stderr. It now does.
- PASS:
  - `sandbox.available.script`, `sandbox.available.cli`;
  - `sudo.wrapper.root` (wrapper `sudo -n -u root true` rc=1);
  - `board.disabled_without_pat`;
  - **all board checks**: `board.detect` (#5 "Dev-tasks" linked to `llipe/dev-tasks`), `board.add_idempotent` (issue #324, same item id twice, not pre-existing), `board.status.in_progress` / `in_review` / `ready` (each set and read back), `board.cleanup` (card deleted, issue `llipe/dev-tasks#324` closed, both confirmed afterwards).
- Versions: Claude Code 2.1.309, sandbox-runtime 0.0.81.
- **Consequence:** D-110, a root wrapper with a `setpriv` drop. The board result (D-105, AC7) stands. The board path doesn't depend on the uid switch, so the re-probe repeats it only as a regression check.

### 5.2 Re-probes 2b (runtime v3, D-110 image), 2c (fix round 2) and 2d (fix round 3)

Raw evidence for 2b: `infra/changes/20261024-bug-fix-spike-probe/backup/probe-run-2.sse` (leak scan 0); summary in `result.md`, row 2b. **2b: 34 PASS / 3 FAIL.**

Raw evidence for 2c (runtime v4): `backup/probe-run-3.sse` (leak scan 0); `result.md`, row 2c. **2c: 18 PASS / 19 FAIL.** Every FAIL is `SandboxUnavailable: sandbox cannot resolve localhost`: AgentCore's `/etc/hosts` is empty and read-only, so fix round 2 couldn't append and every sandboxed run was refused before it started. Checks that don't use the sandbox passed. 

Raw evidence for 2d (runtime v5, image `…5b24b169…`, 2026-10-24T15:40:11Z–15:40:53Z): `backup/probe-run-4.sse` (leak scan 0); `result.md`, row 2d. **2d: 39 PASS / 0 FAIL.** `net.localhost`: `via=nss addrs=['127.0.0.1', '::1'] hosts=[] nsswitch='files myhostname dns'`, so AgentCore keeps the image's nsswitch and gai.conf. The `net.blocked.*` passes now carry the proxy's 403 (strong evidence, unlike 2b). Versions on the runtime: Claude Code 2.1.309, sandbox-runtime 0.0.81.

| Check | Spec / test | Run 1 (D-109) | Re-probe 2b | Re-probe 2c | Re-probe 2d | Detail (2b) |
| ----- | ----------- | ------------- | ----------- | ----------- | ----------- | ----------- |
| `setpriv.wrapper.root`, `setpriv.drop.uid`, `setpriv.drop.sandbox` | 3.17, D-110 | n/a (new) | PASS ×3 | PASS, PASS, FAIL | PASS ×3 | wrapper uid 0, `CapEff=a82425fb`, `NoNewPrivs=1`; drop: uid/gid 10002 ×4, caps 0, `NoNewPrivs=1`; in srt `Seccomp=2` |
| `userns.available` | 3.17, D-110, §12 | n/a (new) | **PASS** | PASS | PASS | fixer and root: `bwrap rc=0`, `unshare rc=0`, `max_user_namespaces=32059`. **AgentCore allows user namespaces under `no_new_privs`;** no CLI-runtime fallback needed |
| `noescalate.fixer.uid`, `noescalate.fixer.sandbox`, `noescalate.no_sudo` | 3.17, D-110, SC-IC-03 | n/a (new) | PASS ×3 | PASS, FAIL, PASS | PASS ×3 | `setuid(0)=EPERM` (`EINVAL` in srt), `su rc=1`, `setpriv --reuid=0 rc=1`; no sudo |
| `sudo.fixer.uid`, `sudo.fixer.sandbox`, `sudo.wrapper.root` | 3.16, D-109 (retired) | FAIL, FAIL, PASS | n/a (replaced) | n/a | n/a | |
| `sandbox.available.script`, `sandbox.available.cli`, `sandbox.starts` | §12 "bwrap starts on AgentCore ARM64" | PASS, PASS, FAIL (`no_new_privs`) | PASS ×3 | PASS, PASS, FAIL | PASS ×3 | `ok exit=0` |
| `net.localhost` | fix rounds 2, 3 | n/a | n/a (new) | FAIL | **PASS** (`via=nss`, `127.0.0.1` first) | 2c: `SandboxUnavailable` (`/etc/hosts` read-only). 2d must show `via=nss`, `addrs` with `127.0.0.1` first, `nsswitch='files myhostname dns'` |
| `net.blocked.169.254.170.2`, `.169.254.169.254`, `.169.254.170.23` | 3.6, SC-IC-01 | FAIL (`no_new_privs`) | PASS ×3 (weak) | FAIL ×3 | PASS ×3 (proxy `403 blocked-by-allowlist`, TCP blocked) | `Temporary failure in name resolution`: blocked because the proxy host didn't resolve (§4.3 note) |
| `net.blocked.example.com`, `.api.github.com`, `.api.anthropic.com` | 3.6, SC-IC-02 | FAIL (`no_new_privs`) | PASS ×3 (weak) | FAIL ×3 | PASS ×3 (`Tunnel connection failed: 403 host is not on the allow list`, TCP blocked) | same; 2c must show the proxy's 403 |
| `net.reachable.registry.npmjs.org` | 3.6, SC-IC-02 | FAIL (`no_new_privs`) | **FAIL** | FAIL | **PASS** (`1.3.0`) | `getaddrinfo EAI_AGAIN localhost`: root cause 1, fixed (§4.3) |
| `net.reachable.pypi.org` | 3.6, SC-IC-02 | FAIL (`no_new_privs`) | **FAIL** | FAIL | **PASS** (`six-1.17.0` saved) | `Temporary failure in name resolution`: root cause 1, fixed |
| `proc.wrapper.sandbox`, `proc.wrapper.uid` | 3.7, 3.17, SC-IC-03 | FAIL (`no_new_privs`) | PASS ×2 | FAIL, PASS | PASS ×2 | wrapper is pid 1; `environ` and `mem` `EACCES` from both; `cmdline` readable by design |
| `env.fixer.sandbox`, `env.fixer.uid` | 3.7, SC-IC-03 | FAIL (`no_new_privs`) | PASS ×2 | FAIL, PASS | PASS ×2 | uid: `CI HOME LANG PATH`; srt adds its proxy variables only |
| `policy.tamper`, `secrets.dir.sandbox`, `secrets.dir.uid` | SC-IC-05 (part) | FAIL (`no_new_privs`) | PASS ×3 | FAIL, FAIL, PASS | PASS ×3 | write `EACCES`; canary `ENOENT` (srt) / `EACCES` (uid) |
| `cli.version` | 3.9 | FAIL (`''`) | PASS | FAIL | PASS | `2.1.309 (Claude Code)` = pin |
| `cli.deny.git_push` (denial **and** no ref on the bare remote) | 3.8, SC-IC-04 | FAIL (`no_new_privs`) | PASS | FAIL (`cli`) | PASS (`denied=True remote_refs=0`) | `denied=True remote_refs=0` |
| `cli.deny.webfetch` | 3.8, SC-IC-04 | FAIL (`no_new_privs`) | **FAIL (probe misread)** | FAIL (`cli`) | **PASS** (`offered=False`, 22 tools) | `denied=False turns=4 denials=[Bash×3]`: the tool was never offered (root cause 2, §4.3); 2c checks `offered=False` |
| `cli.deny.websearch` | 3.8, SC-IC-04 | n/a | n/a (new) | FAIL (`cli`) | **PASS** (`offered=False`) | |
| `board.detect` | 3.15 (1), SC-IC-11 | PASS | PASS | PASS | PASS | #5 "Dev-tasks" linked to `llipe/dev-tasks` |
| `board.add_idempotent` | 3.15 (2), SC-IC-11 | PASS | PASS | PASS | PASS | issue #324, same item id twice, not pre-existing |
| `board.status.in_progress`, `.in_review`, `.ready` | 3.15 (3), SC-IC-11 | PASS ×3 | PASS ×3 | PASS ×3 | PASS ×3 | set and read back |
| `board.pat_absent.sandbox`, `board.pat_absent.uid` | 3.15 (4), SC-IC-13 | FAIL (`no_new_privs`) | PASS ×2 | FAIL, PASS | PASS ×2 (`files_scanned=471`) | `matches=0 files_scanned=468` |
| `board.disabled_without_pat` | 3.15 (5), SC-IC-14 | PASS | PASS | PASS | PASS | `reason=no_token_secret_id` |
| `board.cleanup` (card deleted, probe issue closed) | 3.15, SC-IC-12 | PASS | PASS | PASS | PASS (#324 closed, card deleted) | card deleted; `llipe/dev-tasks#324` closed |

## 6. Verdict

Run 1: **FAIL** on sandbox and isolation (`no_new_privs` blocks `sudo`, §5.1) and **PASS** on the board. Re-probe 2b: **FAIL** on `net.reachable.*` (root cause 1) and `cli.deny.webfetch` (root cause 2, a probe misread); everything else PASS. Re-probe 2c: **FAIL** on every sandboxed check (read-only `/etc/hosts`, §4.4); every non-sandbox check PASS. Re-probe 2d: **39 PASS / 0 FAIL.**

**Final verdict (task 3.9): PASS.** Every check under the sandbox exit rule passes on the deployed runtime (AgentCore, ARM64): `setpriv.*`, `sandbox.starts`, `userns.available`, `net.*`, `proc.wrapper.*`, `noescalate.*` and `cli.deny.*`. The board checks pass too, so `BOARD_UPDATES_ENABLED` stays `1`. **Wave B (#373–#377) is unblocked by this spike.** The design that passed is D-110 (root wrapper, `setpriv` drop to `fixer`) plus D-111 (`localhost` via image NSS). Residual, not part of the exit rule: open question 3 (§7).

- **Sandbox exit rule (spec §12, AC8):** any FAIL among `setpriv.*`, `sandbox.starts`, `userns.available`, `net.*`, `proc.wrapper.*`, `noescalate.*` or `cli.deny.*` keeps Wave B (#373–#377) blocked and routes to `product-engineer` drift reconciliation.
- **Board (D-105, AC7):** a FAIL of `board.detect`, `board.add_idempotent` or `board.status.*` sets `BOARD_UPDATES_ENABLED=0` and routes to drift. It does not block Wave B.
- **User namespaces (D-110):** if `userns.available` FAILs on AgentCore, the fallback (a separate CLI runtime) is reopened through `product-engineer`.
- After the run: unset `ALLOW_PROBE` and redeploy (task 3.10). **Done:** runtime v6 (2026-10-24T15:53:10Z) has no `ALLOW_PROBE`, and a probe payload returns `PROBE_REFUSED` (`backup/probe-refused-v6.sse`). `test_agentcore_config.py` pins `agentcore.json` without it; its never-committed test passes again (544 passed).

## 7. Open questions for the IC run

1. ~~Does AgentCore allow unprivileged user namespaces (bwrap) under its `no_new_privs`?~~ **Answered by 2b: yes** (`userns.available` PASS, fixer and root).
2. ~~Does `sudo` work there?~~ **Answered by run 1: no.** AgentCore sets `no_new_privs` (§5.1), hence D-110. New question: does the runtime run the image as root with `CAP_SETUID`/`CAP_SETGID`? `setpriv.wrapper.root` answers it.
3. Does the CLI's own Bash sandbox start, and does `failIfUnavailable` refuse when it can't (LOCAL-07)? **Partly answered by 2d:** the CLI ran on AgentCore under the managed policy (`cli.deny.*` PASS: permission denies hold, WebFetch/WebSearch not offered), and srt, the library the CLI's Bash sandbox is built on, starts and filters there (`sandbox.starts`, `net.*`). **Still open:** a direct check that an *allowed* Bash tool call runs inside the CLI's sandbox (e.g. a Bash write outside the cwd must fail, a non-registry fetch must hit the proxy's 403). Not in the exit rule; tracked as a follow-up probe item before S-191 relies on it.
4. ~~Is the wrapper pid 1 in the AgentCore container?~~ **Answered by 2b: yes** (`proc.wrapper.*` reads `pid=1`).
5. ~~Is AgentCore's `/etc/hosts` empty, and is it writable by the root wrapper?~~ **Answered by 2c: empty and read-only.** Hence fix round 3 (§4.4, D-111). ~~Does AgentCore keep the image's `/etc/nsswitch.conf` and `/etc/gai.conf`?~~ **Answered by 2d: yes** (`via=nss`, `nsswitch='files myhostname dns'`, `127.0.0.1` first).
