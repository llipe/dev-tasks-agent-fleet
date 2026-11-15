# Fidelity Report — #463 + #464 (code-review: leaner diff, PRD v1.6 FR-5)

> **Fidelity: High** · **Highest drift impact: Minor** · **Blocking findings: none**
> Scope: issues [#463](https://github.com/llipe/dev-tasks-agent-fleet/issues/463) and [#464](https://github.com/llipe/dev-tasks-agent-fleet/issues/464), branch `feat/code-review-diff-context-463-464` (`af259be`, `21245ee`) vs `main`. No PR yet (pre-PR-ready audit).
> Every drift item below is **non-blocking**: it does not hold PR readiness or the issues' completion. Drift routes to `product-engineer` (`activity-drift-reconciliation`); code/doc fixes go to `developer`.

## Changelog

| Version | Date | Summary | Author |
| ------- | ---- | ------- | ------ |
| 1.0 | 2026-11-15 | Initial pre-PR-ready audit (Audit Mode). | verifier |

## 1. Human-readable summary

The code-review agent sends the model each changed file's "before vs after" view with surrounding lines, plus a full copy of changed code files. Two things wasted most of the space the model can read:

- **Documents got as much surrounding text as code.** A small edit to a document written one long paragraph per line (like `TESTING.md`) pulled in tens of thousands of words of unchanged text. Documents now get 3 surrounding lines instead of 50; code still gets 50.
- **Some files were sent twice.** A brand-new file (or a short file whose changes already show all of it) was sent once as its change view and again as a full copy. Such files are now sent once.

Both changes work as the issues ask, and all quality gates pass (3,501 tests, 99.68% coverage). The follow-ups are all small and about wording:

- A few lines in the PRD, the specification and the decision log still describe the old "50 lines everywhere" behavior.
- The specification's change history says one budget step was updated, but it was not.
- One unrelated small fix (a default for which folders the agent searches) rode along without its own issue or decision record.

## 2. Per-AC result table

| AC-ID | Description | Codebase evidence | Workstream/doc evidence | Test evidence | Result |
| ----- | ----------- | ----------------- | ----------------------- | ------------- | ------ |
| 463-AC-1 | `.md` diff uses 3 context lines; `.ts`/`.py` use 50 | `context/diff.py:415-421` `context_lines_for`; `:595` per file; `PROSE_CONTEXT_LINES = 3` `:104` | D-68; spec §8.3 step 1 (L546); PRD FR-5 L95 | `test_diff_context_by_type.py::test_context_lines_for`, `test_a_doc_file_gets_3_lines_and_code_gets_50` (hunk headers `@@ -97,7 …` vs `@@ -50,101 …`) | Pass (Drift: D-01 `.adoc`) |
| 463-AC-2 | Head path, case-insensitive (`README.MD`); `.md` → `.ts` rename uses 50 | `context_lines_for(f.filename)` (head path) `diff.py:595`; `is_doc_path` lowercases via `_suffix` `:271-278` | D-68 "the head path decides" | `test_context_lines_for[README.MD]`, `test_the_head_path_decides_on_a_rename` (both directions) | Pass |
| 463-AC-3 | Added/removed prose file unaffected (whole file) | `unified_diff` from/to `/dev/null` unchanged | — | `test_added_and_removed_doc_files_are_whole_as_before` | Pass |
| 463-AC-4 | `changed_ranges` identical at either context | `changed_ranges(base, head)` takes no context argument `diff.py:610` | §8.6 unchanged | `test_changed_ranges_do_not_depend_on_the_context` | Pass |
| 463-AC-5 | riel#632-shaped fixture keeps diff estimate < 40% of ±50 | — | Issue measurements (110,675 → 34,891, 31.5%) | `test_riel_632_shaped_long_line_doc_costs_under_40_percent` (long-line doc only; no code part in the fixture, see D-09) | Pass |
| 463-AC-6 | `make validate` green | — | `TESTING.md` baseline 99.68%, 3,501 | **Re-run by verifier:** 3,501 passed, coverage 99.68%, ruff/format/mypy/pip-audit clean ("validate: all gates passed") | Pass |
| 464-AC-1 | Added file appears once (diff), not in `full_files_included` | `prompt.py:540-547` filters `not f.diff_covers_head`; `diff.py:612` sets the flag | D-69; spec §8.3 step 6 (L567) | `test_expanded_diff_marks_covered_files`, `test_a_covered_file_is_neither_included_nor_dropped`, `test_pipeline_selection.py::test_the_selection_ranking_orders_full_file_drops` (added GUIDE) | Pass |
| 464-AC-2 | Fully covered modified file skipped; any uncovered head line keeps it a candidate | `diff_covers_head` `diff.py:424-440` | D-69 | `test_diff_covers_head_rule`, `test_diff_covers_head_boundaries_at_50_lines`, `test_diff_covers_head_agrees_with_the_emitted_diff` (seeded property test) | Pass (Drift: D-02 method) |
| 464-AC-3 | Skipped file not in `full_files_dropped`, not named in "too large" note | Never becomes a candidate, so never dropped; `render.py:790-796` unchanged | D-69 "neither included nor dropped" | `test_a_covered_file_is_not_counted_on_the_retry`; `test_pipeline_prompt_capture.py::test_prompt_capture_drops_the_largest_file_first` | Pass (Drift: D-04 wording, D-05 no `in_diff` reason) |
| 464-AC-4 | Added file keeps head line numbers (`@@ -0,0 +1,N @@`); findings validate | `changed_ranges` unchanged for added files | §8.6 | `test_an_added_file_keeps_its_head_line_numbers_and_changed_ranges` (`((1, 7),)`) | Pass |
| 464-AC-5 | riel#632 shape: 3 code files in full, added docs not repeated; §8.4.3 invariant | — | — | `test_riel_632_shape_puts_the_code_files_in_full_once` (tight budget with room for exactly the 3 modified files; invariant asserted). Uses `diff_covers_head=True` set by hand; end-to-end flag computation covered by `test_expanded_diff_marks_covered_files` | Pass |
| 464-AC-6 | `make validate` green | — | — | As 463-AC-6 | Pass |

AC coverage: 12/12 ACs have a result; 12 Pass, none Fail. Traceability `AC → test → observed → result` is the table above.

## 3. Drift catalog

All items are **non-blocking** to PR readiness and issue completion.

| ID | Description | Impact | Intent | Evidence | Recommendation |
| -- | ----------- | ------ | ------ | -------- | -------------- |
| D-01 | Prose set reuses `DOC_EXTENSIONS`, adding `.adoc` to #463's list (`.md .mdx .markdown .rst .txt`). | Minor | Intended | `diff.py:130`; D-68 row says so explicitly | No action. |
| D-02 | #464's "full-coverage skip" is computed from `difflib.SequenceMatcher.get_grouped_opcodes(context)` rather than parsed hunk headers. Same grouping `unified_diff` uses, so equivalent. | Minor | Intended | `diff.py:424-440`; property test agrees with the emitted diff (QA: 150,000 cases, no mismatch) | No action. |
| D-03 | Tests that relied on the sample PR's tiny files getting full copies now use a long `src/app.py` (`Harness.use_long_app`) or local long fixtures; sample-PR assertions flipped to "no full files". | Minor | Intended | `tests/helpers/pipeline_run.py:342-354`; `test_pipeline_e2e.py:346`, `test_prompt_sample_pr.py:86`, `test_pipeline_prompt_capture.py:85-115` | No action. |
| D-04 | When the only remaining full-file candidate is dropped, the comment now says "full files omitted to fit the model's context (1 file)" instead of naming it as "too large to include in full". Existing S-210 DR-12 branch, now hit more often because covered files are no longer candidates. | Minor | Intended | `render.py:790-796`; `test_pipeline_prompt_capture.py:114` | No action (optionally name the files in that branch too). |
| D-05 | #464 Scope 2 suggested a distinct reason (e.g. `in_diff`). Implementation records nothing: covered files are never candidates. AC-3 met, but metrics cannot tell "0 full files: all covered" from other zero cases. | Minor | Intended | D-69 row; `prompt.py:540-547`; `test_pipeline_e2e.py:346` | No action, or add a `full_files_in_diff` count to metrics later. |
| D-06 | Spec v1.7 changelog says §8.4 e was amended; it was not. Row e still reads "whole, source and tests only (docs are diff-only, D-67)". | Minor | Unintended | `workstream/specification-prd-code-review-agent.md:12` vs `:582` | `developer`: add "; a file whose diff covers the whole head file is not a piece (D-69)" to row e. |
| D-07 | Stale "±50 for every file" text in the PRD: FR-6 "whose ±50-line diff alone exceeds", AC-4 "±50 lines of context per hunk, full content of touched code files", and the PRD vocabulary "expanded diff" (the spec's row was updated, the PRD's was not). | Minor | Unintended | `docs/requirements/prd-code-review-agent.md:96`, `:238`, `:341` (spec `:899` is current) | `developer`: FR-6 → "whose expanded diff alone"; AC-4 → "±50 lines for code, ±3 for documentation (D-68); full content of touched code files the diff does not show whole (D-67, D-69)"; copy spec L899 text to PRD L341. |
| D-08 | #463 Scope 2 asks to note the per-type context in the "D-26 text". The D-26 rows are unannotated (`n=50`); D-68 rows say "amends D-26". The repo usually leaves amended rows untouched (D-61 was not edited for D-67), so this is a cross-reference gap, not a contradiction. D-04 (PRD L300) and D-61 ("±50-line diff of every file") are historical too. | Minor | Undetermined | `workstream/decisions-code-review-agent.md:32`, `:67`; spec `:852`; PRD `:300` | `product-engineer`: append "(amended by D-68)" to the D-26 rows, or confirm the convention and close. |
| D-09 | #463 AC-5's fixture is "a long-line markdown file with a small change, **plus code**"; the test measures only the doc file. Including unchanged-ratio code would raise the ratio (riel#632: 31.5%), still under 40%. | Minor | Unintended | `test_diff_context_by_type.py:119-132` | `developer` (optional): add a code file to the fixture and assert on the summed estimate. |
| D-10 | "Documentation" means two things: diff context uses the extension only (`docs/conf.py` → ±50), full-file tier uses extension **or** `docs/` prefix (`docs/conf.py` → no full copy). D-68's rationale says `.adoc` was added "so docs mean one thing everywhere", which is not quite true. Behaviour matches #463 ("by extension") and spec §8.3 step 1. | Minor | Undetermined | `diff.py:276-278`, `:294-301`; `test_context_lines_for[docs/conf.py]`; D-68 row | `product-engineer`: reword D-68 ("the doc extensions") or decide that `docs/` code also gets ±3. |
| D-11 | Out-of-scope change: `pipeline.py` falls back to `DEFAULT_CONTEXT_FOLDERS` instead of `""` when `context_folders` is absent. Production always runs `apply_defaults` (`main.py:366`), so this is hardening for direct callers. No issue or decision row; only the commit message records it. | Minor | Intended | `pipeline.py:1160-1164`; `test_full_files_in_diff.py:217-229` | Mention it in the PR body. |
| D-12 | Fixture README still calls the golden "the expected ±50-line expanded diff". Golden is unchanged (its doc file is added, so whole either way). | Minor | Unintended | `tests/fixtures/github/sample-pr/README.md:26` | `developer` (optional): "expanded diff (±50 code, ±3 docs)". |

## 4. Documentation structure and vocabulary

- **Documentation structure:** not applicable. This repository has no `core/checks` (`tsx core/checks/run.ts` → `ERR_MODULE_NOT_FOUND`) and no `docs/runbooks/` structure check to run. No finding.
- **Vocabulary conformance:** `checkExportedIdentifiers` unavailable (same reason); the change adds no TypeScript `export`. Manual check: `docs/domain/ubiquitous-language.md` defines no "prose"/"documentation file" term, so `PROSE_CONTEXT_LINES` (vs "documentation" in the PRD/spec) hits no forbidden synonym. No finding.
- **Stale ±50-only / "every touched file in full" text:** code, prompt label (`prompt.py:153-156`), system prompt (`prompt.py:297`), `rubric.md`, the deployment runbook and the README files carry no stale text. Stale doc text is in D-06, D-07, D-08, D-12.
- **Runbook coverage:** not triggered (no task list; code and doc steps only; no script/workflow/infra change). The runtime redeploy after merge follows the existing `docs/runbooks/code-review-deployment.md`.
- **Roadmap:** the v1.6 row (`docs/roadmap.md:12`) names the scope, #463/#464 and "after merge: redeploy". Its status "In review (not deployed)" is outside the roadmap vocabulary (`Not started` / `In progress` / `Done`); advisory, use `In progress (in review, not deployed)`. Pre-existing and outside this diff: the Wave B row (`:13`) and the runbook `last_verified` still say runtime v4, while row `:11` and `cf463f6` record v5.

## 5. Randomized test outcomes

No prior test plan exists for this scope. QA added a seeded property test (`test_diff_covers_head_agrees_with_the_emitted_diff`) checking that `diff_covers_head` agrees with the hunk ranges of the emitted `unified_diff`. It asserts both outcomes occur. The QA commit reports 150,000 cases with no mismatch. The seed is fixed in the test, so a failure replays by re-running it. Boundary tests pin off-by-one at a hunk gap and at the last line.

## 6. Recommendations

| Item | Next step | Owner |
| ---- | --------- | ----- |
| D-06, D-07 | Amend spec §8.4 row e and PRD FR-6 / AC-4 / vocabulary (text above). | `developer` (route via `activity-drift-reconciliation`) |
| D-08, D-10 | Decide the D-26 annotation convention; reword the D-68 rationale or extend ±3 to `docs/` code. | `product-engineer` |
| D-09, D-12 | Optional test/fixture-README touch-ups. | `developer` |
| D-11 | Name the `context_folders` fallback in the PR body. | `developer` |
| Roadmap | Status wording on `:12`; v4→v5 on `:13` and the runbook (pre-existing). | `product-engineer` |
| D-01–D-05 | No action needed. | — |

## Publication

Pre-PR audit; no PR exists yet. The caller is to link this report from the PR body and from #463 / #464 when the draft PR opens. This audit did not post to GitHub because it was scoped to a single uncommitted write.

## Remediation (developer, 2026-11-15, before PR ready)

| Item | Action |
| ---- | ------ |
| D-06 | Fixed: spec §8.4 row e says a file whose diff covers the whole head file is not a piece (D-69). |
| D-07 | Fixed: PRD FR-6 ("expanded diff alone"), AC-4 (±50 code, ±3 docs; code files the diff does not show whole), PRD vocabulary "expanded diff". |
| D-08 | Fixed: D-26 rows in the PRD and spec decision tables marked "Amended by D-68", the convention used for D-61 → D-67. |
| D-09 | Fixed: the riel#632-shaped test adds a modified code file and asserts the PR's summed diff estimate is under 40% of the ±50 figure. |
| D-10 | Fixed: D-68 no longer claims docs mean one thing everywhere; it states the extension-only match and that D-67's full-file rule also treats `docs/` paths as documentation. Unifying the two rules is left as an open question. |
| D-12 | Fixed: the sample-pr fixture README. |
| Roadmap | Fixed: the v1.6 row status reads "In progress (in review, not deployed)"; the Wave B row and the deployment runbook's `last_verified` now say runtime v5. |
| D-01–D-05, D-11 | Intended; listed in the PR body. |
