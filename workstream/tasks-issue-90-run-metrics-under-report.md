# Implementation Plan - Issue #90: Run metrics under-report changed packages and fixed advisories

## Relevant Files

- `agents/dependency-update/app/dependencyUpdate/audit.py` - Added `count_advisories_fixed` (advisory ID-set diff); made `snapshot_lockfile_packages` workspace-aware/recursive (`pnpm list -r --depth Infinity`, `npm list --all`); rewrote `_parse_list_json` + added `_collect_deps` to recurse into nested/transitive dependencies.
- `agents/dependency-update/app/dependencyUpdate/main.py` - Replaced the `in_range` bucket subtraction with `count_advisories_fixed(audit_before, audit_after)`; single `fixed_count` now feeds both `runs.metrics.advisories_fixed` and the PR body Security Summary; threaded `advisories_fixed_count` into `build_pr_body_from_state`.
- `agents/dependency-update/app/dependencyUpdate/pull_request.py` - `build_pr_body` accepts `advisories_fixed_count` used for the Security Summary (falls back to in-range table length when omitted).
- `agents/dependency-update/app/dependencyUpdate/tests/unit/test_audit.py` - `TestCountAdvisoriesFixed` (ID-set diff); monorepo recursive-parse + workspace-aware snapshot tests.
- `agents/dependency-update/app/dependencyUpdate/tests/component/test_pipeline.py` - `test_security_summary_uses_id_set_diff_not_bucket_count` asserting PR body Security Summary and Package Changes agree with the real diff.
- `agents/dependency-update/app/dependencyUpdate/tests/fixtures/audit_pnpm_before.json`, `audit_pnpm_after.json` - before/after audit pair (all `unknown` bucket) for the ID-set diff.
- `agents/dependency-update/app/dependencyUpdate/tests/fixtures/list_pnpm_monorepo.json` - `pnpm list -r` monorepo listing with workspace + transitive deps.
- `docs/technical-guidelines.md` - §9/§11 current-state correction + changelog v1.4 (via technical-writer).
- `docs/adr/ADR-003-run-metric-under-report-fix.md` - ADR for the guideline change.
- `agents/dependency-update/README.md` - run-metrics "Corrected as of issue #90" note.
- `workstream/fidelity-report-issue-90.md` - verifier audit fidelity report.

## Tasks

- [x] 1.0 Implement Issue #90 — https://github.com/llipe/dev-tasks-agent-fleet/issues/90: Fix run-metric under-reporting of changed packages and fixed advisories

  > Note: Two independent bugs. (1) `packages_changed: 0` — `snapshot_lockfile_packages` used `list --json --depth 0`, which in a workspace/monorepo sees no workspace-package or transitive changes, so `diff_packages` is empty. (2) `advisories_fixed: 0` — computed as `(in_range in classified) - (in_range in reclassified)`, which is `0 - 0` when nothing was ever `in_range`. Fixed by comparing advisory ID sets before vs. after. The `advisories_fixed` value is now identical in `runs.metrics` and the PR body Security Summary.

  - [x] 1.1 (test-first) Add a before/after audit fixture pair (advisory IDs disappear between them, none classified `in_range`) and write a failing unit test for an advisory-ID-set diff helper in `test_audit.py`.
  - [x] 1.2 Implement the advisory-ID-set diff helper in `audit.py` (`advisories_fixed` = count of advisory IDs present before but absent after), operating on the normalized advisory dicts from `extract_advisories`.
  - [x] 1.3 Wire the ID-set diff into `main.py`: replace the `in_range` subtraction with the helper over `audit_before.advisories` vs `audit_after.advisories`; feed the same count into `build_pr_body_from_state` so the Security Summary "Advisories fixed" matches `runs.metrics.advisories_fixed`.
  - [x] 1.4 (test-first) Add a monorepo/workspace `pnpm list -r` fixture and write a failing unit test for `_parse_list_json` recursing into workspace entries + nested `dependencies` (transitive), and for `snapshot_lockfile_packages` using the workspace-aware command.
  - [x] 1.5 Implement the workspace-aware snapshot in `audit.py`: make `snapshot_lockfile_packages` use a recursive/workspace-aware listing (pnpm `list -r --depth Infinity --json`, npm `list --all --json`) and extend `_parse_list_json` to walk nested `dependencies` so transitive/workspace changes are captured.
  - [x] 1.6 (test-first -> verify) Add a component test in `test_pipeline.py` asserting the PR body Security Summary "Advisories fixed" and the Package Changes section are consistent with the actual diff (both non-zero in the monorepo scenario).
  - [x] 1.x Verify Acceptance Criterion: `advisories_fixed` reflects advisories actually resolved (ID-set diff, not bucket subtraction).
  - [x] 1.y Verify Acceptance Criterion: `packages_changed` is non-zero when the update produces package version changes in a monorepo/workspace layout.
  - [x] 1.z Verify Acceptance Criterion: PR body Security Summary and Package Changes sections are consistent with the real diff.
  - [x] 1.aa Verify Acceptance Criterion: unit tests cover the monorepo/workspace case and the ID-set diff.
  - [x] 1.bb Run Tests: `pytest -m "unit or component"` full agent suite — 361 passed; gates: lint clean, format:check clean, mypy no issues, pip-audit no vulnerabilities.
  - [x] 1.cc E2E note: "Verified by a real E2E run on a monorepo repository" requires live AWS/Supabase/GitHub access — documented as an operator-run step (mirrors issue #77 runbook handling); DEFERRED, not runnable in this environment.
