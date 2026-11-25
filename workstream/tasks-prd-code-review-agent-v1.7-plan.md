# Implementation Plan - Code Review Agent v1.7 (Anthropic model)

> Execution plan for [`prd-code-review-agent`](../docs/requirements/prd-code-review-agent.md) (v1.7) /
> [`specification-prd-code-review-agent`](specification-prd-code-review-agent.md) (v1.8) /
> [`user-stories-prd-code-review-agent`](user-stories-prd-code-review-agent.md) (v1.5, section "v1.7 — Anthropic model") /
> [`decisions-code-review-agent`](decisions-code-review-agent.md) (D-70…D-90).
> GitHub issues **#480** (S-216), **#481** (S-217), **#482** (S-218).
>
> **Order:** S-216 → S-217 → S-218. S-216 and S-217 are code: one branch and reviewed PR each into `integration/code-review-anthropic-model` (branched from `main`, which has PR #478), then one consolidated PR to `main` that the user merges. S-218 is an `infra-engineer` pass that starts only after that PR is merged; it needs AWS access and the user's API key.
>
> **Test-first:** every `[T]` task comes before its `[I]` task. A story is ready when `make -C agents/code-review/app/codeReview validate` and the root `pnpm run validate` pass; `qa-engineer` and the `verifier` audit run at the merge gate.
>
> **Packages:** `[code-review]` = `agents/code-review/app/codeReview/` (abbreviated `pkg/`); `[code-review-cdk]` = `agents/code-review/agentcore/`; `[supabase]` = `supabase/`; `[repo root]` = docs, runbooks, `infra/changes/`.

## Relevant Files

- `pkg/model_adapter.py` (new) - Anthropic client factory, `review()`: `count_tokens` check, streaming structured-output call, context-length retry, repair, refusal, fallback model, error mapping, cost (S-216)
- `pkg/bedrock_adapter.py` (deleted) - replaced by `model_adapter.py` (S-216)
- `pkg/legacy_bedrock.py` (new, temporary) - the selection call's Bedrock client factory and response helpers until S-217 deletes it (S-216)
- `pkg/findings_schema.py` - `sent_schema()` strips `minimum`, `maxLength`, `pattern` (S-216)
- `pkg/credentials.py`, `pkg/config.py` - Anthropic key fetch from Secrets Manager, scrubber registration (S-216); `PARAMS_SCHEMA` bounds (S-217)
- `pkg/pipeline.py`, `pkg/render.py`, `pkg/main.py`, `pkg/pyproject.toml` - imports, renamed metrics, footer `answered_by_model`, `anthropic` pin (S-216)
- `pkg/context/selection.py` - selection call on the Anthropic client (S-217)
- `pkg/tests/unit/test_model_adapter.py`, `test_model_adapter_hostile.py`, `test_properties_model.py`, `test_model_adapter_sdk.py` (CT-15), `test_anthropic_fake_contract.py` (CT-14), `pkg/tests/fixtures/anthropic_fake.py`, `pkg/tests/helpers/model_run.py` (new) - adapter tests, fake client and harness (S-216)
- `pkg/tests/unit/test_credentials.py`, `test_config.py`, `test_outcomes.py`, `test_render.py`, `test_render_hostile.py`, `test_layout.py`, `test_contracts.py`, `test_deadline.py`, `test_full_code_files.py`, `test_selection.py`, `pkg/tests/helpers/pipeline_run.py`, `pkg/tests/integration/test_cross_story_joins.py`, `test_pipeline_selection.py` - ported to the Anthropic codes, metrics and fake (S-216)
- `TESTING.md` - the fake Anthropic client and CT-15 harness (S-216)
- `pkg/tests/unit/test_selection*.py`, `test_seed_contract.py`, `test_properties_params.py`, `pkg/tests/fixtures/params_cases.json`, `pkg/tests/integration/test_pipeline_selection.py` - selection and params tests (S-217)
- `pkg/tests/integration/test_pipeline_e2e.py`, `test_pipeline_prompt_capture.py`, `test_pipeline_hostile.py` - moved to the fake Anthropic client (S-216); large-PR capture (S-217)
- `supabase/migrations/<ts>_seed_code_review_agent.sql` (new), `supabase/seed.sql` - params schema and defaults (S-217)
- `agents/code-review/agentcore/agentcore.json`, `agentcore/cdk/lib/cdk-stack.ts`, `agentcore/cdk/test/code-review-runtime.test.ts` - secret grant, no `bedrock:`, env (S-217)
- `docs/runbooks/code-review-deployment.md` - key secret, tier check, deploy order, rollback, error codes (S-217); verification log (S-218)
- `infra/changes/<ChangeId>/{plan.md,commands.sh,rollback.sh,result.md}` - infra change record (S-218)

## Tasks

- [x] 1.0 Implement Story S-216 - https://github.com/llipe/dev-tasks-agent-fleet/issues/480: Review call on Claude Sonnet 5.5 through the Anthropic API
  - [x] 1.1 [code-review] `[T]` Add `tests/fixtures/anthropic_fake.py`: a fake client that records `count_tokens` and `beta.messages.stream` requests and replays scripted messages, stop reasons, `model` values and SDK error classes (D-80)
  - [x] 1.2 [code-review] `[T]` Write failing `test_model_adapter.py` request-shape tests: `model`, `max_tokens=64000`, `output_config.effort`, `output_config.format`, `betas=["server-side-fallback-2026-07-01"]`, `fallbacks="default"`; no `tool_choice`, tools or `thinking` (D-80, D-82, D-83, D-86; AC-15)
  - [x] 1.3 [code-review] `[T]` Write the failing pinned test: `sent_schema(SUBMIT_REVIEW_SCHEMA)` equals the full schema minus `minimum`, `maxLength`, `pattern`; a reply breaking a removed keyword gets one repair call (D-81; AC-15)
  - [x] 1.4 [code-review] `[T]` Write failing `count_tokens` tests: over `B` with full files → rebuild without them; over `B` with none → `BudgetInvariantError`, nothing sent; count failure → estimate check plus `warn`; budget exactly `B` is sent (D-84)
  - [x] 1.5 [code-review] `[T]` Write failing retry tests: a `400` containing `prompt is too long` → one rebuild; a second one, or one on the repair call → `MODEL_API_ERROR`
  - [x] 1.6 [code-review] `[T]` Write failing error-mapping tests: `RateLimitError` → `MODEL_RATE_LIMITED`; `AuthenticationError`/`PermissionDeniedError` → `MODEL_ACCESS_DENIED`; other API/connection errors → `MODEL_API_ERROR`; timeout → `RUN_TIMEOUT` past the deadline, else `MODEL_API_ERROR`; final `stop_reason: refusal` → `MODEL_REFUSED` (D-72, D-85; AC-11, AC-16)
  - [x] 1.7 [code-review] `[T]` Write failing tests: `message.model` is recorded as `answered_by_model` and the artifact `model_id`; a fallback answer posts normally; 3-call cap → `CallBudgetExceeded` on a fourth (`count_tokens` not counted); cost at $2/$10 per MTok for `claude-sonnet-5-5`, `None` plus `warn` for another model (D-86, D-87)
  - [x] 1.8 [code-review] `[T]` Port `test_bedrock_hostile.py` → `test_model_adapter_hostile.py` (model text never in errors or events) and the property tests → `test_properties_model.py`
  - [x] 1.9 [code-review] `[T]` Write failing credentials tests: key read once from `ANTHROPIC_API_KEY_SECRET_ID`, registered with the scrubber before the first model call, passed to the client constructor, never in `os.environ`, logs, run events, artifacts or the prompt (D-88; AC-17)
  - [x] 1.10 [code-review] `[I]` Pin `anthropic` in `pyproject.toml`; `boto3` stays for Secrets Manager only (D-80)
  - [x] 1.11 [code-review] `[I]` Add `sent_schema()` to `findings_schema.py`; `validate_review` keeps checking the full schema (D-81)
  - [x] 1.12 [code-review] `[I]` Add `model_adapter.py`: client factory, `review()` with the `count_tokens` check, streaming call, `ReviewResult`/`CallMetrics` with the same shape, repair, retries, refusal handling, error mapping, cost; read blocks by `type` and ignore `thinking` (D-80–D-87)
  - [x] 1.13 [code-review] `[I]` Add the key fetch to `credentials.py` and `config.py`; wire the scrubber (D-88)
  - [x] 1.14 [code-review] `[I]` Switch `pipeline.py` and `main.py` imports; rename metrics to `model_ms`, `model_calls`; `output_mode` `structured_output`; footer in `render.py` uses `answered_by_model` (D-86, D-87)
  - [x] 1.15 [code-review] `[I]` Delete `bedrock_adapter.py`, `fixtures/bedrock.py` and Bedrock-only tests; move `test_pipeline_e2e.py`, `test_pipeline_prompt_capture.py`, `test_pipeline_hostile.py` to the fake Anthropic client (D-74)
  - [x] 1.16 Verify Acceptance Criterion: request shape and sent schema (AC-15) → 1.2, 1.3
  - [x] 1.17 Verify Acceptance Criterion: `count_tokens` check and `prompt is too long` retry → 1.4, 1.5
  - [x] 1.18 Verify Acceptance Criterion: error mapping and refusal failure comment (AC-11, AC-16) → 1.6
  - [x] 1.19 Verify Acceptance Criterion: answering model in footer and artifact; 3-call cap; cost; renamed metrics → 1.7, 1.14
  - [x] 1.20 Verify Acceptance Criterion: key handling (AC-17, key half) → 1.9
  - [x] 1.21 Verify Acceptance Criterion: no Bedrock code left; `pipeline.py`, `validate.py`, `budget.py` change only at imports and metric names → `grep -r bedrock pkg/` empty, diff review
    > Note (PR #484): the review path has no Bedrock code. The selection call's Bedrock client stays in the temporary `pkg/legacy_bedrock.py` (imported by `context/selection.py` and `pipeline.py`'s `bedrock_factory` dep), with `tests/fixtures/bedrock.py`, until 2.5 deletes them; `test_layout.py` pins that residual. `pipeline.py` also gained the API-key wiring (AC9), beyond imports and metric names.
  - [x] 1.22 Run edge-case tests: `max_tokens` stop, empty text, two JSON values (each → repair); refusal after fallback; fallback-model answer; 429 with `retry-after`; deadline mid-stream; `count_tokens` 5xx; budget exactly `B`
  - [x] 1.23 Record the AC-to-test mapping (AC-11, AC-15, AC-16, AC-17 key half) in the PR body
  - [x] 1.24 Run Tests: `make -C agents/code-review/app/codeReview validate` and `pnpm run validate` (lint, format:check, typecheck, test, audit)

- [ ] 2.0 Implement Story S-217 - https://github.com/llipe/dev-tasks-agent-fleet/issues/481: Selection call, params, CDK, and runbook for the Anthropic model
  - [x] 2.1 [code-review] `[T]` Port `test_selection.py` and `test_selection_hostile.py` to the fake Anthropic client; add failing tests: `max_tokens=8000`, effort `low`, stripped selection schema, fallback beta, `max_retries=0`, `timeout=min(60 s, 15% of time left)`; refusal, 429, timeout under 5 s, invalid output and empty candidates all fail open (D-71, D-82, D-83; FR-33)
  - [x] 2.2 [code-review] `[T]` Add failing bound cases to `test_properties_params.py` and `tests/fixtures/params_cases.json`: `max_diff_lines` 19,999 / 20,000 / 20,001; `max_context_tokens` 899,999 / 900,000 / 900,001 (D-77, D-90)
  - [x] 2.3 [code-review] `[T]` Add the failing large-PR prompt-capture test: a generated diff of about 393k estimated tokens is reviewed with the default params, not budget-skipped (AC-14)
  - [x] 2.4 [code-review-cdk] `[T]` Add failing assertions to `code-review-runtime.test.ts`: `secretsmanager:GetSecretValue` on the Anthropic key secret ARN only; no `bedrock:` action; env `MODEL_ID=claude-sonnet-5-5` and `ANTHROPIC_API_KEY_SECRET_ID`; no `PRICE_*` (D-74, D-88; AC-17 IAM half)
  - [x] 2.5 [code-review] `[I]` Switch `context/selection.py` to the adapter's client factory with structured output; `SELECTION_MODEL_ID` falls back to `MODEL_ID` (D-71)
  - [x] 2.6 [code-review] `[I]` Update `PARAMS_SCHEMA` in `config.py`: `max_diff_lines` maximum 20,000 (default 2,000); `max_context_tokens` default and maximum 900,000 (D-77, D-90)
  - [x] 2.7 [supabase] `[I]` Create the migration `supabase/migrations/<ts>_seed_code_review_agent.sql` with the same schema and defaults; update `supabase/seed.sql`; document rollback in the migration header (re-apply the previous seed's values; roll it back before the runtime) (D-89)
  - [x] 2.8 [code-review] `[I]` Make `test_seed_contract.py` and the Python/Ajv parity fixtures pass
  - [ ] 2.9 [code-review-cdk] `[I]` Update `agentcore.json` and `cdk-stack.ts`: secret grant, Bedrock grant removed, env updated (D-74, D-88)
  - [ ] 2.10 [repo root] `[I]` Update `docs/runbooks/code-review-deployment.md`: create and rotate the key secret, tier/ITPM check (D-78), deploy order runtime → migration → riel rule (D-89), v1.8 rollback, the new `MODEL_*` error codes (FR-49a)
  - [ ] 2.11 Migration gate: do **not** apply the migration in this story; applying it is S-218 step 3.5, with explicit user confirmation
  - [ ] 2.12 Verify Acceptance Criterion: selection on Anthropic, fail-open (FR-33) → 2.1
  - [ ] 2.13 Verify Acceptance Criterion: params bounds and seed migration parity (FR-1) → 2.2, 2.8
  - [ ] 2.14 Verify Acceptance Criterion: large PR reviewed (AC-14) → 2.3
  - [ ] 2.15 Verify Acceptance Criterion: CDK grants and env (AC-17 IAM half) → 2.4
  - [ ] 2.16 Verify Acceptance Criterion: runbook covers the key secret, tier check, deploy order, rollback and error codes → 2.10 review
  - [ ] 2.17 Record the AC-to-test mapping (AC-14, AC-17 IAM, FR-1) in the PR body
  - [ ] 2.18 Run Tests: `make -C agents/code-review/app/codeReview validate`, `pnpm run validate` (panel, Ajv parity), `npm test` in `agents/code-review/agentcore/cdk`

- [ ] 3.0 Implement Story S-218 - https://github.com/llipe/dev-tasks-agent-fleet/issues/482: Infra pass and live verification on Claude Sonnet 5.5
  > Note: runs through `/infra-engineer` after the integration PR is merged to `main`. One approval per step; every step has a rollback.
  - [ ] 3.1 [repo root] Plan the change and create `infra/changes/<ChangeId>/` with `plan.md`, `commands.sh`, `rollback.sh`
  - [ ] 3.2 Create the secret `agent-fleet/prod/ANTHROPIC_API_KEY` from the key the user enters (`! aws secretsmanager create-secret …` or the console); its value never appears in the record or the session (D-88)
  - [ ] 3.3 Record the tier check: the account's input-tokens-per-minute limit for `claude-sonnet-5-5`; if it is under 900,000, lower the default `max_context_tokens` through a follow-up migration (D-78; Q10)
  - [ ] 3.4 Run the live structured-output probe: record whether `maxItems` is accepted and adjust `sent_schema` if not (Q9); confirm the `prompt is too long` message (Q12)
  - [ ] 3.5 Deploy runtime v6 (it includes the v1.6 change from #478) and verify; then, **with explicit user confirmation**, apply the seed migration and verify the `agents` row and the panel form (900,000 accepted, 900,001 rejected); then set the riel `/review` rule's `max_diff_lines` to 20,000 (D-89)
  - [ ] 3.6 Verify Acceptance Criterion AC-12: seeded-bug fixture PR → blocking finding; clean PR → clear; 5-PR smoke recorded with `answered_by_model`
  - [ ] 3.7 Verify Acceptance Criterion AC-14: a live riel PR of 200k+ tokens is reviewed
  - [ ] 3.8 Verify Acceptance Criterion AC-17: no `bedrock:` action on the runtime role; the key is absent from the runs' CloudWatch logs
  - [ ] 3.9 Record p95 `model_ms` (Q11)
  - [ ] 3.10 Run edge cases live: docs-only PR (still no model call), over-line-cap PR (> 20,000 lines), a 429 if the tier is low
  - [ ] 3.11 [repo root] Write `result.md`; add a v1.8 entry to the runbook verification log; open a draft PR with the change record and the log (never merged by an agent)

## Decisions Consumed

| ID   | Decision (short form)                                                    |
| ---- | ------------------------------------------------------------------------ |
| D-71 | Selection call also on Sonnet 5.5                                        |
| D-72 | Server-side fallback; a final refusal is a visible failure              |
| D-74 | No Bedrock path                                                          |
| D-77 | `max_diff_lines` maximum 20,000                                          |
| D-78 | Tier 4+, checked before deploy                                           |
| D-80 | `anthropic` SDK with streaming; `model_adapter.py`                       |
| D-81 | Structured outputs with a stripped sent schema; full-schema validation   |
| D-82 | Adaptive thinking with effort; selection at `low`                        |
| D-83 | `max_tokens` 64,000 review, 8,000 selection                              |
| D-84 | `count_tokens` check before every call                                   |
| D-85 | SDK retries; `MODEL_*` error codes                                       |
| D-86 | Fallback beta; `answered_by_model` recorded and shown                    |
| D-87 | Price table $2/$10 per MTok; `PRICE_*` retired                           |
| D-88 | Key secret in Secrets Manager; IAM reads that secret only                |
| D-89 | Deploy order: runtime, migration, riel rule                              |
| D-90 | `max_context_tokens` default and maximum 900,000                         |
