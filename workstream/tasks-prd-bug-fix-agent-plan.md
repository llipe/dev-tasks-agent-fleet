# Implementation Plan - Bug Fix Agent (Wave A)

> Execution plan for [`prd-bug-fix-agent`](../docs/requirements/prd-bug-fix-agent.md) v2.0 /
> [`specification-prd-bug-fix-agent`](specification-prd-bug-fix-agent.md) v2.0 /
> [`user-stories-prd-bug-fix-agent`](user-stories-prd-bug-fix-agent.md) v2.0.
> **Scope: Wave A only (PRD v2.0, issue mode).** GitHub issues **#362–#364, #366–#368, #370–#372** (S-180–S-182, S-184–S-186, S-188–S-190), milestone `v5.0 — Phase 5 Bug Fix Agent`. Tasks 4.0 and 8.0 are removed in v2.0.
> Waves B (#373–#377) and C (#378–#380) are planned separately, after the S-182 spike verdict.
>
> **Ordering is dependency-correct.** Each story is a branch with a reviewed PR into
> `integration/bug-fix-agent`. The integration branch reaches `main` through a single reviewed PR at
> the end. Human review is the gate, and no agent merges to `main`. **Test-first:** a `[T]` task
> MUST precede its `[I]` task.

## Changelog

| Version | Date       | Summary                                                    | Author           |
| ------- | ---------- | ---------------------------------------------------------- | ---------------- |
| 2.0.10 | 2026-10-24 | S-190 (developer): 11.1–11.5, 11.8 and 11.9 checked (test-first; agent gate green, 3020 passed, coverage 97%; image smoke 58/58 on a local arm64 build, no deploy). 11.10 base corrected to `integration/bug-fix-agent-wave-a`. 11.6 (redeploy) and 11.7 (manual invoke) stay with the planner through `/infra-engineer`. Carry-ins done: the one strict run-link validator `run_link.py` (S-188 QA gap 2), `refresh_if_stale` errors mapped by `exc.error_code` (S-185 residual), the `github_client.py` docstring names the race-loss `DELETE` (DF-188-02), RT-07 (moved here), TC-189-08/-21 in `test_main.py` (DF-35 still open: Wave A makes no board call), the sysctl preflight in the `preflight` step (S-189). RT-07 found a new shape for `product-engineer`: a run can own the issue while another run's agent PR is open (the post-check reads claims only, spec §8.6); unreachable in Wave A, pinned as a strict xfail. Draft PR #460 open; `verifier` audit and `coverage_gate` left to the planner. Relevant Files updated. | developer |
| 2.0.9 | 2026-10-24 | S-189 (developer): 10.1 checked as D-112 (OQ-1: a Python `make install` target, else `repo_gate` "missing install target"; confirmed by @llipe 2026-10-24, recorded via the docs write-back PR). 10.11 base corrected to `integration/bug-fix-agent-wave-a`; 10.12, 10.13 and 10.15 reworded to the D-110 uid model (root wrapper, `fixer` 10002, no `wrapper` user). 10.2–10.10 and 10.12–10.19 checked (test-first; agent gate green, 2579 passed, coverage 97.37%; image smoke 53/53 on a local arm64 build, no deploy). Draft PR #458 open; `verifier` audit and `coverage_gate` left to the planner. Relevant Files updated. | developer |
| 2.0.8 | 2026-10-24 | S-188 (developer): 9.1 worded to the single DF-33 open-claim rule confirmed by @llipe 2026-10-24 (no `pr`, `disposition` or `refusal` marker); 9.8 base corrected to `integration/bug-fix-agent-wave-a`. 9.1–9.7 checked (test-first; agent gate green, 2271 passed, coverage 98%). Draft PR #454 open; `verifier` audit and `coverage_gate` left to the planner. Relevant Files updated. | developer |
| 2.0.7 | 2026-10-24 | S-185 fix round (developer), from the QA gate and the S-185 fidelity report: page caps with pages left raise `GITHUB_UNAVAILABLE` (QA 1); an unknown `v_runs.effective_status` is `SUPABASE_UNAVAILABLE` with a `run_event` warning, and the missing-row warning is a `run_event` too (QA 2, DF-185-03); no request follows a redirect, a 3xx is `GITHUB_REQUEST_REJECTED` (QA 3); the `Link` parser matches `rel` as a whole parameter (QA 4); one 120 s wait budget per logical operation, `Retry-After` honoured up to 60 s (QA 5, DF-185-06); a failed mint is a `CredentialError`, and a refresh re-checks `issues: write` on the new token (QA 6); GraphQL `errors[]` split into transient (retry, then `GITHUB_UNAVAILABLE`) and permanent (`GITHUB_REQUEST_REJECTED`) (DF-185-05); a cross-repo linked PR is named `owner/repo#M` (DF-185-07, CT-33); agent-side CT-34 table (DF-185-08 partial; the L2.5 real-database read remains). No new public error code. DF-185-01/02/04 unchanged. | developer |
| 2.0.6 | 2026-10-24 | S-185 (developer): 6.1–6.9 checked (test-first; agent gate green, 1858 passed, coverage 97.76%). 6.10 base corrected to `integration/bug-fix-agent-wave-a`; Draft PR #453 open, `verifier` audit and `coverage_gate` left to the planner. Relevant Files updated. | developer |
| 2.0.5 | 2026-10-24 | Drift reconciliation of S-186 audit findings DF-186-01 and DF-186-02, confirmed by @llipe 2026-10-24. 7.2 notes the D-65 amendment (references kept as written). 6.2 and 9.2 name the in-repo GitHub double (`fake_github.py`) instead of `responses`; 6.3 adds a parser-level `Link`-header unit test. S-199 is outside this Wave A list; its stories and test plan carry the same harness. | product-engineer |
| 2.0.4 | 2026-10-24 | S-186 (developer): 7.1–7.10 checked (test-first; `make validate` green, 1136 passed, coverage 97.89%). 7.11 base corrected to `integration/bug-fix-agent-wave-a`; Draft PR #451 open, `verifier` audit and `coverage_gate` left to the planner. Relevant Files updated. | developer |
| 2.0.3 | 2026-10-24 | S-184 (developer): 5.1–5.5, 5.8, 5.9 and 5.11 checked; migration `20261024130000_seed_bug_fix_agent.sql` verified on the local stack only. 5.6/5.7 (cloud apply gate), 5.10 (manual UI), 5.12 (`coverage_gate`, cloud part) and 5.13 (verifier) left to the planner. Relevant Files updated. | developer |
| 2.0.2 | 2026-10-24 | S-182 IC done: 3.5–3.10, 3.15, 3.17.6 checked (re-probe 2d 39/39 PASS on runtime v5; `ALLOW_PROBE` removed on v6). Spike verdict PASS. 3.11–3.13 checked (552 passed, coverage_gate PASS 97.5%, verifier Medium/Major); 3.16 marked superseded; 3.13 base corrected (DF-182-08). | planner |
| 2.0.1 | 2026-10-24 | 3.17 (D-110) split into checkable sub-items 3.17.1–3.17.6; 3.17.1–3.17.5 done (root wrapper + `setpriv`, probe `setpriv.*`/`noescalate.*`/`userns.available`, local evidence). 3.17.6 (re-probe) stays with `infra-engineer`. Relevant Files updated (`sudoers-bug-fix` and `test_image_sudoers.py` removed). | developer |
| 2.0 | 2026-10-22 | Issue-mode rewrite (PRD v2.0, spec v2.0, stories v2.0; D-88–D-106). 4.0 and 8.0 removed. 5.0, 6.0 (refusal checks and reply), 7.0, 9.0 and 11.0 rewritten. 1.0, 2.0 (Projects PAT), 3.0 (board probe 3.15) and 10.0 (`repo_gate` refusal) updated. | product-engineer |
| 1.5 | 2026-10-20 | Supersedes the parallel design line merged in PR #350 (D-87, @llipe, 2026-10-20). Decision IDs from this line are renumbered D-25–D-67 → D-44–D-86 after main's D-43. The superseded line's changelog rows remain in git history (`875299a`, PR #350). | product-engineer |
| 1.4     | 2026-10-20 | Drift reconciliation of verifier DF-20 to DF-28 (D-79–D-86). New sub-tasks: 5.16, 6.12, 7.11 and 11.12. 9.9 and 10.13 reworded. The Verify-AC steps 5.11, 6.7, 8.7 and 10.9 are renumbered to the v1.4 story ACs, and the header versions are updated (DF-24). | product-engineer |
| 1.3     | 2026-10-20 | Drift reconciliation of the verifier's Minor findings DF-04 to DF-19 (D-64–D-78): sub-tasks added to 3.0 (3.14), 5.0 (5.14–5.15), 6.0 (6.10–6.11), 8.0 (8.10), 9.0 (9.9) and 11.0 (11.11). The Wave B and C findings are carried in stories v1.3 and the issue ACs. | product-engineer |
| 1.2     | 2026-10-20 | Drift reconciliation of verifier DF-12 (D-63): 10.6 is reworded, and sub-tasks 10.17–10.19 are added. | product-engineer |
| 1.1     | 2026-10-20 | Drift reconciliation of verifier DF-02 (D-62): task 10.0 gains sub-tasks 10.12–10.16 for wrapper-git confinement, and 10.6 is reworded to match. | product-engineer |
| 1.0     | 2026-10-20 | Initial Wave A task list from stories v1.0 (S-180…S-190).  | product-engineer |

## Conventions

- **Branches:** `story/S-180-agent-scaffold`, …; integration branch `integration/bug-fix-agent`.
- **Commits:** Conventional Commits (`feat(bug-fix): …`, `test(bug-fix): …`, `feat(panel): …`, `chore(infra): …`, `docs: …`).
- **Packages** (bracket prefix). This repository has no package map in `docs/tech.md`, so the brackets use the top-level areas: `[agents/bug-fix]`, `[panel]`, `[supabase]`, `[infra]`, `[repo root]`.
- **Layers** (`TESTING.md`): L1 unit, L2 component, L2.5 integration (`REQUIRE_LOCAL_DB=1`), E2E (Playwright), IC in-container on the deployed runtime.
- **Agent gate:** from `agents/bug-fix/app/bugFix/`, `make lint && make format-check && make typecheck && make test && make audit`. **Panel gate:** `pnpm --filter panel run lint && pnpm --filter panel run format:check && pnpm --filter panel run typecheck && pnpm --filter panel run test && pnpm run audit`. Then `make validate`.
- **DoD per story:**
  - tests written first, and passing;
  - gates green;
  - `coverage_gate` recorded;
  - `verifier` audit run, with drift routed to `product-engineer`;
  - for UI stories, a DESIGN.md pixel match;
  - a PR against `integration/bug-fix-agent` whose body summarizes the changes, the tests and anything blocked.
- **Infra stories** (2.0, and the redeploys in 3.0 and 11.0) run through `/infra-engineer`, not `developer`.
- **Execution order:** 1.0 → 2.0 → 3.0 → 5.0 → 7.0 → 6.0 → 9.0 → 10.0 → 11.0. (6.0 uses the markers from 7.0.)
- **Task 0 is not needed.** `agents/bug-fix/` is a new component, but S-180 (task 1.0) is its setup task.

## Relevant Files

- `agents/bug-fix/agentcore/agentcore.json` - Runtime config: env, `maxLifetime` 3600, `FIX_LOOP_ENABLED` (`0`, S-190), `PANEL_BASE_URL`
- `agents/bug-fix/app/bugFix/Dockerfile` - ARM64 image: Python 3.13, Node 26 + pnpm, git, bubblewrap, socat, ripgrep, procps, util-linux (`setpriv`), libnss-myhostname + `/etc/gai.conf` (`localhost` without `/etc/hosts`, D-111), pinned Claude Code and sandbox runtime; the wrapper runs as root, no `sudo` (D-110)
- `agents/bug-fix/app/bugFix/managed-settings.json` - Managed Claude Code policy, installed at `/etc/claude-code/`
- `agents/bug-fix/app/bugFix/{Makefile,pyproject.toml}` - Agent quality gates
- `agents/bug-fix/app/bugFix/{agent_reporter,heartbeat,signal_backstop,scrubber,credentials}.py` - Copied sibling modules (extended; S-186: `signal_backstop.py` disposition hook with a 10 s budget, `TokenContext.app_id` in `credentials.py`; S-185: `mint_installation`, `TokenContext.permissions` and `has_issues_write` in `credentials.py`; S-190: `GitHubSession` and `resolve_github_session` (keeps the PEM for `refresh_if_stale`), a typed Supabase HTTP error in `credentials.py`)
- `agents/bug-fix/app/bugFix/config.py` - Typed env config; S-188: optional `PANEL_BASE_URL` (bare `https` origin) and `Config.run_link()`; S-190: `PANEL_BASE_URL` through `run_link.parse_origin`, `run_link()` returns a `RunLink`, `fix_loop_enabled` (`FIX_LOOP_ENABLED`, off when absent)
- `agents/bug-fix/app/bugFix/main.py` - Entrypoint and step orchestration (S-190): `preflight` → `refuse` → `checkout` → `claim` → `fix` (only with `FIX_LOOP_ENABLED=1`), `Runtime` boundaries, `TokenSource` (refresh errors by `exc.error_code`), `wire_claim`, the ownership-gated `finally` path, heartbeat and backstop, `runs.metrics`
- `agents/bug-fix/app/bugFix/outcomes.py` - Outcome mapping (spec §8.9; S-190): `RunResult`, closed outcome/reason/code sets, breaker flag, step-result builders
- `agents/bug-fix/app/bugFix/run_link.py` - The one strict run-link validator: `parse_origin`, `RunLink`, `is_valid_run_link`, `run_ref` (S-190, S-188 QA gap 2)
- `agents/bug-fix/app/bugFix/sandbox.py` - `fixer` subprocess spawner: `setpriv` drop from the root wrapper, allow-list env, `srt`/CLI sandbox, read-only `localhost` preflight (D-111), timeout, two-pass post-run sweep (S-182, D-110)
- `agents/bug-fix/app/bugFix/fixer_exec.py` - Runs as `fixer` after `setpriv`; rebuilds the env from the allow-list and refuses to run as root (S-182, D-110)
- `agents/bug-fix/app/bugFix/probe.py` - Spike probe mode (S-182, D-70, D-105, D-110: `setpriv.*`, `noescalate.*`, `userns.available`)
- `agents/bug-fix/app/bugFix/probe_inner.py` - The probe's `fixer`-side helper, stdlib only (S-182)
- `agents/bug-fix/app/bugFix/srt-settings.json` - `/etc/bug-fix/srt-settings.json`: sandbox-runtime policy for `fixer` scripts (S-182)
- `agents/bug-fix/app/bugFix/params.py` - Typed params: spec §5.2 v2.0 bounds and seed-equal defaults (S-184, D-82, D-93); `SCHEMA_KEYS` for the `invalid_params` closed set (S-185)
- `agents/bug-fix/app/bugFix/issues.py` - GitHub issue I/O (REST and GraphQL); S-186: comments, reactions, 65,536-unit truncation; S-185: built on `github_client.py`, issue facts (`IssueFacts`), linked PRs (closing references plus `issue/<N>-` heads); S-188: `delete_comment()` (idempotent, a 404 is already gone)
- `agents/bug-fix/app/bugFix/markers.py` - Claim, disposition, refusal and `pr` markers; leading block, trust, open claims (S-186); S-188: the single DF-33 open-claim rule (`refusal` closes its own run's claim)
- `agents/bug-fix/app/bugFix/disposition.py` - Idempotent, ownership-gated disposition (S-186)
- `agents/bug-fix/app/bugFix/refusal.py` - Preflight, refusal checks and the marked reply; `v_runs` reader (S-185); S-188: duplicate refused-set rule removed (DF-185-04), `active_claim_runs(before=, warn=)` shared with the race check; S-189: `post_refusal()`, `repo_gate` items `package.json or Makefile`, `lockfile`, `install`; S-190: `run_preflight()` and `run_refusals()` (the two steps), `CheckOutcome.client`, the run link through `run_link.run_ref`
- `agents/bug-fix/app/bugFix/claim.py` - Claim comment plus 👀, post-claim race check, withdrawal, ownership gate (S-188)
- `agents/bug-fix/app/bugFix/github_client.py` - Shared GitHub client: retry policy, typed errors, GraphQL queries, `Link` header parsing (S-185)
- `agents/bug-fix/app/bugFix/neutralize.py` - Model-text neutralizer (S-186)
- `agents/bug-fix/app/bugFix/claim.py` - Claim and race check
- `agents/bug-fix/app/bugFix/toolchain.py` - Stack detection, gate names, static `Makefile` parsing and the repo gate, read through a `RepoReader` (copied from `dependency-update` at ff52835, extended; S-189, D-112)
- `agents/bug-fix/app/bugFix/safe_git.py` - The wrapper's only git: hardened command shape, the wrapper clone, `materialize()` as `fixer`, `capture()`, `TreeReader` (S-189, D-62)
- `agents/bug-fix/app/bugFix/checkout.py` - Clone, materialize, repo gate (refusal `repo_gate`), frozen install, base gates, `restore_base()`; `CLONE_FAILED`, `INSTALL_FAILED` (S-189); S-190: `record_link_protection()`, called by the `preflight` step
- `agents/bug-fix/app/bugFix/{claim,disposition}.py` - S-190: the run link through `run_link.run_ref` (the loose `https://\S+` checks removed)
- `agents/bug-fix/app/bugFix/github_client.py` - S-190: the module docstring names the race-loss single-id `DELETE` as the one write retried on a 5xx and a transport error (DF-188-02)
- `agents/bug-fix/app/bugFix/gates.py` - Gate runner: four gates plus `audit` in `Mode.SCRIPT`, scrubbed tails (S-189)
- `agents/bug-fix/app/bugFix/scripts/image-smoke.sh` - Image assertions; S-189: wrapper git end to end, TC-189-19; S-190: `main.py` (the image `CMD`) imports in the image
- `agents/bug-fix/app/bugFix/tests/fixtures/repos/**` - S-189 fixture repos (README lists each)
- `agents/bug-fix/app/bugFix/tests/{unit,component,fixtures}/**` - Agent tests and fixture repos (S-182: `unit/test_{sandbox,probe,probe_inner,image_setpriv,image_localhost,agentcore_config}.py`, `component/test_sandbox_proc.py`; `test_image_sudoers.py` and `sudoers-bug-fix` removed by 3.17; S-184: `unit/test_{params,params_property,payload_contract,no_defaults_in_code}.py`; S-186: `unit/test_{markers,markers_property,markers_contract,neutralize,neutralize_property,comment_bodies_property}.py`, `component/{fake_github,test_issues,test_disposition}.py`, extended `unit/test_{credentials,signal_backstop}.py`; S-185: `unit/test_{refusal,github_client,permissions}.py`, `component/test_{refusal,label_invariance}.py`, extended `fake_github.py`, `unit/test_{credentials,comment_bodies_property}.py` and `tests/conftest.py`; S-188: `unit/test_race.py`, `component/test_claim.py`, `DELETE` in `fake_github.py`, extended `unit/test_{markers,markers_property,config,agentcore_config}.py` and `component/test_issues.py`; S-189: `unit/test_{toolchain,safe_git}.py`, `component/{repo_fixtures,test_checkout,test_gates,test_git_confinement,test_safe_git_faults}.py`; S-190: `unit/test_{outcomes,run_link}.py`, `component/{test_main,test_claim_state_machine}.py`, extended `unit/test_{config,agentcore_config,credentials,github_client,comment_bodies_property,image_smoke_s189,main_stub,probe}.py` and `component/test_s189_fix_round.py`)
- `agents/bug-fix/app/bugFix/tests/fixtures/contract/{params_schema,payload.webhook,payload.manual}.json` - Panel → agent contract fixtures; `params_schema.json` is the spec §5.2 v2.0 copy shared with the panel tests (S-184)
- `agents/bug-fix/app/bugFix/tests/fixtures/contract/markers/{*.md,expected.json,.gitattributes}` - CT-32 golden marker bodies, byte-exact (S-186)
- `agents/bug-fix/{README.md,AGENTS.md}` - Agent docs (S-186: markers and disposition section; S-185: refusal checks section; S-188: claim and race check section, `PANEL_BASE_URL`; S-189: checkout, repo gate and gates section, image and testing notes; S-190: status, "Run steps and outcomes", `FIX_LOOP_ENABLED`, the run-link validator)
- `agents/bug-fix/agentcore/{.gitignore,.llm-context/**,cdk/**}` - Generic AgentCore CDK app and schema context, mirrored from the sibling (S-180)
- `agents/bug-fix/app/bugFix/{.gitignore,.dockerignore,.ca-placeholder}` - Package ignores and the build-time CA placeholder (S-180)
- `Makefile` - Repo-root `AGENT_DIRS` includes `agents/bug-fix/app/bugFix` (S-180)
- `.github/workflows/ci.yml` - `python-quality` matrix entry for `bug-fix` (S-180)
- `TESTING.md` - `bug-fix` package rows and the image-smoke Layer 2 command (S-180); GitHub REST double and marker goldens (S-186); GraphQL and fault injection in the double, `Link` header at L1, RT-13, no-sleep retry fixture (S-185); comment deletion in the double (S-188); real-git fixture repos, `SpawnSpy`, `StubSandbox`/`LocalSandbox`, and the image-smoke wrapper-git checks (S-189); `test_main.py`'s harness, RT-07 and its strict xfails, the SIGTERM technique, the entrypoint smoke check (S-190)
- `panel/tests/integration/bug-fix-seed.test.ts` - Seed, schema, webhook-resolve check, and the webhook fire at the seeded runtime ARN (S-184)
- `panel/tests/unit/bug-fix-params-schema.test.ts` - TC-184-07 boundary table through the panel's Ajv (S-184)
- `panel/tests/fixtures/github/issue_comment.created.json` - `issue_comment.created` payload, modeled on GitHub's documented shape (not recorded) (S-184)
- `supabase/migrations/20261024130000_seed_bug_fix_agent.sql`, `supabase/seed.sql` (block 4a) - `agents` row (S-184)
- `infra/changes/<date>-bug-fix-runtime/` - Infra change record
- `docs/runbooks/bug-fix-agent.md` - Runbook stub (completed in Wave C); root wrapper + `setpriv` fact and the probe-invocation procedure (3.17); S-190: `FIX_LOOP_ENABLED`, what a Wave A run writes, the 11.7 expected result
- `docs/runbooks/README.md` - Runbook index row (3.17: probe in the trigger)
- `workstream/spike-bug-fix-sandbox.md` - Spike report
- `workstream/decisions-bug-fix-agent.md` - OQ-1 recorded as D-112 by the docs write-back PR (not edited in S-189's PR)

## Tasks

- [x] 1.0 Implement Story S-180 (#362 - https://github.com/llipe/dev-tasks-agent-fleet/issues/362): Agent scaffold, image, and managed Claude Code policy

  > Note: skeleton only. `main.py` ends `succeeded`/`not_applicable` "not yet implemented", so a deploy is harmless.

  - [x] 1.1 `[T]` [agents/bug-fix] L1 `tests/unit/test_scrubber.py` (the Anthropic key is redacted) and `tests/unit/test_config.py` (reads `MODEL_ID`, `SUPABASE_KEY_SECRET_ID`, `ANTHROPIC_KEY_SECRET_ID`; a missing var raises a typed error with no values in the message) (D-50)
  - [x] 1.2 `[T]` [agents/bug-fix] L1 `tests/unit/test_main_stub.py`: the entrypoint reports `started`, then `succeeded`/`not_applicable` "not yet implemented"
  - [x] 1.3 `[I]` [agents/bug-fix] Create the layout: `agentcore/agentcore.json`, `app/bugFix/{main.py, config.py, Dockerfile, Makefile, pyproject.toml}`, `README.md`, `AGENTS.md` (D-03)
  - [x] 1.4 `[I]` [agents/bug-fix] Copy `agent_reporter.py`, `heartbeat.py`, `signal_backstop.py`, `scrubber.py`, `credentials.py` from `security-analyst`, each with a source and commit header. Add the Anthropic key and the Projects PAT to the scrubber's secrets (D-03, D-50, D-99)
  - [x] 1.5 `[I]` [agents/bug-fix] `config.py` and the minimal `main.py`
  - [x] 1.6 `[I]` [agents/bug-fix] `agentcore.json`: runtime `bug_fix`, `Container`, `PUBLIC`, `maxLifetime: 3600`, envs `SUPABASE_URL`, `SUPABASE_KEY_SECRET_ID`, `ANTHROPIC_KEY_SECRET_ID=agent-fleet/prod/ANTHROPIC_API_KEY`, `PROJECTS_TOKEN_SECRET_ID=agent-fleet/prod/GITHUB_PROJECTS_TOKEN`, `BOARD_UPDATES_ENABLED=1`, `MODEL_ID` (a Sonnet id on the Anthropic API). No Bedrock reference (D-50)
  - [x] 1.7 `[I]` [agents/bug-fix] Dockerfile (ARM64): Python 3.13, Node 26 + pnpm, git, `bubblewrap`, `socat`, pinned `@anthropic-ai/claude-code`; users `wrapper` and `fixer` with different uids; `/work/repo` and `/work/out` owned by `fixer`; `/home/fixer` (D-05, D-18, D-51)
  - [x] 1.8 `[I]` [agents/bug-fix] `managed-settings.json`, root-owned with mode 0644, at `/etc/claude-code/`:
    - sandbox enabled;
    - registry-only network: `registry.npmjs.org`, `registry.yarnpkg.com`, `pypi.org`, `files.pythonhosted.org`;
    - denies `Bash(git push:*)`, `Bash(gh:*)`, `Bash(curl:*)`, `Bash(wget:*)`, `WebFetch`, `WebSearch`, and Read/Edit of `/proc/**`, `/etc/claude-code/**`, `/work/secrets/**`;
    - key names are provisional until 3.0 (D-51).
  - [x] 1.9 `[I]` [agents/bug-fix] `scripts/image-smoke.sh` and `make image`. The smoke script asserts that `id fixer` ≠ `id wrapper`, that `claude --version` and `bwrap --version` work, and that the policy file is owned by root with mode 0644
  - [x] 1.10 Edge cases: each missing env var gives a typed error, never a traceback that contains values
  - [x] 1.11 Verify AC: layout and copied modules (AC1–AC2); `agentcore.json` envs with no Bedrock (AC3); ARM64 build with the toolchain (AC4); users and dirs (AC5); policy ownership and content (AC6); stub entrypoint (AC7). Map each to 1.1, 1.2 or 1.9
  - [x] 1.12 Run tests: `make test`, `make image`, `scripts/image-smoke.sh`; agent gate; `make validate`; record `coverage_gate`
  - [x] 1.13 `verifier` audit; open PR → `integration/bug-fix-agent`

- [x] 2.0 Implement Story S-181 (#363 - https://github.com/llipe/dev-tasks-agent-fleet/issues/363): Infra change — Anthropic key, runtime and role, panel invoke policy, App Issues write

  > Note: run with `/infra-engineer`. One approval per step; each step reversible and recorded. No secret value is ever logged or committed (D-58).

  - [x] 2.1 [infra] Open the change record `infra/changes/<date>-bug-fix-runtime/` with a plan, plus backup and revert steps for each item
  - [x] 2.2 [infra] **Operator action:** create a dedicated Anthropic API key with a spend cap. Store it as `agent-fleet/prod/ANTHROPIC_API_KEY` in Secrets Manager. Record the cap, never the key (D-50, D-58)
  - [x] 2.2b [infra] **Operator action:** create a classic PAT with only the `project` scope. Store it as `agent-fleet/prod/GITHUB_PROJECTS_TOKEN`, and record the scope and expiry, never the token (D-99)
  - [x] 2.3 [infra] Runtime role: `secretsmanager:GetSecretValue` on exactly the Supabase key, App PEM, Anthropic key and Projects token ARNs, with no `bedrock:*` (D-58, D-99)
  - [x] 2.4 [infra] `agentcore deploy` the 1.0 image. Record the runtime ARN from `agentcore status`
  - [x] 2.5 [infra] Panel `invoke-runtime` policy: add the runtime ARN and its `runtime-endpoint/DEFAULT` (issue #280) (D-58)
  - [x] 2.6 [infra] **Operator action:** GitHub App → **Issues: read and write**, then accept the change on every installation in `github_installations` (D-58)
  - [x] 2.7 [infra] Verify with `aws iam simulate-principal-policy`: allowed on the three secrets, denied on another secret, denied on `bedrock:InvokeModel`
  - [x] 2.8 [infra] Verify a token-mint probe shows `permissions.issues == "write"` for each installation. List any installation that hasn't accepted (edge case)
  - [x] 2.9 [panel] Manual check: invoking the stub from the deployed panel creates a run that ends `succeeded`/`not_applicable`
  - [x] 2.10 [repo root] Create the runbook stub `docs/runbooks/bug-fix-agent.md` with the deploy and verify sections (FR-49a)
  - [x] 2.13 [infra] Remove the copied CDK construct's default Bedrock grant (`bedrock:InvokeModel`, `InvokeModelWithResponseStream`, `CountTokens` on all foundation models; `@aws/agentcore-cdk` `AgentCoreRuntime`) before the first deploy, using an explicit `executionRoleArn` or a construct override. Verify with the 2.7 simulation that `bedrock:InvokeModel` is denied (DF-180-04, D-50). Do this before 2.4.
  - [x] 2.11 Verify AC: AC1 key and cap recorded; AC2 deployed with the ARN recorded; AC3 role simulation; AC4 panel invoke; AC5 `issues: write`; AC6 backup and revert per item. Map each to the change-record verification table
  - [x] 2.12 `verifier` audit; draft PR → `integration/bug-fix-agent`

- [x] 3.0 Implement Story S-182 (#364 - https://github.com/llipe/dev-tasks-agent-fleet/issues/364): Sandbox spike on the deployed runtime

  > Note: **gates all of Wave B.** If any check fails, record FAIL, keep #373–#377 blocked, and hand off to `product-engineer` drift reconciliation (D-51, spec §12). Resolves spec OQ-2.

  - [x] 3.1 `[T]` [agents/bug-fix] L1 `tests/unit/test_sandbox.py`:
    - the env is built from an allow-list (`ANTHROPIC_API_KEY`, `PATH`, `HOME`, `LANG`, `CI=1`), never a deny-list;
    - no `AWS_*` or `AWS_CONTAINER_*` variable passes through;
    - timeout → SIGTERM, then SIGKILL after 15 s;
    - exit-code mapping;
    - a missing sandbox binary raises a typed error;
    - zombie children are reaped (D-51).
  - [x] 3.2 `[T]` [agents/bug-fix] L1 `tests/unit/test_probe.py`: probe mode is refused unless `ALLOW_PROBE=1`, even when `__probe: true` is sent
  - [x] 3.3 `[I]` [agents/bug-fix] `sandbox.py`: run as `fixer` with the minimal env, under the sandbox runtime with the registry-only network policy and a wall-clock timeout (D-51)
  - [x] 3.4 `[I]` [agents/bug-fix] `probe.py` and its `main.py` hook, reporting each check as a `run_event`
  - [x] 3.5 [infra] Redeploy with `ALLOW_PROBE=1` through `/infra-engineer`
  - [x] 3.6 IC: inside the sandbox, `169.254.170.2`, `169.254.169.254` and `example.com` are unreachable, while `registry.npmjs.org` and `pypi.org` are reachable (D-51)
  - [x] 3.7 IC: as `fixer`, `/proc/<wrapper pid>/environ` and `/proc/<wrapper pid>/mem` can't be read, and no `AWS_*` variable is present
  - [x] 3.8 IC: through `claude -p` (as `fixer`, in the sandbox), a repo `.claude/settings.json` that allows `Bash(git push:*)` loses to the managed deny rule, and `WebFetch` is denied (D-05, D-51)
  - [x] 3.9 [agents/bug-fix] Write `workstream/spike-bug-fix-sandbox.md`: CLI version, the sandbox runtime chosen (`bwrap` or the CLI's own), the verified managed-settings keys, and a PASS/FAIL verdict per check. Update `managed-settings.json` to match (OQ-2)
  - [x] 3.10 [infra] Unset `ALLOW_PROBE` and redeploy
  - [x] 3.15 IC board probe (D-105), run with `GITHUB_PROJECTS_TOKEN` against linked board #5:
    - `repository.projectsV2` on `llipe/dev-tasks` returns #5;
    - on probe issue `[probe] bug-fix board probe` in `llipe/dev-tasks`, `addProjectV2ItemById` is idempotent;
    - each of the three statuses is set and read back;
    - the PAT is absent from every `fixer` env and file;
    - with no PAT the board is disabled and the run ends normally.
    
    Cleanup deletes the card (`deleteProjectV2Item`) and closes the probe issue. If the first three checks fail, set `BOARD_UPDATES_ENABLED=0` and route to drift; Wave B is not blocked. Record the result in the spike report
  - [x] 3.16 `[T]`/`[I]` [agents/bug-fix] **Superseded by 3.17 (D-110)**: done, then replaced after probe run 1 (`no_new_privs` blocks `sudo`). Do this before 3.3 (DF-180-03, D-109).
    - Dockerfile: install `sudo` with exactly one sudoers line, `wrapper ALL=(fixer) NOPASSWD: ALL`, plus `Defaults env_reset` and a fixed `secure_path` (`/etc/sudoers.d/bug-fix`, mode 0440).
    - `sandbox.py`: spawn through `sudo -u fixer --` with the allow-listed env passed explicitly.
    - `image-smoke.sh` asserts: `sudo -u fixer id -u` = 10002; `sudo -u fixer sudo -n true` fails; `sudo -n -u root true` as `wrapper` fails; the sudoers file is root-owned 0440.
    - IC (3.7): as `fixer`, `/proc/<wrapper pid>/environ` is unreadable.
  - [x] 3.17 `[T]`/`[I]` [agents/bug-fix] (D-110, replaces D-109 after probe run 1 found `no_new_privs` on AgentCore)
    - [x] 3.17.1 Dockerfile: the wrapper runs as root; remove `sudo` and `/etc/sudoers.d/bug-fix`.
    - [x] 3.17.2 `sandbox.py`/`fixer_exec.py`: launch through `setpriv --reuid=10002 --regid=10002 --clear-groups --inh-caps=-all --no-new-privs`, with the allow-listed env passed explicitly.
    - [x] 3.17.3 `image-smoke.sh`: `setpriv` drop gives uid 10002 with no capabilities; `fixer` can't regain root; `fixer` can't read the root wrapper's `/proc/<pid>/environ` or `mem`; no `sudo` binary.
    - [x] 3.17.4 Probe: the uid and `sudo` checks change to `setpriv` and no-escalation checks; add a user-namespace check for `bwrap`/`srt` under `no_new_privs`.
    - [x] 3.17.5 Local evidence with `--security-opt no-new-privileges` (default and permissive profiles) in the spike report; README and runbook (root wrapper, probe procedure) updated.
    - [x] 3.17.6 [infra] Re-probe on the deployed runtime (change record `20261024-bug-fix-spike-probe`, steps 1b–2d; 2d: 39/39 PASS).
  - [x] 3.11 Verify AC: AC1–AC2 by 3.1 and 3.2; AC3–AC5 by the IC events in 3.6–3.8; AC6–AC7 by the spike report
  - [x] 3.12 Run tests: `make test`; agent gate; `make validate`; record `coverage_gate`
  - [x] 3.13 `verifier` audit; open PR → `integration/bug-fix-agent-wave-a`. On FAIL, route to `product-engineer`
  - [x] 3.14 `[T]` [agents/bug-fix] Do this before 3.11. L1 `tests/unit/test_probe.py`: `__probe` is read only from the **top-level** payload, never from `params`; `params.__probe` is ignored; both forms are refused without `ALLOW_PROBE=1` (DF-14, D-70)

- [ ] ~~4.0 Implement Story S-183 (#365)~~ — **removed in v2.0** (D-95); #365 closed as not planned.

- [x] 5.0 Implement Story S-184 (#366 - https://github.com/llipe/dev-tasks-agent-fleet/issues/366): `agents` seed row, params schema, and typed params

  > Note: issue-mode params (D-93, D-102). `issue_number` is the only required key. Needs the runtime ARN from 2.4.

  - [x] 5.1 `[T]` [panel] L2.5 `panel/tests/integration/bug-fix-seed.test.ts`:
    - after `db reset`, the row exists (`requires_repository`, 3600/120/300, the ARN);
    - `validateParams` accepts `{issue_number: 7}` and rejects `{}`, `{issue_number: 0}` and `{select_labels: [...]}`;
    - `resolveRoute` with the runbook mapping (`issue.number`, `comment.id`) yields valid params (D-88, D-93).
  - [x] 5.2 `[T]` [agents/bug-fix] L1 `tests/unit/test_params.py`: valid params; missing `issue_number`; each bound's edges and a wrong type; defaults applied for budgets, caps and status names; unknown keys ignored (D-82)
  - [x] 5.3 `[I]` [supabase] Migration `supabase/migrations/<ts>_seed_bug_fix_agent.sql`: an upsert with `params_schema` from spec §5.2 v2.0, and `default_params` holding only budgets, caps and status names
  - [x] 5.4 [supabase] Document the rollback in the migration header: `delete from agents where slug = 'bug-fix'`
  - [x] 5.5 [supabase] Mirror the row in `supabase/seed.sql`
  - [x] 5.6 **Confirmation gate:** ask the user before applying the migration to any shared or cloud project
  - [x] 5.7 [supabase] Apply after confirmation, then verify: `select slug, params_schema->'required' from agents where slug='bug-fix'`
  - [x] 5.8 `[I]` [agents/bug-fix] `params.py`: typed params, bounds and defaults (D-82)
  - [x] 5.9 Edge cases: a `project` that fails the pattern; a 100-character status name; `trigger_comment_id` as a string
  - [x] 5.10 Manual UI: `/agents/bug-fix/invoke` shows `issue_number` as required
  - [x] 5.11 Verify AC (v2.0): AC1–AC3 and AC5 by 5.1; AC4 by 5.2
  - [x] 5.12 Run tests: `supabase db reset`, `pnpm --filter panel run test:integration`, `make test`; gates; `make validate`; record `coverage_gate`
    > Local run done (2026-10-24, developer): `supabase db reset --local`, `test:integration` 42 files / 328 tests with `REQUIRE_LOCAL_DB=1`, agent `make validate` green. Panel `audit` fails on a pre-existing advisory outside this story (`zod` via `agents/dependency-update/agentcore/cdk`). Open: `coverage_gate` (planner's `qa-engineer`) and the post-apply cloud check.
  - [x] 5.13 `verifier` audit; open PR → `integration/bug-fix-agent-wave-a`

- [x] 6.0 Implement Story S-185 (#367 - https://github.com/llipe/dev-tasks-agent-fleet/issues/367): Refusal checks and marked reply

  > Note: D-92, D-104. This replaces the label and assignee preflight; the linked-PR check moves here from the old 8.0.

  - [x] 6.1 `[T]` [agents/bug-fix] L1 `tests/unit/test_refusal.py`:
    - the decision table, first match wins: `pull_request`, `closed`, `linked_pr`, `active_run`, plus `invalid_params`;
    - fixed text per code (snapshot);
    - a refusal marker is never a claim (D-92, D-104).
  - [x] 6.2 `[T]` [agents/bug-fix] L2 `tests/component/test_refusal.py` with the in-repo GitHub double `tests/component/fake_github.py`, not `responses` (DF-186-02):
    - each code posts exactly one marked reply, with no reaction, claim or board call;
    - the happy path proceeds;
    - a reply-post failure is logged and the outcome is unchanged;
    - missing `issues: write` → `failed`/`GITHUB_PERMISSION_MISSING` (D-58).
  - [x] 6.3 `[T]`/`[I]` [agents/bug-fix] `github_client.py`: 5xx and secondary rate limits retried 3 times, then `GITHUB_UNAVAILABLE`; an unexpected 4xx on a write → `GITHUB_REQUEST_REJECTED` (D-67); an L1 parser-level test of real `Link`-header pagination parsing, which the L2 double does not exercise (DF-186-02)
  - [x] 6.4 `[I]` [agents/bug-fix] `credentials.py`: return the minted token's `permissions` (D-58)
  - [x] 6.5 `[I]` [agents/bug-fix] `issues.py`: issue facts (`state`, `pull_request`), and linked PRs through GraphQL `closedByPullRequestsReferences` plus open PRs with head `issue/<N>-` (D-55)
  - [x] 6.6 `[I]` [agents/bug-fix] `refusal.py`: checks in order; `active_run` reads trusted claim markers and `v_runs.effective_status` (a Supabase failure → `SUPABASE_UNAVAILABLE`); the reply with the `refusal` marker and fixed text (D-92, D-104)
  - [x] 6.7 Edge cases: an issue that is both closed and a PR; a linked PR from a fork; an untrusted claim marker (ignored); a terminal claim (proceeds)
  - [x] 6.8 Verify AC (v2.0): AC1–AC5 by 6.1–6.3
  - [x] 6.9 Run tests: `make test`; agent gate; `make validate`; record `coverage_gate`
    > Local run done (2026-10-24, developer): agent gate green (`ruff`, `ruff format --check`, `mypy`, `pytest --cov` 1858 passed, 3 xfailed, coverage 97.76%, `pip-audit` clean), with the known macOS-only `test_sandbox_proc.py::TestTimeoutReal::test_sigterm_ignored_child_is_killed_after_grace` deselected (#447). `coverage_gate` is SKIPPED(no-delegation) here; the planner's `qa-engineer` records it.
  - [x] 6.10 `verifier` audit; open PR → `integration/bug-fix-agent-wave-a`

- [x] 7.0 Implement Story S-186 (#368 - https://github.com/llipe/dev-tasks-agent-fleet/issues/368): Markers, reactions and the idempotent disposition

  - [x] 7.1 `[T]` [agents/bug-fix] L1 `tests/unit/test_markers.py`:
    - a round-trip for `claim`, `disposition`, `refusal` (`reason=`) and `pr`;
    - the leading marker block;
    - forged markers (human author, wrong App id, `user.type == "User"`) untrusted (D-53, D-80, D-104).
  - [x] 7.2 `[T]` [agents/bug-fix] L1 `tests/unit/test_neutralize.py`: closing keywords, `owner/repo#N`, issue URLs and `@mentions`, plus `hypothesis` property tests (D-65; references kept as written, `(ref <reference as written>)`, per the DF-186-01 amendment)
  - [x] 7.3 `[T]` [agents/bug-fix] L2 `tests/component/test_disposition.py`:
    - diagnosis comment plus 😕;
    - no label or assignee calls;
    - a second call makes zero writes;
    - no reaction when `trigger_comment_id` is absent;
    - the backstop applies only when ownership is confirmed (D-81, D-93).
  - [x] 7.4 `[I]` [agents/bug-fix] `markers.py` (D-53, D-80, D-104)
  - [x] 7.5 `[I]` [agents/bug-fix] `neutralize.py` (D-65, D-85)
  - [x] 7.6 `[I]` [agents/bug-fix] `issues.py`: comments and reactions (`eyes`, `rocket`, `confused`); a reaction 4xx is logged and not fatal
  - [x] 7.7 `[I]` [agents/bug-fix] `disposition.py` and the `signal_backstop.py` hook (10-second budget)
  - [x] 7.8 Edge cases: CRLF bodies; a diagnosis truncated to 65,536 characters
  - [x] 7.9 Verify AC (v2.0): AC1, AC2 and AC4 by 7.1–7.2; AC3, AC5 and AC6 by 7.3
  - [x] 7.10 Run tests: `make test`; agent gate; `make validate`; record `coverage_gate`
    > Local run done (2026-10-24, developer): agent `make validate` green (1136 passed, 3 xfailed, coverage 97.89%, `pip-audit` clean). `coverage_gate` is SKIPPED(no-delegation) here; the planner's `qa-engineer` records it.
  - [x] 7.11 `verifier` audit; open PR → `integration/bug-fix-agent-wave-a`

- [ ] ~~8.0 Implement Story S-187 (#369)~~ — **removed in v2.0** (D-90); linked-PR detection moved to 6.0; #369 closed as not planned.

- [x] 9.0 Implement Story S-188 (#370 - https://github.com/llipe/dev-tasks-agent-fleet/issues/370): Claim with the post-claim race check

  > Note: the claim is 👀 plus a marker comment, with no labels and no assignee (D-93). The race check stays (D-54).

  - [x] 9.1 `[T]` [agents/bug-fix] L1 race verdicts: an earlier terminal claim is ignored; an earlier active claim with no `pr`, `disposition` or `refusal` marker means this run lost (D-54; DF-33)
  - [x] 9.2 `[T]` [agents/bug-fix] L2 `tests/component/test_claim.py`, with the in-repo GitHub double (DF-186-02):
    - a happy claim: the marker comment first, then 👀;
    - a lost race: only this run's comment is deleted → `not_applicable`/`active_run`, with no board call;
    - a crash after the comment, once the run is terminal: a new run proceeds (AC-24);
    - a post-check `SUPABASE_UNAVAILABLE`: no disposition, `failed` (D-81).
  - [x] 9.3 `[I]` [agents/bug-fix] `config.py` and `agentcore.json`: `PANEL_BASE_URL`
  - [x] 9.4 `[I]` [agents/bug-fix] `claim.py`: claim, post-check, ownership gate
  - [x] 9.5 Edge cases: two comments in the same second; the other run already terminal; a reaction 422 (logged)
  - [x] 9.6 Verify AC (v2.0): AC1–AC5 by 9.1–9.2
  - [x] 9.7 Run tests: `make test`; agent gate; `make validate`; record `coverage_gate`
    > Local run done (2026-10-24, developer): agent `make validate` green (`ruff`, `ruff format --check`, `mypy`, `pytest --cov` 2271 passed, 3 xfailed, coverage 98%, `claim.py` 100%, `pip-audit` clean), with the known macOS-only `test_sandbox_proc.py::TestTimeoutReal::test_sigterm_ignored_child_is_killed_after_grace` deselected (#447). `coverage_gate` is SKIPPED(no-delegation) here; the planner's `qa-engineer` records it.
  - [x] 9.8 `verifier` audit; open PR → `integration/bug-fix-agent-wave-a`

- [x] 10.0 Implement Story S-189 (#371 - https://github.com/llipe/dev-tasks-agent-fleet/issues/371): Checkout, repository gate, toolchain, and the gate runner

  > Note: needs `sandbox.py` from 3.0. Resolves spec OQ-1 (Python install contract). No issue is changed before the repo gate passes (FR-5).

  - [x] 10.1 **Decide OQ-1 before 10.5:** for Python, require a `make install` target, or end `not_applicable` "missing install target" (the proposal). Append the result to `workstream/decisions-bug-fix-agent.md` as a new `D-NN`, with user confirmation (D-112, recorded via the docs write-back PR)
    > Confirmed by @llipe on 2026-10-24: Python repos need a `make install` target, which the wrapper runs in the sandbox; without it the run ends with refusal `repo_gate`, "missing install target", before any issue change (FR-5). JS stays `pnpm install --frozen-lockfile` or `npm ci`.
  - [x] 10.2 [agents/bug-fix] Fixture repos `tests/fixtures/repos/{js-pnpm-ok, js-missing-typecheck, py-make-ok, py-no-developer-md}`
  - [x] 10.3 `[T]` [agents/bug-fix] L1 `tests/unit/test_toolchain.py`: stack detection (pnpm, npm, Makefile, none), gate-name resolution, `Makefile` target parsing (`format_check` ≠ `format-check`) (D-17, D-19)
  - [x] 10.4 `[T]` [agents/bug-fix] L2 `tests/component/test_checkout.py` and `test_gates.py` with real `git`:
    - shallow clone and base SHA recorded;
    - repo gate pass and fail, naming the missing item;
    - per-gate `{pass, exit_code, tail}` with the tail scrubbed;
    - base results recorded, never blocking (D-06, D-14, D-19).
  - [x] 10.5 `[I]` [agents/bug-fix] `toolchain.py`: copy from `dependency-update`, add Python `Makefile` targets and the `.claude/agents/developer.md` check (D-06, D-18, D-19)
  - [x] 10.6 `[I]` [agents/bug-fix] `checkout.py`: clone into the wrapper clone and materialize `/work/repo` as `fixer` through `safe_git.py` (10.13–10.14, DF-02); install in the sandbox; a missing repo-gate item ends with refusal `repo_gate` through `refusal.py` (6.0, D-92); (JS `pnpm install --frozen-lockfile` or `npm ci`, Python per 10.1) (D-63); `CLONE_FAILED` and `INSTALL_FAILED` codes
  - [x] 10.7 `[I]` [agents/bug-fix] `gates.py`: the four gates plus `audit` through `sandbox.py`, with tails scrubbed (D-14)
  - [x] 10.8 Edge cases: a `package.json` with no `scripts`; a monorepo root `package.json`; a clone failure; an install failure
  - [x] 10.9 Verify AC (v1.4): AC1–AC3 by 10.12–10.16; AC4, AC5, AC7 and AC8 by 10.3 and 10.4; AC6 by the decision-log row from 10.1; AC9 by 10.17 (DF-24)
    > AC1: `test_checkout.py::TestClone`, `TestNoTokenAtRest`, image smoke (root 0700 clone). AC2: `test_git_confinement.py::TestHardened`, `tests/unit/test_safe_git.py` (static scan). AC3: `TestMaterialize`, `TestPlantedRepoNeverRuns`, image smoke (fixer-owned files, plants never run). AC4, AC5: `tests/unit/test_toolchain.py`, `test_checkout.py::TestRepoGate`. AC6: D-112 (docs write-back PR). AC7, AC8: `test_gates.py`, `test_checkout.py::TestBaseGates`. AC9: `test_checkout.py::TestInstall`, `TestRestoreBase`.
  - [x] 10.10 Run tests: `make test`; agent gate; `make validate`; record `coverage_gate`
    > Local run done (2026-10-24, developer): agent gate green (`ruff`, `ruff format --check`, `mypy`, `pytest --cov` 2579 passed, 3 xfailed, coverage 97.37%: `checkout.py` 95%, `safe_git.py` 93%, `gates.py` 96%, `toolchain.py` 96%, `refusal.py` 100%; `pip-audit` clean), with the known macOS-only `test_sandbox_proc.py::TestTimeoutReal::test_sigterm_ignored_child_is_killed_after_grace` deselected (#447). `coverage_gate` is SKIPPED(no-delegation) here; the planner's `qa-engineer` records it.
  - [x] 10.11 `verifier` audit; open PR → `integration/bug-fix-agent-wave-a`
  - [x] 10.12 `[T]` [agents/bug-fix] Do this before 10.9. L2 `tests/component/test_git_confinement.py`:
    - a `.git/hooks/{post-checkout,pre-commit}`, `core.fsmonitor`, `diff.external` and a filter driver planted in `/work/repo` never run in the root wrapper's git calls during checkout or capture (uid model per D-110);
    - every wrapper git call carries `GIT_CONFIG_NOSYSTEM=1`, `GIT_CONFIG_GLOBAL=/dev/null`, `core.hooksPath=/dev/null` and `core.fsmonitor=false`;
    - `safe.directory=*` is never set;
    - `capture()` includes untracked files and stores symlinks without following them (DF-02, DF-01, D-62).
  - [x] 10.13 `[I]` [agents/bug-fix] Do this before 10.9. `safe_git.py`:
    - a hardened git runner;
    - the wrapper clone at `/work/wrapper/repo`, mode 0700 (root-owned, uid model per D-110), with `info/exclude` listing only `node_modules/`, `.venv/`, `.pnpm-store/`, `__pycache__/` (D-83);
    - `materialize(tree, dest)`: `git archive` piped to `tar -x` running as `fixer`;
    - `capture(work_tree)`: `git --git-dir=<wrapper clone> --work-tree=<dir> add -A` (DF-02, D-62).
  - [x] 10.14 `[I]` [agents/bug-fix] Do this before 10.9. `checkout.py` clones into the wrapper clone and materializes the base tree into a fresh `/work/repo` as `fixer`. No wrapper git call targets a `fixer`-writable `.git` (DF-02, D-62)
  - [x] 10.15 `[I]` [agents/bug-fix] Dockerfile: `/work/wrapper` owned by root with mode 0700, unreadable by `fixer` (uid model per D-110; the `wrapper` user no longer exists). Extend `scripts/image-smoke.sh` to assert this (DF-02, D-62)
    > The Dockerfile already had `/work/wrapper` `root:root` 0700 (3.17). Added: build fails without git `--attr-source` (≥ 2.40), `/usr/bin/tar` or `/usr/bin/rm`. `image-smoke.sh` now runs `safe_git` end to end as root under `no_new_privs` and asserts TC-189-19. Local arm64 build: 53/53 checks passed (2026-10-24). Not deployed; the redeploy is S-190 via `infra-engineer`.
  - [x] 10.16 Verify AC: the S-189 v1.1 wrapper-clone and `safe_git.py` ACs by 10.12 and the 10.15 smoke check (DF-02, D-62)
  - [x] 10.17 `[T]` [agents/bug-fix] Do this before 10.9. L2 `tests/component/test_checkout.py`:
    - an npm fixture installs with `npm ci` and a pnpm fixture with `pnpm install --frozen-lockfile`;
    - an out-of-sync `package-lock.json` gives `INSTALL_FAILED`, and the lockfile is unchanged;
    - a base gate that rewrites a tracked file (an autofix lint) and creates an untracked file has both restored to base before the CLI step, with a `run_event`;
    - ignored `node_modules/` is left as it is (TC-189-14, TC-189-15) (DF-12, D-63).
  - [x] 10.18 `[I]` [agents/bug-fix] Do this before 10.9. `checkout.py`: install command per detected manager, and `restore_base()` after install and the base gates (capture → restore changed tracked paths as `fixer` through `safe_git.py`) (DF-12, D-63)
  - [x] 10.19 Verify AC: the S-189 v1.2 install and base-restore AC by 10.17 (DF-12, D-63)

- [x] 11.0 Implement Story S-190 (#372 - https://github.com/llipe/dev-tasks-agent-fleet/issues/372): Orchestration, outcome mapping, and reporting through the claim

  > Note: `FIX_LOOP_ENABLED=0`, so after a confirmed claim the run disposes with "fix loop not yet enabled". Only `failed` counts toward the breaker (D-20, D-61, D-67).

  - [x] 11.1 `[T]` [agents/bug-fix] L1 `tests/unit/test_outcomes.py`: one test per Wave A row of spec §8.9 v2.0 (every refusal code, a lost race, the D-67 codes, `GITHUB_PERMISSION_MISSING`); every `needs_review` and `not_applicable` result carries `result.summary`
  - [x] 11.2 `[T]` [agents/bug-fix] L2 `tests/component/test_main.py`:
    - one test per terminal path;
    - SIGTERM during `checkout` → no disposition;
    - SIGTERM after a confirmed claim → disposition;
    - a reporter flush failure never masks the outcome.
  - [x] 11.3 `[I]` [agents/bug-fix] `outcomes.py`
  - [x] 11.4 `[I]` [agents/bug-fix] `main.py`:
    - steps `preflight` → `refuse` → `checkout` → `claim` → `fix` (`fix` only when `FIX_LOOP_ENABLED=1`);
    - `run_steps` and `run_events`;
    - heartbeat and backstop;
    - `runs.metrics.issue_number` and step timings.
  - [x] 11.5 `[I]` [agents/bug-fix] `agentcore.json`: `FIX_LOOP_ENABLED=0`
  - [x] 11.6 [infra] Redeploy through `/infra-engineer`
  - [x] 11.7 Manual/IC: a manual invoke with an `issue_number` on the fixture repo claims (a marker comment, no reaction) and disposes ("fix loop not yet enabled"); the panel shows the steps and summary
  - [x] 11.8 Verify AC (v2.0): AC1 by 11.2; AC2 by 11.1; AC3 by 11.2; AC4 by the metrics assertion; AC5 by 11.7
    > AC1: `test_main.py::TestWaveAHappyPath`, `TestFixStep`, `TestRefusals` (steps and events per path). AC2: `test_outcomes.py` (TC-190-03/-04/-05/-12), `test_main.py::TestFaults`, `test_every_github_call_is_scoped_to_the_one_issue` (TC-190-11/-13). AC3: `test_main.py::TestOwnershipGate` (TC-190-06/-07/-08), `TestReporter` (heartbeat, flush failure), RT-07 (`test_claim_state_machine.py`). AC4: `test_main.py::TestMetrics` (TC-190-09). AC5: open; the planner's 11.6/11.7 through `/infra-engineer` (the runbook's "Wave A run" lists the expected result).
  - [x] 11.9 Run tests: `make test`; agent gate; `make validate`; record `coverage_gate`
    > Local run done (2026-10-24, developer): agent gate green (`ruff`, `ruff format --check`, `mypy`, `pytest --cov` 3020 passed, 5 xfailed, coverage 97%: `main.py` 97%, `outcomes.py` 99%, `run_link.py` 94%; `pip-audit` clean), with the known macOS-only `test_sandbox_proc.py::TestTimeoutReal::test_sigterm_ignored_child_is_killed_after_grace` deselected (#447). Image smoke 58/58 on a local arm64 build (not deployed). `coverage_gate` is SKIPPED(no-delegation) here; the planner's `qa-engineer` records it.
  - [x] 11.10 `verifier` audit; open PR → `integration/bug-fix-agent-wave-a`; roadmap Wave A row → `In progress` (set by `planner`)

## Decisions Consumed

| ID   | Decision (short form) |
| ---- | --------------------- |
| D-03 | Sibling AgentCore + Supabase reporting contract. |
| D-05 | Headless Claude Code inside a Python wrapper. |
| D-06 | No `developer.md` → refusal. |
| D-14 | Block on test, lint, format, typecheck; audit recorded. |
| D-19 | Canonical gate names. |
| D-20 | Only `failed` counts toward the breaker. |
| D-50 | CLI model via the Anthropic API key. |
| D-51 | Three-layer confinement; spike first. |
| D-53 | Hidden markers trusted by App id. |
| D-54 | Claim and post-claim race check. |
| D-55 | Linked PR = closing reference or `issue/<N>-` branch. |
| D-58 | One infra change; run-start Issues-write check. |
| D-62 | Wrapper git only on its own clone. |
| D-63 | Frozen install per manager; base restore. |
| D-65 | Model-text neutralizer. |
| D-67 | `GITHUB_UNAVAILABLE`, `GITHUB_REQUEST_REJECTED`, `SUPABASE_UNAVAILABLE`. |
| D-70 | `__probe` top-level, `ALLOW_PROBE` only. |
| D-80 | Leading marker block. |
| D-81 | Disposition and board only after confirmed ownership. |
| D-82 | The agent enforces schema bounds. |
| D-83 | Reject symlinks and gitlinks; parent-chain `lstat`. |
| D-85 | Neutralizer on every comment with model text. |
| D-88 | The webhook trigger supports `/bug-fix` by configuration. |
| D-92 | Refusal cases with a reply. |
| D-93 | Claim = reactions + marker comments; reduced params. |
| D-95 | `string-list` removed. |
| D-99 | Projects PAT, wrapper-only, best effort. |
| D-102 | Linked-board detection and status mapping. |
| D-104 | Marked refusal reply. |
| D-105 | Spike board probe on board #5. |
| D-110 | Root wrapper drops to `fixer` with `setpriv`; no `sudo`. |
| D-111 | `localhost` through NSS in the image. |
| D-112 | Python install is a `make install` target, else refusal `repo_gate` "missing install target" (OQ-1; recorded via the docs write-back PR). |
