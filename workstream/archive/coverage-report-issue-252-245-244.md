# Coverage & Gap Report — Issues #252, #245, #244

**Scope:** `integration/run-detail-followups-and-audit` vs `origin/main`
(planner batch: issues #252, #245, #244).
**Skill:** `activity-coverage-gap-analysis` per `/TESTING.md`.
**Date:** 2026-10-13.
**Environment:** Node 22.23.2 (via `nvm use 22`), pnpm 10.11.0; Python 3.13
agent venvs. **Docker daemon UNAVAILABLE** (`docker info` → `DOCKER_UNAVAILABLE`)
— this gates Layer 2.5 (`integration`) and E2E, see Structural Gaps.

This report does not modify code or tests and does not commit itself; the
planner will commit it.

---

## Branch scope (files changed vs origin/main)

Source files in scope (the three issues' run-detail / audit-gate surface):

- `panel/components/run-detail/AuditReportPanel.tsx` (+ `.module.css`) — #245
- `panel/components/run-detail/LiveLogViewer.tsx` — #244
- `panel/components/run-detail/RunDetailLogSection.module.css` — #244
- `agents/dependency-update/app/dependencyUpdate/pyproject.toml` + new
  `tests/unit/test_credentials_real_jwt.py` — #252
- `agents/security-analyst/app/securityAnalyst/pyproject.toml` + new
  `tests/unit/test_credentials_real_jwt.py` — #252

Test files changed/added in scope: `AuditReportPanel.test.tsx`,
`RunDetailLogSection.test.tsx`, `live-log-viewer.test.tsx`,
`run-detail-page-wiring.test.tsx`, plus E2E `run-detail-layout.spec.ts` (new)
and `live-tail.spec.ts` (extended) and `e2e/fixtures/seed.ts`.

---

## Path A — Measured coverage

### Panel (`@vitest/coverage-v8`, `pnpm --filter panel run test:coverage`)

Run result: **Test Files 85 passed | 18 skipped (103); Tests 1190 passed |
113 skipped (1303).** The 18 skipped files are every `tests/integration/*`
(Layer 2.5) suite plus `tests/unit/bundle-secrets.test.ts` (4, CI-gated) —
skipped locally because the Supabase/Postgres stack is unreachable with Docker
down (expected per `/TESTING.md` → "CI-vs-local Layer 2.5 gating"; `REQUIRE_LOCAL_DB`
unset ⇒ skip-with-reason, not fail).

**In-scope run-detail component coverage (statements / branch / funcs / lines):**

| File | % Stmts | % Branch | % Funcs | % Lines | Uncovered lines |
| --- | --- | --- | --- | --- | --- |
| `components/run-detail/AuditReportPanel.tsx` (#245) | **100** | **100** | **100** | **100** | — |
| `components/run-detail/LiveLogViewer.tsx` (#244) | **99.05** | 88 | 100 | **99.05** | 204 |
| `components/run-detail/RunDetailLogSection.tsx` (#244) | **100** | **100** | **100** | **100** | — |
| `components/run-detail/` (directory rollup) | 98.99 | 92.98 | 100 | 98.99 | — |

Target component test files all **passed** (not skipped), with the batch's new
assertions executing:

- `AuditReportPanel.test.tsx` — **33 tests** (incl. #245 findings-disclosure
  cap / `MAX_ROWS` notice, seeded randomized tactics).
- `live-log-viewer.test.tsx` — **21 tests** (#244 live-tail additions).
- `RunDetailLogSection.test.tsx` — **7 tests**.
- `run-detail-page-wiring.test.tsx` — **8 tests**.

**Against `/TESTING.md` thresholds:** `panel` has **no repo-level numeric
coverage floor** (tracked gap #5 in `/TESTING.md` "Harness defects"; `@vitest/
coverage-v8` is configured and runs, but no aggregate `fail_under` is enforced).
So there is no numeric threshold to violate for the panel. The in-scope files
are at or near 100% line coverage, well above the panel's historical per-module
norm. Panel aggregate for reference: **All files 72.33% lines / 89.96% branch /
80.86% funcs** — depressed by Layer-2.5-only server modules that do not execute
with Docker down (`lib/supabase/queries.ts` 2.01%, `app/.../events/stream/route.ts`
0%, `lib/supabase/browser.ts`/`types.ts` 0%), none of which are in this batch's
scope.

### Agents — `credentials.py` coverage (`make test-cov`)

Both agents gained a new `tests/unit/test_credentials_real_jwt.py` (#252,
2 tests each). Measured:

| Agent | `credentials.py` Stmts | Miss | Branch | BrPart | **% cover** | Suite | Package TOTAL | `fail_under` |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `dependency-update` | 75 | 0 | 8 | 0 | **100%** | 462 passed | 94% | none (measured only) |
| `security-analyst` | 75 | 0 | 8 | 0 | **100%** | 714 passed | **96.92%** | **90% — reached** |

- `dependency-update`: `credentials.py` **100%** (baseline in `/TESTING.md` was
  already 100% from #106/#108/#109; the #252 real-JWT tests hold it there). No
  package floor; coverage measured and reported.
- `security-analyst`: `credentials.py` **100%**; package TOTAL **96.92%**,
  satisfying the enforced `fail_under = 90` ("Required test coverage of 90.0%
  reached. Total coverage: 96.92%").

**Threshold policy result:** the only enforced numeric floor in scope —
`security-analyst`'s 90% — is **satisfied (96.92%)**. `dependency-update` and
`panel` have no enforced floor; both in-scope `credentials.py` files are 100%
and the in-scope panel components are at/near 100%.

---

## Path B — Structural gap analysis (always runs)

### In-scope source-to-test mapping

Every in-scope source file has a corresponding, executing test file:

| Source | Test(s) | Executed? |
| --- | --- | --- |
| `AuditReportPanel.tsx` | `AuditReportPanel.test.tsx` (33) | yes |
| `LiveLogViewer.tsx` | `live-log-viewer.test.tsx` (21) | yes |
| `RunDetailLogSection.tsx` | `RunDetailLogSection.test.tsx` (7) + `run-detail-page-wiring.test.tsx` (8) | yes |
| `dependency-update/credentials.py` | `test_credentials.py` (22) + `test_credentials_real_jwt.py` (2) | yes |
| `security-analyst/credentials.py` | `test_credentials.py` (22) + `test_credentials_real_jwt.py` (2) | yes |

No in-scope source file is wholly untested. No disproportionately-tested
in-scope surface (large module behind one case) was observed — the component
files carry 7–33 cases each.

### Risk notes

- `credentials.py` handles **authentication** (GitHub App RS256 JWT + Supabase
  key resolution) — highest-risk surface in scope; both copies at 100% line/branch.
  Standing caveat from `/TESTING.md` (not introduced by this batch): server-side
  JWT *rejection* cases are mocked at GitHub's token endpoint, so bad-assertion
  refusal is still not proven. The #252 `test_credentials_real_jwt.py` adds
  real-JWT exercise but does not close the server-side-rejection gap.
- `LiveLogViewer.tsx` line 204 is the only uncovered in-scope line (one branch
  of SSE handling); branch coverage 88%. Low risk, cosmetic/edge.

### Exclusions applied

- `agent_reporter.py`, `main.py`, `tests/*`, `.venv/*` — coverage-omitted per
  both agents' `pyproject.toml` `[tool.coverage.run] omit` (vendored SDK /
  entrypoint). Stated, not silently dropped.
- `pnpm-lock.yaml` churn and docs (`DESIGN.md`, `docs/technical-guidelines.md`,
  `package.json`, planner-state / tasks markdown) are not source and carry no
  coverage obligation.

---

## Structural gaps — pending on CI (NOT counted as covered)

Docker was unavailable locally, so the following could not run here and are
**pending-on-CI**, explicitly **not** counted as covered:

1. **E2E `run-detail-layout.spec.ts` (new, #244/#245)** — 0 scenarios executed
   locally. Playwright requires the real Supabase stack. **PENDING-ON-CI.**
2. **E2E `live-tail.spec.ts` (extended, #244)** — added scenarios not executed
   locally. **PENDING-ON-CI.**
3. **All 18 `tests/integration/*` Layer 2.5 suites** — skipped-with-reason
   (unreachable local Postgres). CI runs them with `REQUIRE_LOCAL_DB=1`, which
   converts any probe failure into a hard failure, so these cannot pass CI
   vacuously. **PENDING-ON-CI.**

These are the authoritative gate for the DOM-layout and live-tail behaviors the
component layer can only approximate under jsdom. The component layer (above)
covers the units; the E2E/integration layer remains CI-only in this environment.

---

## Artifact validation

No stale or scope-narrowed coverage artifact was consumed. All figures in this
report come from live runs performed in this session (panel `test:coverage`;
both agents' `make test-cov`), not from a committed report. No coverage database
or HTML report is committed in-scope.

## Coverage is not confidence

The panel component layer runs under jsdom and mocks SSE/`EventSource` and the
data layer. High per-component line coverage (100% on `AuditReportPanel`,
`RunDetailLogSection`; 99% on `LiveLogViewer`) demonstrates the rendering/branch
logic is exercised, but **does not** prove real-stack streaming or DOM-layout
behavior — that evidence lives in the Layer 2.5 / E2E suites listed as
pending-on-CI. Treat the measured panel numbers as unit-level confidence only.

---

## What was not analyzed, and why

- Layer 2.5 integration + E2E execution: **Docker daemon unavailable locally**
  — deferred to CI (`panel-quality` job, `REQUIRE_LOCAL_DB=1` + Playwright).
- `agentcore-cdk-app`: out of scope (not touched by this batch; no coverage
  tooling, per `/TESTING.md`).

---

## Summary

- In-scope auth surface (`credentials.py`, both agents): **100%**.
- `security-analyst` enforced floor (90%): **satisfied — 96.92%**.
- In-scope run-detail components: `AuditReportPanel` **100%**,
  `RunDetailLogSection` **100%**, `LiveLogViewer` **99.05%** (line 204 only).
- All in-scope component/unit test files **passed** (not skipped).
- E2E (`run-detail-layout.spec.ts`, `live-tail.spec.ts` additions) and all 18
  Layer 2.5 suites: **pending-on-CI** (Docker unavailable) — not counted as
  covered.

coverage_gate: PASS
