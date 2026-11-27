# Fidelity Report — Issue #482 (S-218) sub-tasks 3.4.1–3.4.6: sent-schema `maxItems` fix

**Fidelity: High** | **Highest drift impact: Minor** | **Drift findings: 10 (all non-blocking)**

Scope: llipe/dev-tasks-agent-fleet issue #482 (S-218), PR #504, branch `issue/482-sent-schema-maxitems`, diff `origin/main...HEAD` (7 commits, 9 files). Audited 2026-11-26 by `verifier` (Audit Mode, grey-box).

---

## 1. Human-readable summary

When we tested the code-review agent against the live Anthropic API, the API refused the request. The format we send to describe the review's answer included a rule, "at most N items in this list", and the API does not accept that rule. This change stops sending that rule, for both the main review call and the smaller document-selection call. The agent still enforces the limits itself after the answer comes back: a review with more than 40 findings is still sent back for one repair, and the selection still keeps at most 6 documents. No other part of the request changed.

The change also points the agent at its own API key by default. The old default was the bug-fix agent's key, which the two agents should not share. The deployed settings and permissions on `main` still name the old key. They are updated on the separate infrastructure branch, so that branch has to go out with or before the deployment of this change.

Several planning documents still say the "at most N items" question is open, or name the old key. Those are paperwork updates for product-engineer and do not block this PR.

## 2. Requirements extracted

| AC-ID | Source | Requirement |
| --- | --- | --- |
| AC-1 | D-81, spec §6.3 l.368, task 3.4.3 | The review call's sent schema removes every keyword the API rejects; the live probe shows `maxItems` is rejected, so `maxItems` is removed at any depth. `additionalProperties: false` and `required` remain. |
| AC-2 | D-81 ("the selection call does the same"), task 3.4.2/3.4.3 | The selection call's sent schema removes `maxItems` the same way. |
| AC-3 | D-81, TC-216-12, task 3.4.2 | `validate_review` still checks the full schema: 41 findings → one repair call (`MAX_FINDINGS` = 40 enforced locally). |
| AC-4 | D-81, TC-217-02, task 3.4.2 | The selection wrapper still caps picks at `MAX_PICKS` (6), `index ≥ 1`, reason cut. |
| AC-5 | D-81, TC-216-13 | `request_tokens` counts the copy sent, not the full schema. |
| AC-6 | Caller check | Nothing else in either request shape changes. |
| AC-7 | D-88, task 3.4.4 | The default key secret ID is the code-review agent's own (`agent-fleet/prod/CODE_REVIEW_ANTHROPIC_API_KEY`), read once per run, overridable by `ANTHROPIC_API_KEY_SECRET_ID`. |
| AC-8 | `implement` test-first rule, tasks 3.4.2/3.4.4 | Tests are written before the implementation code. |
| AC-9 | Task 3.4.1, 3.4.5, 3.4.6 | Probe result recorded; validate gate recorded; re-probe left open for after merge. |

## 3. Per-AC results

| AC-ID | Description | Codebase evidence | Workstream evidence | Test evidence | Result |
| --- | --- | --- | --- | --- | --- |
| AC-1 | Review sent schema strips `maxItems` | `findings_schema.py:267` `SENT_SCHEMA_STRIPPED = {"minimum","maxLength","pattern","maxItems"}`; `model_adapter.py:528` sends `sent_schema(SUBMIT_REVIEW_SCHEMA)`. Remaining keywords in the sent copy: `type`, `properties`, `required`, `additionalProperties`, `items`, `enum` (checked by script) | Task 3.4.3 `[x]` | `test_sent_schema_pinned` (literal fixture without `maxItems: 40`), `test_sent_schema_keeps_structure_…`, new `test_sent_schema_request_carries_no_max_items` (no `maxItems` anywhere in `output_config`), CT-16 `test_ct16_sent_is_full_minus_exactly_the_stripped_keywords` | Pass |
| AC-2 | Selection sent schema strips `maxItems` | `context/selection.py:347` sends `sent_schema(SELECTION_SCHEMA)` — same function, so the strip applies; docstring updated (l.23–24) | Task 3.4.3 `[x]` | `test_sent_selection_schema_is_pinned` (literal without `maxItems: 6`, plus no `maxItems` in `output_config`), `test_request_shape` | Pass |
| AC-3 | `MAX_FINDINGS` still enforced locally | `findings_schema.py:92` full schema keeps `maxItems: MAX_FINDINGS`; `_check_array` l.258 enforces it | — | `test_repair_41_findings_goes_to_repair` (repair_calls == 1); `test_repair_not_needed_for_full_schema_edges[40-findings]`; new test asserts `SUBMIT_REVIEW_SCHEMA…maxItems == 40` | Pass |
| AC-4 | `MAX_PICKS` still enforced locally | `selection.py:292` full schema `maxItems: MAX_PICKS`; `selection.py:475` parse loop stops at `MAX_PICKS` | — | `test_parse_discards_duplicates_and_entries_past_six` (6 kept, 4 discarded); `test_sent_selection_schema_is_pinned` asserts full `maxItems == MAX_PICKS` and `minimum == 1` | Pass |
| AC-5 | `request_tokens` counts the sent copy | Unchanged; estimate is over `output_config` as sent | — | `test_sent_schema_request_tokens_count_the_copy_sent` passes with the smaller sent schema | Pass |
| AC-6 | No other request-shape change | Diff touches only the strip set and docstrings in production code; no change to `model_adapter.py` request builder or `selection.build_request` | — | Pinned literal request/schema fixtures in `test_selection.py::test_request_shape` and `test_model_adapter.py` changed only by the removed `maxItems` lines | Pass |
| AC-7 | Default key secret is code-review's own | `config.py:45` `DEFAULT_ANTHROPIC_API_KEY_SECRET_ID = "agent-fleet/prod/CODE_REVIEW_ANTHROPIC_API_KEY"`; env override at `config.py:236–237` unchanged; `credentials.py:94` falls back to the default | Task 3.2 text and 3.4.4 `[x]` updated | `test_anthropic_key_secret_id_defaults`, new `test_anthropic_key_secret_id_default_is_not_the_bug_fix_key`, `test_credentials.py` `GetSecretValue(SecretId=…CODE_REVIEW…)` | Pass (see DR-8, DR-9) |
| AC-8 | Test-first ordering | Schema: `b5e3ecf` (tests) precedes `820367e` (fix). Key default: `d24a73a` carries test and code in one commit | Task 3.4.4 says "tests first" | Reproduced: at `b5e3ecf` 6 schema tests fail (pinned review/selection schemas, no-`maxItems` request, CT-16, structure test, selection request shape); at `820367e` all pass (one extra failure in both, `test_ct08_constant_equals_spec_6_3_verbatim`, is an artifact of the extracted tree lacking `workstream/`; it passes at HEAD) | Drift (Minor, DR-10) |
| AC-9 | Probe recorded, gate recorded, re-probe open | — | 3.4.1 `[x]` with the probe error and ITPM 5,000,000; 3.4.5 `[x]` (3,529 passed, 99.48% coverage, lint/format/mypy/pip-audit clean); 3.4.6 `[ ]` after merge; parent 3.4 `[ ]` | Verifier re-ran the 6 affected unit modules at HEAD: 461 passed (not the full `validate` gate; the 3,529 / 99.48% figures come from the task list and were not re-run) | Pass |

Quality gates are recorded as passing in task 3.4.5. This audit adds to those gates and does not replace them.

## 4. Drift catalog

Drift findings are **non-blocking** to PR readiness and to issue completion. They go to `product-engineer` through `activity-drift-reconciliation`.

| ID | Description | Impact | Intent | Evidence source(s) |
| --- | --- | --- | --- | --- |
| DR-1 | Spec §6.3 sent-schema paragraph (`specification-prd-code-review-agent.md` l.368) still says "whether `maxItems` survives is settled by a live test in the infra pass, §17 Q9". The live probe settled it: rejected, so it is stripped. The pinned-test sentence should list `maxItems` among the stripped keywords. | Minor | Intended | Spec l.368; probe req_011ChSPkrmLiYuKwsmwoExbZ; `findings_schema.py:267` |
| DR-2 | Spec §17 Q9 (l.862) is still an open question. Partly resolved: `maxItems` is rejected and stripped, and after the strip no other array constraint is left in either sent schema. Still open until 3.4.6: whether the stripped schema is accepted end to end, the `count_tokens` + `output_config.format` question (DF-29), and Q12, which the probe did not reach. | Minor | Intended | Spec l.862; task 3.4.1, 3.4.6 |
| DR-3 | Spec risk R1 (l.830): the risk happened (`maxItems` rejected) and was mitigated as planned. Its status should say so. | Minor | Intended | Spec l.830 |
| DR-4 | Decision log D-81 (`decisions-code-review-agent.md` l.87) says "any array constraint the API refuses beyond `maxItems`", which reads as if `maxItems` is kept. Update it: `maxItems` is stripped too (S-218 probe, 2026-11-26), and local enforcement still applies. | Minor | Intended | Decision log l.87 |
| DR-5 | Test plan TC-216-08 (`test-plan-prd-code-review-agent.md` l.824) says "`maxItems: 40` **kept** (pending live Q9)". The pinned fixture now leaves it out. | Minor | Intended | Test plan l.824; `test_model_adapter.py` `SENT_SCHEMA_PINNED` |
| DR-6 | Test plan TC-217-02 (l.887) says "`maxItems: 6` kept pending Q9". The pinned fixture now leaves it out. The wrapper-enforcement clause is still correct. | Minor | Intended | Test plan l.887; `test_selection.py` `SENT_SELECTION_SCHEMA` |
| DR-7 | Test plan TC-218-05 (l.931): record the outcome (`maxItems` rejected → follow-up PR #504), and note that the `count_tokens` (DF-29) and Q12 parts were not reached and move to the 3.4.6 re-probe. New test `test_sent_schema_request_carries_no_max_items` has no TC ID. Suggest tracing it to TC-216-08 or adding a new TC. | Minor | Intended | Test plan l.931, l.1079 |
| DR-8 | D-88's secret name is stale across the artifacts: `agent-fleet/prod/ANTHROPIC_API_KEY` appears in decision log D-88 (l.94), spec env-var list (l.715) and decision summary (l.927), test plan TC-216-46 (l.862), TC-217-23 (l.908), S-218 AC2 (l.918), and TC-218-03 (l.929). The code and task 3.2 now use `agent-fleet/prod/CODE_REVIEW_ANTHROPIC_API_KEY`, because the old name is the bug-fix agent's key. | Minor | Intended | Listed lines; `config.py:45`; `agents/bug-fix/agentcore/agentcore.json:23` on `main` |
| DR-9 | **Ordering note.** On `main`, `agents/code-review/agentcore/agentcore.json:23` sets `ANTHROPIC_API_KEY_SECRET_ID=agent-fleet/prod/ANTHROPIC_API_KEY`. `iam/runtime-role-policy.json:78` grants only that ARN, and `cdk/test/code-review-runtime.test.ts:33` pins it. The env var overrides the config default, so a runtime deployed from `main` after this PR still reads the bug-fix key until the infra branch (ChangeId `20261125-code-review-anthropic-v18`) updates all three. If `agentcore.json` changes without the IAM policy, the run fails with `AccessDeniedException`. Merge or deploy the infra branch changes with or before this runtime goes out. This PR does nothing wrong here. | Minor | Intended | `origin/main` `agentcore.json:23`, `runtime-role-policy.json:78`, `code-review-runtime.test.ts:33` |
| DR-10 | Test-first ordering was not kept at commit level for the key default. `d24a73a` changes `config.py` and its tests in one commit, while task 3.4.4 says "tests first". The schema change did follow test-first (`b5e3ecf` → `820367e`, failures reproduced). | Minor | Undetermined | `git show --stat d24a73a` |

Count: 10 drift findings. DR-1 to DR-8 are spec, decision-log and test-plan write-backs. DR-9 is a deployment ordering note. DR-10 is a process note.

## 5. Edge-case, randomized, and advisory checks

- **RT-16 (property test, seed 480003):** `test_properties_model.py` passes at HEAD. Its keyword pool already includes `maxItems`, so the oracle now also checks that `maxItems` is removed.
- **No remaining array constraints:** a script walk over `sent_schema(SUBMIT_REVIEW_SCHEMA)` and `sent_schema(SELECTION_SCHEMA)` finds only `type`, `properties`, `required`, `additionalProperties`, `items`, `enum`. There is no `minItems` or `uniqueItems` to probe further.
- **Documentation structure:** not run. `core/checks` is not present in this repository, so `tsx core/checks/run.ts` cannot resolve. The PR touches nothing under `docs/`.
- **Vocabulary conformance:** not run, for the same reason (`checkExportedIdentifiers` is unavailable). The production diff adds no new exported identifiers, only a changed constant value and a changed frozenset member.
- **Runbook coverage (FR-49b):** not triggered. The PR's sub-tasks are code changes, not three or more configuration/environment/data steps, and the PR does not touch `templates/scripts/` or workflows.
- **Roadmap:** no mismatch. S-218 is open and the v1.7 row is `In progress`, which is correct.

## 6. Recommendations

| ID | Next step |
| --- | --- |
| DR-1–DR-4 | `product-engineer`: spec and decision-log changelog write-back (Q9 partly resolved, R1 realized, D-81 wording), with human confirmation. |
| DR-5–DR-7 | `product-engineer`: test-plan write-back (TC-216-08, TC-217-02, TC-218-05; trace the new test). |
| DR-8 | `product-engineer`: amend D-88 and the spec/test-plan secret name references. |
| DR-9 | `infra-engineer`: land the `agentcore.json`, IAM policy and CDK test updates from the infra branch with or before runtime v6. No code change in this PR. |
| DR-10 | No action needed. Process note only. |

## Changelog

- 2026-11-26 — v1.0, initial audit of PR #504 (verifier, Audit Mode).
