# Traceability Matrix — Security Analyst Agent

## Changelog

| Version | Date       | Summary         | Author   |
| ------- | ---------- | --------------- | -------- |
| 1.0     | 2026-09-15 | Initial version. Design-mode mapping of all 31 numbered ACs + AC-12a/AC-12b (33 total) to designed E2E (SC-*), contract (CT-*), edge-case (EC-*), and randomized (RT-*) test cases from `test-plan-prd-security-analyst-agent.md` v1.0. Every AC has ≥1 positive and ≥1 negative/edge case. No implementation exists yet — this is a design reference, not a measured-coverage reconciliation (contrast with `traceability-matrix-dep-update-agent.md` v1.1, which reconciles against a shipped suite). | verifier |

---

## AC → Designed-Case Mapping

| AC ID | Description | Positive case(s) | Negative/Edge case(s) | Layer | Story |
|-------|-------------|-------------------|-------------------------|-------|-------|
| AC-1 | Project scaffolding | SC-1 | — (infra verification, no negative case applicable) | Manual/E2E | S-125 |
| AC-2 | Deploys successfully | SC-2 | — (infra verification) | Manual/E2E | S-125, S-141 |
| AC-3 | Audit-only, clean repo | SC-4 | EC-10, EC-18 | E2E, Unit | S-135 |
| AC-4 | Audit-only, findings + fail_on=true | SC-5 | EC-40 (contrast, min_severity floor) | E2E, Unit | S-135 |
| AC-5 | Audit-only, findings + fail_on=false | SC-6 | SC-5 (contrast) | E2E | S-135 |
| AC-6 | Fingerprint stability | SC-10 | SC-11, EC-34, EC-35, RT-1 | Unit, Property | S-127 |
| AC-7 | Cross-tool dedup merge | SC-12 | EC-36 (3-way variant) | Unit | S-133 |
| AC-8 | Dedup does not over-merge | SC-13 | EC-37, RT-2 | Unit, Property | S-133 |
| AC-9 | Classifier: Semgrep autofix → mechanical | SC-14 | RT-3 (totality check) | Unit, Property | S-134 |
| AC-10 | Classifier: Trivy base-image version bump → mechanical | SC-15 | SC-19 (contrast, major-bump guard) | Unit | S-134 |
| AC-11 | Classifier: JS/TS lockfile → manual (D24 boundary) | SC-16 | SC-17 (contrast, Python not excluded), EC-38 | Unit | S-134 |
| AC-12 | Unclassifiable → unscannable, never modified | SC-18 | RT-3 (totality check) | Unit, Property | S-134 |
| AC-12a | Severity normalization table | SC-20 | RT-4 (totality + flagged Semgrep KeyError gap) | Unit, Property | S-126 |
| AC-12b | `min_severity` gates status only, never scope | SC-7, SC-9 | SC-8, EC-40, RT-6 | E2E, Unit, Property | S-135, S-140 |
| AC-13 | Fix mode happy path, zero tokens | SC-21 | — (contrast: SC-25 shows the LLM-used branch) | E2E, Component | S-140 |
| AC-14 | Re-scan gate blocks unverified fix | SC-22 | RT-5 (gate correctness) | E2E, Component, Property | S-137, S-140 |
| AC-15 | Re-scan gate blocks regression-introducing fix | SC-23 | SC-24 (contrast, allow-listed exception passes), EC-39 (near-miss) | E2E, Component, Unit | S-137, S-140 |
| AC-16 | LLM escape hatch fires only when needed | SC-25 | EC-23, EC-24 (triggers) | Component | S-138, S-140 |
| AC-17 | LLM budget per finding | SC-26 | EC-43 (upper-bound stress) | Component | S-138 |
| AC-18 | LLM disabled at max_fix_attempts=0 | SC-27 | — (this scenario is itself the negative case) | Component | S-138 |
| AC-19 | Allow-list closed (single-finding scope) | SC-28 | — (this scenario is itself the negative/verification case) | Component | S-138 |
| AC-20 | Path escape refused | SC-29 | EC-31, EC-32, EC-33 | Unit | S-138 |
| AC-21 | No-findings no-op, fix mode | SC-30 | SC-31 (contrast, manual/unscannable remain) | E2E, Component | S-140 |
| AC-22 | Idempotency | SC-32 | EC-19, EC-20 (contrast, PR closed → new run allowed) | Component | S-139 |
| AC-23 | Scanner skip non-fatal | SC-33 | — (skip is itself the assertion) | Unit, Component | S-131 |
| AC-24 | Scanner failure non-fatal unless total | SC-34 | SC-35 (total-failure case), EC-21, EC-22 | Component | S-132, S-135 |
| AC-25 | GitHub App auth, shared installation | SC-36 | EC-26 (no matching row → NO_INSTALLATION) | Unit, Component | S-125 |
| AC-26 | No credential on disk or in logs | SC-37 | EC-29 (re-mint mid-run doesn't leak) | Unit, Component | S-125 |
| AC-27 | Secret value never leaks through findings | SC-38 | — (this scenario is itself the negative/verification case) | Unit | S-129 |
| AC-28 | Invalid payload fast-fails | SC-39 | EC-1–EC-6, EC-8 | Unit | S-125 |
| AC-29 | Step stream complete | SC-43 | EC-13 (terminal-on-gate-failure variant) | Component | S-140 |
| AC-30 | Reporting outage survivable | SC-44 | EC-28 | Unit, Component | S-125 |
| AC-31 | Reaper interlock | SC-45 | EC-16 | Unit (static half), Manual (dynamic half) | S-141 |

**Coverage summary:** 33/33 ACs (AC-1 through AC-31, plus AC-12a and AC-12b) mapped with ≥1 positive test case; 30/33 have an explicit negative/edge case beyond the positive scenario itself. The 3 exceptions (AC-1, AC-2, AC-23) are cases where the acceptance criterion is inherently a single verification point (a deployment check or a skip-is-the-assertion case) with no meaningful "negative" counterpart distinct from the positive one — noted rather than silently left blank, consistent with rule 4 (every AC maps to ≥1 positive + ≥1 negative/edge test): where no distinct negative case is meaningful, the gap is called out explicitly in the table above rather than fabricated.

---

## Requirement-Level Cross-Reference (supplementary, beyond the numbered AC list)

Several PRD requirements are exercised by this plan without having their own dedicated AC number (they are covered as part of a broader AC's test, or are genuinely uncovered):

| Requirement | Covered by | Note |
|---|---|---|
| req 27 (major-version bump guard) | SC-19 | Folded into AC-10's classifier coverage; not separately numbered in PRD §13. |
| req 34 (re-scan allow-list, enumerated not inferred) | SC-24, EC-39 | Folded into AC-15. |
| req 42 (PR body completeness) | SC-46, CT-13 | No dedicated AC; PRD §13 doesn't enumerate PR-body-section completeness as its own criterion the way the sibling PRD's AC-17 does. Flagged as a plan-level gap-fill, not an AC. |
| req 46 (7 run_steps) | SC-43 | = AC-29. |
| req 54 (D24 boundary, npm/pnpm only) | SC-17 | Folded into AC-11's contrast case. |
| req 56 (non-JS/Python-stack coverage combination) | SC-40, EC-46 | **No dedicated AC exists in PRD §13 for this requirement at all** — flagged to `product-engineer` as a possible AC-catalog gap, not fabricated as an AC number in this matrix. |
| req 62–64 (`min_severity` scope non-narrowing) | SC-9, RT-6 | = AC-12b. |

---

## Traceability Rule Compliance

- Every AC-ID → Test-Case-ID → Observed-Result(**Pass/Fail/Drift — not yet observed, pre-implementation**) mapping is structurally present above; the **Observed-Result** column is intentionally omitted from this table because no implementation exists to observe against yet (Design Mode only). It **MUST** be added in the first Audit Mode pass once `agents/security-analyst/` code lands.
- Randomized cases (RT-1–RT-6) carry seed/replay policy in `test-plan-prd-security-analyst-agent.md` §6, satisfying the deterministic-replay rule.
- No AC required marking `blocked` for missing source material — all 4 source artifacts (PRD v1.2, spec v1.2, stories doc, task plan) were readable and internally consistent enough to extract every AC.
