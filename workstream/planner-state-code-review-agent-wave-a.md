# Planner State: code-review-agent-wave-a

## Run Info

- Task source: `workstream/tasks-prd-code-review-agent-plan.md` (Wave A, tasks 1.0–10.0)
- Integration branch: `integration/code-review-agent` (from `main` @ dc89014)
- Repository: llipe/dev-tasks-agent-fleet
- Started: 2026-10-22
- Last updated: 2026-10-23 (S-213 merged; Wave A stories complete)

## Story Status

| Sequence | Story ID | Issue # | Status    | PR   | Branch                            |
| -------- | -------- | ------- | --------- | ---- | --------------------------------- |
| 1        | S-204    | #406    | ✅ Merged | #425 | `story/S-204-agent-scaffold`      |
| 2        | S-205    | #407    | ✅ Merged | #426 | `story/S-205-github-client`       |
| 3        | S-206    | #408    | ✅ Merged | #429 | `story/S-206-expanded-diff`       |
| 4        | S-207    | #409    | ✅ Merged | #430 | `story/S-207-issues-spec`         |
| 5        | S-208    | #410    | ✅ Merged | #431 | `story/S-208-verifier-candidates` |
| 6        | S-209    | #411    | ✅ Merged | #432 | `story/S-209-budget-prompt`       |
| 7        | S-210    | #412    | ✅ Merged | #435 | `story/S-210-bedrock-adapter`     |
| 8        | S-211    | #413    | ✅ Merged | #436 | `story/S-211-findings-validation` |
| 9        | S-212    | #414    | ✅ Merged | #437 | `story/S-212-comment-render`      |
| 10       | S-213    | #415    | ✅ Merged | #438 | `story/S-213-run-pipeline`        |

## Current Position

- Next story: none. All Wave A stories are merged; next is Phase 5 (wrap-up and the consolidated PR)
- Last merged PR: #438 (merge commit af35dca)
- Integration branch HEAD: af35dca + checkpoint commit (package `validate` green post-merge)

## Decisions Log

- 2026-10-22: User approved the Wave A plan (S-204 → S-213, sequential) and pushing `integration/code-review-agent` and `story/S-2xx-*` branches.
- 2026-10-22: Wave B (S-214, S-215) deferred to its own run: no AWS CLI or credentials in this runtime; `infra-engineer` approvals required.
- 2026-10-22: `gh` has no valid token and the `developer` subagent has no GitHub tools. Developer pushes the story branch; planner opens, reviews and merges story PRs through the GitHub MCP tools.
- 2026-10-22: memo-cli binary absent while `memo.config.json` exists → `memo_run_outcome: skipped(memo-unavailable)`; per-story memo fields expected `skipped(memo-unavailable)`.
- 2026-10-22: CI runs only on PRs to `main` (precedent: webhook runs). Story merge gate uses local `make validate` evidence.
- 2026-10-22: Issue task checklists are synced into each issue body when its story starts, so later stories reflect any plan changes.
- 2026-10-22: S-204 migration applied locally only; prod apply is in S-214 with explicit user confirmation.
- 2026-10-22: S-204 merge gates: developer gates PASS; technical-writer drift-fixed (a7de081); qa-engineer coverage_gate PASS 98.42% (f3e7abe, +7 security-negative tests); verifier High / Minor, 8 drift items (e8696c6, `workstream/fidelity-report-S-204.md`); planner re-ran package validate. Root `make validate` fails on the pre-existing security-analyst opentelemetry-api CVE-2026-114603 (same on base). memo_intent/memo_outcome: skipped(memo-unavailable). Migration not applied (no Supabase CLI/Docker); prod apply in S-214.
- 2026-10-22: Open product questions from the S-204 audit: D3 (`pr_number: 7.0` rejected by the agent, accepted by the schema) and D4 (seed row enabled with a placeholder runtime ARN; consider seeding disabled until S-214).
- 2026-10-22: Carry to S-205: `credentials.py` lets a GitHub 401/403 escape as `requests.HTTPError` instead of `CredentialError` (qa-engineer finding).
- 2026-10-22: S-205 merge gates: developer gates PASS; qa-engineer coverage_gate PASS 99.23% (7c6c0e3, +~50 guard-bypass tests) found a trailing-newline anchoring defect, fixed in 7aa8340 (`fullmatch`, `trust_env=False`); verifier High / Minor, 7 drift items (d509dc6, `workstream/fidelity-report-S-205.md`); planner re-ran package validate. memo fields skipped(memo-unavailable).
- 2026-10-22: User decisions: D-39 seed the row disabled until S-214 (follow-up PR before S-206); D-40 keep rejecting `pr_number: 7.0` (documented difference); no issue for the opentelemetry-api CVE — root `make validate` stays red on the pre-existing security-analyst audit and is reported as such in the consolidated PR.
- 2026-10-22: Carry forward: S-206 treats `ForbiddenCall` on a backslash filename as content unavailable; S-207/S-208/S-213 map `GitHubNotFound` to not_applicable or skip, never a run error_code; S-213 decides whether a rate-limited 403 on the comment POST suppresses the failure comment (verifier recommends keying on exception type); S-214 enables the row (D-39).
- 2026-10-22: S-204 follow-up #428 (D-39) merged: row seeded `is_enabled = false`. Gates: package validate PASS; panel `make validate-js` PASS on Node 26 (planner installed it via nvm); qa-engineer PASS and fixed an E2E fleet-toggle leak that re-enabled every agent (ccedef4); verifier High / Minor (6375069). Verifier F1 written back: spec v1.2 §5.1/§15, stories v1.3 S-204/S-214, issue #416. F2 (stale E2E comment) left as optional.
- 2026-10-22: S-206 merge gates: developer gates PASS; qa-engineer coverage_gate PASS (46cbc2d, +61 probe tests) found an FR-10 leak on rename-away and C1/U+2028 header forging, fixed in 1ed702f and 0b4e129; verifier High / Minor, 9 drift items (5730124). Planner decisions: D-42 (classify both names, base withheld); D6 keep GitHub counts for the size check; D7 (`binary` label on empty or mode-only files) deferred to S-212.
- 2026-10-22: Spec write-back backlog for one batched update before the consolidated PR: S-206 D1 (binary rule), D2 (truncated listing → OverBudget), D3 (EC-07 deletion anchor), D4 (D-42), D5 (per-thread client_factory, §11), D8 (hardening), D9 (D-26 wording); S-205 D2 (GitHubNotFound), D3 (extra retries), D5 (TC-205-07 wording).
- 2026-10-22: Carry forward to S-212: render_budget says "at least" when `OverBudget.truncated`; context line names `base_withheld` files; fix the `binary` label for empty added files. To S-213: pass `client_factory`; map `GitHubNotFound`; DF-16 lockfile-only PR.
- 2026-10-22: S-207 merge gates: developer gates PASS; qa-engineer coverage_gate PASS (21ae48d, hostile-input suite) found a CR-only FR-10 checklist leak, quadratic spec-heading (~24 s) and issue-link (~3.4 s) regexes, and Unicode-digit links; all fixed in 9ee1b47 with D-43 and a 200-citation cap; verifier High / Minor, 10 drift items (07d46b2). D-43 logged.
- 2026-10-22: Spec write-back backlog adds S-207 DR-1 (DF-18), DR-2 (DF-20), DR-3 (PRD §15 spec name), DR-4 (skip taxonomy, §13), DR-5 (tokens.py), DR-6 (D-43), DR-7 (hardening), DR-8 (context/ naming); undetermined DR-9 (setext spec headings in trimming) and DR-10 (story IDs from titles only) go to the user with the batch.
- 2026-10-22: Carry forward to S-209/S-213: import `estimate`/`truncate` from `context/tokens.py`; read `SpecContext.specs`; pass a `warn` callback; render "issues unavailable (permission)".
- 2026-10-22: S-208 merge gates. Developer gates PASS. D-44 (numbered drift headings) taken by the planner: the spec regex rejected every report for this PRD. qa-engineer `coverage_gate` PASS (2c942d6) found D1 (quadratic ADR Status scan), D2 (`\v`/`\f` heading never ends its section), D3 (BOM ADR title), D4 (backtick line taken as a fence, losing a Critical+Unintended row); all fixed, plus a 64 KiB per-ADR cap. Verifier verdict High, highest drift Minor, 12 items (a1cc47d). DR-10 (S-207 `spec.py` fence) fixed in the same PR through the shared `context/markdown.py`. D-44 and D-45 logged.
- 2026-10-22: Spec write-back backlog adds S-208 DR-1 (D-44 regex, §8.3 step 4), DR-2 (test-plan TC-208-05, EC-16, DF-05, matrix rows), DR-3 (§13 403 extension), DR-4 (row_index), DR-5..DR-8 (D-45 details, QA contract details), DR-12 (1,000-entry `docs/adr` listing limit in §8.3 step 5). For the user: DR-9 (PRD FR-9 asks for the report verdict line, which the spec does not pass; add it in S-209 or amend FR-9). Accepted residual: DR-11 (BOM on line 1 of a report).
- 2026-10-22: Carry forward. S-209: only `Candidate.label()` goes outside nonce markers, `Candidate.text` goes in a `verifier-candidate V<k>` block and `VerifierReport.section` in a `verifier` block; the §8.4 d 10%-of-R cap still applies; candidate text may end in `[truncated]`. S-212: render per-report states, `unavailable` (a 403 shows as `none` plus `unavailable`), and `other_drift` counts; the candidate count is uncapped, so the size stages matter. S-213: wire `verifier_candidates(client, issues, head_sha, warn=)` and `repo_conventions(client, head_sha, max_context_tokens=, warn=)`.
- 2026-10-23: S-209 merge gates. Developer gates PASS. qa-engineer `coverage_gate` PASS (88e648e): the budget invariant and nonce integrity held. Two Low defects were fixed: the name-only cut is now named, and dropped files on the retry path are listed smallest first. Residuals fixed: deduped notes, an empty-spec note, and the NonceError attempt count. Verifier verdict High, highest drift Minor, 12 items (38aac6b). DR-10 was fixed as D-46. Merged #432 at 697e4b1.
- 2026-10-23: Spec write-back backlog adds S-209 DR-1 to DR-8 (pinned budget and prompt contract; test plan and matrix still number AC1–AC6; TC-209-13 kind list). For the user: DR-9 (FR-9 verdict line), DR-11 (CJK and emoji token under-count versus D-27 and R4), DR-12 (output tokens and the repair payload sit outside `max_context_tokens`; this blocks S-210 AC4–AC6).
- 2026-10-23: Carry forward. S-210: send `Prompt.system_blocks()` and `fallback_system_blocks()` exactly; the R4 retry is `build_prompt(include_full_files=False)` and passes its ContextData downstream; never retry the INTERNAL_ERROR types; log the second context-length rejection distinctly. S-211: a dropped candidate always blocks; ignore checks for IDs outside `shown_candidates`; normalize `file` with `escape_path`. S-212: token-path OverBudget wording; notes include the `empty` and `name-only` cases; rubric_version in the footer; neutralize paths. S-213: two OverBudget paths; inject the sink; log per-block token counts.
- 2026-10-23: User decisions: D-47 (DR-12, B caps every call; the repair call is rebuilt without full files and the echoed output is cut to fit; B + 16k must fit the model window, checked in S-215), D-48 (DR-11, accept and record; S-210 logs the second context-length rejection distinctly), D-49 (DR-9, amend PRD FR-9 to drift section only). All three go into the batched spec and PRD write-back.
- 2026-10-23: S-210 merge gates. Developer gates PASS. qa-engineer `coverage_gate` PASS (287d585) found 6 defects, all fixed. High: a call could outlast the deadline; each call now gets a fresh client sized per call, with a 13 s backoff reserve. Medium: 4 HTTP attempts became `total_max_attempts` 3. Low: retry classification (reasoning first), unbounded cost math, RecursionError, RUN_TIMEOUT past the deadline. Verifier High, highest drift Minor, 13 items (7ae5149). Merged #435 at 72f04be.
- 2026-10-23: Spec write-back backlog adds S-210 DR-1 to DR-10: retry rules, the D-47 per-call check, repair shape and the `model-output` kind, repair room at small B, the stricter per-call deadline, the error-mapping additions, strict JSON, OpenAI ID detection, metrics, and test-plan/matrix lag. Undetermined: DR-11 goes to S-213, DR-12 to S-212, DR-13 to S-215.
- 2026-10-23: Carry forward. S-211: reviewed files come from `result.context`, never from `full_files_included`; expect duplicate candidate IDs and duplicate or huge ranks; normalize `file` with `escape_path`; a dropped candidate always blocks. S-212: fixed failure text per error code; the context line says why full files were left out (DR-12). S-213: `review(client_factory=make_client, deadline=, clock=)`; map errors on `.code`; up to 3 sink prompts; define `estimated_input_tokens` for multi-call runs (DR-11); reuse the Stubber pattern. S-214: `MODEL_ID` must be a system-defined profile ID (DR-8). S-215: capture real refusal messages, check repair at small B, measure p95 latency.
- 2026-10-23: S-211 merge gates: developer PASS; planner overrode the removed-file rule (D-52, TC-211-05); qa-engineer coverage_gate PASS (38616dc) found QA-211-D1, a location bypass through a huge span, fixed as D-50; QA-211-Q1 blank placeholders became D-51; `escape_path` made injective; verifier High / Minor with 9 items (63a8818), and DR-2, a false downgrade of a fully changed long span, closed by an exemption, a prompt sentence and the `downgraded_span` counter. Merged #436 at 089ca51. D-50..D-52 logged.
- 2026-10-23: Spec write-back backlog adds S-211 DR-1 and DR-3 to DR-9: D-50, D-51, removed files, path matching, rule details, the four candidate statuses, the metrics shape, and the test-plan/matrix lag.
- 2026-10-23: Carry forward to S-212: neutralize raw model text and paths; render huge line numbers compactly; show the model reason only when `reason_from_model`; word `outside_diff` as not located in the diff; render a `dropped_for_budget` or `not_checked` candidate as not checked by the model. Carry forward to S-213: call `validate_result` with the same DiffContext; map SchemaViolation and ValueError to INTERNAL_ERROR; build `verifier[]` from `v.candidates`; merge `v.metrics()`.
- 2026-10-23: S-212 merge gates: developer PASS; manual 9.6 GitHub preview PASS (comment 6369319634); qa-engineer coverage_gate PASS (250fa53): D1 GH-<n> references, D2 stage-5 count, D3 canonical code, plus field caps, invisible-character strip and lowercase marker run_id; verifier High / Minor, 10 items (ba3ff5d); DR-4 (verifier candidates rendered or counted) and DR-9 (size measured as max of code points and UTF-16 units) fixed in fc12bb7. Merged #437 at f1c2990.
- 2026-10-23: Spec write-back backlog adds S-212 DR-1..3, DR-5..7 and DR-10. For the user: DR-8 (amend FR-20 to "every review comment") and DF-01 (amend FR-24 so Verifier comes before Suggestions).
- 2026-10-23: Carry forward to S-213:
  - Pass the accepted call's ReviewResult.context to render_review.
  - Find the marker anchored at the start of the body, filter by the bot author, and compare the run_id lowercased.
  - Map GITHUB_NOT_FOUND on load_pr to not_applicable.
  - Record canonical_code(code).
  - Set comment_chars and comment_truncated from Rendered, and warn on truncation.
  - Scrub before posting.
- 2026-10-23: S-213 merge gates. Developer PASS. qa-engineer coverage_gate PASS (532d328) found 7 defects, all fixed:
  - BaseException left the run silent;
  - a second comment after a posted review;
  - unscrubbed BaseException paths;
  - the failure path was not hardened;
  - a 2xx with an unreadable body;
  - path cuts split secrets;
  - INVALID_PARAMS raised from inside the pipeline.
    The post-phase timeout split was added on top. Verifier High / Minor, 12 items (282b818); no functional Wave A gap. Manual 10.7 NOT RUN (no token). Merged #438 at af35dca.
- 2026-10-23: For the user in the Phase 5 batch:
  - DR-5: a lost POST response gives a review plus a failure note;
  - FR-20: rubric version on notes and on budget/failure comments (S-212 DR-8, S-213 DR-9);
  - FR-24: section order (DF-01);
  - FR-9: amendment (D-49).
    Spec write-back adds S-213 DR-1..4, DR-6..8 and DR-10; docs: DR-11; roadmap: DR-12.
- 2026-10-23: User decisions D-53 (amend FR-20), D-54 (amend FR-24), D-55 (accept DR-5 for base) and approval to apply the batched spec/PRD/test-plan write-back in the consolidated PR. Phase 5 started.
