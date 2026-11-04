# Fidelity Report — Code Review Agent PRD v1.5: full code files (verifier, Audit Mode)

**Fidelity: High** · **Highest drift impact: Minor** · 9 drift items (0 Critical, 0 Major, 9 Minor); 5 Unintended (DR-04 to DR-08, all stale wording in docs, comments, or decision tables). All non-blocking.
**Scope:** `docs/requirements/prd-code-review-agent.md` v1.5 (FR-5 amended), decision D-67 (amends D-61), spec v1.6 §8.3 step 6 and §8.4. Branch `feat/code-review-full-code-files`, range `origin/main..HEAD` (8ece8ed feature + docs, dfcbc67 QA tests). No GitHub issue; no PR yet.
**Audit status:** complete, not blocked. Every requirement has codebase, spec and test evidence.

## Changelog

| Version | Date       | Change                                    | Author   |
| ------- | ---------- | ----------------------------------------- | -------- |
| 1.0     | 2026-11-03 | Initial pre-PR audit of PRD v1.5 delivery. | verifier |

## 1. Human-readable summary

When the code reviewer has too little room, it has to choose what to show the AI. Before this change, the complete text of each changed file came last, after the background documents (the spec and the project conventions). Large specs could push the complete source files out, so the AI saw only the changed lines and the lines around them. Documentation files also used up room as complete copies.

Now only code files (source and tests) are sent as complete copies. Documentation files are sent as their changes only, which is how the reviewer already reads them. The complete code files go in before the spec and the conventions. So when room is short, the spec is shortened first. This is what the user asked for on 2026-11-03.

The code does what the request asks, and the tests check it. One small behavior changed as a side effect, and it was expected. Some documentation and code comments still describe the old order. They should be corrected so that later readers are not misled. None of these findings has to be fixed before the PR is opened.

## 2. Per-requirement results

| AC-ID | Description | Codebase evidence | Workstream evidence | Test evidence | Result |
| --- | --- | --- | --- | --- | --- |
| AC-1 (FR-5, D-67) | Only code files (source, tests) get a full head copy; docs (doc extension or under `docs/`) are diff-only and neither included nor dropped | `prompt.py:531-537` `_pieces` filters `file_tier(f.filename) != TIER_DOC`; `context/diff.py:284` `file_tier` | spec §8.3 step 6 (line 566), D-67 | `test_full_code_files.py::test_documentation_files_get_their_diff_only` (README.md, `docs/guide.py`, `workstream/audit.md` absent as files, present in diff block), `::test_the_retry_drops_only_code_files`; integration pins `test_pipeline_e2e.py:346`, `test_pipeline_prompt_capture.py`, `test_pipeline_selection.py:168`, `test_prompt_sample_pr.py` | Pass |
| AC-2 (FR-5, D-67) | Full code files filled at e, after drift sections, before spec (f) and conventions (g) | `budget.py:117-125` `FILL_ORDER`; `budget.py:368-371` `fill` | spec §8.4 table (lines 581-583) | `test_full_code_files.py::test_a_complete_code_file_is_kept_before_a_large_spec` (spec note `budget`), `::test_code_files_do_not_take_the_drift_sections_room`; `test_budget_fit.py::test_full_code_files_before_the_spec_which_starves_conventions`, FILL_ORDER pin | Pass |
| AC-3 (FR-5, D-61 retained) | Within code files: source before tests; selection rank, else smallest-first placement (largest dropped first); ±50-line diff always kept | `budget.py:327` `full_file_order` (unchanged), `each_that_fits` | spec §8.4 e, "Full-file order" | `test_file_tiers.py` (unchanged, green), `test_pipeline_selection.py::test_the_selection_ranking_orders_full_file_drops` | Pass |
| AC-4 (R4 / repair) | `include_full_files=False` drops code files only; context-length retry only when the prompt has a full file | `bedrock_adapter.py:1027` (unchanged) | spec §16 R4 ("only when the prompt has one") | `::test_a_docs_only_pr_is_not_retried_on_context_length`, `::test_the_context_length_retry_counts_and_notes_code_files_only`, `::test_a_docs_only_pr_has_no_full_file_and_no_full_file_note` | Pass (DR-01) |
| User intent (2026-11-03) | "more context on code files only, the complete file, not only the diff"; chosen option "code-only full files (docs diff-only) + full code files filled before spec/conventions" | as AC-1, AC-2 | D-67, PRD v1.5 changelog | as AC-1, AC-2 | Pass |

Gates: `make validate` re-run by the verifier: 3,468 passed, 2 skipped, "validate: all gates passed".

## 3. Drift catalog

Every item below is **non-blocking** to PR readiness and issue completion. Routing: `product-engineer` `activity-drift-reconciliation`.

| ID | Description | Impact | Intent | Evidence |
| --- | --- | --- | --- | --- |
| DR-01 | A reviewed PR whose every full-file candidate is documentation-tier and that Bedrock rejects for context length now ends `BEDROCK_ERROR` (`WARN_CONTEXT_NO_FILES`) on the first rejection; before, it retried once without the doc full copies. Reachable only for PRs that pass the FR-35 extension-only docs-only skip, e.g. `README.md` + a lockfile, or root `docs/*.py`/`docs/*.json`. The first prompt is now the same size the old retry prompt was, so no PR that used to succeed now fails because of this change; only the retry call is gone. | Minor | Intended | `bedrock_adapter.py:1027`; spec §16 R4; `test_a_docs_only_pr_is_not_retried_on_context_length` |
| DR-02 | `docs/` is matched only at the repository root and case-sensitively (`context/diff.py:290` `path.startswith("docs/")`, the D-61 rule unchanged). `packages/x/docs/*.py` and `Docs/*.py` get full copies. Nested `.md` files are still docs through their extension. This matches the "code files only" intent. FR-5's "under `docs/`" does not say root-only. | Minor | Intended | `context/diff.py:284-295`; PRD FR-5 (line 94) |
| DR-03 | Full code files can now take all of `R`, which leaves the spec `omitted (budget)` and the conventions starved, where before the files starved. The PR title and body (a), candidates (b), issues (c) and drift sections (d) are unaffected. This is what D-67 asks for ("a large spec is trimmed before a complete code file is dropped"). The R4 and repair rebuilds give the spec its room back. | Minor | Intended | `budget.py:368-371`; `test_full_code_files_before_the_spec_which_starves_conventions` |
| DR-04 | Stale code comments and docstrings still describe the D-61 tiers or the old step letter. `budget.py:328` calls `full_file_order` "(g)", and `budget.py:330` says "documentation first, source last (D-61)". `budget.py:426` (`ContextData`) says included plus dropped "are every reviewed, non-removed file", which is now every reviewed, non-removed **code** file. `context/diff.py:125-126` says "dropped documentation first". `context/selection.py:6` and the selection prompt at `:301` still rank documentation for "the full-file fill", which is harmless but no longer used. | Minor | Unintended | grep over `agents/code-review/app/codeReview` |
| DR-05 | Spec §8.4 "Full-file order" paragraph (`workstream/specification-prd-code-review-agent.md:591`) says the documentation tier "no longer applies", then keeps "documentation is dropped first and source last" in the same paragraph, which contradicts the first sentence. | Minor | Unintended | spec line 591 |
| DR-06 | The decision summary tables were not updated. PRD §18 (`prd-code-review-agent.md:321`) and spec decision table (`specification-…:884`) have no D-67 row and still show D-61 as "docs, then tests, then source". The PRD status line (`prd-code-review-agent.md:23`) lists the v1.5 date but not "v1.5 amends FR-5 per D-67". | Minor | Unintended | PRD lines 23, 321; spec line 884 |
| DR-07 | Decision log D-37 (`workstream/decisions-code-review-agent.md:43`) still states the fill order "… spec, conventions, full files" and is not marked as amended. D-67's "Amends" column names only D-61, and D-61 (`:67`) is not marked "amended by D-67". | Minor | Unintended | decisions log lines 43, 67, 71 |
| DR-08 | PRD AC-4 (`prd-code-review-agent.md:237`) still reads "full content of touched files … dropped largest-first". The spec glossary "expanded diff" (`specification-…:895`) still reads "full head content of touched files". Neither says code files only. AC-4 was already stale before this change (after D-61). | Minor | Unintended | PRD line 237; spec line 895 |
| DR-09 | Decision numbering in the code-review log jumps from D-64 to D-67, and D-65/D-66 are not used anywhere in code-review artifacts. It may be intentional, for example to avoid clashing with bug-fix D-67, but nothing says so. | Minor | Undetermined | decisions log lines 70-71 |

Checked and not stale: ADR-010 (no fill-order text), `docs/technical-guidelines.md` (no full-file or fill-order text; `docs/tech.md` is absent, old name in use), spec §8.8 context line (generic "full files" clauses, still correct), spec §16 R4, `render.py:789-797`, prompt notes `prompt.py:632`.

## 4. Edge-case, documentation, and vocabulary outcomes

- **Edge cases.** No Design Mode test plan exists for v1.5. The QA tests cover nested and non-extension docs paths (`docs/guide.py`, `workstream/*.md`), a docs-only reviewed PR with and without full files, the retry counts, and drift-section precedence. Not covered: nested `x/docs/*.py` and `Docs/*.py` (DR-02), which have no test pinning them as source.
- **Documentation structure.** `core/checks` is not present in this repository, so `checkDocsStructure` could not run. No file under `docs/runbooks/` was touched.
- **Vocabulary conformance.** `checkExportedIdentifiers` could not run (`core/checks` is absent). The added lines are Python test helpers and tests only; they add no new exported production identifier. No findings.
- **Runbook coverage (FR-49b).** Not triggered. The change has no setup, configuration or migration steps and no script or workflow. A redeploy is needed after merge, and the existing code-review deployment procedure covers it.
- **Roadmap.** No mismatch. The `docs/roadmap.md` v1.5 row is "In review (not deployed)" and links the branch, which is correct because there is no PR yet. Add the PR number once it is opened.

## 5. Recommendations

| ID | Next step |
| --- | --- |
| DR-01, DR-02, DR-03 | No action needed. Optional: a unit test that pins `packages/x/docs/a.py` as source (DR-02). |
| DR-04 | `developer`: update the comments and docstrings at `budget.py:328,330,426` and `context/diff.py:125`, and optionally drop "then documentation" from the selection prompt at `context/selection.py:301`. |
| DR-05, DR-06, DR-08 | `product-engineer`: remove the "documentation is dropped first" clause at spec:591, add D-67 rows to PRD §18 and the spec decision table, and amend the PRD status line, AC-4 and the spec "expanded diff" definition to say "code files". |
| DR-07 | `product-engineer`: mark D-37 and D-61 "amended by D-67", or add D-37 to D-67's Amends column. |
| DR-09 | `product-engineer`: confirm the D-65/D-66 gap or renumber. |

## Remediation (developer, 2026-11-03, before PR ready)

| Item | Action |
| ---- | ------ |
| DR-04 | Fixed: `budget.full_file_order` docstring (step e, tests before source), `ContextData` ("every reviewed, non-removed code file"), `context/diff.py` tier comment. The selection prompt still ranks documentation last, which stays correct and harmless. |
| DR-05 | Fixed: spec "Full-file order" paragraph now says tests are dropped before source. |
| DR-06 | Fixed: D-67 rows added to PRD §18 and the spec's decision table; D-61 rows marked "Amended by D-67"; the PRD status line says v1.5 amends FR-5 per D-67. |
| DR-07 | Fixed: D-67's Amends column names D-61 and D-37. |
| DR-08 | Fixed: PRD AC-4 and the spec's "expanded diff" vocabulary entry say code files. |
| DR-09 | Explained: D-65 and D-66 are reserved by PR #476 (Wave B's model decisions, renumbered from D-58/D-59 on `integration/code-review-agent-wave-b`), still open. |
| DR-01–DR-03 | Intended; listed in the PR body. |
