# Fidelity Report — Code Review Agent PRD v1.4: context selection (verifier, Audit Mode)

**Fidelity: Medium** · **Highest drift impact: Major** · 13 drift items (0 Critical, 1 Major, 12 Minor); 2 Unintended (DR-01 Major, DR-02 Minor). All non-blocking.
**Scope:** `docs/requirements/prd-code-review-agent.md` v1.4 (FR-1, FR-5, FR-8, FR-9, FR-18, FR-32–FR-36), decisions D-59–D-64, ADR-010 addendum, spec v1.5. Branch `claude/elegant-ramanujan-zwe4n0`, commits 1127334, 25f2022, 6aa861c, 62f24c0 (range `cfaad49..HEAD`; the local `main` and `origin/main` refs are stale and still lack the merged #473). No GitHub issue; no PR yet.
**Audit status:** complete, not blocked. Every audited FR has codebase, spec and test evidence. One requirement from an earlier version, FR-10 (excluded context), is breached by the new selection path (DR-01).

## Changelog

| Version | Date       | Change                                    | Author   |
| ------- | ---------- | ----------------------------------------- | -------- |
| 1.0     | 2026-11-03 | Initial pre-PR audit of PRD v1.4 delivery. | verifier |

## 1. Human-readable summary

The code reviewer used to look for its background documents (the spec and the verification report) only under fixed file names. In other repositories it often found nothing. This change adds one extra, tightly limited question to the AI before the review: "from this numbered list of documents, which ones describe this change?" The AI can only answer with numbers from a list the agent built itself, so a malicious pull request cannot make it read arbitrary files. If that question fails, the review goes ahead the old way. The review comment now says which documents were picked. Two smaller changes: pull requests that only touch documentation or images are skipped with a short note, and when the review has to leave whole files out, it leaves out documentation first and source code last.

The work matches the request closely, and the specification was updated to match the code. One gap matters. The list of documents the AI chooses from also includes the developer's own task lists, decision logs and research notes. An earlier rule says these must never reach the reviewer, because they push the reviewer toward the author's reasoning. The AI's instructions even invite it to pick a "plan", which is what a task list is. This should be fixed before merge. The other findings are small.

## 2. Per-requirement results

| AC-ID | Description | Codebase evidence | Workstream evidence | Test evidence | Result |
| --- | --- | --- | --- | --- | --- |
| FR-1 | `context_folders` (default `docs,workstream`), `context_selection` (`llm`\|`rules`, default `llm`) | `config.py` PARAMS_SCHEMA; `main.py` `maxLength` + `fullmatch` pattern check; migration `20261103120000_…`; `seed.sql` §4a | spec §5.1, §5.4 | `test_seed_contract.py`, `params_cases.json` (CT-01), panel `code-review-params-parity.test.ts`, `seed-schema.test.ts` | Pass |
| FR-5 | Tiered full-file drops: docs, tests, source; ranking within a tier, else largest first; ±50 diff always kept | `budget.py:301` `each_that_fits`, `:325` `full_file_order`; `context/diff.py` `file_tier` | spec §8.4 g (greedy placement stated) | `test_file_tiers.py` (8 order/drop tests), `test_pipeline_selection.py::test_the_selection_ranking_orders_full_file_drops` | Drift (DR-03, Intended) |
| FR-8 | Selected spec documents added after rule-based specs, deduplicated | `context/spec.py:185` | spec §8.3 step 3 | `test_spec_selected.py` | Pass (see DR-07) |
| FR-9 | Report names: `-issue-<N>[-<slug>]`, `<ID>[-<slug>]` for title story IDs, or selection pick | `context/verifier.py:179` `title_story_ids`, `_suffixed`, `:233`; `conventions.py:167` | spec §8.3 step 4 | `test_verifier_report_names.py`, `test_verifier_candidates.py` (2 tests updated, DR-05), `test_a_suffixed_issue_report_is_found_without_the_model` | Drift (DR-02 Unintended, DR-05 Intended) |
| FR-10 | Never pass `workstream/tasks-*`, `planner-state-*`, `decisions-*`, `research-*` | Not applied on the selection path: `context/selection.py:213-227` `build_candidates` filters on extension only | spec §8.3 step 2a has no FR-10 filter either | None for the selection path | **Fail (DR-01)** |
| FR-18 | Selection call separate, before the review, not counted toward `MAX_CALLS` | `pipeline.py` `_select` uses `deps.bedrock_factory` directly; `_bedrock_client` (counting) unchanged for the review | spec §6.3 | `test_selection_metrics_are_recorded_apart_from_the_review` | Pass |
| FR-32 | One forced-schema Converse call, no tools; candidates ≤400 doc blobs under folders from one tree read; ≤6 picks by index; discard bad index/role/extras; untrusted wrapping | `context/selection.py` (build_candidates, build_request with nonce `2×blocks+1` check, parse_selection); `github_client.py` `git_tree` allowlist + `bind_head_sha` | spec §6.2 (8 templates, verified 8), §6.3, §8.3 2a | `test_selection.py`, `test_selection_hostile.py`, `test_github_client_tree.py`, candidate-cap test | Pass |
| FR-33 | Fail open on error/timeout/invalid output; `min(60 s, 15%)`; no repair; rules mode makes no call | `selection.py:538` `selection_timeout`, `:559` `select_context` (catch-all, `max_attempts=1`) | spec §6.3, §8.9 | `test_an_invalid_selection_falls_back_to_the_rules`, `test_a_throttled_selection_falls_back_to_the_rules`, `test_rules_mode_makes_no_selection_call` | Pass |
| FR-34 | Context line names picks with role, or skip/fail; metrics record selection tokens/cost/duration apart | `render.py` `_selection_clause`; `selection.py` `as_metrics`; `pipeline.py` `_empty_metrics`, `audit_metadata` `selection` block, `_scrub_selection` | spec §5.2, §5.3, §8.8 | `test_render_selection.py`, `test_scrub_selection.py`, `test_the_artifact_records_the_picks` | Pass (cost: DR-06) |
| FR-35 | Docs-only PR: one-line note, no model call, `not_applicable` | `pipeline.py:1056`; `context/diff.py:271` `is_docs_only`; `render.py` `render_docs_only` | spec §8.1, §8.2, §8.8 | `test_a_docs_only_pr_gets_a_note_and_no_model_call`, `test_a_shell_script_among_docs_is_reviewed`, `test_file_tiers.py::test_is_docs_only` | Pass (see DR-08) |
| FR-36 | Folder validation: segments `[A-Za-z0-9._-]`, no empty/`.`/`..`, no leading `/`, ≤10; invalid fails `validateParams`; empty skips | `conventions.py` `CONTEXT_FOLDERS_PATTERN`; `selection.py:170` `parse_context_folders` | spec §5.1 | `test_invalid_context_folders_are_invalid_params`, CT-01 shared cases; probe: `a/./b`, `..`, 11 folders, trailing newline rejected; `.github` accepted | Pass |
| D-63 / ADR-010 addendum | One read-only tree GET, bound to head SHA, allowlisted | `github_client.py` `_fits` refuses `sha` before binding; `bind_head_sha` once, full hex | spec §6.2 | `test_github_client_tree.py` (refused before bind, other SHA refused, no rebind, only `recursive` query) | Pass (see DR-09, DR-10) |

Gates: `make validate` re-run by the verifier: 3,451 passed, 2 skipped, coverage 99.68% (`context/selection.py` 100%), `pip-audit` clean, "validate: all gates passed".

## 3. Drift catalog

Every item below is **non-blocking** to PR readiness and issue completion. Routing: `product-engineer` `activity-drift-reconciliation`.

| ID | Description | Impact | Intent | Evidence | Note |
| --- | --- | --- | --- | --- | --- |
| DR-01 | The selection candidate list includes FR-10 excluded files (`workstream/tasks-*.md`, `planner-state-*`, `decisions-*`, `research-*`) and `*-rollup.md`. A pick reads them into the review prompt as a spec or verifier report. The selection system prompt asks for "a specification, requirement, design or plan", which invites the task list. Verified by probe: `build_candidates` returned all six such paths for `docs,workstream`. The default config makes this reachable. | Major | Unintended | `context/selection.py:213-227` (filter at `:222` is extension-only), `:288-289` (prompt wording); `context/spec.py:185`; `context/verifier.py:233`; spec §8.3 2a omits the filter; PRD FR-10 | Breaches a PRD SHALL NOT. Non-blocking by policy, but it should be fixed before merge. |
| DR-02 | `title_story_ids` accepts any `[A-Z]{1,4}-\d+` in a title, so `UTF-8`, `SHA-256`, `ISO-8601`, `HTTP-2` count as story IDs. They use up the 3-ID cap and cost blind 404 reads. Probe: `"Story S-170: fix UTF-8 and SHA-256 for GC-08"` gives `('S-170','UTF-8','SHA-256')`, so `GC-08` is missed. | Minor | Unintended | `context/conventions.py:167-168`; `context/verifier.py:179` | D-64 wording allows it; the effect (crowding out real IDs) was not intended. |
| DR-03 | Full-file fill is greedy (each file in tier order placed if it fits, else skipped) rather than a strict prefix. The result is a superset of the strict-prefix set. No file is dropped to make room for a later one. A small doc file can be kept while a large source file is dropped, but only when that source file would not fit even with every doc dropped. | Minor | Intended | `budget.py:301`, `:325`; spec §8.4 g; `test_a_smaller_file_after_a_dropped_one_still_gets_its_room` | Consistent with D-61's drop order. Documented in spec v1.5. |
| DR-04 | The new spec step is §8.3 "2a" rather than a renumbering. | Minor | Intended | spec §8.3 | Keeps existing step citations valid. No action. |
| DR-05 | D-64 replaces S-208's "first `Story S-<id>` only" rule (up to 3 IDs). The lowercase `story S-170` is now a match through the bare-ID rule. Two S-208 tests were updated. | Minor | Intended | `test_verifier_candidates.py` (near-miss case removed; `…uses_every_story_id…`, `…reads_a_bare_story_id`) | Authorized by D-64. S-208's story text is now superseded; write back to stories if they are kept current. |
| DR-06 | `selection_cost_usd` is recorded only when `SELECTION_MODEL_ID` equals `MODEL_ID`; otherwise it is `None`, because `PRICE_*` price `MODEL_ID` only. FR-34 says the cost "SHALL" be recorded. | Minor | Intended | `config.py:209` `selection_prices`; spec §5.3 | Avoids wrong prices. Optional `SELECTION_PRICE_*` later, if cost matters. |
| DR-07 | Selected spec documents share the 30% spec cap equally with the rule-resolved spec, so each pick shrinks the authoritative spec's share (for example 1 rule spec + 2 picks gives 10% each). | Minor | Undetermined | `context/spec.py` (share = cap // len(found)); spec §8.3 step 3, §8.4 e | FR-8 says only "added after". `product-engineer` to decide whether rule specs keep priority. |
| DR-08 | Docs-only skip and the doc tier treat every `.txt` as documentation. A PR that changes only `requirements.txt` or `CMakeLists.txt` is skipped unreviewed. `.svg` (can carry script) also qualifies. | Minor | Undetermined | `context/diff.py:123-124`, `:271`; PRD FR-35 lists `.txt` | Spec-level: implementation matches the PRD. Possible spec gap for `product-engineer`. |
| DR-09 | A tree read is made whenever the run reaches context assembly, including `context_selection = rules` and empty `context_folders`. | Minor | Intended | `pipeline.py:1070`; spec §8.3 2a "whatever the mode"; D-64 (suffix lookup uses the listing) | One extra GET per run in rules mode; accepted. |
| DR-10 | `_read_tree` catches `ForbiddenCall` and treats it as "tree unavailable", a narrow exception to "API-failure handlers cannot swallow `ForbiddenCall`". | Minor | Intended | `pipeline.py:1140`; spec §6.2 ("a head that cannot be bound") | Reachable only with a malformed head SHA. No action needed. |
| DR-11 | Roadmap mismatch (advisory). (a) The Wave A row still reads "consolidated PR #440 to `main` awaiting user merge", but #440 merged 2026-10-24. (b) The v1.4 row says "In review (PR to `main` …)" while no PR exists yet, and `Issues/PRs` lists only 1127334 and 25f2022 (6aa861c and 62f24c0 are missing, and so is the PR number). | Minor | Unintended | `docs/roadmap.md:9`, `:10`; `gh pr view 440` (MERGED) | Roadmap-mismatch triggers 4 and 1. Correct when the PR is opened. |
| DR-12 | Runbook coverage (advisory). Delivery requires ordered operational steps (redeploy runtime, apply `20261103120000_…` with confirmation, optionally set `SELECTION_MODEL_ID`, re-trigger), with no runbook added. | Minor | Intended | `docs/roadmap.md:10`; spec §5.4; ADR-010 assigns the code-review runbook to Wave B (S-214) | Owner: `infra-engineer`. Fold these steps into the S-214 runbook. |
| DR-13 | A selection-picked report can be a `*-rollup.md`. The rule-only "rollups are never requested" no longer holds overall. | Minor | Undetermined | `context/selection.py:213`; `context/verifier.py:233` | Fixed together with DR-01 if rollups are added to the exclusion. |

## 4. Spec v1.5 against the code (spot check)

- §5.1 schema and pattern: byte-equal to `config.py`, seed and migration (seed-contract and parity tests pass).
- §5.2 `selection` block and §5.3 `selection_*` keys: match `audit_metadata` and `_empty_metrics`/`as_metrics`.
- §6.2 eight templates: `ALLOWLIST` has 8 entries; tree read bound to head SHA.
- §6.3 selection call: `maxTokens 2000`, forced `select_context`, no reasoning field, nonce integrity check, `max_attempts=1`, `t = min(60, 15%)`, skip under 5 s: matches.
- §8.1/§8.2 docs-only before size check, not on truncated listing: matches `pipeline.py:1056`.
- §8.3 2a, 3, 4; §8.4 g; §8.8 selection clause last and docs-only note; §8.9; §9 `SELECTION_MODEL_ID`; §18 D-59–D-64: match.
- Gap: §8.3 2a does not state the FR-10 exclusion (DR-01). Spec and code agree, but both diverge from PRD FR-10.

## 5. Edge-case, randomized, and gate outcomes

- No Design Mode test plan exists for v1.4. Hostile-input coverage is in `test_selection_hostile.py` (index-only answers, nonce collisions, bool/float/string indexes, unknown roles, >6 entries) and `test_properties_params.py`.
- Verifier probes: FR-36 rejects `a/./b`, `..`, 11 folders and a trailing newline, and accepts `.github` and `docs, workstream`. DR-01 and DR-02 were reproduced deterministically (no seed needed).
- **Documentation structure:** not run. `core/checks/` does not exist in this repository (`tsx core/checks/run.ts` gives ERR_MODULE_NOT_FOUND). No findings reported.
- **Vocabulary conformance:** not run for the same reason (`checkExportedIdentifiers` unavailable). Advisory only.

## 6. Recommendations

| Item | Next step |
| --- | --- |
| DR-01 | `developer`: in `build_candidates`, exclude any path where `context.diff.path_reason(path) == "excluded"` (reuses `EXCLUDED_WORKSTREAM`), and `*-rollup.md` (DR-13). Reword the selection system prompt to drop "plan". Add a test that excluded files are never candidates. `product-engineer`: add the FR-10 exclusion to spec §8.3 2a. |
| DR-02 | `developer`: drop bare IDs that do not look like story IDs (for example require a word boundary not followed by `.`, or exclude a small deny-list such as `UTF`, `SHA`, `ISO`, `HTTP`, `TLS`, `RFC`), or prefer IDs whose report name the tree lists before blind reads. |
| DR-07, DR-08, DR-13 | `product-engineer`: decide (spec clarification). |
| DR-11 | `product-engineer`/`planner`: set Wave A to `Done` (#440 merged), and fill the v1.4 row's PR number and commits when the PR opens. |
| DR-12 | `infra-engineer`: include the v1.4 rollout order in the S-214 runbook. |
| DR-03, DR-04, DR-05, DR-06, DR-09, DR-10 | No action needed (DR-05: optional story write-back). |

## Remediation (developer, 2026-11-03, before PR ready)

| Item  | Action |
| ----- | ------ |
| DR-01 | Fixed. `build_candidates` drops any path with `path_reason == "excluded"` (PRD FR-10) and any `*-rollup.md`; the selection prompt no longer asks for "plan" documents. Tests: `test_excluded_and_rollup_files_are_never_candidates`, `test_the_selection_prompt_does_not_ask_for_plans`. Spec §8.3 step 2a updated. |
| DR-02 | Fixed. With the tree read, a bare `[A-Z]{1,4}-\d+` title ID counts only when the listing holds its exact or suffixed report; `Story S-<id>` IDs always count; without a listing every ID is read blind. Tests in `test_verifier_report_names.py`. Spec §8.3 step 4 updated. |
| DR-13 | Fixed with DR-01 (rollups are never candidates). |
| DR-11 | Wave A row set to Done (PR #440 merged 2026-10-24); the v1.4 row gets its PR number when the PR opens. |
| DR-07, DR-08, DR-12 | Left for `product-engineer` / the Wave B runbook, as recommended; listed in the PR body. |
