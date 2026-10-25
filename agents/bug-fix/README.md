# bug-fix Agent

An AgentCore agent that answers a `/bug-fix` comment on a GitHub issue: it claims the issue, runs headless Claude Code (`claude -p`) against the target repo inside a sandbox, validates the change with the repo's own gates, and opens a Draft PR for a human to review.

PRD: [`docs/requirements/prd-bug-fix-agent.md`](../../docs/requirements/prd-bug-fix-agent.md). Spec: `workstream/specification-prd-bug-fix-agent.md`.

## Status

**Wave A orchestration (S-190).** `main.py` runs the steps `preflight` → `refuse` → `checkout` → `claim` (see "Run steps and outcomes"). With `FIX_LOOP_ENABLED=0`, the Wave A setting, a run that wins its claim disposes "fix loop not yet enabled" and ends `succeeded` / `needs_review`; the `fix` step runs only with `FIX_LOOP_ENABLED=1`, and this build has no fix runner yet (Wave B). It also has a probe mode for the S-182 spike, off unless the runtime sets `ALLOW_PROBE=1` (see "Probe mode"). A deployed run posts a claim comment and a diagnosis on the issue it is invoked for, and changes nothing else. The pieces and their stories:

| Piece | Story |
| ----- | ----- |
| Runtime, role, secrets, panel invoke policy | S-181 (`infra-engineer`) |
| Sandbox spike; pins the managed-settings key names | S-182 |
| `agents` seed row and typed params (`params.py`) | S-184 |
| Markers, neutralizer, comments and reactions, idempotent disposition, SIGTERM disposition hook (`markers.py`, `neutralize.py`, `issues.py`, `disposition.py`) | S-186 |
| Shared GitHub client with the retry policy, token permissions, issue facts and linked PRs, refusal checks and the marked reply (`github_client.py`, `refusal.py`) | S-185 |
| Claim with the post-claim race check, `PANEL_BASE_URL` run link (`claim.py`) | S-188 |
| Checkout, repo gate, toolchain and gate runner (`safe_git.py`, `toolchain.py`, `checkout.py`, `gates.py`) | S-189 |
| Orchestration, outcome mapping, the one run-link validator (`main.py`, `outcomes.py`, `run_link.py`) | S-190 |
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
    ├── main.py                    # AgentCore entrypoint: steps, ownership-gated finally path, probe hook (S-190)
    ├── outcomes.py                # spec §8.9 outcome mapping: RunResult, closed code sets, breaker flag (S-190)
    ├── run_link.py                # the one strict run-link validator; RunLink from the panel origin (S-190)
    ├── config.py                  # typed env config (ConfigError); run link from PANEL_BASE_URL; FIX_LOOP_ENABLED
    ├── params.py                  # typed run params: schema bounds, seed-equal defaults (S-184)
    ├── markers.py                 # build, parse, trust-check comment markers; the one open-claim rule (S-186, DF-33)
    ├── neutralize.py              # model-text neutralizer: closing refs, @mentions (S-186)
    ├── github_client.py           # shared GitHub REST/GraphQL client: retries, typed errors, Link header (S-185)
    ├── issues.py                  # issue facts, linked PRs (S-185); comments and reactions (S-186); App token
    ├── refusal.py                 # preflight, refusal checks, marked refusal reply (S-185)
    ├── disposition.py             # diagnosis comment + 😕, once per run, after ownership (S-186)
    ├── claim.py                   # claim comment + 👀, post-claim race check, ownership gate (S-188)
    ├── safe_git.py                # the wrapper's only git: hardened, own clone, trees in/out as fixer (S-189)
    ├── toolchain.py               # copied from dependency-update + extended: stack, gate names, repo gate (S-189)
    ├── checkout.py                # clone, repo gate, frozen install, base gates, base restore (S-189)
    ├── gates.py                   # four gates + audit in the script sandbox, scrubbed tails (S-189)
    ├── sandbox.py                 # starts fixer processes: setpriv drop, env, sandbox, timeout
    ├── fixer_exec.py              # runs as fixer after setpriv; rebuilds the env, refuses root
    ├── probe.py                   # S-182 spike checks (probe mode)
    ├── probe_inner.py             # the probe's fixer-side helper (stdlib only)
    ├── agent_reporter.py          # copied: runs / run_steps / run_events reporting
    ├── heartbeat.py               # copied: stream keep-alive
    ├── signal_backstop.py         # copied + extended: SIGTERM disposition (10 s budget), terminal report
    ├── scrubber.py                # copied + extended: secret redaction
    ├── credentials.py             # copied + extended: Supabase key, App token + App id + permissions, fetch_secret_string
    ├── scripts/image-smoke.sh     # image assertions
    └── tests/{unit,component,fixtures/{contract,repos}}/   # contract: params_schema.json (spec §5.2), payloads, marker goldens; repos: S-189 fixture repos
```

Copied modules follow the sibling convention (copy, don't share; D-03). Each starts with a header naming its source path in `agents/security-analyst/app/securityAnalyst/` and the source commit. `toolchain.py` is the exception to the source agent: it is copied from `agents/dependency-update/app/dependencyUpdate/toolchain.py`, with the same kind of header.

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
| `PANEL_BASE_URL` | no | `https://dt-agent-fleet-panel.fly.dev`, a bare `https` origin. `Config.run_link(run_id)` returns a `run_link.RunLink`, `<origin>/runs/<run_id>`, the run link in agent comments. Absent: comments name the run id instead. Anything but an `https` origin with no userinfo, path, query, fragment, whitespace or control character is a config error (S-188, S-190). |
| `FIX_LOOP_ENABLED` | no | `0` in Wave A. `1` adds the `fix` step after the claim; absent or `0` means a won claim disposes "fix loop not yet enabled". Any other value is a config error (S-190). |

`config.load_config()` raises `ConfigError(variable, reason)` for a missing, blank or invalid required variable. The message names the variable, never its value. The entrypoint maps it to `failed` / `CONFIG_INVALID`.

Lifecycle: `maxLifetime` 3600 s, `idleRuntimeSessionTimeout` 900 s. `config.MAX_LIFETIME` and `config.IDLE_SESSION_TIMEOUT` must match, and the seed's `max_runtime_seconds` (S-184) must equal `maxLifetime`. Unit tests pin all three (`test_agentcore_config.py` reads the seed migration and `supabase/seed.sql`).

## Params (S-184, spec §5.2 v2.0)

The `agents` row is seeded by `supabase/migrations/20261024130000_seed_bug_fix_agent.sql` and mirrored in `supabase/seed.sql`. Its `params_schema` has `additionalProperties: false`, and `issue_number` is the only required key (D-93). The webhook rule maps `issue.number` → `issue_number` and `comment.id` → `trigger_comment_id` (D-88).

| Key | Type and bounds | Default |
| --- | --------------- | ------- |
| `issue_number` | integer ≥ 1, **required** | none |
| `trigger_comment_id` | integer ≥ 1 | none |
| `project` | `owner/number`, `^[A-Za-z0-9-]{1,39}/[1-9][0-9]{0,6}$` | none (board auto-detect, D-102) |
| `status_in_progress` / `status_in_review` / `status_ready` | string, 1–100 characters | `In progress` / `In review` / `Ready` |
| `max_turns` | integer 5–100 | 40 |
| `cli_timeout_minutes` | integer 5–45 | 30 |
| `run_budget_minutes` | integer 10–55 | 55 |
| `max_code_files` | integer 1–50 | 10 |
| `max_code_lines` | integer 10–2000 | 400 |

`params.parse_params()` enforces the same types and bounds, because a direct invoke bypasses the panel's Ajv (D-82). It applies the defaults itself, because the panel validates with `useDefaults: false`, so a webhook fire sends only `issue_number` and `trigger_comment_id`. A missing `issue_number` raises `MissingRequiredParam`; a type or bounds violation raises `InvalidParam`. Both name the key and never the value. Unknown keys are ignored. `tests/fixtures/contract/params_schema.json` is the spec copy: the panel's L2.5 test proves the seed equals it, and this package's tests prove `params.DEFAULTS` and the bounds equal it.

## Markers and disposition (S-186, spec §8.3, §8.8)

Every comment the agent posts starts with a hidden marker block, one line per run: `<!-- agent-fleet:bug-fix:<kind> run_id=<uuid> -->`, where `<kind>` is `claim`, `disposition` or `pr`, or `<!-- agent-fleet:bug-fix:refusal run_id=<uuid> reason=<code> -->` (D-104).

- `markers.parse_block()` reads only the leading block from line 1 (D-80). A line must match the grammar exactly: a lowercase UUID, a known kind and a known refusal reason. A CRLF line end is accepted.
- `markers.is_trusted()` trusts a comment only when `performed_via_github_app.id` equals the fleet App id (`TokenContext.app_id`, from the `github_installations` row) and `user.type == "Bot"`. The login is never consulted (D-53).
- `markers.open_claims()` is the one definition of an open claim (DF-33): a trusted claim with no trusted `pr`, `disposition` or `refusal` marker for the same run, ordered by integer comment id. A refusal never opens a claim; it closes only its own run's. Refusal (d) and the post-claim race check both use it, then drop claims whose run is terminal in `v_runs.effective_status` (`refusal.active_claim_runs()`).
- `neutralize.neutralize()` turns a closing keyword plus a reference into `(ref <reference>)` and puts U+200B after every `@` (D-65).
- `issues.IssuesClient` posts, lists and deletes comments (`delete_comment()`: idempotent, a 404 means already gone) and adds the `eyes`, `rocket` and `confused` reactions with the App installation token. A missing `trigger_comment_id` skips the reaction with no call, and a reaction 4xx is logged, not raised. Bodies are cut to 65,536 UTF-16 units.
- `disposition.Disposer` posts the diagnosis comment (why the run stopped, what was tried, the diffstat when a cap was hit), then 😕, then the board hook. It writes no label or assignee and never edits the issue (D-93). It does nothing before `confirm_ownership()` (D-81), and nothing when a trusted `disposition` marker for the run already exists or a disposition is already in flight in the process. The one exception is the SIGTERM backstop: a disposition the dying process can't finish (for example the `finally` path suspended under the signal handler) is taken over. An owner that hasn't started posting is preempted so it can't post as well, and a post that may have landed is re-checked against the trusted marker first. Model text is scrubbed, neutralized, and has `<!--` defused (D-85).
- `signal_backstop.install_termination_backstop(..., get_disposition=...)` runs that disposition on SIGTERM with a 10-second budget before `fail()`, and the `fail()` detail says what it did (posted, already posted, skipped, failed or abandoned). `main.py` installs it with the run's `Disposer`, which returns nothing before confirmed ownership (S-190).
- **Run link** (S-190). Every comment builder (`claim.build_claim_body`, `refusal.build_reply`, `disposition.build_body`) puts the run link through `run_link.run_ref()`, the one strict validator. It accepts only a `RunLink`, which only the configured panel origin builds, for this comment's run: `https`, no userinfo, the panel host, the path `/runs/<run_id>`, no query or fragment, printable ASCII, no `javascript:`. Anything else, a plain string included, falls back to the run id in backticks. `config.load_config` checks `PANEL_BASE_URL` with the same module.

## Claim and race check (S-188, spec §8.6)

`claim.Claimer.claim()` (or `claim.claim_issue()`) is the `claim` step, run after checkout. `main.wire_claim()` builds it with the run's real `Disposer` and `Config.run_link(...)` (S-190).

1. **Claim.** Post the claim comment (the `claim` marker, then `🔧 Bug-fix run <run link> is working on this issue.`), then 👀 on `trigger_comment_id` when present. A manual invoke has none, so no reaction is made. A reaction fault is a `run_event`, never fatal. No label or assignee is written (D-93).
2. **Post-check** (D-54). List the comments; `claim.race_winner()` finds the earliest open claim (DF-33) with a lower comment id than this run's whose run is `queued` or `running`. The integer comment id decides, so same-second claims still have one winner. A missing `v_runs` row counts as finished and an unknown status fails closed, both reported as `run_event` warnings.
3. **Lost race.** Delete only this run's own comment and end `succeeded`/`not_applicable`, `result.reason = active_run`, naming the winning run. No board call and no disposition. The loser's 👀 stays, as spec §8.6 is written (DF-32). A 404 on the `DELETE` is logged as already gone; any other `DELETE` fault ends `failed` with its D-67 code.
4. **Ownership gate** (D-81). Only a won race calls `Disposer.confirm_ownership()`, then the `board_in_progress` hook (best effort). A post-check fault (`SUPABASE_UNAVAILABLE`, or a GitHub fault on the listing) keeps the claim comment, confirms nothing and ends `failed`, so neither the `finally` path nor the SIGTERM backstop disposes.

A crashed run leaves its claim comment and 👀. Refusal (d) blocks a new `/bug-fix` only while that run is non-terminal; once the reaper marks it `timed_out`, a new run proceeds (AC-24, D-94).

## Checkout, repo gate and gates (S-189, spec §8.7)

`checkout.run_checkout()` is the `checkout` step. It runs after the refusal checks and **before** the claim, so a repo the agent can't work in gets only a refusal reply, and no issue changes before the repo gate passes (FR-5).

The link-protection sysctls are recorded by `checkout.record_link_protection()`, which the run's `preflight` step calls (S-190): `fs.protected_hardlinks` and `fs.protected_symlinks` are read from `/proc/sys/fs` and logged as a `run_event` (`info` when both are 1, else `warn`). It never fails the run: local Docker may differ, and the AgentCore value is checked by probe #446. The work-tree walk (step 6) doesn't rely on it.

1. **Clone** (D-62). `safe_git.clone()` shallow-clones `base_branch` of `https://github.com/<owner>/<repo>.git` into the wrapper clone `/work/wrapper/repo` (mode 0700, under root-owned `/work/wrapper`, D-110), with `--no-checkout` and strict `transfer`/`fetch`/`receive.fsckObjects` (so git refuses trees with `.git`, `..` or duplicate entries; only `zeroPaddedFilemode` is ignored), and records the base SHA. `info/exclude` lists only `node_modules/`, `.venv/`, `.pnpm-store/` and `__pycache__/` (D-83). The installation token is an `http.https://github.com/.extraheader` passed through `GIT_CONFIG_*` env variables, never argv or `.git/config`, and redirects are off. A clone failure, or a hostile branch name, is `failed`/`CLONE_FAILED`.
2. **Materialize.** The base tree goes into the empty `/work/repo` as plain files. `safe_git` builds a tar from raw blobs (`ls-tree` and `cat-file --batch`; not `git archive`, which would apply the repo's `export-ignore`/`export-subst`), and `tar -x` runs as `fixer` through the `setpriv` drop. Every path is checked first: no `..`, no absolute path, and no `.git` component in any case or lookalike (`.git.`, `git~1`, HFS+ zero-width characters). A tree over 100,000 entries or 2 GiB is refused before anything streams (`safe_git.MAX_TAR_ENTRIES`, `MAX_TAR_BYTES`). Both end `failed`/`CLONE_FAILED`. `/work/repo` has no `.git`; `fixer` may create one, and the wrapper never reads it.
3. **Repo gate** (FR-6, D-06, D-19, D-112). `toolchain.check_repo_gate()` reads the **base commit in the wrapper clone** (regular blobs only, never the work tree). A root `package.json` means JS/TS, even next to a makefile; it needs scripts `test`, `lint`, `format:check`, `typecheck` and a lockfile. The manager is the `packageManager` field, which must name pnpm or npm and have its own lockfile (`pnpm-lock.yaml` or `package-lock.json`; else the `lockfile` miss); without the field it is `pnpm-lock.yaml`, then `package-lock.json`. yarn and bun (the field, or only a `yarn.lock`, `bun.lockb` or `bun.lock`) are the `supported package manager (pnpm or npm)` miss. Otherwise a root makefile means Python: the first of `GNUmakefile`, `makefile`, `Makefile` that exists, GNU make's own order, and the others are ignored as make ignores them. It needs targets `test`, `lint`, `format-check`, `typecheck` and `install`. The makefile is parsed statically (`include` not followed; a comment, `.PHONY` or a prerequisite is not a target; `test::` is). Both need `.claude/agents/developer.md`. A miss is refusal `repo_gate`: the marked reply names the first item through a fixed phrase per item (`refusal.REPO_GATE_PHRASES`; for Python's `install`, "missing install target (the Makefile target `install`)", D-112), `result.summary` names every miss ("missing script typecheck", "missing target format-check", "missing install target"), and the run ends `succeeded`/`not_applicable` with no claim, reaction or board call.
4. **Install** in the script sandbox as `fixer`: `pnpm install --frozen-lockfile`, `npm ci`, or `make install` (D-63, D-112). A lockfile mismatch fails, and the lockfile is never rewritten. Any failure, including an unavailable sandbox, is `failed`/`INSTALL_FAILED`.
5. **Base gates** (D-14). `gates.run_gates()` runs `test`, `lint`, `format`, `typecheck`, then `audit` (skipped when the repo has none), each as `<pm> run <script>` or `make <target>` in `Mode.SCRIPT`. Each result is `{pass, exit_code, tail}` plus the command and outcome; the tail is stdout then stderr, scrubbed before it is cut to 4,000 characters. Each gate is a `run_event`, and the report is kept for the PR body. Base results never block.
6. **Restore the base** (D-63). `checkout.restore_base()` captures `/work/repo`. Before root git reads it, `safe_git.check_work_tree()` walks it with `lstat` (no link followed) and refuses any regular file with more than one link, and any FIFO, socket or device node, outside `node_modules/`, `.venv/`, `.pnpm-store/` and `__pycache__/` (git never descends there, and pnpm/uv hardlink into them). A hardlink could put a file `fixer` can't read into the captured change; a FIFO `.gitignore` would block root `git add`. The refusal is fixed text with counts, never a path, and ends `failed`/`CLONE_FAILED`. The capture is (`git --git-dir=/work/wrapper/repo/.git --work-tree=/work/repo add -A` after a stat-free `read-tree`, so every file is re-hashed), and every path that differs from base is put back as `fixer` (`rm -rf`, then the base version through `tar -x`). It repeats until the tree equals base (an edited `.gitignore` can hide a new file until it is restored), and logs "base runs modified N tracked files; restored". Ignored paths such as `node_modules/` are left as they are.

`safe_git.py` is the only module that runs git (a unit test scans the others). Every call has `GIT_CONFIG_NOSYSTEM=1`, `GIT_CONFIG_GLOBAL=/dev/null`, `-c core.hooksPath=/dev/null -c core.fsmonitor=false`, `--attr-source=<empty tree>` (no `.gitattributes` from the work tree, so no filter driver, textconv or eol conversion) and an explicit `--git-dir` on the wrapper clone, with an env built from scratch. It never sets `safe.directory` and never uses `-C`, `GIT_DIR` or a `cwd` in the work tree. Symlinks are captured as links (mode 120000), never followed; untracked files are included (DF-01); an embedded repository is a gitlink.

## Refusal checks (S-185, spec §8.2)

`refusal.run_preflight()` is the `preflight` step and `refusal.run_refusals()` the `refuse` step; `refusal.run_refusal_checks()` runs both. They make no claim and no board call. `main.py` gives the issues client a token source that refreshes a stale token (S-190).

1. **Preflight.** A credential failure ends `failed`/`CREDENTIALS_UNAVAILABLE`, a failed token mint included (a non-2xx is a typed `CredentialError`, never a raw `HTTPError`). `refresh_if_stale` re-mints with the new token's own `permissions` and raises `PermissionMissing` (`GITHUB_PERMISSION_MISSING`) if it lost `issues: write`. A token without `issues: write` in its minted `permissions` ends `failed`/`GITHUB_PERMISSION_MISSING` with no GitHub call (D-58). A `params.py` error is refusal `invalid_params`; when there is no usable `issue_number`, nothing is written (D-82).
2. **Checks**, in order, first match wins, each later check run only if needed (D-92): `pull_request` (the `GET /issues/{n}` payload has `pull_request`), `closed`, `linked_pr` (an open PR from GraphQL `closedByPullRequestsReferences`, or an open PR whose head starts with `issue/<N>-`, forks included; D-55), and `active_run` (a trusted claim with no trusted `pr`, `disposition` or `refusal` marker for its run, whose run is `queued` or `running` in `v_runs.effective_status`). A claim whose run has no `v_runs` row counts as terminal, with a `run_event` warning; an `effective_status` outside the known active and terminal sets ends `SUPABASE_UNAVAILABLE`, also with a warning. A closing PR in another repository is named `owner/repo#M`; a same-repo PR is preferred, then the lowest `(owner/repo, number)`. A 404 on the issue is `invalid_params` with no write. Labels and the commenter are never read (D-90, D-91).
3. **Reply** (D-104). One comment: the `refusal` marker, one fixed sentence per code, and `Run: <link>`. Its only variable parts (the issue number, `#M` or `owner/repo#M`, a `repo_gate` item, an `invalid_params` key) come from closed sets or GitHub's name grammar. No reaction. The run ends `succeeded`/`not_applicable` with `result.reason`. A failed reply post is a `run_event`; the outcome doesn't change.

Faults are never read as "no match" (D-67): exhausted GitHub retries, a spent wait budget, or a page cap reached with pages left (100 REST pages, 20 GraphQL pages) end `GITHUB_UNAVAILABLE`; a 3xx, another 4xx or a permanent GraphQL error `GITHUB_REQUEST_REJECTED`; a `v_runs` read failure or unknown status `SUPABASE_UNAVAILABLE`. All with no write.

`github_client.GitHubClient` is the shared transport. A request is tried at most 3 times. Reads (`GET`, GraphQL queries) retry transport errors, 5xx and rate limits with backoff (1 s, 2 s). Writes retry only rate limits, because GitHub may already have applied a write that answered 5xx. The one exception is the race-loss withdrawal, the single-id `DELETE` of this run's own claim comment: it is retried on a 5xx or a transport error, because a repeat gets a 404, read as "already gone" (DF-188-02, D-67 amendment). `Retry-After` and `x-ratelimit-reset` are honoured up to 60 s, so GitHub's common secondary-limit `Retry-After: 60` is retried; a longer wait gives up at once. A secondary limit with no usable header waits 60 s, as GitHub advises. Every logical operation (a call, a paged list, a GraphQL query with its own `RATE_LIMITED` retries) runs against one monotonic deadline, 120 s unless the caller sets one with `GitHubClient.deadline()`. A wait that would pass it is not taken, and the call ends `GITHUB_UNAVAILABLE`. A GraphQL `errors[]` of transient types (`RATE_LIMITED`, `INTERNAL`, `SERVER_ERROR`, `TIMEOUT`, `SERVICE_UNAVAILABLE`, or untyped with a 5xx-like message) is retried like a 5xx; any other ends `GITHUB_REQUEST_REJECTED` at once. Redirects are never followed (`allow_redirects=False` on every GitHub and Supabase request); a redirected write is never reported as posted. A 404 is data where the caller says so. `next_link()` parses the real `Link` header itself, matching `rel` only as a whole parameter name. `issues.IssuesClient` is built on it.

## Run steps and outcomes (S-190, spec §4, §8.9)

`main.invoke()` validates the config and payload, reads the Supabase key, then runs `main.execute()` in a worker thread under `heartbeat.run_with_heartbeat()`, streaming heartbeat chunks so a long install or gate never idles the AgentCore stream. Each step is one `run_steps` row with `run_events` at its decisions:

1. `preflight`: the link-protection sysctls (above); the payload's `repository_org`, `repository_name` and `base_branch` (else `failed`/`INVALID_PAYLOAD`); the installation token and `issues: write` (D-58); the params (refusal `invalid_params`).
2. `refuse`: refusal checks (a)–(d) (D-92).
3. `checkout`: clone, repo gate (refusal `repo_gate`), install, base gates, base restore. Nothing on the issue changes before this step passes (FR-5).
4. `claim`: the claim, the race check and the ownership gate. With `FIX_LOOP_ENABLED=0`, a won claim then disposes "fix loop not yet enabled" (the diagnosis, and 😕 when `trigger_comment_id` is set).
5. `fix`: only with `FIX_LOOP_ENABLED=1`. It runs `Runtime.fix_runner`; this build has none, so the step disposes "the fix step is not available in this build".

Every terminal path is one `outcomes.RunResult` (spec §8.9):

| Path | Status / outcome | `error_code` |
| ---- | ---------------- | ------------ |
| Refusal `pull_request`, `closed`, `linked_pr`, `active_run`, `repo_gate`, `invalid_params` | `succeeded` / `not_applicable` | — |
| Lost race (own comment deleted, or already gone) | `succeeded` / `not_applicable`, reason `active_run` | — |
| Fix loop not yet enabled | `succeeded` / `needs_review`, reason `fix_loop_disabled` | — |
| Token without `issues: write`, at preflight or after a refresh | `failed` | `GITHUB_PERMISSION_MISSING` |
| Secrets or token mint | `failed` | `CREDENTIALS_UNAVAILABLE` |
| Clone / install | `failed` | `CLONE_FAILED` / `INSTALL_FAILED` |
| GitHub retries exhausted / request refused / `v_runs` read | `failed` | `GITHUB_UNAVAILABLE` / `GITHUB_REQUEST_REJECTED` / `SUPABASE_UNAVAILABLE` |
| Any other exception | `failed` (after the disposition, if ownership was confirmed) | `UNHANDLED_ERROR` |

- Only `failed` counts toward the breaker (D-20): `RunResult.counts_toward_breaker`.
- Every `needs_review` and `not_applicable` result has `result.summary` and `result.reason`; an empty one is rejected when the result is built. The agent never produces `no_findings`.
- **Ownership gate** (D-81). The `finally` path in `main.execute()` disposes after a fault only when the claim's post-check confirmed ownership, and only if no disposition was attempted yet. The SIGTERM backstop gets the run's `Disposer`, which returns nothing before confirmed ownership. A fault or SIGTERM during `checkout`, or before the post-check confirms, disposes nothing and keeps any claim comment.
- **Token refresh** (S-185 residual). The issues client takes its token from `main.TokenSource`, which calls `credentials.refresh_if_stale()` and maps its errors by `exc.error_code`: `PermissionMissing` → `GITHUB_PERMISSION_MISSING`, a mint failure → `CREDENTIALS_UNAVAILABLE`. A refreshed token is added to the scrubber. A refresh error that a best-effort call swallowed (the refusal reply) still fails the run.
- **Metrics** (FR-27): `runs.metrics` holds `issue_number`, `step_timings_ms` (integer milliseconds per step) and, after checkout, `gates_base` (`{gate: {pass, exit_code}}`).
- The reporter doesn't capture the standard `logging` stream (`capture_logging=False`): every `run_event` comes from a module's own scrubbed call. A reporter failure never changes the outcome or the terminal chunk.
- Wave A has no board client (`projects.py` is S-199), so no path makes a Projects call. Where the board look-up sits relative to the repo gate is DF-35, still open.

## Image

`Dockerfile`, built for `linux/arm64`:

- Python 3.13 (wrapper), Node 26 + pnpm 10.11.0, git, make, `bubblewrap`, `socat` and `ripgrep` (the Claude Code sandbox runtime on Linux), `util-linux` (`setpriv`, the drop to `fixer`), and `procps` (`kill` and `pkill` for the post-run sweep). No `sudo`: the build fails if it is present.
- `@anthropic-ai/claude-code` pinned by `ARG CLAUDE_CODE_VERSION`, and `@anthropic-ai/sandbox-runtime` (`srt`) pinned by `ARG SANDBOX_RUNTIME_VERSION`, both installed root-owned; `DISABLE_AUTOUPDATER=1`.
- Users: the wrapper (`main.py`) runs as **root**, the image's default user (D-110). `fixer` (uid/gid 10002, in no other group, private home) runs the CLI and repo scripts. There is no other runtime user.
- Directories: `/work/repo` and `/work/out` owned by `fixer`; `/work/wrapper` (the wrapper clone, `safe_git.py`) and `/work/secrets` `root:root` 0700.
- git ≥ 2.40 (`--attr-source`), `/usr/bin/tar` and `/usr/bin/rm`, all needed by `safe_git.py`; the build fails without them.
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
- **Sandbox.** Two modes, and no bare exec. `SCRIPT` (install, gates, tests, probe helpers) runs under `srt --settings /etc/bug-fix/srt-settings.json`: bwrap with no network namespace, a fresh pid namespace and `/proc`, and srt's filtering proxy limited to the same four registries as the managed policy. `CLI` runs only the pinned `claude` binary, which enforces its own Bash sandbox from the managed policy. (Nesting `claude` in `srt` would cut it off from the Anthropic API.) Every headless run (`-p`/`--print`) also gets `--disallowedTools=WebFetch,WebSearch`, on top of the managed deny.
- **`localhost` for the sandbox proxy (D-111).** srt and the CLI's Bash sandbox point their proxy variables at `localhost` (hard-coded), and the sandbox's network namespace has no DNS. The image's `/etc/hosts` is empty (BuildKit can't fill it), and on AgentCore it is also read-only (S-182 re-probe 2c). So the image resolves `localhost` through `libnss-myhostname` (`hosts: files myhostname dns`), and `/etc/gai.conf` puts `127.0.0.1` before `::1`. Before every run the wrapper checks, read-only, that `localhost` resolves through `/etc/hosts` or NSS (`check_localhost_resolution`; `Sandbox.localhost_via` is `hosts`, `nss` or `none`), and raises `SandboxUnavailable` if neither works. It never writes `/etc/hosts`. Without this, every registry fails with `getaddrinfo EAI_AGAIN localhost` (re-probe 2b).
- **Timeout.** SIGTERM at the wall-clock deadline. `setpriv` and `fixer_exec.py` exec, so the child pid is the runtime itself. If the child is still alive 15 s later, every `fixer` process is swept and the child gets SIGKILL. The timeout outcome is distinct from a non-zero exit (srt itself exits 0 after a relayed SIGTERM).
- **No survivors (D-62).** After every run the sweep kills every `fixer` process, daemons included, in two passes. First, `kill -9 -- -1` as `fixer`: one kernel pass over every process `fixer` may signal, which a fork loop can't outrun. Second, `pkill -KILL -u 10002` as root. Then zombies are reaped.
- A missing `setpriv`, `python3`, `fixer_exec.py`, `srt`, settings file or `claude` raises `SandboxUnavailable`.

### Managed Claude Code policy

`managed-settings.json` (spec §12, D-51 layer 2) takes precedence over a target repo's `.claude/`:

- Bash sandbox enabled, `allowUnsandboxedCommands: false`, `failIfUnavailable: true`, bypass-permissions mode disabled.
- Managed-only: `allowManagedPermissionRulesOnly` (repo, user and `--settings` permission rules are ignored, not just outranked), `sandbox.network.allowManagedDomainsOnly`, `allowManagedHooksOnly` and `allowManagedMcpServersOnly` (D-29).
- Network allow-list: exactly `registry.npmjs.org`, `registry.yarnpkg.com`, `pypi.org`, `files.pythonhosted.org`. No link-local, no GitHub, no wildcard.
- Deny: `Bash(git push:*)`, `Bash(gh:*)`, `Bash(curl:*)`, `Bash(wget:*)`, `WebFetch`, `WebSearch`, and Read/Edit of `/proc/**`, `/etc/claude-code/**` and `/work/secrets/**`.
  The bare `WebFetch`/`WebSearch` entries are tool-wide denies: the CLI removes those tools from the list it offers the model, so a run never records a denial for them. Keep them unscoped. A `WebFetch(domain:…)` rule would leave the tool offered.

Path rules use Claude Code's `//` prefix for an absolute path (`Read(//proc/**)`). A single leading `/` is resolved relative to the settings file, so `Read(/proc/**)` here would guard `/etc/claude-code/proc/**`.

**The key names are provisional until the S-182 IC run.** Phase 1 found every key above in the settings schema of the pinned CLI (2.1.309); the IC run on the deployed runtime confirms they take effect. See `workstream/spike-bug-fix-sandbox.md`. `tests/unit/test_managed_policy.py` pins them.

## Probe mode (S-182, D-70)

A top-level payload key `__probe: true` (the JSON boolean, outside `params`) runs the spike checks in `probe.py`, but only when the runtime sets `ALLOW_PROBE=1`. Without the flag the run fails with `PROBE_REFUSED` and no check runs. `params.__probe` and non-boolean values are ignored (the normal path runs). The panel can't send the key; `infra-engineer` invokes the runtime directly, and sets and unsets the flag (tasks 3.5 and 3.10). The procedure is in `docs/runbooks/bug-fix-agent.md`, section "Run the sandbox probe".

Each check is one `run_event` `{check, verdict: PASS|FAIL, detail}`, scrubbed, and the run ends `succeeded` / `not_applicable` with a JSON summary. Check groups:
- `setpriv.*`: the wrapper is root with `CAP_SETUID`/`CAP_SETGID`, and a dropped process has uid/gid 10002, no groups, no capabilities and `NoNewPrivs: 1`.
- `sandbox.*`: the sandbox runtime starts.
- `userns.available`: reported on its own. Can `fixer`'s `bwrap` create the user, pid and net namespaces under AgentCore's `no_new_privs`? The detail adds `unshare`, the sysctls and the same measurement as root.
- `net.*`: `net.localhost` first (srt's proxy host resolves to loopback in the sandbox, `127.0.0.1` first; the detail names the route, `via=hosts|nss|none`), then: credential and metadata endpoints and non-registry hosts are blocked; registries are reachable.
- `proc.*`, `env.*` and `noescalate.*`: as `fixer`, inside the sandbox and with the drop alone. `noescalate.*` covers `setuid(0)`, `su` and `setpriv --reuid=0`, and checks that no `sudo` is present.
- `policy.*` / `secrets.*`.
- `cli.version`: exit code, outcome and stderr are always in the detail.
- `cli.*`: `claude -p` in a throwaway repo whose `.claude/settings.json` allows what the managed policy denies. `cli.deny.webfetch`/`websearch` read the tool list from the `stream-json` init event: they pass when the tool isn't offered, or is offered and denied.
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
- `localhost` without `/etc/hosts`: with an empty, read-only `/etc/hosts` mounted (as on AgentCore), NSS resolves it to `127.0.0.1` first, and the wrapper's preflight reports `nss`; nsswitch lists `myhostname` before `dns`; `/etc/gai.conf` prefers IPv4;
- the directory owners and modes, and that `fixer` can't modify either policy file;
- the entrypoint (S-190): `main.py`, the image's `CMD`, imports with the image's interpreter and dependencies, its steps are `preflight` … `fix`, and the fix loop is off by default;
- the wrapper's git (S-189): git supports `--attr-source`; as the root wrapper under `no_new_privs`, `safe_git.clone` makes `/work/wrapper/repo` root-owned 0700, `materialize` writes `/work/repo` files owned by `fixer` with no `.git`, a `fixer`-planted `.git/hooks` and `core.fsmonitor` never run in the wrapper's capture (with a control showing they do fire under `fixer`'s own git), and `fixer` can't list `/work/wrapper` or read `/work/wrapper/repo/.git/config` (TC-189-19).

The repo-root `make validate` includes this package.

`tests/component/fake_github.py` is an in-memory GitHub REST and GraphQL double at the `requests.Session` boundary, used by `test_issues.py`, `test_disposition.py`, `test_refusal.py`, `test_claim.py`, `test_label_invariance.py`, `test_main.py` and `test_claim_state_machine.py`. It serves comments (list, post, delete), reactions, issue facts, open pulls and the closing-reference query (with each PR's repository, for cross-repo cases), with per-route fault injection, 3xx answers (`redirect()`), and a record of each request's `allow_redirects`. It hands the client pre-parsed `links`, so `tests/unit/test_github_client.py` covers the real `Link` header parsing. The marker grammar is pinned by golden bodies in `tests/fixtures/contract/markers/` (CT-32).

The S-189 tests use real `git` on the fixture repos in `tests/fixtures/repos/` (see its README), committed and cloned from a local bare remote by `tests/component/repo_fixtures.py`. `SpawnSpy` there records every spawn `safe_git` makes, checks that every non-git spawn starts with the production `setpriv` drop, and then runs it as the current user. `StubSandbox` answers `Sandbox.run` with scripted results, and `LocalSandbox` runs install and gates for real with npm and pnpm forced offline (the tests that need `npm` or `pnpm` skip without them). `test_git_confinement.py` plants hooks, `core.fsmonitor`, `diff.external` and a filter driver in a `fixer` repository inside the work tree, and checks that no canary fires, with a control that does.

`tests/component/test_main.py` (S-190) drives `main.invoke()` end to end: the GitHub double, the `v_runs` double, the real `RunReporter` over a recording Supabase client, and a real-git checkout of a fixture remote. The boundaries come from `main.Runtime`, which the tests supply through `main.default_runtime`. SIGTERM is exercised by calling `signal_backstop.handle_termination()` with the getters `main` installed, from inside the running step, then raising a `BaseException` as the dying process would. `tests/component/test_claim_state_machine.py` is RT-07: a `hypothesis` stateful walk (200 × 30) over the claim, race, PR and disposition states, through `main.wire_claim()`. It pins three shapes: DF-32 (a race loser's 👀 stays, strict `xfail`), a post-check fault leaves 👀 unanswered by design (D-81), and the S-190 finding that a run can own the issue while another run's agent PR is open (strict `xfail`, routed to `product-engineer`).

`tests/component/test_sandbox_proc.py` runs the real command chain with real processes. Only `setpriv` and `srt` are replaced by exec-through shims, and the sweep is scoped to a per-test marker (the production sweep would kill every process of the current user).

## Deployment

Deploys are run by `infra-engineer`, never by a developer story. The first deploy, the runtime role and its secret grants, and the panel invoke-policy entry are S-181. S-190's image (the orchestration) and its `FIX_LOOP_ENABLED=0` env entry reach the runtime through a redeploy by `infra-engineer` (task 11.6), followed by a manual invoke on the fixture repo (task 11.7). The runbook is `docs/runbooks/bug-fix-agent.md` (stub in S-181, completed in Wave C).
