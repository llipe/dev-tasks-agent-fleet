# Fidelity Report — S-184 (#366): `agents` seed row, params schema, typed params

**Fidelity: High** · **Highest drift impact: Minor** · Scope: S-184 / issue #366 · Draft PR #449 · `story/S-184-agents-seed` (HEAD `236c2e7`) → `integration/bug-fix-agent-wave-a`

All five ACs pass locally. The cloud side of AC1 and AC2 (applying the migration to the shared project) is **pending apply**: confirmation gate 5.6 is deliberately open. Six advisory drift items are listed, all Minor. **None blocks the PR or the issue.**

| Field | Value |
| ----- | ----- |
| Mode | Audit (grey-box) |
| Date | 2026-10-24 |
| Sources | issue #366; task list §5.0 (v2.0.3); spec v2.2 §5.1–§5.2; PRD v2.1; decisions D-82, D-88, D-93, D-102, D-105; test plan + traceability matrix (TC-184-*, CT-*, RT-06, RT-14); `git diff origin/integration/bug-fix-agent-wave-a...HEAD` (16 files, +1605/−15) |
| Open by design | 5.6 / 5.7 (cloud apply gate), 5.10 (manual UI), 5.12 cloud part + `coverage_gate`, 5.13 (this audit, then PR ready) |

## 1. What changed and why (plain language)

The bug-fix agent is now registered in the panel's list of agents, so the panel can see it, show an invoke form for it, and start it. This applies to the local development database now, and to the shared database once the operator approves.

Starting a run needs only one thing: the number of the GitHub issue to fix. Everything else is optional: the comment that asked for the fix, which project board to update, the board column names, and the run's time and size limits. Each optional setting has a safe default. There are no settings left over from the earlier design for labels, assignees or schedules. Unexpected settings are rejected by the panel.

The agent also gets its own checker for these settings. It applies the same limits and the same defaults as the panel, so a run started outside the panel cannot get past the limits. A missing issue number or an out-of-range value gives a clear error that names the setting. A later story (S-185) turns that error into a polite refusal on the issue.

Tests show that a `/bug-fix` comment on GitHub, routed by the webhook rule, becomes a correctly shaped run aimed at the deployed bug-fix runtime.

## 2. Per-AC results

| AC-ID | Description | Codebase evidence | Workstream evidence | Test evidence | Result |
| ----- | ----------- | ----------------- | ------------------- | ------------- | ------ |
| AC1 | Migration upserts `bug-fix` with the siblings' `on conflict (slug) do update` shape; `seed.sql` mirrors it | `supabase/migrations/20261024130000_seed_bug_fix_agent.sql` (latest timestamp, upsert updates all 11 columns); `supabase/seed.sql` block 4a is byte-identical in values | Tasks 5.3, 5.5 checked; 5.6/5.7 open (gate) | L2.5 `bug-fix-seed.test.ts`: on-conflict shape, seed/migration parity (TC-184-02), re-apply keeps one row (TC-184-01, EC-13). Re-run by the verifier: **35/35 pass** | **Pass** (local); cloud **pending apply** |
| AC2 | `requires_repository = true`, 3600 / 120 / 300, S-181 `runtime_arn` | Both files: `true, 3600, 120, 300`; ARN `arn:aws:bedrock-agentcore:us-east-1:755641879575:runtime/bugfix_bug_fix-BiuPsdGSPK`, qualifier `DEFAULT` | ARN matches `infra/changes/20261023-bug-fix-runtime/result.md` step 7 and `agentcore/.cli/deployed-state.json`; `agentcore.json` `maxLifetime` 3600, `idleRuntimeSessionTimeout` 900 (not used as the start timeout, as required) | TC-184-01/-03 (L2.5), TC-184-04 (`test_agentcore_config.py` reads both SQL files against `maxLifetime`) | **Pass** (local); cloud **pending apply** |
| AC3 | `params_schema` equals spec §5.2; `default_params` holds only budgets, caps and status names | Verifier parsed all three JSON copies (migration, `seed.sql`, contract fixture) and compared them structurally to the spec §5.2 block: **all equal**. `required` is exactly `["issue_number"]`; `additionalProperties: false`; no `select_labels`/`claim_*`/`disposition_*`/`assignee`/`schedule`/`repo` key. `default_params` = 3 status names + 5 budgets/caps, equal to the schema defaults; no project, label or assignee default | Matches D-93 and D-102; spec §5.2 unchanged since v2.0 | CT-06 deep-equal, `default_params` key-set check, TC-184-15 (`{}`, `{issue_number:0}`, `select_labels`, `assignee` rejected), CT-03/CT-04, TC-184-07 boundary table (panel L1, **42/42 pass**) | **Pass** |
| AC4 | `params.py`: typed parse, schema defaults, schema bounds; a typed error naming the key | `params.py`: frozen `Params`; `MissingRequiredParam` / `InvalidParam` carry `key` and never the value; bool rejected as integer; integral floats accepted (matches Ajv `integer`); `project` uses `fullmatch` (no trailing-newline gap); unknown keys ignored; keys checked in schema order, so the reported key is deterministic | Task 5.8 checked. README documents that it isn't wired into `main.py` yet: wiring and the `invalid_params` refusal belong to S-185 (Intended) | `test_params.py`, `test_params_property.py` (RT-06, Hypothesis differential, 1000 examples), `test_payload_contract.py` (CT-01/02), `test_no_defaults_in_code.py` (TC-184-11). Verifier re-ran the agent suite: **767 passed, 3 xfailed** | **Pass** |
| AC5 | Webhook mapping `{issue_number: issue.number, trigger_comment_id: comment.id}` resolves through `resolveRoute` into valid params | No change to `webhook-resolve.ts`, which was not needed | Tasks 5.1, 5.11 checked; fixture `issue_comment.created.json` is modeled on GitHub's documented shape, not recorded (disclosed) | CT-23 (yields `{issue_number: 42, trigger_comment_id: 2500000000}`), CT-24 a–g (missing/null/string, object mapping, undeclared mapping dropped, repo mismatch, disabled agent). End to end: the real webhook route queues a run with 3600/120/300 and calls `invokeAgentRuntime` (stubbed) with the seeded ARN, `DEFAULT`, and exactly the D-60 payload keys | **Pass** |
| S-181 AC4 (deferred here) | Panel invoke reaches the bug-fix runtime | Webhook route → `invoke-resolved-run.ts` → seeded ARN (proved). Manual route `app/api/agents/[slug]/invoke/route.ts` is not exercised with the bug-fix row | planner-state records the deferral | L2.5 webhook-fire case; L1 form-descriptor test (only `issue_number` required; no label/assignee/repo/schedule field). Deployed-panel run: none yet | **Partial locally**; deployed part **pending apply** (5.6, 5.7, 5.10) → DF-184-04 |

Notes on the test run:

- The two L2.5 webhook-route cases fail with `SupabaseConfigError` unless `SUPABASE_URL` and `SUPABASE_SERVICE_ROLE_KEY` are exported (`supabase status -o env`). With them exported, all 35 cases pass.
- The sibling `webhook-fire.test.ts` behaves the same way, so this is an existing harness behavior, not drift from this story.

## 3. Drift catalog

All items are **advisory and non-blocking** to PR readiness and issue completion. They route to `product-engineer` → `activity-drift-reconciliation`.

| ID | Description | Impact | Intent | Evidence | Owner / next step |
| -- | ----------- | ------ | ------ | -------- | ----------------- |
| DF-184-01 | **Stale runbook status.** `docs/runbooks/bug-fix-agent.md:18` says "The panel can't invoke it until S-184 seeds the `agents` row". That stays true for the deployed panel only until 5.7 applies the migration, but the PR doesn't update the line, and nothing records the seed row, its migration or its params in the runbook. The smoke invoke (l. 70, l. 109) sends `params: {}`. That works against the stub today, but once S-185 wires `params.py` it will fail as `invalid_params`. | Minor | Unintended | Runbook l. 18, 70, 109; the diff touches no file under `docs/runbooks/` | `technical-writer` / `developer`: after 5.7, update the status line, add the seed/params facts, and give the smoke payload an `issue_number` (or note the S-185 change) |
| DF-184-02 | **Runbook coverage (FR-49b).** The task list has 4 data-migration steps (5.3 migration, 5.5 seed mirror, 5.6 confirmation gate, 5.7 apply and verify). The PR adds or updates no runbook. The apply, verify and rollback procedure exists only in the migration header. | Minor | Undetermined | Tasks 5.3–5.7; migration header; no `docs/runbooks/` change | `developer` (setup/migration owner): add an "agents seed row" section to `docs/runbooks/bug-fix-agent.md`. Never blocks the PR |
| DF-184-03 | **Rollback note is incomplete.** The header warns that `runs.agent_id` is `ON DELETE RESTRICT`. It doesn't mention that `delete from agents where slug='bug-fix'` **cascades** to `webhook_rules` and `schedules` rows that point at the agent. After S-197 configures the `/bug-fix` rule, the rollback would delete that rule without warning. | Minor | Unintended | `20260902200101_initial_schema.sql:110` (restrict); `20261019180000_webhook_schema.sql:82`, `20261013160000_scheduler_schema.sql:31` (`on delete cascade`) | `developer`: extend the rollback note (export or recreate the rules, or disable the agent instead of deleting it). The rollback itself is documented as the AC requires |
| DF-184-04 | **S-181 AC4 deferral is only partly covered locally.** The webhook route is proved end to end against the seeded ARN. The manual `POST /api/agents/[slug]/invoke` route has its own `invokeAgentRuntime` call site and is not exercised with the `bug-fix` row. The deployed-panel invoke (run ends `succeeded`/`not_applicable`) awaits apply. | Minor | Undetermined | `panel/app/api/agents/[slug]/invoke/route.ts:211` vs `lib/domain/invoke-resolved-run.ts:117`; L2.5 covers only the webhook route | `developer`: optionally add one L2.5 manual-invoke case for `bug-fix`. Planner: close S-181 AC4 with the 5.7 and 5.10 evidence |
| DF-184-05 | **RT-14 not delivered.** The test plan maps RT-14 (`panel/tests/unit/bug-fix-webhook-rule.property.test.ts`, seeded-PRNG routing and resolution fuzz, 2000 iterations) to S-184-AC5 and S-197-AC3. The file doesn't exist, and task list 5.x doesn't list it, so ownership is unclear. | Minor | Undetermined | Test plan l. 1405; `panel/tests/unit/` has only `bug-fix-params-schema.test.ts` | `product-engineer`: assign RT-14 to S-197 (or to a 5.x sub-task) |
| DF-184-06 | Task 5.13 says "open PR → `integration/bug-fix-agent`". PR #449 targets `integration/bug-fix-agent-wave-a`, the planner's wave branch. | Minor | Intended | `gh pr view 449` base | No action needed (optionally align the task wording) |

No Critical or Major drift. The schema, defaults, timeouts, ARN and typed-error contract match the spec and decisions exactly.

## 4. Edge-case and randomized outcomes

- **5.9 / edge-case matrix:** covered in the panel L1 boundary table and `test_params.py`, all passing:
  - `project` failing the pattern (`llipe/0`, `llipe`, `a/b/1`, `llipe/12345678`, `under_score/1`);
  - a status name of 100 characters (accepted) and 101 characters (rejected);
  - `trigger_comment_id` given as a string (rejected).
- **RT-06** (Hypothesis, 1000 examples, `deadline=None`): passes. Hypothesis reproduces failures from its example database and prints the failing example, which meets the replay requirement.
- **RT-14:** not present (DF-184-05).
- **Documentation structure:** `core/checks` (`checkDocsStructure`) is not present in this repository, so the check is not applicable. The runbook front matter is current (`last_verified: 2026-10-24`), so there is no staleness finding beyond DF-184-01.
- **Vocabulary conformance:** `checkExportedIdentifiers` is not present in this repository. The diff adds no TypeScript `export` declarations (Python module and tests only), so there would be nothing to scan. No findings.
- **Roadmap:** the `docs/roadmap.md` Wave A row is `In progress`, lists #366 among the issues, and lists S-184 under "What's missing". That is correct while PR #449 is unmerged. **No mismatch.** The planner updates the row when it merges.

## 5. Recommendations

| Item | Next step |
| ---- | --------- |
| AC1/AC2 cloud | Planner: 5.6 confirmation → 5.7 apply and verify (`select slug, requires_repository, params_schema->'required' …` → `bug-fix | t | ["issue_number"]`) |
| 5.10 / TC-184-17 | Manual check after apply: the `/agents/bug-fix/invoke` form shows `issue_number` as required; submitting `{issue_number}` alone creates a run |
| 5.12 | Record `coverage_gate` (`qa-engineer`). The panel `pnpm audit` failure (GHSA-mrhx-c7xc-m3w5, zod via `agents/dependency-update` CDK) predates this story, and the branch has no lockfile changes |
| DF-184-01, -02, -03 | `developer` / `technical-writer` (doc fixes, can ride with this PR or follow it) |
| DF-184-04 | `developer` (optional L2.5 case) + planner evidence after apply |
| DF-184-05 | `product-engineer` (assign the RT-14 owner) |
| DF-184-06 | No action needed |
| Publication | Planner posts this header and verdict section to #366 / PR #449. This audit was scoped read-only on GitHub |
