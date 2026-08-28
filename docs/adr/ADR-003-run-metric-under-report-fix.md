# ADR-003: Document the run-metric under-reporting fix (`advisories_fixed` / `packages_changed`)

## Status

Accepted

## Context

`docs/technical-guidelines.md` §9 (Code Organization & Structure) and §11
(Testing Strategy) described the `dependency-update` agent's current state after
issue #76. Issue #90 ("Fix run-metric under-reporting of changed packages and
fixed advisories"), implemented on branch `issue/90-run-metrics-under-report`
(PR #93), fixes two metric-computation bugs that the issue #77 E2E surfaced:

1. **`advisories_fixed` reported 0.** The count was `(in_range in classified) -
   (in_range in reclassified)`, which is `0 - 0` on any repo where no advisory
   was ever classified `in_range` (e.g. a monorepo whose advisories all land in
   the `unknown` bucket), even when real advisories disappeared across the
   update. It is now an advisory **ID-set diff** — the number of advisory IDs
   present in the before-update audit but absent from the after-update audit
   (`audit.count_advisories_fixed`, `before_ids − after_ids`, deduplicated,
   never negative).

2. **`packages_changed` reported 0.** `snapshot_lockfile_packages` used
   `pnpm list --json --depth 0` / `npm list --json --depth 0`, a root-only
   listing that in a workspace/monorepo layout sees none of the workspace-package
   or transitive changes the lockfile reconcile applied, so `diff_packages`
   returned empty. The snapshot is now workspace-aware and recursive
   (`pnpm list -r --depth Infinity --json` / `npm list --all --json`), walking
   the nested `dependencies` tree via a new `_collect_deps` helper.

3. **Consistency.** The fixed-advisory count is now computed once (before the
   `open_pr` step) and threaded into **both** the PR body Security Summary
   (`build_pr_body_from_state(advisories_fixed_count=…)`) and
   `runs.metrics.advisories_fixed` (`build_return_payload(advisories_fixed=…)`),
   so the two artifacts can no longer disagree. The npm advisory `id` is
   normalized to a `source`-or-`url` fallback so npm advisories lacking a numeric
   `source` are not collapsed to `id=""` and under-counted in the ID-set diff.

Leaving the §9 status line and §11 test surface unchanged would misrepresent the
current implemented state (which metrics are trustworthy, and how they are
computed) and would keep a stale test count. This ADR exists to satisfy the
repository rule that **every modification to `docs/technical-guidelines.md` is
accompanied by an ADR** — even when the modification is a factual current-state
correction rather than a new decision.

## Decision

Update the current-state descriptions in `technical-guidelines.md` to reflect
the issue #90 fix:

1. §9 status line — record that `advisories_fixed` is an audit ID-set diff and
   `packages_changed` a workspace-aware recursive lockfile snapshot, that both
   previously under-reported (0) on monorepos, and that a single fixed-advisory
   count feeds both the PR body Security Summary and `runs.metrics`. Remove the
   stale "full `runs.metrics` persistence (`llm_used` / `fix_attempts`)" clause
   from the issue #77 deferral list — persistence itself was wired by #77 and the
   values are now correct; only the fix-budget test-output artifact and
   deploy/E2E remain deferred.
2. §11 test surface — add the issue #90 Layer 1 (`test_audit.py`:
   `TestCountAdvisoriesFixed`, monorepo-recursion cases) and Layer 2
   (`test_pipeline.py`: `test_security_summary_uses_id_set_diff_not_bucket_count`)
   tests, and update the suite count from 328 to **362 passing**.

No enforceable guideline rule (§3 architecture patterns, §5 auth, §6 security) is
changed. In particular this preserves the fleet's "explicitness over inference"
posture (§10): the metric is now an explicit set difference over reported
advisory IDs rather than an inference from bucket classification.

## Alternatives Considered

- **Update the guideline without an ADR** because this is a bug-fix status
  correction, not a new architectural decision. Rejected: the repository rule is
  literal — any change to `technical-guidelines.md` requires an ADR (same
  reasoning as ADR-002). This ADR is deliberately scoped as a current-state
  correction record.
- **Amend ADR-002 instead of a new ADR.** Rejected: ADR-002 records the issue #76
  `open_pr` step; ADRs are immutable once Accepted except for status
  transitions, and issue #90 is a distinct change.
- **Treat the metric fix as a new architectural decision (choosing ID-set diff
  as the canonical measure).** Considered but rejected as overstated: the
  before/after audit already existed; this corrects a computation to match the
  already-documented intent ("advisories closed"), it does not introduce a new
  constraint or golden-path rule.

## Consequences

- **Positive:** the foundation doc now states which run metrics are trustworthy
  and how they are computed; readers no longer see a stale test count or the
  implication that `advisories_fixed`/`packages_changed` are best-effort.
- **Negative / cost:** a low-substance ADR for what is essentially a bug-fix
  status update. Accepted as the cost of the "ADR-per-guideline-change"
  invariant.
- **Follow-up:** when issue #77's remaining scope lands (fix-budget test-output
  artifact, deploy, E2E), §9 and §11 will need another current-state refresh.
  The `specification-prd-dependency-update-agent.md` §11 table still cites the
  old `--depth 0` snapshot command (§8-era design text); it is a historical
  specification, left as-is and logged as known drift in the delta report.

## Related

- Requirements:
  - `docs/requirements/prd-dependency-update-agent.md` (§9.1 `runs.metrics`
    fields; "advisories closed")
  - `workstream/specification-prd-dependency-update-agent.md` (§9 return payload;
    §11 package-snapshot note — now historical)
- Workstream:
  - `workstream/tasks-issue-90-run-metrics-under-report.md`
  - `workstream/fidelity-report-issue-90.md` (AC coverage)
- Docs updated:
  - `docs/technical-guidelines.md` (§9, §11, changelog 1.4)
  - `agents/dependency-update/README.md` (Pipeline / run-metrics note)
- Implementation:
  - `agents/dependency-update/app/dependencyUpdate/audit.py`
    (`count_advisories_fixed`, `snapshot_lockfile_packages`, `_collect_deps`,
    `_parse_list_json`, npm advisory `id` normalization)
  - `agents/dependency-update/app/dependencyUpdate/main.py` (single `fixed_count`
    source feeding PR body + `runs.metrics`)
  - `agents/dependency-update/app/dependencyUpdate/pull_request.py`
    (`build_pr_body` `advisories_fixed_count` parameter)
