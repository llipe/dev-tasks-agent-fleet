# Implementation Plan - Code Review Agent (Wave A)

> Execution plan for [`prd-code-review-agent`](../docs/requirements/prd-code-review-agent.md) (v1.1) /
> [`specification-prd-code-review-agent`](specification-prd-code-review-agent.md) (v1.1) /
> [`user-stories-prd-code-review-agent`](user-stories-prd-code-review-agent.md) (v1.2) /
> [`decisions-code-review-agent`](decisions-code-review-agent.md) (D-01…D-38) /
> [`test-plan-prd-code-review-agent`](test-plan-prd-code-review-agent.md) (v1.1).
> GitHub issues **#406–#415** (S-204…S-213). Wave B (S-214 #416, S-215 #417) is a separate run: it needs AWS access and `infra-engineer` approvals.
>
> **Ordering is dependency-correct.** Each story is a branch → reviewed PR into `integration/code-review-agent`; the integration branch goes to `main` via one reviewed PR at the end (the user merges). **Test-first:** `[T]` tasks precede their `[I]` tasks; each `[T]` names its test-plan case IDs. A story is ready when `make -C agents/code-review/app/codeReview validate` and the root `make validate` pass; `qa-engineer` and the `verifier` audit run at the merge gate.
>
> **Packages:** `[code-review]` = `agents/code-review/app/codeReview/` (abbreviated `pkg/`); `[supabase]` = `supabase/`; `[repo root]` = root `Makefile`, `.github/workflows/`, docs.

## Relevant Files

- `agents/code-review/app/codeReview/{main,config}.py` - entrypoint, payload validation, defaults, clock invariant (S-204, S-213)
- `agents/code-review/app/codeReview/{agent_reporter,credentials,heartbeat,signal_backstop,scrubber}.py` - copies of the sibling modules (S-204)
- `agents/code-review/app/codeReview/{pyproject.toml,Makefile,Dockerfile,.dockerignore}` - package, gates, image (S-204)
- `agents/code-review/app/codeReview/github_client.py` - allowlisted GitHub REST client (S-205); `get_content_bytes` for the byte-exact NUL check (S-206)
- `agents/code-review/app/codeReview/context/diff.py` - classification, size check, expanded diff, changed ranges (S-206)
- `agents/code-review/app/codeReview/context/{issues,spec,conventions}.py` - linked issues, checklist strip, spec resolution and trimming (S-207)
- `agents/code-review/app/codeReview/context/tokens.py` - `estimate()` (D-27) and line-boundary `truncate()`, the one token estimator; S-209's budget fit reuses it (S-207)
- `agents/code-review/app/codeReview/context/{verifier,repo_conventions}.py` - drift candidates, repo conventions (S-208)
- `agents/code-review/app/codeReview/{budget,prompt}.py`, `rubric.md` - priority fill, prompt with nonce blocks, rubric v1 (S-209)
- `agents/code-review/app/codeReview/{bedrock_adapter,findings_schema}.py` - Converse adapter and output schema (S-210)
- `agents/code-review/app/codeReview/validate.py` - findings validation and verdict (S-211)
- `agents/code-review/app/codeReview/render.py` - review, budget and failure comments (S-212)
- `agents/code-review/app/codeReview/pipeline.py` - pipeline wiring, outcomes, artifact, failure path (S-213)
- `agents/code-review/app/codeReview/tests/{unit,integration,fixtures,helpers}/**` - tests, recorded GitHub fixtures, fake Bedrock, seeded PRNG helper
- `agents/code-review/app/codeReview/tests/unit/{test_payload,test_config,test_layout,test_seed_contract,test_properties_params}.py` - S-204 tests (TC-204-*, CT-01 Python side, CT-02, RT-01)
- `agents/code-review/app/codeReview/tests/unit/{test_credentials,test_credentials_real_jwt,test_heartbeat,test_scrubber,test_signal_backstop}.py` - sibling tests for the copied modules (S-204)
- `agents/code-review/app/codeReview/tests/integration/test_invoke_skeleton.py` - skeleton invoke against a reporter sink (S-204)
- `agents/code-review/app/codeReview/tests/fixtures/params_cases.json` - CT-01 shared params cases (S-204)
- `agents/code-review/app/codeReview/tests/unit/{test_github_client,test_contracts,test_properties_github_client,test_prng}.py` - S-205 tests (TC-205-\*, CT-04, CT-05 GitHub half, seeded allowlist property, PRNG helper)
- `agents/code-review/app/codeReview/tests/helpers/{prng,github_stub}.py` - seeded PRNG helper (G-6) and `StubTransport` with the recorded-fixture loader (S-205)
- `agents/code-review/app/codeReview/tests/fixtures/github/sample-pr/` - recorded GitHub responses for a sample PR, reused by S-206–S-213 (S-205)
- `agents/code-review/app/codeReview/tests/unit/{test_classify,test_diff,test_changed_ranges,test_properties_classify,test_properties_diff}.py`, `tests/integration/test_context_diff.py` - S-206 tests (TC-206-\*, RT-02, RT-09)
- `agents/code-review/app/codeReview/tests/fixtures/github/sample-pr/expanded_diff.golden` - hand-written golden expanded diff for the sample PR (S-206)
- `agents/code-review/app/codeReview/tests/unit/{test_issue_links,test_checklist_strip,test_spec_resolve,test_spec_trim,test_tokens,test_properties_issue_links,test_properties_spec,test_properties_checklist}.py`, `tests/integration/test_context_issues_spec.py` - S-207 tests (TC-207-\*, CT-12, RT-03, RT-10, RT-12)
- `agents/code-review/app/codeReview/tests/fixtures/github/issue-315/` - issue #315 shape, PR #330 linking it, and the webhook-triggers spec served at head (S-207)
- `agents/code-review/app/codeReview/context/conventions.py` - S-208 adds the report-name mappings, drift heading and candidate-word regexes, token caps, conventions sources, and ADR name/Status regexes
- `agents/code-review/app/codeReview/tests/unit/{test_verifier_candidates,test_conventions,test_properties_verifier}.py` - S-208 tests (TC-208-\*, CT-11, RT-05)
- `agents/code-review/app/codeReview/tests/fixtures/reports/`, `tests/helpers/reports.py` - fidelity-report fixtures (byte copy of `fidelity-report-S-170.md`, synthetic AC-7, no-heading, numbered, empty, bullet-list) and their loader (S-208)
- `agents/code-review/app/codeReview/tests/fixtures/github/sample-pr/{routes.json,adr_002_head.md,README.md}` - ADR-002 route with a `## Status` heading (S-208)
- `supabase/seed.sql`, `supabase/migrations/20261022120000_seed_code_review_agent.sql` - `agents` row (S-204)
- `.github/workflows/ci.yml`, `Makefile`, `TESTING.md` - CI matrix, root aggregate, testing contract (S-204)
- `panel/tests/unit/code-review-params-parity.test.ts` - CT-01 params parity cases on the panel side (S-204)
- `panel/tests/integration/seed-schema.test.ts` - TC-204-15 Layer 2.5 seed row check (S-204)
- `panel/tests/e2e/schedule-dialog.spec.ts` - selects the agent explicitly now that "Code Review" sorts first (S-204)

## Tasks

- [ ] 1.0 Implement Story S-204 (#406): Agent scaffold, params, and agents seed · branch `story/S-204-agent-scaffold`
  - [x] 1.1 `[T]` [code-review] L1 `test_payload.py`: unwrap single and double `prompt` wrapper; every invalid param (`pr_number` 0/negative/string, limits out of range, unknown `reasoning_effort`, extra key, `params` absent); defaults (TC-204-\*)
  - [x] 1.2 `[T]` [code-review] L1 `test_config.py`: clock invariant pass and fail (`run_timeout_seconds` ≤ 900 ≤ 1800) (D-32)
  - [x] 1.3 `[T]` [code-review] `tests/integration/test_invoke_skeleton.py` with a reporter sink: invalid params → `INVALID_PARAMS`, no GitHub call
  - [x] 1.4 `[T]` [code-review, panel] CT-01 shared params case file run by the Python validator and the panel's Ajv `validateParams`
  - [x] 1.5 `[I]` [code-review] Copy `agent_reporter`, `credentials`, `heartbeat`, `signal_backstop`, `scrubber`, `config` from `security-analyst`; `pyproject.toml` pins `bedrock-agentcore`, `boto3`, `requests`, `PyJWT`, `cryptography` at sibling versions, no `strands-agents` (D-20, D-07)
  - [x] 1.6 `[I]` [code-review] `config.py` env vars (`SUPABASE_URL`, `SUPABASE_KEY_SECRET_ID`, `MODEL_ID`, `PANEL_BASE_URL`, `PRICE_INPUT_PER_MTOK`, `PRICE_OUTPUT_PER_MTOK`) and `assert_clock_invariant()` (D-29, D-32)
  - [x] 1.7 `[I]` [code-review] `main.py`: `unwrap_payload`, `validate_payload`, `apply_defaults`, skeleton `invoke` (opens `load_pr`, ends `failed`/`INTERNAL_ERROR` "not implemented") (D-21)
  - [x] 1.8 `[I]` [code-review] `Makefile` (sibling targets incl. `validate`), `Dockerfile` (no scanner toolchains), `.dockerignore`
  - [x] 1.9 `[I]` [supabase] Seed row in `supabase/seed.sql` and data migration `<ts>_seed_code_review_agent.sql` with the spec §5.1 `params_schema`/`default_params`, `on conflict (slug) do update`; set the operational columns to match the siblings (`max_runtime_seconds` = `maxLifetime` 1800, grace and start timeouts, `requires_repository`, name, version — test plan DF-09)
  - [ ] 1.10 Migration lifecycle: rollback note in the PR (`delete … where slug = 'code-review'` or disable); apply **locally only** with `supabase db reset`; verify `select slug, params_schema from agents where slug = 'code-review'`; prod apply waits for S-214 with explicit user confirmation — rollback note written (migration header + PR body); local apply NOT RUN in the S-204 runtime (no Supabase CLI/Docker), static contract pinned by `test_seed_contract.py`
  - [x] 1.11 `[I]` [repo root] Add the package to the `.github/workflows/ci.yml` matrix and the root `Makefile` (record in the PR body: matrix line only; FR-49a runbook ships with S-214)
  - [x] 1.12 Verify Acceptance Criteria: AC1 package copies; AC2 pinned deps; AC3 params validation; AC4 clock invariant; AC5 seed row; AC6 CI + root `Makefile`; AC7 skeleton invoke
  - [ ] 1.13 Manual: `supabase db reset`; panel invoke form for `code-review` renders six params with defaults — NOT RUN in the S-204 runtime (no Supabase CLI/Docker); open for the reviewer
  - [x] 1.14 Map each AC to test evidence in the PR body
  - [x] 1.15 Run Tests: `make -C agents/code-review/app/codeReview validate`; `make validate`

- [ ] 2.0 Implement Story S-205 (#407): GitHub client with a write allowlist · branch `story/S-205-github-client`
  - [x] 2.1 `[T]` [code-review] L1 `test_github_client.py`: each allowed call; every disallowed verb/path (`PUT`, `PATCH`, `DELETE`, `POST` to reviews, merge, labels, another issue's comments) raises `ForbiddenCall` before transport; CT-04 allowlist snapshot
  - [x] 2.2 `[T]` [code-review] L1 retries (2 on 5xx/connection/secondary rate limit, `retry-after` honored, max 30 s), POST never retried; 404 contents → `None`; error mapping; token absent from exception text
  - [x] 2.3 `[T]` [code-review] Edge: paging stops at 30 pages; paths with spaces, `#`, `..` URL-encoded; secondary-rate-limit 403 vs. permission 403
  - [x] 2.4 `[I]` [code-review] `tests/helpers/prng.py` seeded `random.Random` helper (test plan G-6)
  - [x] 2.5 `[I]` [code-review] `github_client.py`: `GitHubClient(token, org, repo, pr_number)` with `get_pull`, `list_pull_files`, `compare`, `get_content_raw`, `list_dir`, `get_issue`, `post_pr_comment`; allowlist; errors `GitHubPermissionDenied`, `GitHubApiError`; request timeout (test plan DF-14)
  - [x] 2.6 `[I]` [code-review] Recorded fixtures under `tests/fixtures/github/` for a sample PR
  - [x] 2.7 Verify Acceptance Criteria: AC1 methods; AC2 allowlist and single write; AC3 retries; AC4 errors without token; AC5 URL-encoding
  - [x] 2.8 Map each AC to test evidence in the PR body
  - [x] 2.9 Run Tests: `make -C agents/code-review/app/codeReview validate`; `make validate`

- [ ] 3.0 Implement Story S-206 (#408): Expanded diff and size check · branch `story/S-206-expanded-diff`
  - [x] 3.1 `[T]` [code-review] L1 `test_classify.py`: lockfiles, generated paths, binaries, excluded workstream paths; near-misses (e.g. `lockfile.md`); property tactic over random paths (fixed seed)
  - [x] 3.2 `[T]` [code-review] L1 `test_diff.py`: added, removed, renamed, modified; ±50 context; empty file; no trailing newline; CRLF; invalid UTF-8; diff round-trip property
  - [x] 3.3 `[T]` [code-review] L1 budget: exactly `max_diff_lines` vs +1; lockfile-only PR; 300+ files; `test_changed_ranges.py`
  - [x] 3.4 `[T]` [code-review] `tests/integration/test_context_diff.py` on recorded fixtures for a 3-file PR
  - [x] 3.5 `[I]` [code-review] `context/diff.py`: `classify`, `OverBudget` without fetching content, merge-base via `compare`, blob fetch (thread pool 8), `difflib.unified_diff(n=50)`, head contents, changed head ranges (D-26, D-11)
  - [x] 3.6 Verify Acceptance Criteria: AC1 classification; AC2 size check; AC3 expanded diff; AC4 head contents; AC5 changed ranges
  - [x] 3.7 Map each AC to test evidence in the PR body
  - [x] 3.8 Run Tests: `make -C agents/code-review/app/codeReview validate`; `make validate` — package `validate` green; root `make validate` stops in `dependency-update` (`/usr/bin/python: No module named pytest`, no sibling venv in this runtime) before reaching `code-review`; the known `security-analyst` audit CVE is not tracked here

- [ ] 4.0 Implement Story S-207 (#409): Linked issues and spec resolution · branch `story/S-207-issues-spec`
  - [x] 4.1 `[T]` [code-review] L1 `test_issue_links.py`: `closes #1`, `Fixes: #2`, `resolved #3`, `owner/repo#4` ignored, branch `issue/5-x`, dedupe, cap 5, linked PR skipped; regex property tactic
  - [x] 4.2 `[T]` [code-review] L1 `test_checklist_strip.py` (heading levels 1–6, case-sensitive) and 8,000-token cap
  - [x] 4.3 `[T]` [code-review] L1 `test_spec_resolve.py` (path → title → label, 404 fall-through, none) and `test_spec_trim.py` (outline, `Spec §8` vs `§8.1`, story IDs, reviewed paths)
  - [x] 4.4 `[T]` [code-review] Issue 403 → skipped, `issues_unavailable=True`
  - [x] 4.5 `[T]` [code-review] `tests/integration/test_context_issues_spec.py` on #315 and `specification-prd-webhook-triggers.md` fixtures
  - [x] 4.6 `[I]` [code-review] `context/conventions.py` regex and mapping constants; `context/issues.py`; `context/spec.py` (D-22, D-23, D-24)
  - [x] 4.7 Verify Acceptance Criteria: AC1 links; AC2 checklist strip; AC3 cap; AC4 spec resolution; AC5 spec trim; AC6 403
  - [x] 4.8 Map each AC to test evidence in the PR body
  - [ ] 4.9 Run Tests: `make -C agents/code-review/app/codeReview validate`; `make validate`

- [ ] 5.0 Implement Story S-208 (#410): Verifier drift candidates and conventions · branch `story/S-208-verifier-candidates`
  - [x] 5.1 `[T]` [code-review] L1 `test_verifier_candidates.py`: real `fidelity-report-S-170.md` (no candidates), synthetic Critical+Unintended and Major+Unintended rows, no drift heading, split cells, `Non-critical`, multiple reports, global numbering; candidate shape (path, row index, text ≤ 300 tokens); drift-row parsing property tactic
  - [x] 5.2 `[T]` [code-review] L1 report lookup (`S-<id>`, `issue-<N>`, rollup ignored) and `test_conventions.py` (`AGENTS.md` / `CLAUDE.md`, ADR titles ≤ 50, 10% cap)
  - [x] 5.3 `[I]` [code-review] `context/verifier.py`, `context/repo_conventions.py` (D-25, D-33, D-38)
  - [x] 5.4 Verify Acceptance Criteria: AC1 lookup; AC2 drift section; AC3 candidates; AC4 drift context; AC5 conventions; AC6 no report
  - [x] 5.5 Map each AC to test evidence in the PR body
  - [x] 5.6 Run Tests: `make -C agents/code-review/app/codeReview validate`; `make validate` — package validate passes; root `make validate` NOT RUN in the S-208 runtime (sibling venvs missing)

- [ ] 6.0 Implement Story S-209 (#411): Budget fit, rubric v1, and prompt builder · branch `story/S-209-budget-prompt`
  - [ ] 6.1 `[T]` [code-review] L1 `test_estimate.py`
  - [ ] 6.2 `[T]` [code-review] L1 `test_budget_fit.py`: priority order a–g, `min(cap, remaining)`, truncation and omission named, smallest-first files, diff over budget, invariant at `max_context_tokens` 20,000 (TC-209-08, RT-07), dropped candidates reported (D-37)
  - [ ] 6.3 `[T]` [code-review] L1 `test_prompt.py`: all blocks, nonce wrapping, forged `<<<END` stays inside, candidate IDs outside and row text inside `verifier-candidate V<k>` blocks (TC-209-16), rubric version; nonce-integrity property tactic (D-38)
  - [ ] 6.4 `[I]` [code-review] `rubric.md` v1 (categories, consequence rule, out-of-scope list, verifier boundary)
  - [ ] 6.5 `[I]` [code-review] `budget.py` priority fill and asserted invariant → `INTERNAL_ERROR` on violation (D-27, D-37)
  - [ ] 6.6 `[I]` [code-review] `prompt.py` system prompt, nonce blocks, per-candidate blocks, prompt sink (D-33, D-38)
  - [ ] 6.7 Verify Acceptance Criteria: AC1 estimate; AC2 priority fill; AC3 invariant; AC4 rubric; AC5 system prompt; AC6 nonce; AC7 candidate blocks; AC8 sink
  - [ ] 6.8 Manual: one rendered prompt for a fixture PR pasted in the PR description
  - [ ] 6.9 Map each AC to test evidence in the PR body
  - [ ] 6.10 Run Tests: `make -C agents/code-review/app/codeReview validate`; `make validate`

- [ ] 7.0 Implement Story S-210 (#412): Bedrock adapter, forced schema, fallbacks · branch `story/S-210-bedrock-adapter`
  - [ ] 7.1 `[T]` [code-review] Fake `converse` in `tests/fixtures/bedrock.py`; L1 `test_bedrock_adapter.py`: forced path; `toolChoice` rejected → fallback; repair → valid; repair invalid → `ModelOutputInvalid`; reasoning rejected → retry; context-length → retry without files; call budget ≤ 5 (property tactic); access denied; throttling; cost null without prices
  - [ ] 7.2 `[T]` [code-review] Contracts CT-06/CT-07 (request/response shape) and CT-08 (`submit_review` schema); edge: empty findings, 41 findings, unknown category, text with no toolUse
  - [ ] 7.3 `[I]` [code-review] `findings_schema.py` (spec §6.3) and a validator, preferring no new dependency
  - [ ] 7.4 `[I]` [code-review] `bedrock_adapter.py`: forced `submit_review`, fallbacks, reasoning field constant, usage/metrics (D-34, D-35)
  - [ ] 7.5 Verify Acceptance Criteria: AC1 forced; AC2 fallback; AC3 reasoning; AC4 context-length; AC5 repair; AC6 call budget and usage; AC7 errors
  - [ ] 7.6 Map each AC to test evidence in the PR body
  - [ ] 7.7 Run Tests: `make -C agents/code-review/app/codeReview validate`; `make validate`

- [ ] 8.0 Implement Story S-211 (#413): Findings validation and verdict · branch `story/S-211-findings-validation`
  - [ ] 8.1 `[T]` [code-review] L1 `test_validate.py`: non-reviewed file dropped; outside-diff and no-scenario downgrades; ±3 boundary; no consequence dropped; suggestion cap; IDs; `line_end < line_start` swap; validation property tactic
  - [ ] 8.2 `[T]` [code-review] L1 `test_verdict.py`: confirmed, not_reproduced, omitted, budget-dropped (counts), mixed, none, unknown candidate ID ignored (D-15, D-33, D-37)
  - [ ] 8.3 `[I]` [code-review] `validate.py` (D-08)
  - [ ] 8.4 Verify Acceptance Criteria: AC1–AC5 validation; AC6 verdict; AC7 counts
  - [ ] 8.5 Map each AC to test evidence in the PR body
  - [ ] 8.6 Run Tests: `make -C agents/code-review/app/codeReview validate`; `make validate`

- [ ] 9.0 Implement Story S-212 (#414): Review, budget, and failure comments · branch `story/S-212-comment-render`
  - [ ] 9.1 `[T]` [code-review] L1 `test_render.py` snapshots: clear and blocking layouts; empty sections omitted; verifier states with rows from wrapper data (D-38); context line; mention, HTML, backtick neutralization
  - [ ] 9.2 `[T]` [code-review] L1 size guarantee: each of the five stages; worst case at schema maxima with escape-heavy text stays ≤ 60,000 (TC-212-14); truncation property tactic (RT-06) (D-36)
  - [ ] 9.3 `[T]` [code-review] L1 budget and failure messages with the run link (D-29)
  - [ ] 9.4 `[I]` [code-review] `render.py` (D-28, D-36)
  - [ ] 9.5 Verify Acceptance Criteria: AC1 layout; AC2 verifier; AC3 context line; AC4 neutralization; AC5 size; AC6 messages
  - [ ] 9.6 Manual: paste a rendered snapshot into a GitHub comment preview and check the layout
  - [ ] 9.7 Map each AC to test evidence in the PR body
  - [ ] 9.8 Run Tests: `make -C agents/code-review/app/codeReview validate`; `make validate`

- [ ] 10.0 Implement Story S-213 (#415): Pipeline wiring, outcomes, and failure path · branch `story/S-213-pipeline-wiring`
  - [ ] 10.1 `[T]` [code-review] L1 `test_outcomes.py` (verdict → outcome; error → code → comment-or-not table incl. `COMMENT_POST_FAILED` → one short failure comment unless 401/403) and `test_deadline.py` (D-36, D-32)
  - [ ] 10.2 `[T]` [code-review] `tests/integration/test_pipeline_e2e.py` on fixtures + fake Bedrock: clear; blocking; AC-7 verifier; AC-9 downgrade/drop; budget; closed PR; draft PR reviewed; no CI read; SHA pinned; issue 403 note; Bedrock error → failure comment; `COMMENT_POST_FAILED` paths; artifact and metrics shape; new comment each run
  - [ ] 10.3 `[T]` [code-review] Prompt capture: ±50 context and full files (AC-4); #315 issue without checklist and its spec (AC-6); no excluded-file content (AC-8); injection text inside nonce markers (AC-13 static)
  - [ ] 10.4 `[I]` [code-review] `pipeline.py` with injected GitHub client, Bedrock client, clock, prompt sink; steps and run_events; outcomes; scrubbed `audit_report` artifact; metrics; deadline and heartbeat; `finally` failure comment (D-13, D-32, D-36)
  - [ ] 10.5 `[I]` [code-review] Replace the skeleton in `main.invoke`
  - [ ] 10.6 Verify Acceptance Criteria: AC1 steps; AC2 states and drafts; AC3 SHA; AC4 budget; AC5 outcomes; AC6 artifact and metrics; AC7 errors and failure comment; AC8 deadline; AC9 new comment; AC10 prompt capture
  - [ ] 10.7 Manual: local run against a scratch PR in a test repository (requires a personal token; record as not run if unavailable)
  - [ ] 10.8 Map each AC to test evidence in the PR body
  - [ ] 10.9 Run Tests: `make -C agents/code-review/app/codeReview validate`; `make validate`

## Decisions Consumed

| ID   | Decision (short form)                                                              |
| ---- | ---------------------------------------------------------------------------------- |
| D-07 | One Bedrock Converse call, no tools, no Strands loop, no clone.                    |
| D-08 | Wrapper enforces the blocking contract.                                            |
| D-11 | Oversized PRs get a budget comment, not a partial review.                          |
| D-13 | Best-effort failure comment.                                                       |
| D-15 | `Critical`+`Unintended` drift counts toward `blocking`.                            |
| D-20 | Layout mirrors `security-analyst`; sibling modules copied; new `github_client.py`. |
| D-21 | Sibling invocation payload via `unwrap_payload`.                                   |
| D-22 | Linked issues from PR-body closing keywords and branch name.                       |
| D-23 | Strip `## Task Checklist` from issue bodies.                                       |
| D-24 | Spec resolution and trimming.                                                      |
| D-25 | Fidelity report lookup.                                                            |
| D-26 | ±50-line diff built locally with `difflib`.                                        |
| D-27 | Token estimate `ceil(chars / 3.5)`.                                                |
| D-28 | Comment kept under 60,000 chars.                                                   |
| D-29 | Run link from `PANEL_BASE_URL`.                                                    |
| D-32 | 900 s run, clock invariant, heartbeat.                                             |
| D-33 | Wrapper selects candidates; model confirms; only confirmed block.                  |
| D-34 | Forced `submit_review` schema with fallback.                                       |
| D-35 | `reasoning_effort` param, default `high`.                                          |
| D-36 | Five-stage size guarantee; failure comment after `COMMENT_POST_FAILED`.            |
| D-37 | Priority fill with asserted invariant.                                             |
| D-38 | Candidate row text only inside per-candidate nonce blocks.                         |
