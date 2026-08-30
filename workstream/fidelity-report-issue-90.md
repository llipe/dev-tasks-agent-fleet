# Fidelity Report — Issue #90

## Verdict

- **Fidelity: High**
- **Highest drift impact: Minor**
- **Scope:** issue #90 (`fix(agent): run metrics under-report changed packages and fixed advisories`) · branch `issue/90-run-metrics-under-report` · draft PR #93 · commit `bc6f4e5`
- **Mode:** Audit (grey-box) — non-blocking, additive gate

## Human-Readable Summary

The two reported bugs are genuinely fixed, not papered over.

1. **Advisories under-reported as 0.** The count is now derived from an advisory
   **ID-set difference** between the before-update and after-update audits
   (`count_advisories_fixed` = number of advisory IDs present before but gone
   after). This replaces the old logic that subtracted "in-range" bucket counts —
   the exact logic that returned 0 on a monorepo where every advisory landed in the
   `unknown` bucket even though real vulnerabilities were resolved. New advisories
   that appear only after the update are correctly ignored (never negative), and
   duplicate IDs are de-duplicated.

2. **Packages under-reported as 0.** The lockfile snapshot now uses a
   workspace-aware, recursive listing (`pnpm list -r --depth Infinity --json` /
   `npm list --all --json`) and walks the nested `dependencies` tree, so workspace
   packages and transitive changes in a turbo monorepo are captured instead of only
   the root's top-level dependencies.

3. **PR body and stored metrics can no longer disagree.** The fixed-advisory count
   is computed **once** before the PR is opened and passed to *both* the PR body's
   Security Summary and the `runs.metrics` payload. The Package Changes count comes
   from the same `pkg_changes` list used to build the PR body. This "single source
   of truth" wiring is the strongest part of the change.

All quality gates pass and the regression is locked in by tests that reproduce the
original failing scenario (all-`unknown` advisories that still disappear). One
lower-tier AC — a live E2E run on a real monorepo — is deferred to an operator
runbook and cannot be exercised in this environment.

## Per-AC Results

| AC | Description | Codebase evidence | Test evidence | Result |
|----|-------------|-------------------|---------------|--------|
| AC-1 | `advisories_fixed` reflects advisories resolved via ID-set diff (not bucket subtraction) | `audit.count_advisories_fixed` (before_ids − after_ids); old bucket-subtraction removed from `main.invoke` | `TestCountAdvisoriesFixed` (6 cases: unknown-bucket fixtures, equal sets, all-fixed, empty-before, no-negative, dedupe) | **Pass** |
| AC-2 | `packages_changed` non-zero on monorepo/workspace update | `snapshot_lockfile_packages` uses `pnpm list -r --depth Infinity` / `npm list --all`; `_collect_deps` recurses nested `dependencies` | `test_pnpm_monorepo_captures_all_workspace_and_transitive` (8 pkgs incl. transitive), `test_npm_nested_dependencies_recursion`, command-shape assertions | **Pass** |
| AC-3 | PR body Security Summary + Package Changes consistent with real diff | Single `fixed_count` feeds both `build_pr_body_from_state(advisories_fixed_count=…)` and `build_return_payload(advisories_fixed=…)`; `pkg_changes` shared | `test_security_summary_uses_id_set_diff_not_bucket_count` asserts `Advisories fixed = 2`, `glob-parent` present, and absence of the contradictory `fixed: 0` | **Pass** |
| AC-4 | Unit tests cover monorepo/workspace case and ID-set diff | Fixtures `list_pnpm_monorepo.json`, `audit_pnpm_before/after.json` | Full suite **361 passed**; touched files 89 passed | **Pass** |
| AC-5 | Verified by a real E2E run on a monorepo | N/A — requires live AWS/Supabase/GitHub | Deferred to operator runbook (documented as out-of-environment) | **Deferred (not assessable)** |

## Drift Catalog

Drift is **non-blocking** to PR/issue completion.

1. **npm advisories missing a numeric `source` collapse to one ID in the fixed-count diff.**
   - **Impact: Minor.** **Intent: Unintended.**
   - The npm extractor dedups on `via.source or via.url or ""` but stores `"id"` as
     `via.get("source", "")` *without* the URL fallback. `count_advisories_fixed`
     diffs on `"id"` and treats `""` as a countable value, so multiple npm advisories
     that lack a numeric `source` would all share `id == ""` and count as at most one.
   - In practice npm v7+ `via` entries for direct advisories carry a numeric
     `source` (the GHSA numeric id), so the common path is unaffected. All delivered
     `count_advisories_fixed` tests use the pnpm shape (numeric ids); the npm-shape
     ID-set diff is untested.
   - **Evidence:** `audit.py` `_extract_npm_advisories` (id vs. dedup-key mismatch);
     `audit.py` `count_advisories_fixed` (`id is not None` admits `""`).
   - **Non-blocking.**

2. **The `main.invoke()` end-to-end wiring is verified by inspection, not measured coverage.**
   - **Impact: Minor.** **Intent: Intended** (pre-existing config decision, not introduced here).
   - `main.py` is in the `[tool.coverage.run] omit` list, so the "single source of
     truth" flow (compute `fixed_count` once → PR body + `runs.metrics`) is not
     exercised by an automated end-to-end assertion. I confirmed the wiring by
     reading `invoke()`: `fixed_count` is computed before `open_pr` and passed to
     both sinks, and `packages_changed=len(pkg_changes)` reuses the PR-body list.
   - **Evidence:** `pyproject.toml` `omit = [... "main.py"]`; `main.py` invoke body.
   - **Non-blocking.**

## Quality Gates (independently re-run in this environment)

- Full test suite: **361 passed** (touched files: 89 passed)
- `ruff check .`: clean
- `ruff format --check .`: 32 files already formatted
- `mypy .`: no issues in 32 source files
- QA `coverage_gate`: PASS (audit.py 88%, pull_request.py 95%; main.py coverage-excluded by config)

## Recommendations

- **Reviewer must check (Drift #1):** decide whether the npm ID-set-diff path needs
  hardening. Cheapest fix: normalize the stored advisory `id` to the same
  `source or url` fallback used for dedup, and add one npm-shape `count_advisories_fixed`
  test. Suggested owner: `developer`. *(No action required to merge; monorepo target here is pnpm.)*
- **Operator (AC-5):** run the deferred live E2E on a real monorepo per the runbook
  and confirm `packages_changed`/`advisories_fixed` are non-zero and match the PR body
  before treating #90 as fully validated end-to-end.
- No spec-level ambiguity found — no `product-engineer` escalation needed.
