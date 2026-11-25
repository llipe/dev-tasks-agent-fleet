# Fidelity Report — code-review agent v1.7 (Anthropic model), PRD-level rollup

**Fidelity: High** · **Highest drift impact: Major** (one finding, R-01, in the S-218 procedure, not in delivered code; non-blocking) · Scope: planner run `code-review-anthropic-model`, S-216 (#480, PR #484) + S-217 (#481, PR #485), `origin/main...origin/integration/code-review-anthropic-model` at `fe596fd` (main `4c8f840`). S-218 (#482) is out of scope and not started.

- Mode: Audit (PRD-level rollup), verifier, 2026-11-25.
- Sources: PRD `docs/requirements/prd-code-review-agent.md` v1.7; spec `workstream/specification-prd-code-review-agent.md` v1.8; decisions D-70–D-90; stories S-216/S-217/S-218; test plan §14 and matrix §F; task list `workstream/tasks-prd-code-review-agent-v1.7-plan.md`; `docs/roadmap.md`; `docs/runbooks/code-review-deployment.md`.
- Per-story audits are on PR #484 (S-216) and PR #485 (S-217). Their findings are not repeated here; they are merged into the consolidated list in §4.
- Drift never blocks PR readiness or issue completion. Every open item goes to `product-engineer`'s `activity-drift-reconciliation` unless another owner is named.

## 1. What changed and why

The code-review agent used to review pull requests with a DeepSeek model on Amazon Bedrock. That model could not read large pull requests, so about one riel review in eight was skipped. After these two stories, the agent talks to one provider, Anthropic, with one model (Claude Sonnet 5.5) and one API key kept in AWS Secrets Manager. That covers both the main review and the earlier step that picks which spec and verifier documents to read. No Bedrock model code is left. The size limits now allow much larger reviews: up to 20,000 changed lines and a 900,000-token budget. A database update to carry those limits to production is written but not applied.

Nothing is deployed yet. The live agent is still the old DeepSeek build. The next story, S-218, is the hands-on infrastructure pass: create the key, check the account's rate limit, deploy, apply the database update, and test it live.

The two stories fit together cleanly. The second story removed every temporary piece the first one left. Both calls read the key the same way, once per run, and they apply the same rule for a reply that the backup model finished. The runbook explains how to roll the change out and back. The main gap is in that plan: one fallback step it describes would not work. If the account's rate limit turns out lower than the new budget, the plan says to lower the default with a database update. Most reviews start from a PR comment, though, and the agent fills those defaults from its own code, not from the database. So the database update alone would not lower them. S-218 should settle this before it deploys.

## 2. Per-AC results (rollup)

| AC / FR | Description | Codebase evidence | Workstream evidence | Test evidence | Result |
| --- | --- | --- | --- | --- | --- |
| FR-1 (D-77, D-90) | `max_diff_lines` max 20,000 (default 2,000); `max_context_tokens` default = max = 900,000 | `config.py` `PARAMS_SCHEMA`; migration `20261125120000_seed_code_review_agent.sql`; `seed.sql` §4a | Tasks 2.2, 2.6–2.8 checked; 2.11 (not applied) honoured | `test_payload.py`, `test_properties_params.py`, `test_seed_contract.py`, `params_cases.json` parity | Pass |
| FR-18 / AC-15 | One Messages call, structured outputs, stripped sent schema, full-schema validation, one repair | `model_adapter.py` request builder, `findings_schema.sent_schema`; selection reuses the factory and `answer_text` | Tasks 1.2–1.12 | `test_model_adapter*.py`, CT-15 real SDK | Pass (live `maxItems` acceptance is S-218, Q9) |
| FR-19 / AC-16 | `MODEL_ID=claude-sonnet-5-5`; answering model in footer and artifact; one adapter; no Bedrock path | `agentcore.json` env; `pipeline.py` footer and artifact `model_id`; `test_layout.py` pins removal | 1.14, 1.15, 2.5 | `test_layout.py::test_no_bedrock_*`, `test_render.py` | Pass |
| FR-29 / AC-11 | Rate limit after retries, surviving refusal → `failed` with a code and failure comment | `model_adapter.py` error mapping; `render.canonical_code` | 1.6 | `test_outcomes.py`, CT-17 | Pass |
| FR-32 / FR-33 | Selection on Sonnet 5.5, one attempt, `min(60 s, 15%)`, fails open | `context/selection.py`; `Pipeline._selection_client` (`max_retries=0`, uncounted, same key) | 2.1, 2.5, 2.12 | `test_selection*.py`, `test_pipeline_selection.py`, CT-15 | Pass (see DF-38) |
| AC-14 | ~393k-token PR reviewed at default params | Budget default 900,000 | 2.3, 2.14 | `test_pipeline_prompt_capture.py::test_large_pr_*` | Pass at L2; live half is S-218 (SC-LIVE-16) |
| AC-17 | Key from Secrets Manager; never in log, event, artifact, comment; role has no `bedrock:` | `credentials.fetch_anthropic_key`; `Pipeline._api_key` (one fetch, scrubber first); `iam/runtime-role-policy.json` | 1.9, 1.13, 2.4, 2.9 | `test_credentials.py`, RT-20, CDK `code-review-runtime.test.ts` | Pass at L1/L2; live half is S-218 (SC-LIVE-17/18) |
| AC-12 | Live seeded-bug / clean PR / 5-PR smoke on Sonnet 5.5 | n/a | Task 3.6 open | none yet | Not in scope (S-218) |

**Cross-story handover (the rollup focus)**

| Check | Result | Evidence |
| --- | --- | --- |
| No Bedrock residue | Holds | Outside tests, every `bedrock` mention in `agents/code-review/` is the AgentCore runtime SDK. `legacy_bedrock.py`, `fixtures/bedrock.py`, `bedrock_factory` and the S-216 residual allowlists are gone. `boto3` stays only for Secrets Manager. `test_layout.py` pins all of this. No panel or Supabase code references `bedrock_ms`, `BEDROCK_*` or `forced_schema`. The only live-state residue is `infra/environments.yaml` (R-05), which is accurate until S-218. |
| One key path | Holds | `main.pipeline_deps.resolve_model_key` → `credentials.fetch_anthropic_key(settings.anthropic_api_key_secret_id)` → `Pipeline._api_key()` (locked, once per run, registered with the scrubber before return). The review (`_model_client`) and selection (`_selection_client`) both take it from there into `model_adapter.make_client(api_key=…)`, never `os.environ`. If the fetch fails during selection, selection fails open and the review fetches again. |
| One fallback rule | Holds | `model_adapter.answer_text` (text blocks after the last `fallback` block) is the only parser. It is used by `_parse` (review) and `selection.py:500`. Both send `FALLBACK_BETA` and `FALLBACKS` from `model_adapter`. The spec text still says "the concatenated `text` blocks" (DF-39 / S216-01). |
| Migration and runtime compatibility | Holds as designed | The v6 `PARAMS_SCHEMA` is a superset of the v1.4 seed (same keys, wider bounds), so v6 accepts every old value. v5 rejects `max_context_tokens` > 400,000. The migration header, runbook §1a and Rollback step 4 all put the runtime first and the migration rollback before the runtime rollback (D-89). Exception: R-01 (who owns the defaults). |
| Deploy-order safety (IAM) | Holds | Runbook §1a step 3 gives a two-pass role policy (interim = final plus the backup's `bedrock:InvokeModel`), so neither v5 nor v6 loses access during the cut-over. D7's second simulation command is present. |
| Rollback completeness | Mostly | Reverse order, Bedrock grant from the change backup, and the v5 commit `f4443bd` are all named. Missing: how to run the old seed statement against the live project (R-03). |
| Runbook coverage (FR-49a/b) | Satisfied | S-217 changed the IAM policy, CDK tests, env and migration, and rewrote `docs/runbooks/code-review-deployment.md` in the same PR. No coverage finding. `last_verified` 2026-11-04 is within 90 days. |

**Gates re-run on the integrated tree** (fresh `git archive` of `fe596fd`): `make validate` in `agents/code-review/app/codeReview`: 3527 passed, coverage 99.48%; ruff check, ruff format, mypy and pip-audit clean. CDK jest: 22/22. CI does not run the CDK jest suite (R-10).

## 3. What S-218 must still do, and readiness

**Present before deploy (delivered here):** the runtime code and image definition, `agentcore.json` env, the desired-state role policy, CDK assertions, the seed migration with header, verify query and rollback, `seed.sql`, the deployment runbook (key create/rotate without shell history, tier check, deploy order, two-pass IAM, v1.8 rollback, error codes), and ADR-011.

**Left strictly for S-218 (#482):** change record `infra/changes/<ChangeId>/`; tier/ITPM check (Q10); key secret creation (record the full ARN; optionally pin the suffix, D2); live structured-output probe (Q9 `maxItems`, Q12 `prompt is too long`, DF-29 `count_tokens` with `output_config`); two-pass role policy; runtime v6 deploy (includes v1.6 #478); seed migration with explicit confirmation; riel `/review` rule `max_diff_lines` 20,000 (and its `max_context_tokens` if set under `static`); live AC-12, AC-14, AC-17; `message.model` equal to the price key (DF-31); p95 `model_ms` (Q11, DF-38); `infra/environments.yaml` update (R-05); the runbook's v1.8 verification-log row and `last_verified`; spec §17 Q9–Q12 write-back.

**S-218 readiness: Ready to start once the consolidated PR merges to `main`, with conditions.** Nothing in the delivered code blocks the infra pass. Before the deploy step, the change record must include:

1. A resolved answer to R-01. If ITPM < 900,000, the lower default needs a code change (`config.py` `DEFAULT_PARAMS`, seed parity tests) merged before deploy, not only a seed migration.
2. The live probe as a hard gate before the runtime deploy (R-02). A rejected `maxItems` would fail every review with `MODEL_API_ERROR`.
3. The interim two-pass role policy document.
4. Concrete forward and rollback commands for the migration (R-03): `supabase db push --dry-run`, with a stop if anything else is pending, then the SQL Editor or `psql` method for re-applying the old seed statement.
5. The step order from R-04: deploy soon after the merge, and no unrelated `db push` until the runtime is on v6.

## 4. Consolidated open drift list (deduplicated)

Status: **Open-W** = write-back only (code already pins the value); **Open-D** = needs a decision; **S-218** = resolved by the live pass; **Closed** = no action left.

| ID | Source(s) | Finding | Impact | Intent | Status | Route |
| --- | --- | --- | --- | --- | --- | --- |
| R-01 | Rollup | **Who owns the param defaults.** Webhook runs send only the rule's `static` and payload params (`panel/lib/domain/webhook-resolve.ts`; Ajv `useDefaults: false`; `panel/lib/schema/validate.ts` projects only the keys present and fills no defaults). The runtime fills the rest from its own `DEFAULT_PARAMS` (`main.apply_defaults`). So (a) the ITPM-below-900k path in runbook §1a step 1, task 3.3, TC-218-04 and D-78/D-90 ("a follow-up seed migration lowers the default") would not lower the budget of a `/review` run. It needs `config.py` plus the parity tests plus a redeploy. (b) Right after the v6 deploy, before the migration, a `/review` run without a `static` `max_context_tokens` already runs at 900,000. TC-218-09's premise ("v6 runs on the old 150,000 default") holds only for panel-prefilled runs. | Major (conditional on ITPM) | Unintended | Open-D | `infra-engineer` (S-218 gate) + `product-engineer` (D-78/D-89 note, TC-218-04/09) + `technical-writer` (runbook §1a step 1) |
| R-02 | Rollup | Runbook §1a's "fixed order" has no step for the live structured-output probe (S-218 AC4, task 3.4: Q9, Q12, DF-29). It also does not say how to produce the exact `sent_schema` payload. Task 3.4 does come before 3.5, so the story is right and the runbook is not. | Minor | Unintended | Open-W | `technical-writer` (runbook) + `infra-engineer` (S-218 plan) |
| R-03 | Rollup | Rollback step 4.2 says "re-apply the 20261103120000 statement" but gives no method. `supabase db push` never re-runs an applied migration, so it needs the SQL Editor or `psql`. History still lists `20261125120000` as applied afterwards, which is intended but unstated. §1a step 5 also lacks the `db push --dry-run` / "stop if anything else is listed" guard the bug-fix runbook uses. | Minor | Unintended | Open-W | `infra-engineer` (S-218 `commands.sh`/`rollback.sh`) + `technical-writer` |
| R-04 | Rollup | Once `20261125120000` is on `main`, any operator `supabase db push` for other work applies it before runtime v6. v5 then rejects every panel-prefilled run (900,000 > 400,000). | Minor | Undetermined | Open-D | `planner` (note in the consolidated PR body) + `infra-engineer` (run S-218 promptly; dry-run guard) |
| R-05 | Rollup | `infra/environments.yaml` code-review entry still says `model_id: deepseek.v3.2` and `change: …20261024-code-review-runtime/`. Accurate until S-218; no story's file list names it. | Minor | Unintended | S-218 | `infra-engineer` (S-218 change PR) |
| R-06 | Rollup | Task list: parent `2.0` is `[ ]` while 2.1–2.18 are `[x]`. Task 1.21's note still describes `legacy_bedrock.py` as present. | Minor | Unintended | Open-W | `planner` (consolidated PR) |
| R-07 | Rollup | PRD status line (line 25) lists amendments through v1.6 only. The §8 out-of-scope rationale (line 174) still cites goal 5, which D-79 dropped. | Minor | Unintended | Open-W | `product-engineer` (PRD changelog) |
| R-08 | Rollup (roadmap) | Roadmap mismatch: the v1.7 row says `Not started`, but S-216 and S-217 are merged. The v1.6 row ("redeploy or ship with v1.7") ships as runtime v6 in S-218. The Wave B row's "`PRICE_*` unset, so `cost_usd` is null" is superseded by D-87. Proposed text in §6. | Minor | Unintended | Open-W | `planner` (consolidated PR) |
| R-09 | S-217 D1 | The story, task 2.9 and the file list name `cdk-stack.ts`. The grant is a desired-state `iam/runtime-role-policy.json` on an imported role, and `cdk-stack.ts` is unchanged. | Minor | Intended | Open-W | `product-engineer` |
| R-10 | S-217 qa-engineer | CI does not run `agents/*/agentcore/cdk` jest, so the AC-17 IAM half is gated only locally. The live role is applied by hand (`put-role-policy`), so file-vs-live drift shows only in SC-LIVE-17. | Minor | Unintended | Open-D | Follow-up issue (`qa-engineer` / `housekeeping`) |
| R-11 | S-217 D2 | The Anthropic secret grant uses the `-??????` suffix wildcard, not the full ARN. | Minor | Intended | S-218 | `infra-engineer` (optionally pin after creation) |
| R-12 | S-217 D3 | A selection answered by an unpriced model records `selection_cost_usd = null` with no warning (D-87 says "with a warning"). | Minor | Undetermined | Open-D | `product-engineer`, then `developer` if yes |
| R-13 | DF-38 + S-217 D4 | Streaming read timeouts bound the gap between events, not the total. An abandoned review stream keeps billing after the run ends, and the selection `t` does not cap the total time or the key fetch. | Minor | Undetermined | Open-D, measured in S-218 (SC-LIVE-19) | `product-engineer`; `infra-engineer` measures |
| R-14 | DF-39 + S-216 drift 1 | Spec §6.3 still says "the concatenated `text` blocks". The code (fixed in `f475527`) uses the text blocks after the last `fallback` block, ignores other block types, and treats no text as invalid output. | Minor | Intended (code) | Open-W | `product-engineer` (spec §6.3) |
| R-15 | DF-23 | Spec §13: the `MODEL_*` rows have no "Failure comment" cell. The code says `yes`. | Minor | Unintended | Open-W | `product-engineer` |
| R-16 | DF-24 | Spec §13 "Code mapping" still says "the nine codes"; there are eleven. | Minor | Unintended | Open-W | `product-engineer` |
| R-17 | DF-25 | `RateLimitError` past the deadline → `RUN_TIMEOUT` (the code and §13 agree; §6.3 and the story have no deadline clause). | Minor | Undetermined | Open-D (ratify) | `product-engineer` |
| R-18 | DF-26 | Any final `refusal` (first call, rebuild or repair) → `MODEL_REFUSED`, no repair. | Minor | Undetermined | Open-D (ratify) | `product-engineer` |
| R-19 | DF-27 | Exact count over `B` on the repair request → `MODEL_OUTPUT_INVALID`. | Minor | Undetermined | Open-D (ratify) | `product-engineer` |
| R-20 | DF-28 | One context-length rebuild per run, whichever trigger. | Minor | Undetermined | Open-D (ratify) | `product-engineer` |
| R-21 | DF-29 | The count payload drops `max_tokens`, `betas` and `fallbacks`. Whether `count_tokens` accepts `output_config` is unverified. | Minor | Undetermined | Open-D + S-218 (TC-218-05) | `product-engineer`; `infra-engineer` probes |
| R-22 | DF-30 | D-80 still says `client.messages.stream`; the spec and code use `beta.messages.stream`. | Minor | Unintended | Open-W | `product-engineer` (decision log) |
| R-23 | DF-31 | The price key is an exact match on `message.model`. A dated or alias string from the API gives `cost_usd: null`. | Minor | Undetermined | S-218 (TC-218-07) | `infra-engineer` |
| R-24 | DF-32 | Answering model: the accepted call's model; `null` if missing; cost `None` when models are mixed. | Minor | Undetermined | Open-D (ratify) | `product-engineer` |
| R-25 | DF-33 + S-217 D6 | Spec §5.2 still lists `bedrock_error`; the code and runbook use `api_error`. | Minor | Unintended | Open-W | `product-engineer` |
| R-26 | DF-34 | Key-fetch failure → `INTERNAL_ERROR` (`ANTHROPIC_KEY_UNAVAILABLE`), fetched after the GitHub token. | Minor | Undetermined | Open-D (ratify) | `product-engineer` |
| R-27 | DF-35 + S-217 D6 | Stale Bedrock text left in the spec: §5.1 "maximum of 400,000 … `B` + 16,000" (line 225), §5.2 example `"output_mode": "forced_schema"` (line 240), §12 "secrets in the diff can reach Bedrock" (line 736). Fixed: §14 L2 now names the fake Anthropic client. §17 Q4 sits in the block already marked superseded, so close it. | Minor | Unintended | Open-W | `product-engineer` |
| R-28 | S-216 drift 2 | Story S-216 AC10 says `pipeline.py` changes only at imports and metric names. The key, footer and artifact wiring needed more. | Minor | Intended | Open-W | `product-engineer` (story wording) |
| R-29 | DF-36 | PRD AC-17 says "comment" and the story says "prompt"; the tests cover both. | Minor | Intended | Open-W (story wording) | `product-engineer` |
| R-30 | DF-37 | AC-14 at L2 uses `max_diff_lines` 2,000; the live check uses the rule's 20,000. | Minor | Intended | S-218 (SC-LIVE-16) | `infra-engineer` |
| R-31 | S-216/S-217 docs | Foundation docs still carry the old names (`docs/product-context.md`, `docs/technical-guidelines.md`; no `docs/tech.md`). | Minor | Unintended | Open-W | `technical-writer` (propose `dev-tasks migrate docs`) |

**Closed in the integrated tree (no action):** S-216 drift 1 code half (`f475527`), S-216 drift 3 (prompt wording, intended), S-216 drift 4 (selection on Bedrock: removed by S-217), S-216 drift 5 (ADR-010 addendum and technical guidelines updated), S-217 D5 (`18c17a7`), S-217 D7 (`5a10700`).

Not drift: SonarCloud duplication on #485 (7.5% vs 3%, the seed migration by design) is an existing non-required gate.

## 5. Edge-case, randomized and automated-check outcomes

- Per-story outcomes are in the #484 and #485 audits. At the rollup, the combined suite (3527 tests, including the RT property suites with their recorded seeds, e.g. 481001) passes on the integrated tree. No randomized failure needed triage.
- **Documentation structure:** not run. This repository has no `core/checks` (`checkDocsStructure` is absent), so there is no implementation to call, and I did not re-derive it by hand.
- **Vocabulary conformance:** not run, for the same reason. `docs/domain/ubiquitous-language.md` exists, but `checkExportedIdentifiers` does not. Advisory either way (D-63).

## 6. Recommendations

1. **R-01 (before S-218 deploys).** `infra-engineer` does the tier check first. If ITPM < 900,000, stop and have `developer` change `config.py` `DEFAULT_PARAMS` and the seed parity tests in a small PR before the runtime deploy. `product-engineer` amends D-78/D-90 and TC-218-04/09 to say the runtime owns the defaults for webhook runs. `technical-writer` fixes runbook §1a step 1.
2. **R-02, R-03, R-04.** Put the probe gate, the migration dry-run, and the SQL method for the rollback statement into the S-218 `plan.md`, `commands.sh` and `rollback.sh`. Have `technical-writer` fold them into the runbook in the S-218 PR. The planner should note R-04 in the consolidated PR body.
3. **R-06, R-08.** The planner fixes these in the consolidated PR. Proposed v1.7 roadmap row:

   `| [prd-code-review-agent](requirements/prd-code-review-agent.md) | v1.7 — Anthropic model | Review and selection calls on Claude Sonnet 5.5 through the Anthropic API (structured outputs, server-side refusal fallback), Bedrock path removed, budgets sized to the 1M window, max_diff_lines max 20,000 (D-70–D-90) | In progress (S-216 and S-217 merged into the integration branch via PRs #484, #485; consolidated PR #<n>; not deployed, live runtime is still v5 on DeepSeek V3.2) | #480, #481, #482; PRs #484, #485, #<n> | S-218 (#482) infra pass after merge: tier/ITPM check, API key secret, live structured-output probe (Q9, Q12), two-pass role policy, runtime v6 (includes v1.6 #478), seed migration 20261125120000, riel rule max_diff_lines 20,000; live AC-12, AC-14, AC-17 and p95 model_ms; spec/story write-back of DF-23–DF-39; duplicate-trigger bug filed separately (D-75) |`

   v1.6 row, What's missing: "Ships as runtime v6 with v1.7 (S-218, #482)". Wave B row: replace "`PRICE_*` unset, so `cost_usd` is null" with "cost from the price table since v1.7 (D-87)". `product-engineer` should decide whether S-215's DeepSeek smoke is superseded by SC-LIVE-15.
4. **R-07, R-09, R-12–R-29.** One `activity-drift-reconciliation` batch: ratify DF-25–DF-28, DF-32 and DF-34 as implemented; decide R-12 and R-13; write back spec §5.1, §5.2, §6.3, §12 and §13, D-80, the PRD status line and §8, and the S-216 AC10 / S-217 AC5 file-list wording. Do it after S-218 so the Q9–Q12 results land in the same changelog entry.
5. **R-10.** File a follow-up issue to run the CDK jest suites in CI.
6. **R-31.** `technical-writer` proposes `dev-tasks migrate docs`.

## Changelog

| Version | Date | Summary | Author |
| --- | --- | --- | --- |
| 1.0 | 2026-11-25 | PRD-level rollup audit of S-216 and S-217 on `integration/code-review-anthropic-model` at `fe596fd`; consolidated drift list (DF-23–DF-39, S-216, S-217, rollup). | verifier |
