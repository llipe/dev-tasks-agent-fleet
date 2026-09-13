# Implementation Plan — Issue #78 (compliance test plan for dependency-update agent)

> **Mode:** Issue Mode. **Nature:** this is a **Design / governance** issue (label `documentation`),
> not a code feature. It tracks the compliance test plan for the dependency-update agent (PRD v1.2:
> 65 requirements / 36 ACs; Spec v1.0). Its artifacts already exist:
> `workstream/test-plan-dep-update-agent.md` and
> `workstream/traceability-matrix-dep-update-agent.md` (moved back from `workstream/archive/`
> in task 3.5, now the maintained record).

## Read this first — why this plan is "reconcile & decide", not "build"

#78's plan claims **82 test cases** across four layers, including **36 E2E black-box scenarios**
(pytest + real infra), **12 contract tests** (moto + responses), **28 edge cases**, and **6 randomized
tactics** (hypothesis). Current reality of the agent suite (verified 2026-09-11):

- The agent has a substantial **Layer 1 (unit)** + **Layer 2 (component)** suite (≈19 unit modules,
  3 component modules) — outcome mapping, classifier, eligibility, mandate, scrubber, safe-path,
  toolchain, updater, validator, PR body/creation, pipeline, fix-agent, etc.
- `pyproject.toml` defines **only** `unit` and `component` markers. There is **no `e2e` marker, no
  `fuzz` marker, and `hypothesis` is not a dependency.** No `--run-e2e` option exists.
- So the plan's E2E (36) and randomized (6) layers — 42 of the 82 cases — are **designed but not
  implemented as marked, runnable tests**. The contract/edge cases are largely covered by the existing
  Layer 1/2 suite but not tallied against the plan's 82-case structure.

This is a **plan-vs-reality gap**, not a code defect. #78 should not be "closed as done" while it
asserts 82/82 with 0 gaps, nor should it silently trigger building a 36-case real-infra E2E harness
that the repo has deliberately not built (the agent's real-infra E2E is the operator runbook
`issue-77-deployment-e2e.md`, run manually, not a pytest layer). The correct move is a **coverage-gap
reconciliation**: measure what the shipped suite actually covers against the 36 ACs, then decide per
gap — accept (documented), backfill as unit/component (cheap), or defer (E2E/fuzz) with an explicit
rationale — and update the plan + traceability matrix + `TESTING.md` to tell the truth.

**This plan intentionally does not commit to writing 82 tests.** Task 1.0 is the decision gate that
determines scope; tasks 2.x execute only what that gate approves.

## Language / toolchain

Python agent (`agents/dependency-update/app/dependencyUpdate/`). Gate: `make validate`
(ruff lint + ruff format-check + mypy + pytest --cov + pip-audit --strict). Layers via
`python -m pytest -m unit` / `-m component`.

## Migration

**Documented opt-out — N/A.** Documentation + (possibly) additive tests only. No schema/data change.

## Relevant Files

- `workstream/test-plan-dep-update-agent.md` — the Design plan, reconciled to measured reality (v1.1) and moved back from `workstream/archive/` (task 3.5).
- `workstream/traceability-matrix-dep-update-agent.md` — the 36-AC → real-test mapping, reconciled (v1.1) and moved back from `workstream/archive/` (task 3.5).
- `agents/dependency-update/app/dependencyUpdate/tests/**` — the shipped suite (source of truth for actual coverage).
- `agents/dependency-update/app/dependencyUpdate/pyproject.toml` — markers (would gain `e2e`/`fuzz` only if the decision gate approves those layers).
- `TESTING.md` — the coverage/gaps record to update so it matches reality.

## Tasks

- [x] 1.0 DECISION GATE — reconcile the #78 plan against the shipped suite (produces the scope for everything below)

  - [x] 1.1 Build an **actual coverage map**: for each of the 36 ACs in `traceability-matrix-dep-update-agent.md`, mark whether a real, runnable test asserts it today (name the test), and at which layer (unit / component). Use the shipped `tests/**` as truth, not the plan's claims.
  - [x] 1.2 Classify each AC into one of: **(a) covered** (cite the test), **(b) cheap backfill** (a unit/component test that should exist and can be added without real infra), **(c) defer** (genuinely needs real AWS/Supabase/GitHub — belongs to the manual `issue-77-deployment-e2e.md` runbook, not a pytest `e2e` marker), or **(d) randomized** (hypothesis property test — decide worth-it per AC).
  - [x] 1.3 Decide the **randomized/fuzz** question explicitly: does the agent adopt `hypothesis` for the 6 planned property tests (classifier range parsing, scrubber, eligibility invariants), or are those covered adequately by table-driven unit tests? Record the decision + rationale (adding `hypothesis` is a new dev dependency → `pip-audit --strict` must stay green). **DECISION: skip** — invariants covered by table-driven unit tests; property-style tests already exist in `test_heartbeat.py` without `hypothesis`.
  - [x] 1.4 Decide the **E2E** question explicitly: confirm the repo's position that real-infra agent verification lives in the operator runbook (manual), so #78's "36 E2E scenarios" are **reframed** as the runbook + the unit/component coverage of the same ACs — NOT a new `pytest -m e2e --run-e2e` harness — unless the user wants that harness built (large, real-credentials, out of proportion to a single-operator tool). **DECISION: keep in runbook** — no `-m e2e` harness.
  - [x] 1.5 **Present the reconciliation summary to the user and get an explicit scope decision** before writing any test or editing the plan: which (b) backfills to write, whether to adopt hypothesis (d), and confirmation that (c) stays runbook-deferred. This is the gate — 2.x/3.x execute only the approved subset. **DECISION (user, 2026-09-11): skip fuzz, keep E2E in runbook, no backfill (AC-33 as-is), close via docs PR, move artifacts to `workstream/`.**

- [x] 2.0 Execute the approved backfill (scope set by 1.5 — **empty**: the suite already covers the automatable ACs; no tests written)

  - [x] 2.1 For each approved **(b) cheap-backfill** AC: write the unit/component test — **none approved (empty).**
  - [x] 2.2 If hypothesis was approved (d): add it as a pinned dev dependency… — **not approved; no `pyproject.toml`/marker change.**
  - [x] 2.3 If any AC was reclassified from the plan's E2E to a unit/component assertion… — **none reclassified to new tests; existing coverage cited in the matrix.**
  - [x] 2.x Verify: every newly written test passes and maps to a specific AC — **N/A (no new tests).**
  - [x] 2.z Run Tests — **N/A for new tests; existing suite unchanged (460 collected).**

- [x] 3.0 Truth-up the documents (the core deliverable of a documentation issue)

  - [x] 3.1 Update `test-plan-dep-update-agent.md`: replace the aspirational "82 cases / 0 gaps" summary with the **measured** state — actual counts per layer, ACs covered, and each **accepted gap** (the deferred-to-runbook E2E ACs) with its rationale. An honest "N covered, M deferred-to-runbook (listed), 0 unaccounted" is the target, not a false 82/82.
  - [x] 3.2 Update `traceability-matrix-dep-update-agent.md` so every AC row points at a **real** test name or the runbook step that exercises it (no phantom rows).
  - [x] 3.3 Update `TESTING.md`'s dependency-update-agent coverage/gaps section to match (it already tracks agent gaps — align it with the reconciled matrix).
  - [x] 3.4 Verify Acceptance Criterion (#78 header): "36/36 ACs have ≥1 positive + ≥1 negative test, 0 gaps" is either **now true by measurement**, or **restated truthfully** with the deferred set explicitly listed and accepted — the issue must not close on an unverified claim. **RESTATED TRUTHFULLY: 30/36 automated, 6 deferred-to-runbook (listed), 0 unaccounted.**
  - [x] 3.5 Decide artifact location: if the plan/matrix are now the maintained record, move them from `workstream/archive/` back to `workstream/`; otherwise update in place and note they remain archived. **MOVED to `workstream/` via `git mv` (history preserved).**

- [x] 4.0 Close-out

  - [x] 4.1 Post a summary comment to #78 (`--body-file`) stating the reconciled coverage (measured counts, accepted deferrals) and linking the updated artifacts. **Posted (github-ops).**
  - [x] 4.2 If any code/test was written (2.x), that rides a PR with `Closes #78`; if the outcome is **documentation-only** (plan truth-up, no new tests), confirm with the user whether #78 closes via a docs PR or via the summary comment alone. **User chose docs PR → PR #179 (`Closes #78`).**
  - [x] 4.3 `qa-engineer` pass + `coverage_gate` recorded; `verifier` audit only if code/tests changed (a pure-docs reconciliation may not warrant a code audit — confirm at 4.2). **`coverage_gate: SKIPPED(documentation-only)`; verifier audit run anyway (workspace steering, non-skippable) → HIGH fidelity, D1 fixed inline, D2 optional→product-engineer; technical-writer drift `clean`.**

## Definition of Done

- [x] Actual AC-by-AC coverage measured against the shipped suite (task 1.1-1.2)
- [x] Scope decision taken **with the user** before writing tests (task 1.5) — no unilateral 82-case build
- [x] Approved backfill tests (if any) written and passing; `make validate` green — **N/A: no backfill approved; suite unchanged & green (460 passed)**
- [x] `test-plan` + `traceability-matrix` + `TESTING.md` reflect measured reality (no false "0 gaps")
- [x] Deferred ACs explicitly listed with rationale (real-infra → operator runbook)
- [x] Migration lifecycle — N/A, documented opt-out
- [ ] #78 closed on a **verified** claim (measured or truthfully restated), reviewed/merged by the user — **awaiting user review/merge of PR #179**
