# Coverage Report: Code Review Agent, Wave A (PRD-level qa-engineer gate)

## Changelog

| Version | Date       | Summary                                                              | Author      |
| ------- | ---------- | -------------------------------------------------------------------- | ----------- |
| 1.0     | 2026-10-23 | PRD-level completion gate for Wave A (S-204 to S-213, #406 to #415). | qa-engineer |

## Summary

```
coverage_gate: PASS
```

- **Scope:** `agents/code-review/app/codeReview/`. Branch `integration/code-review-agent`. The run started at `9e1d73e`.
  During the run, a concurrent docs-only commit `6d9d2c2` landed. It touched nothing under `agents/`, so the
  results below hold for both SHAs. That commit also picked up this gate's two additive `/TESTING.md` edits (see
  Files changed).
- **Package `make validate`:** green. That covers ruff, ruff format, mypy, pytest with coverage at
  `fail_under = 90`, and `pip-audit --strict`.
- **Coverage:** 99.51% combined line and branch: 4,104 statements and 1,154 branches. Every module is at 100% except
  `pipeline.py` (97%) and `main.py` (98%).
- **New tests:** `tests/integration/test_cross_story_joins.py` adds 12 cross-story tests: 10 pass and 2 are strict
  xfails that pin defects.
- **Defects:** 2 new, both Minor (QA-PRD-01, QA-PRD-02). Neither is Critical or Major. No production code was changed.
- **Mapping check:** all 202 test-name citations resolve. The traceability matrix v1.2 has 116 checks over 111
  tokens; the test plan v1.2 has 86 checks over 86 tokens. 0 are unresolved.
- **Reachability:** root `make test` and the CI matrix both reach the package. There are two harness defects
  (H-1 and H-2 below).
- **Root `make validate`:** not run. The sibling venvs (`dependency-update`, `security-analyst`) are missing.
  Only `agents/code-review/app/codeReview/.venv` exists.

## 1. Package `make validate` (`PATH=.venv/bin:$PATH make validate`)

| Gate                    | Result                                                      |
| ----------------------- | ----------------------------------------------------------- |
| `ruff check .`          | All checks passed                                           |
| `ruff format --check .` | 107 files already formatted                                 |
| `mypy .`                | Success: no issues found in 101 source files (notes only)   |
| `pytest --cov`          | 3,115 passed, 2 skipped, 2 xfailed (136 s), CPython 3.13.16 |
| coverage `fail_under`   | 90 required, 99.51% measured                                |
| `pip-audit . --strict`  | No known vulnerabilities found                              |

Before this gate's tests were added, the baseline at `9e1d73e` was 3,105 passed, 2 skipped, 99.47%, and also green.
Both skips are `tests/unit/test_seed_contract.py:300`. They wait for `agentcore.json`, which lands in S-214
(Wave B).

## 2. Coverage per module (branch coverage on)

| Module                      | Stmts | Miss | Branch | BrPart |  Cover | Missing                                                                                              |
| --------------------------- | ----: | ---: | -----: | -----: | -----: | ---------------------------------------------------------------------------------------------------- |
| bedrock_adapter.py          |   464 |    0 |    110 |      0 |   100% |                                                                                                      |
| budget.py                   |   206 |    0 |     30 |      0 |   100% |                                                                                                      |
| config.py                   |    72 |    0 |     20 |      0 |   100% |                                                                                                      |
| context/conventions.py      |    42 |    0 |      0 |      0 |   100% |                                                                                                      |
| context/diff.py             |   222 |    0 |     60 |      0 |   100% |                                                                                                      |
| context/issues.py           |   103 |    0 |     30 |      0 |   100% |                                                                                                      |
| context/markdown.py         |    20 |    0 |      8 |      0 |   100% |                                                                                                      |
| context/repo_conventions.py |   125 |    0 |     48 |      0 |   100% |                                                                                                      |
| context/spec.py             |   128 |    0 |     38 |      0 |   100% |                                                                                                      |
| context/tokens.py           |    26 |    0 |     10 |      0 |   100% |                                                                                                      |
| context/verifier.py         |   201 |    0 |     68 |      0 |   100% |                                                                                                      |
| credentials.py              |    87 |    0 |     14 |      0 |   100% |                                                                                                      |
| findings_schema.py          |    97 |    0 |     46 |      0 |   100% |                                                                                                      |
| github_client.py            |   396 |    0 |    134 |      0 |   100% |                                                                                                      |
| heartbeat.py                |    41 |    0 |      6 |      0 |   100% |                                                                                                      |
| main.py                     |   168 |    2 |     64 |      2 |    98% | 62, 383                                                                                              |
| pipeline.py                 |   576 |   17 |    122 |      5 |    97% | 426->437, 445, 764->770, 767, 1222-1223, 1239-1242, 1250-1251, 1266-1267, 1272-1273, 1292-1293, 1309 |
| prompt.py                   |   296 |    0 |     90 |      0 |   100% |                                                                                                      |
| render.py                   |   518 |    0 |    176 |      0 |   100% |                                                                                                      |
| scrubber.py                 |    14 |    0 |      8 |      0 |   100% |                                                                                                      |
| signal_backstop.py          |    27 |    0 |      6 |      0 |   100% |                                                                                                      |
| validate.py                 |   275 |    0 |     66 |      0 |   100% |                                                                                                      |
| **TOTAL**                   |  4104 |   19 |   1154 |      7 | 99.51% |                                                                                                      |

The coverage artifact is valid. `source = ["."]` measures the whole package. The only file omitted is the vendored
`agent_reporter.py`, which is byte-identical to the sibling's copy. `main.py` is measured. The report was produced
fresh by this run, not read from a stale `.coverage` file.

This gate's tests newly cover `pipeline.py:1088`. That line is the post-render `_scrub_body` replacement, and
before this gate no test had ever made it fire. The comment-scrub path for render-reassembled secrets was therefore
unexercised.

## 3. Cross-story joins (structural analysis and new tests)

The tests are in `tests/integration/test_cross_story_joins.py`. They drive the real `main.invoke` through
`tests/helpers/pipeline_run.py`. The only replacements are `FakeConverse`, `StubTransport`, and the reporter sink.

| Join or invariant                                         | What was checked                                                                                                                                                                                                                                                                                                                                                                                                                         | Test                                                                                                    | Result               |
| --------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------- | -------------------- |
| Every Converse call ≤ B                                   | The worst 5-call sequence (forced → reasoning retry → fallback → context-length retry → repair) at B = 20,000, with a full file in the first build. Each request is recounted **independently** of `request_tokens`: `ceil(len/3.5)` over every string under `system` and `messages`, plus `json.dumps(toolConfig)`.                                                                                                                     | `test_worst_five_call_sequence_fits_b_and_the_repair_context_flows_downstream`                          | Pass                 |
| ≤ B on repair                                             | A 900,000-char invalid tool input is cut so that the repair request stays ≤ B.                                                                                                                                                                                                                                                                                                                                                           | `test_a_huge_invalid_output_is_cut_so_the_repair_request_fits_b`                                        | Pass                 |
| `ContextData` from retry and repair → validate and render | After a repair or an R4 retry, the accepted build (no full files) is the one that `metrics.context_tokens`, the artifact `context.full_files_*`, the comment, and validate's candidates all use. V1 confirmed in the repair output gives `blocking`. `estimated_first_call_tokens` stays the first build's.                                                                                                                              | same, plus `test_a_context_length_retry_context_is_what_validate_and_render_see`                        | Pass                 |
| `escape_path`: match form versus render form              | Path `src/we\u2028ird\tname.py`. The prompt shows `src/we\\u2028ird\\tname.py` and has no raw U+2028. The model cites it in escaped, raw, or backticked `./` form; all three match. The comment shows `` `src/we\\u2028ird\\tname.py:1` ``, the same form the model saw. The artifact keeps the canonical raw path.                                                                                                                      | `test_the_escaped_path_the_model_saw_matches_and_renders_the_same` (3 cases)                            | Pass                 |
| `OverBudget` on both paths                                | Line budget (`check_size`) and token budget (`build_prompt`) give the same terminal state (`succeeded`/`not_applicable`, no verdict, no error). Neither path makes a Converse call, sends to the prompt sink, or writes an artifact. `comment_chars == comment_size(body)`. The comment's line count equals the run's `changed_lines` metric. Name-only files are listed on both paths.                                                  | `test_both_over_budget_paths_end_alike_and_agree_with_the_metrics` (2 cases)                            | Pass                 |
| One comment, ≤ 60k `comment_size`                         | The largest schema-valid review: 40 findings at every `maxLength`, all astral characters (more than 200k UTF-16 units before neutralization), plus `<!--`, `</details>`, mentions and links. Result: one POST, ≤ 60,000 `comment_size`, a single `<!--` (the marker), `comment_truncated` true.                                                                                                                                          | `test_a_hostile_review_is_one_comment_within_60k_utf16_units`                                           | Pass                 |
| No secret in the comment (render-reassembled)             | The token and the Supabase key, split by U+200B in the model output. `neutralize` removes the U+200B, and `_scrub_body` catches the joined, escaped form.                                                                                                                                                                                                                                                                                | `test_a_secret_split_by_invisible_characters_never_reaches_the_comment`                                 | Pass                 |
| Scrub before render                                       | Reviewed by reading the code. `_scrub_validation` and `_scrub_render_inputs` run after `validate` (which matches raw paths) and before every cut. `_scrub_name_only` runs before the note renderers. `_rendered_forms` covers the raw, `neutralize`, and `code_span` forms. The `neutralize` regexes (`_GH_REF_RE` lookbehind, `://`, `www.`) were probed: the standalone form or the raw form always matches the embedded one.          | review, plus the existing `test_secrets_*` and `test_a_secret_straddling_a_path_cut_leaves_no_fragment` | No defect            |
| `comment_chars` on the review path                        | The spec (§5.3) says `comment_chars` is the `comment_size` of the **posted** body.                                                                                                                                                                                                                                                                                                                                                       | `test_comment_chars_is_the_size_of_the_posted_body_after_the_scrub`                                     | **xfail: QA-PRD-01** |
| No secret in the artifact                                 | The same split-secret review, checked against every reporter write.                                                                                                                                                                                                                                                                                                                                                                      | `test_a_split_secret_never_reaches_any_reporter_write`                                                  | **xfail: QA-PRD-02** |
| Never silent, except the documented paths                 | Reviewed against `FAILURE_COMMENT` and `_fail`. The documented silent paths are: 404 or closed/merged PR, `INVALID_PARAMS`, `COMMENT_POST_FAILED` with permission denied, no token, and no time left (under `MIN_POST_SECONDS`). Every other code attempts exactly one comment. The existing `test_pipeline_hostile.py` already exercises this per step and per sub-call, including the seed 415002 property, so no new test was needed. | existing                                                                                                | No defect            |

## 4. Defects

| ID        | Severity                                                                      | Where                                                                                     | Defect                                                                                                                                                                                                                                                                                                                                                                                                                                         | Expected state                                                                                                                                                                                   | Reproducer                                                                                                                                                                                                                                                                                                                            |
| --------- | ----------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| QA-PRD-01 | Minor (metrics contract)                                                      | `pipeline.py` `Pipeline._post_review` (`self._metrics["comment_chars"] = rendered.chars`) | On the review path, `comment_chars` is measured before `_scrub_body`. When the post-render scrub fires, the metric is larger than the posted body: measured 1,051 recorded versus 994 posted. The note path (`_post_note`) measures after the scrub, so the two paths disagree.                                                                                                                                                                | `comment_chars = comment_size(body)` of the scrubbed body that is POSTed (spec §5.3, "Comment").                                                                                                 | Model title `"uses " + "\u200b".join(TOKEN)`. Pinned by `test_comment_chars_is_the_size_of_the_posted_body_after_the_scrub` (strict xfail).                                                                                                                                                                                           |
| QA-PRD-02 | Minor (defense in depth; violates the "no secret anywhere" invariant in form) | `pipeline.py` `_post_review` → `scrub_value(audit_metadata(...))`                         | `scrub_value` matches only the exact raw secret. A secret split by format characters (U+200B) in model text survives into the `audit_report` artifact (`run_artifacts` POST, `findings[].title`/`failure_scenario`), where any viewer that drops format characters shows it as the whole secret. The comment is clean only because `neutralize` rejoins the secret and `_scrub_body` then catches it. Run events and the run record are clean. | No reporter write contains a secret after format characters (Unicode `Cf`) are removed: for example, scrub a copy with `Cf` characters stripped, or strip them from model text before scrubbing. | The same model title. Pinned by `test_a_split_secret_never_reaches_any_reporter_write` (strict xfail). Precondition: the model would have to emit a secret it is never given. The token is minted per run and is never in the prompt; the Supabase key reaches the prompt only if it is already committed to the reviewed repository. |

Both defects route to `developer`. Each fix turns its XPASS red, and the marker is removed with the fix. This gate
changed no production code.

## 5. Mapping check (test plan v1.2 and traceability matrix v1.2)

- **Method:** a script (kept in the session scratchpad, not committed) extracted every backticked test citation
  from both documents. It resolved each one against the `def test_*` names under `tests/`. File-qualified
  citations (`file.py::test_x_*`) were checked against that file. Globs (`test_x_*`) and slash forms
  (`test_tc211_03/04/05/15_*`) were expanded.
- **Result:** matrix 116 of 116 resolve; test plan 86 of 86 resolve; **0 unresolved**. The check was re-run after
  `6d9d2c2` changed the test plan, with the same result.
- **Five bare citations resolve only as prefixes** (`test_budget_msg`, `test_call_budget`, `test_failure_msg`,
  `test_no_report`, `test_payload`). They name a family of tests, not one test. This is cosmetic.
- **Thirty sampled resolutions (grep):**
  - `test_a_stuck_phase_is_abandoned_at_the_deadline`
  - `test_ac9_downgrade_and_drop`
  - `test_blocking_review`
  - `test_budget_comment_post_failure_is_comment_post_failed`
  - `test_budget_path`
  - `test_candidate_blocks_*` → `..._carry_row_text_inside_and_ids_outside`
  - `test_closed_pr`
  - `test_context_length_*` → `..._retries_once_without_full_files`
  - `test_context_step_logs_block_token_counts`
  - `test_ct06_*` → `..._forced_fallback_and_repair_key_sets`
  - `test_d50_*` → `..._a_blocking_span_is_at_most_200_lines`
  - `test_draft_pr`
  - `test_drift_section_over_4000_tokens_is_capped_but_candidates_come_from_the_whole`
  - `test_error_mapping_*` → `..._permission_denied_on_get`
  - `test_estimated_input_tokens_sums_every_call`
  - `test_failure_msg_*` → `..._snapshot`
  - `test_forbidden_*` → `..._call_raises_before_transport`
  - `test_github_client.py::test_method_*`
  - `test_huge_and_duplicate_ranks_sort_stably`
  - `test_issue_403_*` → `test_issue_403_note`
  - `test_layout_*` → `..._blocking_snapshot`
  - `test_metrics_never_contain_finding_text`
  - `test_new_comment_each_run`
  - `test_no_report_*` → `..._both_paths_404_is_state_none`
  - `test_nonce_*` → `..._marker_integrity`
  - `test_paging_*` → `..._stops_at_30_pages_and_reports_truncation`
  - `test_reasoning_*` → `..._rejected_retries_once_without_the_field`
  - `test_retry_*` → `..._get_5xx_three_attempts_then_api_error`
  - `test_rubric_system_prompt_rules`
  - `test_run_link_*` → `..._rejects_injection`
- **TC-ID traceability:**
  - 33 of the 194 Wave A TC IDs in the plan do not appear verbatim in test code. All but the manual and live IDs are
    cited through ranges in module docstrings, for example `TC-210-01..19` in `test_bedrock_adapter.py`,
    `TC-206-06..14` in `test_diff.py`, and `TC-213-01..TC-213-31` in `test_pipeline_e2e.py`.
  - The manual and live IDs have no test by design: TC-204-17, TC-204-19, TC-209-18, TC-212-19, TC-213-32.
  - CT-09, CT-10 and RT-13 are cited by test name only (`test_artifact_metrics`, and `test_outcomes.py` seed 415001),
    not by ID. This is advisory.

## 6. Script reachability

| Gate                            | Reaches `code-review`?           | Evidence                                                                                                                                                                                                                                                                                 |
| ------------------------------- | -------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Package `make validate`         | Yes                              | Run in this gate (section 1).                                                                                                                                                                                                                                                            |
| Root `make test` / `test-py`    | Yes                              | `AGENT_DIRS` lists `agents/code-review/app/codeReview` third. `make -n test-py` loops into it. It is fail-fast in order (H-2).                                                                                                                                                           |
| Root `make validate`            | **Not run**                      | The sibling venvs are missing. Only the code-review `.venv` exists.                                                                                                                                                                                                                      |
| CI (`.github/workflows/ci.yml`) | Yes, on PRs and pushes to `main` | The `python-quality` matrix has `agent: code-review` with `package-dir: agents/code-review/app/codeReview`, on 3.13 and 3.14, with `fail-fast: false`. Its steps are lint → format → mypy → `pytest --cov` (enforces `fail_under = 90`) → `make audit`. The CI run link was not checked. |
| Deploy gate                     | None yet                         | The AgentCore runtime lands with S-214. No deploy workflow invokes the aggregate.                                                                                                                                                                                                        |

**Harness defects** (added to `/TESTING.md` "Harness defects to track", items 7 and 8):

- **H-1:** `.github/workflows/ci.yml` triggers only on `push`/`pull_request` to `main`. Story PRs into
  `integration/code-review-agent` (#425 to #438) never ran CI, so their gates were local only.
  - _Expected state:_ `pull_request` also matches `integration/**`, or the planner records that CI is deferred to the
    consolidated PR.
- **H-2:** root `test-py` and `validate-py` stop at the first failing package, and `code-review` is last. A sibling
  failure (the `security-analyst` CVE, S-204 D8) or a missing sibling venv means the root aggregate never reaches
  `code-review`.
  - _Expected state:_ run every package and fail at the end, or report the packages that were not reached.
- **Advisory, not a defect:** the CI comment calls 3.14 "the AgentCore production runtime", but this agent's
  container is `python:3.13-slim`. Both versions are gated in CI. This gate ran 3.13 only, because no local 3.14 was
  available.

## 7. Ranked residual gaps (Wave A, automatable)

| Rank | Gap                                                                                                                                                                                                                                                                                                | Risk                | Where                                      |
| ---- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------- | ------------------------------------------ |
| 1    | QA-PRD-02: secrets in the artifact are matched in exact form only. No test strips format characters before scrubbing events or metrics.                                                                                                                                                            | Minor               | `pipeline.py` `scrub_value`, `_Events.log` |
| 2    | The "nothing after a posted comment fails the run" branch (`_finish_posted`, `pipeline.py:1239-1242`, and `764->770`/`767`) has no test. It is reachable when the reporter's `post` step `__exit__` raises after the comment is posted, or on `KeyboardInterrupt` after posting.                   | Minor               | `pipeline.py`                              |
| 3    | The `_fail` and `_succeed` self-guards (`1222-1223`, `1250-1251`, `1266-1267`, `1272-1273`, `1292-1293`) and the second-call guard in `_failure_comment` (`1309`) are uncovered. They are defensive branches.                                                                                      | Low                 | `pipeline.py`                              |
| 4    | QA-PRD-01: `comment_chars` on the review path.                                                                                                                                                                                                                                                     | Minor               | `pipeline.py`                              |
| 5    | The ≤ B guarantee is by estimate (`ceil(len/3.5)`), not by the real tokenizer. An estimate that undercounts is caught only by the live R4 retry (see Wave B).                                                                                                                                      | Minor (known, D-27) | `context/tokens.py`                        |
| 6    | Uncovered small branches: `_scrub_render_inputs` with `verifier is None` (`426->437`; dead in the pipeline, because `verifier_candidates` always returns a context), the empty-secret skip in `_rendered_forms` (`445`), the reporter `__exit__` fallback in `main.py:62`, and `__main__` (`383`). | Low                 | `pipeline.py`, `main.py`                   |
| 7    | The ValidationException message patterns (toolChoice, reasoning, context length) are matched against fixture strings, not real Bedrock messages.                                                                                                                                                   | Minor               | `bedrock_adapter.py` `*_PATTERNS`          |

## 8. Wave B live checks (not run; listed separately)

- **SC-LIVE-01 to SC-LIVE-12:** AC-1 live, AC-2, AC-3, AC-12 (seeded bug and clean PR), AC-13 live, the 5-PR smoke
  test, and latency and cost (S-215).
- **TC-213-32:** manual run on a scratch PR. TC-214-11: panel manual invoke.
- **Infrastructure and deployment:**
  - TC-214-01 to TC-214-13: `agentcore.json`, IAM, model access, runbook. Includes un-skipping the 2
    `test_seed_contract.py` cases and the DF-09 `agentcore.json` half.
  - TC-204-15 and TC-204-19 (L2.5 seed migration; needs Docker) and TC-215-01 to TC-215-05 (rule routing; G-1).
- **GitHub's comment-length unit (§17 Q6):** confirm that 60,000 `comment_size` (UTF-16) is under GitHub's real limit
  on a live POST.
- **D-27 recalibration:** `estimated_input_tokens` against real `input_tokens`. Also confirm that the real Bedrock
  context-length, toolChoice and reasoning rejection messages match the `*_PATTERNS` constants.
- **G-4:** the fallback model switch (DeepSeek V4 Pro); there is no fixture or live check yet. **DF-13 PR half:**
  live only.

## 9. Not analyzed, and why

- Root `make validate`: the sibling venvs are missing.
- Python 3.14: not installed locally. CI covers it, but the CI run was not inspected.
- The panel side (CT-01 Ajv parity) and Layer 2.5: outside the package scope, and Docker is unavailable.
- Real Bedrock and real GitHub behavior: Wave B.
- Fidelity judgment of whether these tests prove the ACs: handed to `verifier`.

## Files changed by this gate

- Created: `agents/code-review/app/codeReview/tests/integration/test_cross_story_joins.py`
- Created: `workstream/coverage-report-prd-code-review-agent.md` (this file)
- Edited: `/TESTING.md`. The `code-review` coverage baseline line got the Wave A figures, and harness defects 7 and 8
  were added. Both are additive. The concurrent commit `6d9d2c2` ("docs: fix Wave A rollup findings RU-01 to RU-08")
  swept these edits in, so they are already committed on the branch and not pending in the working tree.
