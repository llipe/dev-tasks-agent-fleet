# Implementation Plan - Issue #90: Run metrics under-report changed packages and fixed advisories

## Relevant Files

- `agents/dependency-update/app/dependencyUpdate/audit.py` - `snapshot_lockfile_packages` (workspace-aware/recursive listing), `_parse_list_json` (recurse into nested deps), and a new advisory-ID-set diff helper.
- `agents/dependency-update/app/dependencyUpdate/main.py` - `advisories_fixed` computation (ID-set diff, not bucket subtraction) and `build_pr_body_from_state` (Security Summary "fixed" count must match).
- `agents/dependency-update/app/dependencyUpdate/tests/unit/test_audit.py` - Unit tests for workspace-aware snapshot, recursive parse, and the advisory-ID-set diff.
- `agents/dependency-update/app/dependencyUpdate/tests/component/test_pipeline.py` - Component tests asserting PR body Security Summary "Advisories fixed" agrees with the ID-set diff.
- `agents/dependency-update/app/dependencyUpdate/tests/fixtures/` - New fixtures: monorepo/workspace `pnpm list -r` output and before/after audit pairs for the ID-set diff.

## Tasks

- [ ] 1.0 Implement Issue #90 — https://github.com/llipe/dev-tasks-agent-fleet/issues/90: Fix run-metric under-reporting of changed packages and fixed advisories

  > Note: Two independent bugs. (1) `packages_changed: 0` — `snapshot_lockfile_packages` uses `list --json --depth 0`, which in a workspace/monorepo sees no workspace-package or transitive changes, so `diff_packages` is empty. (2) `advisories_fixed: 0` — computed as `(in_range in classified) - (in_range in reclassified)`, which is `0 - 0` when nothing was ever `in_range`. Fix by comparing advisory ID sets before vs. after. The `advisories_fixed` value must be identical in `runs.metrics` and the PR body Security Summary.

  - [ ] 1.1 (test-first) Add a before/after audit fixture pair (advisory IDs disappear between them, none classified `in_range`) and write a failing unit test for an advisory-ID-set diff helper in `test_audit.py`.
  - [ ] 1.2 Implement the advisory-ID-set diff helper in `audit.py` (`advisories_fixed` = count of advisory IDs present before but absent after), operating on the normalized advisory dicts from `extract_advisories`.
  - [ ] 1.3 Wire the ID-set diff into `main.py`: replace the `in_range` subtraction with the helper over `audit_before.advisories` vs `audit_after.advisories`; feed the same count into `build_pr_body_from_state` so the Security Summary "Advisories fixed" matches `runs.metrics.advisories_fixed`.
  - [ ] 1.4 (test-first) Add a monorepo/workspace `pnpm list -r` fixture and write a failing unit test for `_parse_list_json` recursing into workspace entries + nested `dependencies` (transitive), and for `snapshot_lockfile_packages` using the workspace-aware command.
  - [ ] 1.5 Implement the workspace-aware snapshot in `audit.py`: make `snapshot_lockfile_packages` use a recursive/workspace-aware listing (pnpm `list -r --depth Infinity --json`, npm `list --all --json`) and extend `_parse_list_json` to walk nested `dependencies` so transitive/workspace changes are captured.
  - [ ] 1.6 (test-first -> verify) Add a component test in `test_pipeline.py` asserting the PR body Security Summary "Advisories fixed" and the Package Changes section are consistent with the actual diff (both non-zero in the monorepo scenario).
  - [ ] 1.x Verify Acceptance Criterion: `advisories_fixed` reflects advisories actually resolved (ID-set diff, not bucket subtraction).
  - [ ] 1.y Verify Acceptance Criterion: `packages_changed` is non-zero when the update produces package version changes in a monorepo/workspace layout.
  - [ ] 1.z Verify Acceptance Criterion: PR body Security Summary and Package Changes sections are consistent with the real diff.
  - [ ] 1.aa Verify Acceptance Criterion: unit tests cover the monorepo/workspace case and the ID-set diff.
  - [ ] 1.bb Run Tests: `pytest -m "unit or component" tests/unit/test_audit.py tests/component/test_pipeline.py` and the full agent suite (`make validate`).
  - [ ] 1.cc E2E note: "Verified by a real E2E run on a monorepo repository" requires live AWS/Supabase/GitHub access — document as an operator-run step (mirrors issue #77 runbook handling); not runnable in this environment.
