# Implementation Plan — Bug Fix Agent, Wave A (Contract and claim)

> Execution plan for [`prd-bug-fix-agent`](../docs/requirements/prd-bug-fix-agent.md) v1.2 /
> [`specification-prd-bug-fix-agent`](specification-prd-bug-fix-agent.md) v1.2 /
> [`user-stories-prd-bug-fix-agent`](user-stories-prd-bug-fix-agent.md) v1.1.
> GitHub issues **#326–#335** (S-180…S-189). Waves B and C (#336–#349) get their own plan after the
> S-189 canary results are recorded, because those results decide CLI fixtures and flags.
>
> **Ordering is dependency-correct.** Each story is a branch → reviewed PR into
> `integration/bug-fix-agent`; the integration branch reaches `main` through one consolidated PR the
> user merges. **Test-first:** every `[T]` task precedes the `[I]` task it covers. `make validate`
> must pass before a PR is marked ready; `qa-engineer` (`coverage_gate`) then `verifier` audit run per
> story, pre-ready.

## Changelog

| Version | Date       | Summary                                        | Author           |
| ------- | ---------- | ---------------------------------------------- | ---------------- |
| 1.0     | 2026-10-19 | Initial Wave A task list (S-180–S-189).        | product-engineer |

## Conventions

- **Branches:** `story/S-180-package-scaffold`, … Integration branch: `integration/bug-fix-agent` (from `main`).
- **Commits:** Conventional Commits, referencing the issue (`feat(bug-fix): … (#326)`, `test(bug-fix): …`, `ci: …`, `docs(runbook): …`).
- **Package tags:** `docs/technical-guidelines.md` has no package map, so tasks use path tags: `[agents/bug-fix]`, `[supabase]`, `[infra]`, `[panel]` (Layer 2.5 tests live under `panel/tests/integration/`), `[repo root]` (CI, `TESTING.md`, runbooks).
- **Layers** (`TESTING.md`): L1 unit, L2 component (all external I/O faked), L2.5 integration (local Supabase, `REQUIRE_LOCAL_DB=1`). `[T]` = test-first, `[I]` = implementation, `[V]` = verification.
- **Quality gate** for the package: `cd agents/bug-fix/app/bugFix && make validate` (lint, format-check, typecheck, test, audit). Repo-wide: `make validate` at the root. `audit` is currently red on `main` for an unrelated reason being fixed in parallel; a pre-existing audit failure is recorded, not fixed, in these stories.
- **DoD per story:** tests first and passing · gates green · `coverage_gate` recorded · `verifier` audit (drift routed to `product-engineer`) · PR to `integration/bug-fix-agent` linking the issue.
- **User gates in this wave:** seed apply to the cloud project (3.x), every `infra-engineer` step (9.x), canary deployment (10.x).

## Relevant Files

- `agents/bug-fix/agentcore/agentcore.json` — runtime `bug_fix`, lifecycle, env vars
- `agents/bug-fix/app/bugFix/pyproject.toml`, `Makefile` — package and canonical targets
- `agents/bug-fix/app/bugFix/config.py` — constants, `assert_clock_invariant()`, `RunDeadline`
- `agents/bug-fix/app/bugFix/{agent_reporter,credentials,heartbeat,scrubber,signal_backstop}.py` — copied from the siblings
- `agents/bug-fix/app/bugFix/Dockerfile`, `managed-settings.json`, `mcp-empty.json` — image and CLI lockdown
- `agents/bug-fix/app/bugFix/main.py` — entrypoint, payload validation, orchestration, `determine_outcome`
- `agents/bug-fix/app/bugFix/github_api.py` — REST client, preflight
- `agents/bug-fix/app/bugFix/selection.py`, `toolchain.py` — selection, linked-PR index, applicability
- `agents/bug-fix/app/bugFix/claim.py` — claim, marker, disposition
- `agents/bug-fix/app/bugFix/sweep.py` — stale-claim sweep
- `agents/bug-fix/app/bugFix/canary.py` — gated canary probes
- `agents/bug-fix/app/bugFix/tests/{unit,component,fakes,fixtures}/` — L1/L2 tests, fake GitHub server, repo fixtures
- `panel/tests/integration/` — L2.5 seed and sweep-read tests
- `supabase/seed.sql` — block 5 `bug-fix` agent row
- `infra/agentcore-invoke-policy.json`, `infra/environments.yaml`, `infra/changes/<date>-bug-fix-agent/` — infra pass
- `.github/workflows/ci.yml` — `bug-fix` matrix entry, image-smoke job
- `TESTING.md`, `docs/runbooks/bug-fix-deployment.md`, `docs/runbooks/README.md`, `workstream/decisions-bug-fix-agent.md`

## Tasks

- [ ] 1.0 Implement Story S-180 (#326 — https://github.com/llipe/dev-tasks-agent-fleet/issues/326): Package scaffold, configuration, clock invariant, and CI
  > Branch `story/S-180-package-scaffold`. Depends on: none.
  - [ ] 1.1 [agents/bug-fix] `[T]` L1 `tests/unit/test_config.py`: invariant passes on shipped defaults; each relation (`0 < HEARTBEAT <= IDLE/2`, `CLONE+INSTALL+CLI+RESERVE <= MAX_LIFETIME`, `MAX_LIFETIME <= REAPER`, `GATE <= CLI`) fails when its operand is perturbed (D-30, D-33)
  - [ ] 1.2 [agents/bug-fix] `[T]` L1 `RunDeadline` with a fake monotonic clock: before, at, after the deadline; `step_timeout(cap) = min(cap, remaining)`; exhausted budget signalled; deadline already past at construction (D-30)
  - [ ] 1.3 [agents/bug-fix] `[T]` L1 hash-parity test: vendored `agent_reporter.py` byte-identical to the sibling copy (D-26)
  - [ ] 1.4 [agents/bug-fix] `[I]` Scaffold `agents/bug-fix/` from the sibling layout: `agentcore/agentcore.json` (runtime `bug_fix`, Container, `PYTHON_3_14`, `maxLifetime` 3600, `idleRuntimeSessionTimeout` 900; env `MODEL_ID=claude-sonnet-5-5`, `SUPABASE_URL`, `SUPABASE_KEY_SECRET_ID`, `ANTHROPIC_KEY_SECRET_ID`, `OPERATOR_GITHUB_LOGIN`, `FIX_PIPELINE_ENABLED=0`), `pyproject.toml`, `Makefile` with canonical targets (D-26, D-40, D-43)
  - [ ] 1.5 [agents/bug-fix] `[I]` `config.py`: constants from spec §11.1, `assert_clock_invariant()`, `RunDeadline`; comment citing D-30 for the omitted `step <= idle` relation (D-30)
  - [ ] 1.6 [agents/bug-fix] `[I]` Copy `heartbeat.py`, `scrubber.py`, `signal_backstop.py`, `credentials.py`, `agent_reporter.py` unchanged from `security-analyst` (D-03)
  - [ ] 1.7 [repo root] `[I]` `.github/workflows/ci.yml`: add `bug-fix` to the `python-quality` matrix (3.13, 3.14)
  - [ ] 1.8 [repo root] `[I]` `TESTING.md`: package row (runner, command, environment)
  - [ ] 1.9 `[V]` Verify AC: `agentcore.json` and `Makefile` present with the listed values
  - [ ] 1.10 `[V]` Verify AC: invariant raises `ClockConsistencyError` for each violated relation (AC-18)
  - [ ] 1.11 `[V]` Verify AC: `RunDeadline` semantics (FR-31)
  - [ ] 1.12 `[V]` Verify AC: reporter hash parity; CI matrix green on 3.13 and 3.14; `TESTING.md` row present
  - [ ] 1.13 `[V]` AC-to-test mapping recorded in the PR body; edge cases (zero/negative heartbeat, `MAX_LIFETIME == REAPER`, past deadline) covered
  - [ ] 1.14 Run `make validate` (package); record `coverage_gate`; `verifier` audit; PR → `integration/bug-fix-agent`

- [ ] 2.0 Implement Story S-181 (#327 — https://github.com/llipe/dev-tasks-agent-fleet/issues/327): Container image, pinned Claude Code CLI, managed settings
  > Branch `story/S-181-image-managed-settings`. Depends on: S-180.
  - [ ] 2.1 [agents/bug-fix] `[T]` L1 `tests/unit/test_managed_settings.py`: deny rules `Bash(git push *)`, `Bash(gh *)`, `WebFetch`, `WebSearch`; `disableBypassPermissionsMode: "disable"`; `allowManagedHooksOnly: true`; `allowManagedMcpServersOnly: true`; `allowManagedPermissionRulesOnly` absent; `mcp-empty.json` is `{"mcpServers":{}}` (D-29)
  - [ ] 2.2 [repo root] `[T]` CI `image-smoke` job (failing first): builds ARM64; asserts `claude --version` equals the pinned ARG, both managed files present with expected content and non-writable mode, `id -u` non-zero
  - [ ] 2.3 [agents/bug-fix] `[I]` `Dockerfile`: ECR-mirror `python:3.13-slim` base, CA placeholder, `git`, `gh`, Node 22, pnpm via corepack, npm, `@anthropic-ai/claude-code@${CLAUDE_CODE_VERSION}`, `DISABLE_UPDATES=1`, non-root user, writable workspace (D-28)
  - [ ] 2.4 [agents/bug-fix] `[I]` `managed-settings.json` and `mcp-empty.json`, installed to `/etc/claude-code/` (D-29)
  - [ ] 2.5 [repo root] `[I]` Runbook stub `docs/runbooks/bug-fix-deployment.md`: pinned CLI version and bump procedure (FR-49a)
  - [ ] 2.6 `[V]` Verify AC: ARM64 build with every listed component
  - [ ] 2.7 `[V]` Verify AC: managed-settings content and empty MCP config
  - [ ] 2.8 `[V]` Verify AC: non-root runtime; managed files not writable by the runtime user
  - [ ] 2.9 `[V]` Verify AC: image-smoke assertions pass in CI; pinned version recorded in the runbook stub
  - [ ] 2.10 `[V]` Edge cases: missing build ARG fails the build; omitted optional native deps fail smoke; manual `docker run --rm <image> claude --version`
  - [ ] 2.11 Run `make validate`; image-smoke green; record `coverage_gate`; `verifier` audit; PR

- [ ] 3.0 Implement Story S-182 (#328 — https://github.com/llipe/dev-tasks-agent-fleet/issues/328): Agent registration, params schema, payload validation
  > Branch `story/S-182-agent-registration`. Depends on: S-180. **Seed apply to the cloud project needs user confirmation.**
  - [ ] 3.1 [agents/bug-fix] `[T]` L1 `tests/unit/test_payload.py`: unknown params, out-of-range values (`issue_number` 0/negative, `max_turns` 4/101, caps outside spec §5.1 ranges), empty `assignee`, double-wrapped payload → `INVALID_PARAMS` (D-26)
  - [ ] 3.2 [agents/bug-fix] `[T]` L1 `resolve_assignee` order: param → `OPERATOR_GITHUB_LOGIN` → `INVALID_PARAMS` (D-35)
  - [ ] 3.3 [panel] `[T]` L2.5 seed test: `supabase db reset` twice → exactly one `bug-fix` row, values unchanged; `max_runtime_seconds` equals `MAX_LIFETIME` (3600)
  - [ ] 3.4 [supabase] `[I]` `supabase/seed.sql` block 5: `bug-fix` row (name "Bug Fix", version 0.1.0, `requires_repository` true, 3600/150/300, `default_params`, `params_schema` with `additionalProperties:false` and the seven params) with `on conflict (slug) do update` (D-09, D-22, D-31, D-35)
  - [ ] 3.5 [agents/bug-fix] `[I]` `main.py` helpers: `unwrap_payload`, `validate_payload`, `apply_defaults`, `classify_invalid_payload`, `resolve_assignee` (D-26, D-35)
  - [ ] 3.6 [supabase] Migration lifecycle (data row, no DDL): rollback note `delete from agents where slug='bug-fix'`; **request user confirmation**; apply to the cloud project; verify with `select slug, max_runtime_seconds from agents where slug='bug-fix'`
  - [ ] 3.7 `[V]` Verify AC: seed idempotent; schema shape; validation rejects; assignee order; parity test
  - [ ] 3.8 `[V]` Manual: panel invoke form renders the schema for `bug-fix`
  - [ ] 3.9 Run `make validate` and `pnpm run test:integration` (seed test, `REQUIRE_LOCAL_DB=1`); record `coverage_gate`; `verifier` audit; PR

- [ ] 4.0 Implement Story S-183 (#329 — https://github.com/llipe/dev-tasks-agent-fleet/issues/329): GitHub REST client and permission preflight
  > Branch `story/S-183-github-client-preflight`. Depends on: S-180.
  - [ ] 4.1 [agents/bug-fix] `[T]` `tests/fakes/fake_github.py`: in-process fake GitHub HTTP server (issues, labels, comments, assignees, pulls, `GET /app`, pagination via `Link`)
  - [ ] 4.2 [agents/bug-fix] `[T]` L1 `tests/unit/test_github_api.py`: retry ladder 2/4/8 s with fake sleep on 403-remaining-0, 429, 5xx; no retry on other 4xx; secondary-rate-limit 403 distinguished from permission 403; pagination with and without `Link`; PR filtering by `pull_request` key
  - [ ] 4.3 [agents/bug-fix] `[T]` L2 `tests/component/test_preflight.py`: 403 on issues → run `failed` / `GITHUB_PERMISSION_DENIED` with zero mutating calls (AC-17)
  - [ ] 4.4 [agents/bug-fix] `[T]` L1 scrubber test: installation token absent from logs, exceptions, events
  - [ ] 4.5 [agents/bug-fix] `[I]` `github_api.py`: every call in spec §6.2, pagination, retries, `GitHubPermissionDenied`; `GET /app` slug cached per run (D-25, D-36)
  - [ ] 4.6 [agents/bug-fix] `[I]` `preflight()` (one issues page, one labels page) and the `GITHUB_PERMISSION_DENIED` error code in the return payload (D-25)
  - [ ] 4.7 `[V]` Verify AC: §6.2 coverage; retry semantics; preflight fails before any mutation; slug cached; no token leakage
  - [ ] 4.8 `[V]` Edge cases: empty pages, token expiry mid-pagination
  - [ ] 4.9 Run `make validate`; record `coverage_gate`; `verifier` audit; PR

- [ ] 5.0 Implement Story S-184 (#330 — https://github.com/llipe/dev-tasks-agent-fleet/issues/330): Selection, linked-PR index, and applicability gate
  > Branch `story/S-184-selection-applicability`. Depends on: S-183.
  - [ ] 5.1 [agents/bug-fix] `[T]` L1 `tests/unit/test_selection.py`: oldest by `created_at` among open `type: bug` + `status: ready`; equal timestamps; zero ready bugs → `no_findings`; all ready bugs with open PRs (AC-1, D-10)
  - [ ] 5.2 [agents/bug-fix] `[T]` L1 linked-PR index: head ref `^issue/(\d+)-`; closing keywords (`Closes #12`, `fixes #12`; `#120` must not match `#12`); PR referencing several issues (D-37)
  - [ ] 5.3 [agents/bug-fix] `[T]` L1 explicit `issue_number`: `not_open`, `missing_label:<label>`, `open_pr:#<n>`, `is_pull_request`, each with no mutation (AC-2, D-10)
  - [ ] 5.4 [agents/bug-fix] `[T]` L1 `tests/unit/test_applicability.py` with `tests/fixtures/repos/`: JS/TS scripts (`test`, `lint`, `format:check`, `typecheck`), Python Makefile targets (`test`, `lint`, `format-check`, `typecheck`), missing `developer.md`, missing gate, `test-unit` without `test`, both stacks present → JS/TS rule (AC-4, D-06, D-18, D-19)
  - [ ] 5.5 [agents/bug-fix] `[I]` Port `toolchain.py` from `dependency-update` (`detect_package_manager`, `detect_scripts`) and add Makefile target detection (D-17, D-19)
  - [ ] 5.6 [agents/bug-fix] `[I]` `selection.py`: one paginated `GET /pulls?state=open`, linked-PR index, ordering, explicit-issue checks, reason strings (D-10, D-37)
  - [ ] 5.7 [agents/bug-fix] `[I]` Reason strings wired into the return payload and run events
  - [ ] 5.8 `[V]` Verify AC: FR-2, FR-3, FR-4, FR-5, FR-6 behaviors; package-manager precedence `packageManager` → `pnpm-lock.yaml` → `package-lock.json`
  - [ ] 5.9 Run `make validate`; record `coverage_gate`; `verifier` audit; PR

- [ ] 6.0 Implement Story S-185 (#331 — https://github.com/llipe/dev-tasks-agent-fleet/issues/331): Claim, claim marker, and disposition protocol
  > Branch `story/S-185-claim-protocol`. Depends on: S-183.
  - [ ] 6.1 [agents/bug-fix] `[T]` L1 `tests/unit/test_claim.py`: marker build/parse round-trip; `parse_claim` accepts only `<app_slug>[bot]` with type `Bot`; human and other-app comments with the same marker return nothing (D-36)
  - [ ] 6.2 [agents/bug-fix] `[T]` L1 `dispose`: reason code, scrubbed diagnosis truncated at 2000 chars, `disposed=<reason>` in the marker, idempotent on an issue already `needs-refinement` (D-08)
  - [ ] 6.3 [agents/bug-fix] `[T]` L2 `tests/component/test_claim_flow.py` on the fake GitHub: exact order assign → add `in-progress` → remove `ready` → comment; bot never assigned (AC-3, FR-8, D-07)
  - [ ] 6.4 [agents/bug-fix] `[T]` L2 partial failure: comment POST fails after labels changed → one retry of remaining actions → second failure raises `GITHUB_API_ERROR`
  - [ ] 6.5 [agents/bug-fix] `[I]` `claim.py`: `claim()`, `build_marker()`, `parse_claim()`, `dispose()`; mutating client calls only here (D-07, D-08, D-36)
  - [ ] 6.6 [repo root] `[I]` Runbook note: manual repair of a partially claimed issue (spec §8.4)
  - [ ] 6.7 `[V]` Verify AC: claim order, marker authentication, disposition content and idempotency, partial-failure path, no bot assignee
  - [ ] 6.8 `[V]` Edge cases: assignee 422, label already present, secret in diagnosis scrubbed; manual: rendered comment on a fixture issue (marker hidden)
  - [ ] 6.9 Run `make validate`; record `coverage_gate`; `verifier` audit; PR

- [ ] 7.0 Implement Story S-186 (#332 — https://github.com/llipe/dev-tasks-agent-fleet/issues/332): Stale-claim sweep
  > Branch `story/S-186-stale-claim-sweep`. Depends on: S-185.
  - [ ] 7.1 [agents/bug-fix] `[T]` L1 `tests/unit/test_sweep.py`: decision matrix over `effective_status` (`failed`, `timed_out`, `failed_to_start`, `canceled`, `queued`, `running`) × PR artifact present × marker valid (D-16, D-36)
  - [ ] 7.2 [agents/bug-fix] `[T]` L2 `tests/component/test_sweep_flow.py` (fake GitHub + fake PostgREST): stale claim disposed with `STALE_CLAIM`; own current claim never swept; unmarked, foreign-author, and live-run claims untouched; per-issue error isolated as a warning (AC-13)
  - [ ] 7.3 [panel] `[T]` L2.5 read test: batched `v_runs?id=in.(…)&select=id,effective_status` and `run_artifacts?run_id=in.(…)&type=eq.pull_request` against seeded runs (spec §5.3)
  - [ ] 7.4 [agents/bug-fix] `[I]` `sweep.py`: list `in-progress` issues, parse claims, two batched reads, dispose stale ones (D-16)
  - [ ] 7.5 `[V]` Verify AC: all five story ACs
  - [ ] 7.6 `[V]` Edge cases: run ID absent from Supabase, 200 in-progress issues (pagination), two claim comments (latest wins), `running` past the reaper threshold
  - [ ] 7.7 Run `make validate` and `pnpm run test:integration`; record `coverage_gate`; `verifier` audit; PR

- [ ] 8.0 Implement Story S-187 (#333 — https://github.com/llipe/dev-tasks-agent-fleet/issues/333): Orchestrator through applicability, reporting, and outcome mapping
  > Branch `story/S-187-orchestrator-wave-a`. Depends on: S-184, S-185, S-186.
  - [ ] 8.1 [agents/bug-fix] `[T]` L1 `tests/unit/test_outcome.py`: `determine_outcome` table of spec §8.8; ceilings → `needs_review`; non-limit CLI faults → `failed` (FR-26, D-20)
  - [ ] 8.2 [agents/bug-fix] `[T]` L2 `tests/component/test_flow_wave_a.py`: no ready bug → `no_findings`; not applicable; preflight denied → `failed`; sweep disposes a stale claim then proceeds; flag off → `not_applicable` "fix pipeline not enabled" with **no claim** (spec §15.1)
  - [ ] 8.3 [agents/bug-fix] `[T]` L2 startup: inconsistent clock config refuses to start; token never in clone URL or logs
  - [ ] 8.4 [agents/bug-fix] `[I]` `main.py` `@app.entrypoint`: steps `resolve_credentials`, `preflight`, `sweep`, `select`, `checkout` (clone + applicability); return payload of spec §6.1; error codes of spec §13
  - [ ] 8.5 [agents/bug-fix] `[I]` `FIX_PIPELINE_ENABLED` handling (default off in code and `agentcore.json`) (spec §15.1)
  - [ ] 8.6 [agents/bug-fix] `[I]` Wire `assert_clock_invariant()` first, heartbeat, `install_termination_backstop`, scrubbing of every event; port `clone_repo` with the credential helper (D-30)
  - [ ] 8.7 `[V]` Verify AC: all six story ACs
  - [ ] 8.8 `[V]` Edge cases: SIGTERM mid-sweep, Supabase unreachable (stderr fallback), clone failure, double-wrapped payload
  - [ ] 8.9 Run `make validate`; record `coverage_gate`; `verifier` audit; PR

- [ ] 9.0 Implement Story S-188 (#334 — https://github.com/llipe/dev-tasks-agent-fleet/issues/334): Operator prerequisites, infra pass, and Wave A deploy
  > Branch `story/S-188-infra-deploy`. Depends on: S-181, S-182, S-187. **Runs through `infra-engineer`; every step needs user approval.**
  - [ ] 9.1 [infra] `[T]` Repo test: the invoke policy lists both the runtime ARN and `/runtime-endpoint/DEFAULT` for every runtime in `environments.yaml` (issue #280)
  - [ ] 9.2 [infra] Plan the change record `infra/changes/<date>-bug-fix-agent/` with `infra-engineer` (backup and revert per step)
  - [ ] 9.3 [infra] **User step:** add Issues read/write to the GitHub App; installation owner accepts; evidence recorded (D-25)
  - [ ] 9.4 [infra] **User step:** create the dedicated Anthropic key in its own Console workspace with a monthly spend limit; store as `agent-fleet/prod/ANTHROPIC_API_KEY`; verify one call with `claude-sonnet-5-5` (D-42, D-43)
  - [ ] 9.5 [infra] Set `OPERATOR_GITHUB_LOGIN` in the runtime env (D-35)
  - [ ] 9.6 [infra] Runtime role: siblings' Secrets Manager reads plus the Anthropic key secret; **no** Bedrock permissions (D-40, D-42)
  - [ ] 9.7 [infra] Deploy the Wave A image (`FIX_PIPELINE_ENABLED=0`); record the runtime ARN
  - [ ] 9.8 [infra] Update `infra/agentcore-invoke-policy.json` and the live policy with the runtime ARN and endpoint ARN; update `infra/environments.yaml`
  - [ ] 9.9 [supabase] Set `runtime_arn` in seed block 5; **request user confirmation**; apply; verify
  - [ ] 9.10 [repo root] `docs/runbooks/bug-fix-deployment.md`: prerequisites, key and rotation, deploy, rollback (`agents.is_enabled=false`, revert policy entry, redeploy previous image); index in `docs/runbooks/README.md` (FR-49a)
  - [ ] 9.11 `[V]` Verify AC: panel invoke reaches `running` and ends `succeeded` with "fix pipeline not enabled" or `no_findings` on a fixture repo
  - [ ] 9.12 `[V]` Edge cases: policy without endpoint ARN → 403; App permission not accepted → `GITHUB_PERMISSION_DENIED`; `OPERATOR_GITHUB_LOGIN` unset → `INVALID_PARAMS`; key secret missing → credential `failed`
  - [ ] 9.13 Run `make validate` (root); record `coverage_gate`; `verifier` audit; PR

- [ ] 10.0 Implement Story S-189 (#335 — https://github.com/llipe/dev-tasks-agent-fleet/issues/335): Canary mode and the Wave A canary run
  > Branch `story/S-189-canary`. Depends on: S-188. **Gate for Wave B and for any schedule.**
  - [ ] 10.1 [agents/bug-fix] `[T]` L1 `tests/unit/test_canary.py`: `canary` param rejected unless `ALLOW_CANARY=1`; results redact secret values, tokens, and the Anthropic key (spec §15.1, D-27)
  - [ ] 10.2 [agents/bug-fix] `[T]` L2 each probe with a fake child process
  - [ ] 10.3 [agents/bug-fix] `[I]` `canary.py` `credentials`: from a child process, try role credentials (env and container endpoint), `GetSecretValue` for the Supabase and App-key secrets; confirm the child sees no AWS variables (D-27, D-41)
  - [ ] 10.4 [agents/bug-fix] `[I]` `canary.py` `idle_survival`: silent 20-minute heartbeated step (D-30)
  - [ ] 10.5 [agents/bug-fix] `[I]` `canary.py` `cli_flags`: CLAUDE.md and `developer` load under the lockdown flags; max-turns subtype and exit code; `num_turns`/`is_error`; `plan` under `-p`; `api.anthropic.com` reachable with the key and `MODEL_ID` (D-28, D-29, D-31, D-41)
  - [ ] 10.6 [infra] **User step:** deploy the canary build with `ALLOW_CANARY=1`; run the three probes from the panel
  - [ ] 10.7 [repo root] Record results in the runbook and as new `D-NN` rows; update spec §12.4 and PRD §18
  - [ ] 10.8 [infra] Redeploy production without `ALLOW_CANARY`
  - [ ] 10.9 `[V]` Decision gate: if a child process can read the secrets, create the credential-isolation story and mark it as blocking S-202 (#348)
  - [ ] 10.10 `[V]` Edge cases: `ALLOW_CANARY` unset, invalid or revoked key, secret read denied, CLI missing
  - [ ] 10.11 Run `make validate`; record `coverage_gate`; `verifier` audit; PR
  - [ ] 10.12 Hand-off: plan Waves B and C (#336–#349) with the canary findings

- [ ] 11.0 Wave A close-out
  - [ ] 11.1 Consolidated PR `integration/bug-fix-agent` → `main` (user merges)
  - [ ] 11.2 `docs/roadmap.md`: Wave A row → `In progress`/`Done` per merged state (planner owns the update)

## Decisions Consumed

| ID   | Decision (short form) |
| ---- | --------------------- |
| D-03 | Sibling AgentCore + Supabase reporting contract. |
| D-06 | No `developer.md` → `not_applicable`. |
| D-07 | Claim = assign + `in-progress` + marked comment. |
| D-08 | Disposition: diagnosis comment + `needs-refinement`. |
| D-09 | Size caps (params). |
| D-10 | Oldest ready bug; explicit number keeps the label gate. |
| D-16 | Stale-claim sweep. |
| D-17 | Toolchain detection precedent. |
| D-18 | JS/TS and Python. |
| D-19 | Gate contract (scripts / Make targets). |
| D-20 | Outcome mapping; only `failed` counts toward G3. |
| D-22 | Budgets (turns, CLI, run). |
| D-25 | App lacks Issues write; preflight. |
| D-26 | Package layout and touchpoints. |
| D-27 | Trust anchor; credential spike. |
| D-28 | Claude Code CLI facts and unverified items. |
| D-29 | Hooks and MCP disabled; managed settings. |
| D-30 | Run-level deadline; relaxed invariant. |
| D-31 | `--agent developer`; task list sources. |
| D-33 | Install step joins the clock budget. |
| D-35 | Default assignee from `OPERATOR_GITHUB_LOGIN`. |
| D-36 | Claim marker plus App-bot author check. |
| D-37 | Linked-PR detection. |
| D-40 | Anthropic API, no Bedrock. |
| D-41 | CLI auth by `ANTHROPIC_API_KEY`; no AWS vars. |
| D-42 | Dedicated key with spend limit. |
| D-43 | `MODEL_ID` default `claude-sonnet-5-5`. |
