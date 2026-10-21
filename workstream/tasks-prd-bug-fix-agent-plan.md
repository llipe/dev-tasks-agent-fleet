# Implementation Plan - Bug Fix Agent (Wave A)

> Execution plan for [`prd-bug-fix-agent`](../docs/requirements/prd-bug-fix-agent.md) v1.4 /
> [`specification-prd-bug-fix-agent`](specification-prd-bug-fix-agent.md) v1.5 /
> [`user-stories-prd-bug-fix-agent`](user-stories-prd-bug-fix-agent.md) v1.5.
> **Scope: Wave A only.** GitHub issues **#362–#372** (S-180…S-190), milestone `v5.0 — Phase 5 Bug Fix Agent`.
> Waves B (#373–#377) and C (#378–#380) are planned separately, after the S-182 spike verdict.
>
> **Ordering is dependency-correct.** Each story is a branch with a reviewed PR into
> `integration/bug-fix-agent`. The integration branch reaches `main` through a single reviewed PR at
> the end. Human review is the gate, and no agent merges to `main`. **Test-first:** a `[T]` task
> MUST precede its `[I]` task.

## Changelog

| Version | Date       | Summary                                                    | Author           |
| ------- | ---------- | ---------------------------------------------------------- | ---------------- |
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
- **Execution order:** 1.0 → 2.0 → 3.0 → 5.0 → 6.0 → {7.0, 8.0} → 9.0 → 10.0 → 11.0. Task 4.0 runs in parallel at any point.
- **Task 0 is not needed.** `agents/bug-fix/` is a new component, but S-180 (task 1.0) is its setup task.

## Relevant Files

- `agents/bug-fix/agentcore/agentcore.json` - Runtime config: env, `maxLifetime` 3600, `FIX_LOOP_ENABLED`, `PANEL_BASE_URL`
- `agents/bug-fix/app/bugFix/Dockerfile` - ARM64 image: Python 3.13, Node 26 + pnpm, git, bubblewrap, socat, pinned Claude Code
- `agents/bug-fix/app/bugFix/managed-settings.json` - Managed Claude Code policy, installed at `/etc/claude-code/`
- `agents/bug-fix/app/bugFix/{Makefile,pyproject.toml}` - Agent quality gates
- `agents/bug-fix/app/bugFix/{agent_reporter,heartbeat,signal_backstop,scrubber,credentials}.py` - Copied sibling modules (extended)
- `agents/bug-fix/app/bugFix/config.py` - Typed env config
- `agents/bug-fix/app/bugFix/main.py` - Entrypoint and step orchestration
- `agents/bug-fix/app/bugFix/outcomes.py` - Outcome mapping (spec §8.9)
- `agents/bug-fix/app/bugFix/sandbox.py` - `fixer` subprocess spawner (minimal env, sandbox, timeouts)
- `agents/bug-fix/app/bugFix/probe.py` - Spike probe mode
- `agents/bug-fix/app/bugFix/params.py` - Typed params and cross-field label rules
- `agents/bug-fix/app/bugFix/preflight.py` - Permission, label and assignee checks
- `agents/bug-fix/app/bugFix/issues.py` - GitHub issue I/O (REST and GraphQL)
- `agents/bug-fix/app/bugFix/markers.py` - Claim and disposition markers
- `agents/bug-fix/app/bugFix/disposition.py` - Idempotent disposition
- `agents/bug-fix/app/bugFix/select.py` - Selection
- `agents/bug-fix/app/bugFix/claim.py` - Claim and race check
- `agents/bug-fix/app/bugFix/toolchain.py` - Stack detection and repo gate (copied from `dependency-update`, extended)
- `agents/bug-fix/app/bugFix/checkout.py` - Clone and install
- `agents/bug-fix/app/bugFix/gates.py` - Gate runner
- `agents/bug-fix/app/bugFix/scripts/image-smoke.sh` - Image assertions
- `agents/bug-fix/app/bugFix/tests/{unit,component,fixtures}/**` - Agent tests and fixture repos
- `agents/bug-fix/{README.md,AGENTS.md}` - Agent docs
- `panel/lib/schema/form.ts` - `string-list` control mapping
- `panel/components/invoke/FieldRow.tsx` (+ CSS module) - String List rendering
- `panel/components/invoke/InvokeDialog.tsx`, `panel/components/schedules/ScheduleDialog.tsx` - Pre-fill and submit arrays
- `panel/tests/{unit,component,integration,e2e}/**` - Panel tests (`form.test.ts`, `schedules-string-list.spec.ts`, `bug-fix-seed.test.ts`)
- `DESIGN.md` - §3.11 String List, plus notes in §5.4 and §5.7
- `supabase/migrations/<ts>_seed_bug_fix_agent.sql`, `supabase/seed.sql` - `agents` row
- `infra/changes/<date>-bug-fix-runtime/` - Infra change record
- `docs/runbooks/bug-fix-agent.md` - Runbook stub (completed in Wave C)
- `workstream/spike-bug-fix-sandbox.md` - Spike report
- `workstream/decisions-bug-fix-agent.md` - Append for OQ-1

## Tasks

- [ ] 1.0 Implement Story S-180 (#362 - https://github.com/llipe/dev-tasks-agent-fleet/issues/362): Agent scaffold, image, and managed Claude Code policy

  > Note: skeleton only. `main.py` ends `succeeded`/`not_applicable` "not yet implemented", so a deploy is harmless.

  - [ ] 1.1 `[T]` [agents/bug-fix] L1 `tests/unit/test_scrubber.py` (the Anthropic key is redacted) and `tests/unit/test_config.py` (reads `MODEL_ID`, `SUPABASE_KEY_SECRET_ID`, `ANTHROPIC_KEY_SECRET_ID`; a missing var raises a typed error with no values in the message) (D-50)
  - [ ] 1.2 `[T]` [agents/bug-fix] L1 `tests/unit/test_main_stub.py`: the entrypoint reports `started`, then `succeeded`/`not_applicable` "not yet implemented"
  - [ ] 1.3 `[I]` [agents/bug-fix] Create the layout: `agentcore/agentcore.json`, `app/bugFix/{main.py, config.py, Dockerfile, Makefile, pyproject.toml}`, `README.md`, `AGENTS.md` (D-03)
  - [ ] 1.4 `[I]` [agents/bug-fix] Copy `agent_reporter.py`, `heartbeat.py`, `signal_backstop.py`, `scrubber.py`, `credentials.py` from `security-analyst`, each with a source and commit header. Add the Anthropic key to the scrubber's secrets (D-03, D-50)
  - [ ] 1.5 `[I]` [agents/bug-fix] `config.py` and the minimal `main.py`
  - [ ] 1.6 `[I]` [agents/bug-fix] `agentcore.json`: runtime `bug_fix`, `Container`, `PUBLIC`, `maxLifetime: 3600`, envs `SUPABASE_URL`, `SUPABASE_KEY_SECRET_ID`, `ANTHROPIC_KEY_SECRET_ID=agent-fleet/prod/ANTHROPIC_API_KEY`, `MODEL_ID` (a Sonnet id on the Anthropic API). No Bedrock reference (D-50)
  - [ ] 1.7 `[I]` [agents/bug-fix] Dockerfile (ARM64): Python 3.13, Node 26 + pnpm, git, `bubblewrap`, `socat`, pinned `@anthropic-ai/claude-code`; users `wrapper` and `fixer` with different uids; `/work/repo` and `/work/out` owned by `fixer`; `/home/fixer` (D-05, D-18, D-51)
  - [ ] 1.8 `[I]` [agents/bug-fix] `managed-settings.json`, root-owned with mode 0644, at `/etc/claude-code/`:
    - sandbox enabled;
    - registry-only network: `registry.npmjs.org`, `registry.yarnpkg.com`, `pypi.org`, `files.pythonhosted.org`;
    - denies `Bash(git push:*)`, `Bash(gh:*)`, `Bash(curl:*)`, `Bash(wget:*)`, `WebFetch`, `WebSearch`, and Read/Edit of `/proc/**`, `/etc/claude-code/**`, `/work/secrets/**`;
    - key names are provisional until 3.0 (D-51).
  - [ ] 1.9 `[I]` [agents/bug-fix] `scripts/image-smoke.sh` and `make image`. The smoke script asserts that `id fixer` ≠ `id wrapper`, that `claude --version` and `bwrap --version` work, and that the policy file is owned by root with mode 0644
  - [ ] 1.10 Edge cases: each missing env var gives a typed error, never a traceback that contains values
  - [ ] 1.11 Verify AC: layout and copied modules (AC1–AC2); `agentcore.json` envs with no Bedrock (AC3); ARM64 build with the toolchain (AC4); users and dirs (AC5); policy ownership and content (AC6); stub entrypoint (AC7). Map each to 1.1, 1.2 or 1.9
  - [ ] 1.12 Run tests: `make test`, `make image`, `scripts/image-smoke.sh`; agent gate; `make validate`; record `coverage_gate`
  - [ ] 1.13 `verifier` audit; open PR → `integration/bug-fix-agent`

- [ ] 2.0 Implement Story S-181 (#363 - https://github.com/llipe/dev-tasks-agent-fleet/issues/363): Infra change — Anthropic key, runtime and role, panel invoke policy, App Issues write

  > Note: run with `/infra-engineer`. One approval per step; each step reversible and recorded. No secret value is ever logged or committed (D-58).

  - [ ] 2.1 [infra] Open the change record `infra/changes/<date>-bug-fix-runtime/` with a plan, plus backup and revert steps for each item
  - [ ] 2.2 [infra] **Operator action:** create a dedicated Anthropic API key with a spend cap. Store it as `agent-fleet/prod/ANTHROPIC_API_KEY` in Secrets Manager. Record the cap, never the key (D-50, D-58)
  - [ ] 2.3 [infra] Runtime role: `secretsmanager:GetSecretValue` on exactly the Supabase key, App PEM and Anthropic key ARNs, with no `bedrock:*` (D-58)
  - [ ] 2.4 [infra] `agentcore deploy` the 1.0 image. Record the runtime ARN from `agentcore status`
  - [ ] 2.5 [infra] Panel `invoke-runtime` policy: add the runtime ARN and its `runtime-endpoint/DEFAULT` (issue #280) (D-58)
  - [ ] 2.6 [infra] **Operator action:** GitHub App → **Issues: read and write**, then accept the change on every installation in `github_installations` (D-58)
  - [ ] 2.7 [infra] Verify with `aws iam simulate-principal-policy`: allowed on the three secrets, denied on another secret, denied on `bedrock:InvokeModel`
  - [ ] 2.8 [infra] Verify a token-mint probe shows `permissions.issues == "write"` for each installation. List any installation that hasn't accepted (edge case)
  - [ ] 2.9 [panel] Manual check: invoking the stub from the deployed panel creates a run that ends `succeeded`/`not_applicable`
  - [ ] 2.10 [repo root] Create the runbook stub `docs/runbooks/bug-fix-agent.md` with the deploy and verify sections (FR-49a)
  - [ ] 2.11 Verify AC: AC1 key and cap recorded; AC2 deployed with the ARN recorded; AC3 role simulation; AC4 panel invoke; AC5 `issues: write`; AC6 backup and revert per item. Map each to the change-record verification table
  - [ ] 2.12 `verifier` audit; draft PR → `integration/bug-fix-agent`

- [ ] 3.0 Implement Story S-182 (#364 - https://github.com/llipe/dev-tasks-agent-fleet/issues/364): Sandbox spike on the deployed runtime

  > Note: **gates all of Wave B.** If any check fails, record FAIL, keep #373–#377 blocked, and hand off to `product-engineer` drift reconciliation (D-51, spec §12). Resolves spec OQ-2.

  - [ ] 3.1 `[T]` [agents/bug-fix] L1 `tests/unit/test_sandbox.py`:
    - the env is built from an allow-list (`ANTHROPIC_API_KEY`, `PATH`, `HOME`, `LANG`, `CI=1`), never a deny-list;
    - no `AWS_*` or `AWS_CONTAINER_*` variable passes through;
    - timeout → SIGTERM, then SIGKILL after 15 s;
    - exit-code mapping;
    - a missing sandbox binary raises a typed error;
    - zombie children are reaped (D-51).
  - [ ] 3.2 `[T]` [agents/bug-fix] L1 `tests/unit/test_probe.py`: probe mode is refused unless `ALLOW_PROBE=1`, even when `__probe: true` is sent
  - [ ] 3.3 `[I]` [agents/bug-fix] `sandbox.py`: run as `fixer` with the minimal env, under the sandbox runtime with the registry-only network policy and a wall-clock timeout (D-51)
  - [ ] 3.4 `[I]` [agents/bug-fix] `probe.py` and its `main.py` hook, reporting each check as a `run_event`
  - [ ] 3.5 [infra] Redeploy with `ALLOW_PROBE=1` through `/infra-engineer`
  - [ ] 3.6 IC: inside the sandbox, `169.254.170.2`, `169.254.169.254` and `example.com` are unreachable, while `registry.npmjs.org` and `pypi.org` are reachable (D-51)
  - [ ] 3.7 IC: as `fixer`, `/proc/<wrapper pid>/environ` and `/proc/<wrapper pid>/mem` can't be read, and no `AWS_*` variable is present
  - [ ] 3.8 IC: through `claude -p` (as `fixer`, in the sandbox), a repo `.claude/settings.json` that allows `Bash(git push:*)` loses to the managed deny rule, and `WebFetch` is denied (D-05, D-51)
  - [ ] 3.9 [agents/bug-fix] Write `workstream/spike-bug-fix-sandbox.md`: CLI version, the sandbox runtime chosen (`bwrap` or the CLI's own), the verified managed-settings keys, and a PASS/FAIL verdict per check. Update `managed-settings.json` to match (OQ-2)
  - [ ] 3.10 [infra] Unset `ALLOW_PROBE` and redeploy
  - [ ] 3.11 Verify AC: AC1–AC2 by 3.1 and 3.2; AC3–AC5 by the IC events in 3.6–3.8; AC6–AC7 by the spike report
  - [ ] 3.12 Run tests: `make test`; agent gate; `make validate`; record `coverage_gate`
  - [ ] 3.13 `verifier` audit; open PR → `integration/bug-fix-agent`. On FAIL, route to `product-engineer`
  - [ ] 3.14 `[T]` [agents/bug-fix] Do this before 3.11. L1 `tests/unit/test_probe.py`: `__probe` is read only from the **top-level** payload, never from `params`; `params.__probe` is ignored; both forms are refused without `ALLOW_PROBE=1` (DF-14, D-70)

- [ ] 4.0 Implement Story S-183 (#365 - https://github.com/llipe/dev-tasks-agent-fleet/issues/365): Panel `string-list` schema-form control

  > Note: runs in parallel with any task. Pixel contract: DESIGN.md §3.11 (new), §3.2, §3.3, §6.4. A `ux-engineer` lite pass is recommended before 4.5 (D-47, D-48).

  - [ ] 4.1 `[T]` [panel] L1 `tests/unit/form.test.ts`:
    - `type: array` + `items.type: string` maps to `string-list`, carrying `minItems`, `uniqueItems`, `items.minLength` and `default`;
    - arrays of numbers, arrays of objects, and `items` + `oneOf` stay `unsupported` (D-48).
  - [ ] 4.2 `[T]` [panel] L2 component `FieldRow`:
    - Enter or Tab commits a chip;
    - Backspace on empty input removes the last chip;
    - the × button has `aria-label="Remove <value>"`;
    - a pasted newline-separated list splits into chips and drops blank lines;
    - `"a, b"` stays one chip;
    - the focus ring follows §6.4.
  - [ ] 4.3 `[T]` [panel] L2 component tests for `InvokeDialog` and `ScheduleDialog`: pre-fill from schema `default`, then `default_params`; submit as a JSON array; `unsupported` is still skipped; inline Ajv errors for `minItems`, `uniqueItems` and `minLength`
  - [ ] 4.4 `[I]` [panel] `panel/lib/schema/form.ts`: add the `string-list` control kind and its mapping (D-48)
  - [ ] 4.5 `[I]` [panel] `FieldRow.tsx` (+ CSS module): String List built from DESIGN.md §3.2 and §3.3 tokens
  - [ ] 4.6 `[I]` [panel] `InvokeDialog.tsx:48-59,87` and `ScheduleDialog.tsx:126-150`: pre-fill and submit `string-list` fields
  - [ ] 4.7 [repo root] `DESIGN.md`: add §3.11 String List (anatomy, tokens, states, keyboard), notes in §5.4 and §5.7, and a changelog row
  - [ ] 4.8 `[T]` [panel] L2.5 `panel/tests/integration/schedule-array-params.test.ts`: saving, then firing, a schedule round-trips an array param through `validateParams` into the payload
  - [ ] 4.9 `[T]` [panel] E2E `panel/tests/e2e/schedules-string-list.spec.ts`: create a schedule with custom labels, reopen it, and confirm the chips persist
  - [ ] 4.10 Edge cases: an empty list with `minItems` 1 shows an error; a duplicate shows a `uniqueItems` error; a whitespace-only chip is rejected; a long label wraps; 20+ chips stay usable
  - [ ] 4.11 Confirm in the PR description that no seeded sibling schema has a list-of-strings property (backward compatibility)
  - [ ] 4.12 Manual UI: `/agents/<slug>/invoke`, and `/schedules` → new → edit labels → save → reopen
  - [ ] 4.13 Verify AC: AC1 by 4.1; AC2 by 4.2; AC3–AC4 by 4.3; AC5 by the DESIGN.md diff; AC6 by 4.8 and 4.9
  - [ ] 4.14 Run tests: `pnpm --filter panel run test`, `pnpm --filter panel run test:integration`, `pnpm --filter panel run test:e2e`; panel gate; `make validate`; record `coverage_gate`
  - [ ] 4.15 `verifier` audit with a DESIGN.md pixel check; open PR → `integration/bug-fix-agent`

- [ ] 5.0 Implement Story S-184 (#366 - https://github.com/llipe/dev-tasks-agent-fleet/issues/366): `agents` seed row, params schema, and typed params

  > Note: defaults live in the seed, never in agent code (D-45, D-57). `repo` is not a param (D-60). Needs the runtime ARN from 2.4.

  - [ ] 5.1 `[T]` [panel] L2.5 `panel/tests/integration/bug-fix-seed.test.ts`:
    - after `db reset`, the `bug-fix` row exists with `requires_repository`, 3600/120/300 and the ARN;
    - `validateParams` accepts the defaults;
    - it rejects `params.repo` (`additionalProperties`) and an empty `select_labels` (D-60, D-45).
  - [ ] 5.2 `[T]` [agents/bug-fix] L1 `tests/unit/test_params.py`:
    - valid defaults pass;
    - `claim_remove_labels ⊄ select_labels` fails;
    - empty `select_labels` or `claim_add_labels` fails;
    - a missing label list raises a typed error, never an invented default;
    - unknown keys are ignored (D-45, D-46).
  - [ ] 5.3 `[I]` [supabase] Migration `supabase/migrations/<ts>_seed_bug_fix_agent.sql`: upsert with the sibling `on conflict (slug) do update` shape; `params_schema` = spec §5.2 (`additionalProperties: false`); `default_params` with the label lists, `assignee: "llipe"`, budgets and caps (D-45, D-57)
  - [ ] 5.4 [supabase] Document the rollback in the migration header: `delete from agents where slug = 'bug-fix'` (no dependent rows before the first run)
  - [ ] 5.5 [supabase] Mirror the row in `supabase/seed.sql`
  - [ ] 5.6 **Confirmation gate:** ask the user before applying the migration to any shared or cloud project
  - [ ] 5.7 [supabase] Apply after confirmation, then verify: `select slug, requires_repository, max_runtime_seconds from agents where slug='bug-fix'`
  - [ ] 5.8 `[I]` [agents/bug-fix] `params.py`: a typed params object with the cross-field rules (D-46)
  - [ ] 5.9 Edge cases: unicode or colon labels; duplicate labels (`uniqueItems`); `max_turns` at its 5 and 100 boundaries
  - [ ] 5.10 Manual UI: `/agents/bug-fix/invoke` shows every field (the label lists as String Lists once 4.0 has merged)
  - [ ] 5.11 Verify AC (v1.4): AC1–AC3 by 5.1; AC4 by 5.14, 5.15 and 5.16; AC5 by 5.2 and 5.15 (DF-24)
  - [ ] 5.12 Run tests: `supabase db reset`, `pnpm --filter panel run test:integration`, `make test`; both gates; `make validate`; record `coverage_gate`
  - [ ] 5.13 `verifier` audit; open PR → `integration/bug-fix-agent`
  - [ ] 5.14 `[T]` [panel] Do this before 5.11. Extend 5.1: `params_schema.required` is exactly the four label lists plus `assignee`, and `validateParams` rejects a payload without `select_labels` or `assignee` (DF-10, D-68)
  - [ ] 5.15 `[T]`/`[I]` [agents/bug-fix] Do this before 5.11. `params.py`:
    - absent budgets and caps take defaults equal to the seed values (`max_turns` 40, `cli_timeout_minutes` 30, `run_budget_minutes` 55, `max_code_files` 10, `max_code_lines` 400);
    - absent labels or `assignee` raise a typed missing-required error;
    - the subset rule compares labels case-insensitively (DF-10, DF-13, D-68, D-69).
  - [ ] 5.16 `[T]`/`[I]` [agents/bug-fix] Do this before 5.11. `params.py` enforces the schema's type and range bounds for budgets and caps (`max_turns` 5–100, `cli_timeout_minutes` 5–45, `run_budget_minutes` 10–55, `max_code_files` 1–50, `max_code_lines` 10–2000). A violation raises a typed bounds error naming the key. Table tests cover both edges and a wrong type (DF-25, D-82)

- [ ] 6.0 Implement Story S-185 (#367 - https://github.com/llipe/dev-tasks-agent-fleet/issues/367): Preflight checks — Issues permission, label configuration, assignee

  - [ ] 6.1 `[T]` [agents/bug-fix] L1 permission parsing (`issues` absent, `read`, `write`) and reason formatting (D-58)
  - [ ] 6.2 `[T]` [agents/bug-fix] L2 `tests/component/test_preflight.py` with `responses`:
    - missing `issues: write` → `failed`/`GITHUB_PERMISSION_MISSING`;
    - missing labels → `not_applicable` listing every missing label;
    - a cross-field violation → `not_applicable` naming the rule;
    - an unassignable assignee → `not_applicable`;
    - every failure path makes zero GitHub write calls;
    - `status: ready` is requested URL-encoded;
    - the happy path passes (D-46, D-57, D-58).
  - [ ] 6.3 `[I]` [agents/bug-fix] `credentials.py`: return the minted token's `permissions` (D-58)
  - [ ] 6.4 `[I]` [agents/bug-fix] `issues.py`: label lookup with URL encoding, and the assignee check
  - [ ] 6.5 `[I]` [agents/bug-fix] `preflight.py`: permission → labels → cross-field → assignee (spec §8.2)
  - [ ] 6.6 Edge cases: a label lookup 404 versus 5xx (retry, then `failed`); a rate-limit response; an org member without push access
  - [ ] 6.7 Verify AC (v1.4): AC1–AC5 by 6.2; AC6 by 6.10, 6.11 and 6.12 (DF-24)
  - [ ] 6.8 Run tests: `make test`; agent gate; `make validate`; record `coverage_gate`
  - [ ] 6.9 `verifier` audit; open PR → `integration/bug-fix-agent`
  - [ ] 6.10 `[T]` [agents/bug-fix] Do this before 6.7. L2 `test_preflight.py`: a direct invoke missing a required param → `not_applicable` naming the key, with zero writes. Label-existence matching is case-insensitive (DF-10, DF-13, D-68, D-69)
  - [ ] 6.11 `[T]`/`[I]` [agents/bug-fix] Do this before 6.7. A shared GitHub client retry policy: 5xx and secondary rate limits are retried 3 times with backoff, then `failed`/`GITHUB_UNAVAILABLE`. An unexpected 4xx on a write → `failed`/`GITHUB_REQUEST_REJECTED`. Unit tests in `tests/unit/test_github_client.py` (DF-09, D-67)
  - [ ] 6.12 `[T]` [agents/bug-fix] Do this before 6.7. L2 `test_preflight.py`: a direct invoke with `run_budget_minutes: 600`, `max_code_files: 0` or `max_turns: "40"` → `not_applicable` naming the key, with zero GitHub writes (DF-25, D-82)

- [ ] 7.0 Implement Story S-186 (#368 - https://github.com/llipe/dev-tasks-agent-fleet/issues/368): Claim/disposition markers and an idempotent disposition

  - [ ] 7.1 `[T]` [agents/bug-fix] L1 `tests/unit/test_markers.py`:
    - claim and disposition markers round-trip;
    - only a first-line match parses;
    - a forged marker (human author, wrong App id, `user.type == "User"`) is untrusted;
    - `live_claim` picks the right claim among several claims and dispositions (D-53).
  - [ ] 7.2 `[T]` [agents/bug-fix] L2 `tests/component/test_disposition.py`:
    - the disposition applies once, and a second call makes zero writes;
    - it removes `claim_add_labels`, adds `disposition_add_labels`, and keeps the assignee;
    - the signal backstop applies it within 10 s under a simulated SIGTERM (D-08, D-45).
  - [ ] 7.3 `[I]` [agents/bug-fix] `markers.py`: build, parse and check trust against the App ID from `github_installations` (D-53)
  - [ ] 7.4 `[I]` [agents/bug-fix] `issues.py`: comment list and create, label add and remove (a 404 on removing a label is tolerated)
  - [ ] 7.5 `[I]` [agents/bug-fix] `disposition.py`: a scrubbed diagnosis comment with the marker, the label swap, and a no-op when a trusted disposition already exists for the run (D-08)
  - [ ] 7.6 `[I]` [agents/bug-fix] `signal_backstop.py`: call the disposition with a 10-second budget before `fail()` when a claim exists
  - [ ] 7.7 Edge cases: CRLF bodies; a diagnosis truncated to 65,536 characters; an already-absent label
  - [ ] 7.8 Verify AC: AC1–AC3 by 7.1; AC4–AC6 by 7.2
  - [ ] 7.9 Run tests: `make test`; agent gate; `make validate`; record `coverage_gate`
  - [ ] 7.10 `verifier` audit; open PR → `integration/bug-fix-agent`
  - [ ] 7.11 `[T]`/`[I]` [agents/bug-fix] Do this before 7.8:
    - `markers.py` parses the **leading marker block** (line 1 plus the consecutive matching lines after it), so one comment can name several `run_id`s; a marker after a non-marker line is ignored (DF-22, D-80);
    - `neutralize.py` implements the D-65 neutralizer (closing keyword + reference → `(ref #N)`, `@` → `@` + U+200B), with property tests;
    - `disposition.py` runs all model-derived text through it (DF-28, D-65, D-85). S-194 reuses `neutralize.py`.

- [ ] 8.0 Implement Story S-187 (#369 - https://github.com/llipe/dev-tasks-agent-fleet/issues/369): Selection — oldest ready bug, AND labels, linked-PR skip, explicit issue

  - [ ] 8.1 [agents/bug-fix] Fixtures `tests/fixtures/graphql/*.json`: PRD AC-1 (newest ready, oldest ready, needs-refinement), AC-2, AC-17 (`kind/bug`, `triage/ok`), multi-page results, a closed-but-not-merged PR, a fork PR
  - [ ] 8.2 `[T]` [agents/bug-fix] L1 table: the AND filter, excluding `claim_add_labels`, and both linked-PR rules (D-44, D-55)
  - [ ] 8.3 `[T]` [agents/bug-fix] L2 `tests/component/test_select.py`:
    - with no `issue_number`, the oldest eligible issue wins;
    - no candidate → `succeeded`/`no_findings`;
    - an explicit `issue_number` failing → `not_applicable` with the specific reason: not open, missing labels, already claimed, or open PR #M;
    - pagination (D-10, D-55).
  - [ ] 8.4 `[I]` [agents/bug-fix] `issues.py`: GraphQL candidate query (first `select_labels` label, `CREATED_AT ASC`, 50 per page, `closedByPullRequestsReferences(includeClosedPrs: false)`), plus open PRs listed once per run (D-55)
  - [ ] 8.5 `[I]` [agents/bug-fix] `select.py`: AND over `select_labels`, none of `claim_add_labels`, skip linked issues, stop at the first eligible (D-10, D-44, D-55)
  - [ ] 8.6 Edge cases: zero open issues; label letter case; 200+ candidates
  - [ ] 8.7 Verify AC (v1.4): AC1, AC2, AC4 and AC5 by 8.3; AC3 by 8.10; AC6 by 8.3 using the AC-1 fixture (DF-24)
  - [ ] 8.8 Run tests: `make test`; agent gate; `make validate`; record `coverage_gate`
  - [ ] 8.9 `verifier` audit; open PR → `integration/bug-fix-agent`
  - [ ] 8.10 `[T]`/`[I]` [agents/bug-fix] Do this before 8.7. The AND filter and the lock exclusion are case-insensitive. A fixture issue labelled `Status: Ready` matches `status: ready` (DF-13, D-69)

- [ ] 9.0 Implement Story S-188 (#370 - https://github.com/llipe/dev-tasks-agent-fleet/issues/370): Claim with the post-claim race check

  > Note: G1 applies only to scheduled fires, so a manual invoke can overlap a scheduled run (`scheduler_g1_overlap.sql:72`) (D-54). The claim never assigns the App bot (FR-8).

  - [ ] 9.1 `[T]` [agents/bug-fix] L1 race verdict: an earlier marker from a terminal run is ignored; an earlier marker from a running run means this run lost (D-54)
  - [ ] 9.2 `[T]` [agents/bug-fix] L2 `tests/component/test_claim.py`:
    - happy claim: the marker comment is posted first, then the labels, then the assignee;
    - lost race: only this run's comment is deleted, and labels and assignee are untouched → `not_applicable` "claimed by run <id>";
    - a pre-check failure;
    - a crash right after the comment leaves a comment with unchanged labels (D-07, D-54).
  - [ ] 9.3 `[I]` [agents/bug-fix] `config.py` and `agentcore.json`: `PANEL_BASE_URL` for the run link
  - [ ] 9.4 `[I]` [agents/bug-fix] `claim.py`: pre-check, then the claim (comment → remove `claim_remove_labels` → add `claim_add_labels` → assignee), then the post-check with `v_runs.effective_status` (D-07, D-45, D-54)
  - [ ] 9.5 Edge cases: two comments in the same second (comment-id order decides); the other run already terminal; a 422 on the assignee (fault path)
  - [ ] 9.6 Verify AC: AC1–AC4 by 9.2. AC4 checks the PRD AC-3 issue state
  - [ ] 9.7 Run tests: `make test`; agent gate; `make validate`; record `coverage_gate`
  - [ ] 9.8 `verifier` audit; open PR → `integration/bug-fix-agent`
  - [ ] 9.9 `[T]` [agents/bug-fix] Do this before 9.6. L2 `test_claim.py`: a 422 on the assignee → `failed`/`GITHUB_REQUEST_REJECTED`; a Supabase read failure in the post-check → the run keeps its comment, leaves labels and assignee untouched, applies **no** disposition and ends `failed`/`SUPABASE_UNAVAILABLE` (D-81); a crash after the comment and before the labels leaves the issue selectable, and the next run's post-check ignores the orphaned terminal marker (DF-09, DF-19, D-67, D-78)

- [ ] 10.0 Implement Story S-189 (#371 - https://github.com/llipe/dev-tasks-agent-fleet/issues/371): Checkout, repository gate, toolchain, and the gate runner

  > Note: needs `sandbox.py` from 3.0. Resolves spec OQ-1 (Python install contract). No issue is changed before the repo gate passes (FR-5).

  - [ ] 10.1 **Decide OQ-1 before 10.5:** for Python, require a `make install` target, or end `not_applicable` "missing install target" (the proposal). Append the result to `workstream/decisions-bug-fix-agent.md` as a new `D-NN`, with user confirmation
  - [ ] 10.2 [agents/bug-fix] Fixture repos `tests/fixtures/repos/{js-pnpm-ok, js-missing-typecheck, py-make-ok, py-no-developer-md}`
  - [ ] 10.3 `[T]` [agents/bug-fix] L1 `tests/unit/test_toolchain.py`: stack detection (pnpm, npm, Makefile, none), gate-name resolution, `Makefile` target parsing (`format_check` ≠ `format-check`) (D-17, D-19)
  - [ ] 10.4 `[T]` [agents/bug-fix] L2 `tests/component/test_checkout.py` and `test_gates.py` with real `git`:
    - shallow clone and base SHA recorded;
    - repo gate pass and fail, naming the missing item;
    - per-gate `{pass, exit_code, tail}` with the tail scrubbed;
    - base results recorded, never blocking (D-06, D-14, D-19).
  - [ ] 10.5 `[I]` [agents/bug-fix] `toolchain.py`: copy from `dependency-update`, add Python `Makefile` targets and the `.claude/agents/developer.md` check (D-06, D-18, D-19)
  - [ ] 10.6 `[I]` [agents/bug-fix] `checkout.py`: clone into the wrapper clone and materialize `/work/repo` as `fixer` through `safe_git.py` (10.13–10.14, DF-02); install in the sandbox (JS `pnpm install --frozen-lockfile` or `npm ci`, Python per 10.1) (D-63); `CLONE_FAILED` and `INSTALL_FAILED` codes
  - [ ] 10.7 `[I]` [agents/bug-fix] `gates.py`: the four gates plus `audit` through `sandbox.py`, with tails scrubbed (D-14)
  - [ ] 10.8 Edge cases: a `package.json` with no `scripts`; a monorepo root `package.json`; a clone failure; an install failure
  - [ ] 10.9 Verify AC (v1.4): AC1–AC3 by 10.12–10.16; AC4, AC5, AC7 and AC8 by 10.3 and 10.4; AC6 by the decision-log row from 10.1; AC9 by 10.17 (DF-24)
  - [ ] 10.10 Run tests: `make test`; agent gate; `make validate`; record `coverage_gate`
  - [ ] 10.11 `verifier` audit; open PR → `integration/bug-fix-agent`
  - [ ] 10.12 `[T]` [agents/bug-fix] Do this before 10.9. L2 `tests/component/test_git_confinement.py`:
    - a `.git/hooks/{post-checkout,pre-commit}`, `core.fsmonitor`, `diff.external` and a filter driver planted in `/work/repo` never run as uid `wrapper` during checkout or capture;
    - every wrapper git call carries `GIT_CONFIG_NOSYSTEM=1`, `GIT_CONFIG_GLOBAL=/dev/null`, `core.hooksPath=/dev/null` and `core.fsmonitor=false`;
    - `safe.directory=*` is never set;
    - `capture()` includes untracked files and stores symlinks without following them (DF-02, DF-01, D-62).
  - [ ] 10.13 `[I]` [agents/bug-fix] Do this before 10.9. `safe_git.py`:
    - a hardened git runner;
    - the wrapper clone at `/work/wrapper/repo`, mode 0700, with `info/exclude` listing only `node_modules/`, `.venv/`, `.pnpm-store/`, `__pycache__/` (D-83);
    - `materialize(tree, dest)`: `git archive` piped to `tar -x` running as `fixer`;
    - `capture(work_tree)`: `git --git-dir=<wrapper clone> --work-tree=<dir> add -A` (DF-02, D-62).
  - [ ] 10.14 `[I]` [agents/bug-fix] Do this before 10.9. `checkout.py` clones into the wrapper clone and materializes the base tree into a fresh `/work/repo` as `fixer`. No wrapper git call targets a `fixer`-writable `.git` (DF-02, D-62)
  - [ ] 10.15 `[I]` [agents/bug-fix] Dockerfile: `/work/wrapper` owned by `wrapper` with mode 0700, unreadable by `fixer`. Extend `scripts/image-smoke.sh` to assert this (DF-02, D-62)
  - [ ] 10.16 Verify AC: the S-189 v1.1 wrapper-clone and `safe_git.py` ACs by 10.12 and the 10.15 smoke check (DF-02, D-62)
  - [ ] 10.17 `[T]` [agents/bug-fix] Do this before 10.9. L2 `tests/component/test_checkout.py`:
    - an npm fixture installs with `npm ci` and a pnpm fixture with `pnpm install --frozen-lockfile`;
    - an out-of-sync `package-lock.json` gives `INSTALL_FAILED`, and the lockfile is unchanged;
    - a base gate that rewrites a tracked file (an autofix lint) and creates an untracked file has both restored to base before the CLI step, with a `run_event`;
    - ignored `node_modules/` is left as it is (TC-189-14, TC-189-15) (DF-12, D-63).
  - [ ] 10.18 `[I]` [agents/bug-fix] Do this before 10.9. `checkout.py`: install command per detected manager, and `restore_base()` after install and the base gates (capture → restore changed tracked paths as `fixer` through `safe_git.py`) (DF-12, D-63)
  - [ ] 10.19 Verify AC: the S-189 v1.2 install and base-restore AC by 10.17 (DF-12, D-63)

- [ ] 11.0 Implement Story S-190 (#372 - https://github.com/llipe/dev-tasks-agent-fleet/issues/372): Orchestration, outcome mapping, and reporting through the claim

  > Note: `FIX_LOOP_ENABLED=0`, so after the claim the run applies the disposition "fix loop not yet enabled". `sweep` is a no-op until Wave C (S-196). Only `failed` counts toward G3 (D-20, D-61).

  - [ ] 11.1 `[T]` [agents/bug-fix] L1 `tests/unit/test_outcomes.py`: one test per Wave A row of spec §8.9; every `needs_review` and `not_applicable` result carries `result.summary` (D-20, D-61)
  - [ ] 11.2 `[T]` [agents/bug-fix] L2 `tests/component/test_main.py`:
    - one test per terminal path, with collaborators mocked;
    - the `finally` path after an exception in `claim`;
    - SIGTERM during `checkout` → no disposition;
    - SIGTERM after `claim` → disposition applied;
    - a reporter flush failure never masks the outcome.
  - [ ] 11.3 `[I]` [agents/bug-fix] `outcomes.py`: the mapping table
  - [ ] 11.4 `[I]` [agents/bug-fix] `main.py`:
    - steps `preflight` → `sweep` (no-op) → `select` → `checkout` → `claim` → `fix`, the last only when `FIX_LOOP_ENABLED=1`;
    - each step is a `run_steps` entry with `run_events` at its decisions;
    - heartbeat and backstop wiring;
    - `runs.metrics.issue_number` and step timings (FR-25, FR-26, FR-27).
  - [ ] 11.5 `[I]` [agents/bug-fix] `agentcore.json`: `FIX_LOOP_ENABLED=0`
  - [ ] 11.6 [infra] Redeploy through `/infra-engineer` (the 2.4 flow)
  - [ ] 11.7 Manual/IC: one deployed manual run on the fixture repo selects, claims and applies the disposition ("fix loop not yet enabled"). The issue ends with `disposition_add_labels`, and the panel shows the steps, events and summary
  - [ ] 11.8 Verify AC: AC1 by 11.2; AC2 by 11.1; AC3 by 11.2's SIGTERM cases; AC4 by the metrics assertion; AC5 by the deployed-run evidence in 11.7
  - [ ] 11.9 Run tests: `make test`; agent gate; `make validate`; record `coverage_gate`
  - [ ] 11.10 `verifier` audit; open PR → `integration/bug-fix-agent`; roadmap Wave A row → `In progress` (set by `planner`)
  - [ ] 11.11 `[T]` [agents/bug-fix] Do this before 11.8. Extend 11.1 with the spec §8.9 v1.3 rows: `GITHUB_UNAVAILABLE`, `GITHUB_REQUEST_REJECTED`, `SUPABASE_UNAVAILABLE` (`failed`, counted by G3), and missing required param → `not_applicable` (DF-09, DF-10, D-67, D-68)
  - [ ] 11.12 `[T]` [agents/bug-fix] Do this before 11.8. L2 `test_main.py`: the `finally` path and the backstop apply the disposition only after the race post-check has confirmed ownership. An exception or SIGTERM before or during the post-check, and a failed post-check, apply **no** disposition and leave labels untouched (DF-23, D-81)

## Decisions Consumed

| ID   | Decision (short form)                                                                               |
| ---- | --------------------------------------------------------------------------------------------------- |
| D-03 | Sibling AgentCore + Supabase reporting contract.                                                    |
| D-05 | Headless Claude Code inside a Python wrapper; repo's own `.claude/`.                                |
| D-06 | No `developer.md` → `not_applicable`.                                                               |
| D-07 | Claim = assign + lock label + claim comment.                                                        |
| D-08 | No PR → diagnosis comment + disposition labels, no auto-retry.                                      |
| D-10 | Oldest ready bug; explicit number never bypasses the labels.                                        |
| D-14 | Block on test, lint, format, typecheck; audit recorded.                                             |
| D-17 | Toolchain precedent: pnpm/npm detection.                                                            |
| D-18 | JS/TS and Python in v1.                                                                             |
| D-19 | Canonical gate names as scripts or Make targets.                                                    |
| D-20 | Outcome mapping; only `failed` counts toward G3.                                                    |
| D-44 | Selection labels are a per-run parameter with AND semantics.                                        |
| D-45 | Four label-list params; defaults in the seed.                                                       |
| D-46 | Missing label or invalid label params → `not_applicable` before any select or claim.                |
| D-47 | Arrays store and validate; the panel form could not edit them.                                      |
| D-48 | `string-list` form control.                                                                         |
| D-50 | CLI model via the Anthropic API key, not Bedrock.                                                   |
| D-51 | Three-layer confinement; spike first.                                                               |
| D-53 | Hidden markers trusted by App id; newest trusted claim is live.                                     |
| D-54 | Pre-check, claim, post-claim race check.                                                            |
| D-55 | Linked PR = GraphQL closing reference or `issue/<N>-` branch.                                       |
| D-57 | `assignee` seed default `llipe`, checked before claim.                                              |
| D-58 | One infra change in Wave A; run-start Issues-write check.                                           |
| D-60 | `repo` is the run's repository, not a param.                                                        |
| D-61 | Budget ceilings → `needs_review`; `failed` only for unattributable faults.                          |
| D-62 | Wrapper git only on its own clone; fixer trees via file ops as `fixer`; host-scoped push (DF-02).    |
| D-63 | Frozen install per manager; restore the base after the base runs (DF-12).                            |
| D-67 | `GITHUB_UNAVAILABLE`, `GITHUB_REQUEST_REJECTED`, `SUPABASE_UNAVAILABLE` (DF-09).                      |
| D-68 | Labels and assignee `required`; seed-equal budget and cap defaults (DF-10).                         |
| D-69 | Case-insensitive labels; wider D-52 lists (DF-13).                                                  |
| D-70 | `__probe` top-level, `ALLOW_PROBE` only (DF-14).                                                    |
| D-78 | S-188: an orphaned marker leaves the issue selectable; the sweep is not involved (DF-19).           |
| D-80 | A leading marker block names several `run_id`s (DF-22).                                             |
| D-81 | Disposition only after confirmed ownership; the sweep isolates per-issue failures (DF-23).          |
| D-82 | The agent enforces schema bounds; a violation → `not_applicable` (DF-25).                           |
| D-83 | Reject symlinks and gitlinks; narrow `info/exclude`; parent-chain `lstat` (DF-26).                  |
| D-85 | Neutralizer applied to every agent comment with model text (DF-28).                                 |
