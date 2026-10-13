# Implementation Plan - CI audit gates (#252) and run-detail follow-ups (#245, #244)

> Planner batch: one integration branch, merged in the order 1.0 → 2.0 → 3.0 (D-09). #217 (Next 16.4.0 upgrade) is a **separate planner run that starts immediately after** this batch (D-09). Sources: `workstream/issue-252-fix-deps-audit-gates-refinement.md`, `workstream/issue-245-run-detail-unscrollable-summary-refinement.md`, `workstream/issue-244-run-detail-refresh-on-terminal-refinement.md`, `workstream/decisions-run-detail-followups-and-audit.md`.

## Relevant Files

- `package.json` - root `pnpm.overrides` (sharp, source-map-js, fast-uri)
- `pnpm-lock.yaml` - regenerated after the overrides
- `agents/dependency-update/app/dependencyUpdate/pyproject.toml` - PyJWT pin
- `agents/security-analyst/app/securityAnalyst/pyproject.toml` - PyJWT pin + semgrep bump 1.177.0→1.180.0 (semgrep ≤1.178.0 pins pyjwt~=2.13.0, blocking the 2.15.1 pin)
- `agents/dependency-update/app/dependencyUpdate/credentials.py` - `jwt.encode` caller (verify only)
- `agents/security-analyst/app/securityAnalyst/credentials.py` - `jwt.encode` caller (verify only)
- `agents/*/agentcore/` - deployed-state hash after the redeploy
- `panel/components/run-detail/AuditReportPanel.tsx` - `<details>` disclosure
- `panel/components/run-detail/AuditReportPanel.module.css` - disclosure styling, 40vh scroll cap
- `panel/components/run-detail/RunDetailLogSection.module.css` - 240px `min-height` floor
- `panel/components/run-detail/LiveLogViewer.tsx` - refresh-on-terminal effect (or mount point)
- `panel/components/run-detail/RunRefreshOnTerminal.tsx` - optional new client component for the refresh effect
- `panel/lib/hooks/useRunStream.ts` - source of `closedReason` / `authStopped` (read only)
- `panel/tests/component/AuditReportPanel.test.tsx` - disclosure tests
- `panel/tests/component/RunDetailLogSection.test.tsx` - regression
- `panel/tests/component/live-log-viewer.test.tsx` - refresh wiring tests
- `panel/tests/component/run-detail-page-wiring.test.tsx` - already-terminal no-refresh test
- `panel/tests/e2e/stale-and-artifact.spec.ts` / `panel/tests/e2e/live-tail.spec.ts` - E2E for the layout and refresh
- `panel/tests/e2e/fixtures/seed.ts` - `seedArtifact` gains an optional `metadata` param (F-2)
- `panel/tests/e2e/fixtures/` - seeded 50-finding `audit_report` artifact
- `agents/*/app/*/tests/` - real-library JWT round-trip test TC-252-3a (F-1)
- `workstream/test-plan-issue-252-245-244.md` - verifier Design Mode plan (cited in every handoff)
- `DESIGN.md` - §5.3 disclosure rule plus changelog row
- `docs/roadmap.md` - batch row status (planner, consolidated PR)

## Tasks

- [ ] 1.0 Implement Issue #252 - https://github.com/llipe/dev-tasks-agent-fleet/issues/252: fix(deps): unblock the pnpm and pip-audit CI gates

  > Note: `next` is NOT touched here; its two moderate advisories belong to #217 (D-05, D-06). Run the panel audit under Node 22 (`engines: >=22 <25`); it refuses to run on Node 26.

  - [x] 1.1 [agents/dependency-update, agents/security-analyst] Reproduce: run `pip-audit . --strict` in both agent packages and record the PyJWT 2.13.0 findings (D-01)
  - [x] 1.2 [panel] Reproduce: run `pnpm --filter panel run audit` and `pnpm audit --prod --json` under Node 22 and record the blocking `sharp` / `source-map-js` advisories (D-01)
  - [x] 1.3 [agents/dependency-update] Pin `PyJWT==2.15.1` in `pyproject.toml`; reinstall `.[dev]` (D-06)
  - [x] 1.4 [agents/security-analyst] Pin `PyJWT==2.15.1` in `pyproject.toml`; reinstall `.[dev]` (D-06)
  - [x] 1.5 [agents/dependency-update, agents/security-analyst] Run the existing GitHub App credential tests (RS256 `jwt.encode`) and confirm they pass unchanged; if PyJWT 2.15 requires a change, keep it minimal and document it in the PR
  - [x] 1.5a [agents/dependency-update, agents/security-analyst] (verifier F-1) Add a real-library test, TC-252-3a, to each agent's `tests/`. Generate an RSA key with `cryptography`, call the real `credentials.py` signing path with `jwt` NOT mocked, then `jwt.decode` with the public key. Assert header `alg=RS256`, integer `iat`/`exp`, string `iss`, and `exp - iat == 600`. Prove the test bites by breaking the signing call locally before trusting it
  - [x] 1.6 [repo root] In root `package.json` `pnpm.overrides`, replace `sharp@<0.34.4 → 0.35.4` with `sharp@<0.35.5 → 0.35.5`; add `source-map-js@<1.2.2 → 1.2.2` and `fast-uri@<3.1.8 → 3.1.8` (D-06)
  - [x] 1.7 [repo root] Regenerate `pnpm-lock.yaml` (`pnpm install`); review that the diff touches only the overridden packages and their direct dependents
  - [x] 1.8 [panel] Run `pnpm --filter panel build` and confirm `sharp` 0.35.5 resolves a prebuilt binary; build `Dockerfile.panel` locally if Docker is available
  - [x] 1.9 Verify Acceptance Criterion AC1: `pnpm --filter panel run audit` exits 0; `pnpm audit --prod --json` shows no high/critical advisory, and only the two moderate `next` ones remain
  - [x] 1.10 Verify Acceptance Criterion AC2: `pip-audit . --strict` exits 0 in both agents (3.13 locally; 3.14 via the CI matrix)
  - [x] 1.11 Verify Acceptance Criterion AC3: agent credential tests pass on PyJWT 2.15.1
  - [x] 1.12 Verify Acceptance Criterion AC5: panel build succeeds; `pnpm run test:e2e` and the auth-gate parser test are unaffected
  - [x] 1.13 Run Tests: `make validate` (Python and JS/TS branches) passes; both CI jobs (`python-quality`, `panel-quality`) are green on the PR (AC4)
  - [x] 1.14 AC-to-test mapping: record AC1→panel audit step, AC2→pip-audit matrix, AC3→credential suites, AC4→`make validate`+CI, AC5→build+E2E, AC6→live invocation, in the PR body
  - [x] 1.15 Note on #217 that the two `next <15.5.27` advisories remain open pending the Next 16.4.0 upgrade (D-06)
  - [ ] 1.16 [agents/dependency-update, agents/security-analyst] **Post-merge, approval-gated:** hand off to `infra-engineer` to redeploy both agents with PyJWT 2.15.1 (`agentcore deploy -y`, per each agent's README "Deployment" section); the user approves before the deploy runs (D-10)
  - [ ] 1.17 Verify Acceptance Criterion AC6: a real invocation of each agent completes GitHub App auth and reaches a terminal status; record the new deployed-state hash and run ids on #252, then close #252 (D-10)

- [ ] 2.0 Implement Issue #245 - https://github.com/llipe/dev-tasks-agent-fleet/issues/245: fix(panel): run detail becomes unscrollable when the summary grows

  - [ ] 2.1 [panel] Write failing component tests first in `AuditReportPanel.test.tsx`: 10 rows → `<details open>`; 11 rows → closed; 50 rows → closed by default, toggles open, `open` attribute reflects the state, all 50 rows are in the DOM once open; the summary line is inside `<summary>` and always visible; `<caption>` and `th[scope=col]` are preserved (D-02, D-07)
  - [ ] 2.2 [panel] Add test cases: the zero-findings empty state and the generic fallback render with no disclosure; the "N more not shown." notice renders inside the open body
  - [ ] 2.3 [panel] Implement the `<details>`/`<summary>` wrapper in `AuditReportPanel.tsx`, with `open` server-set when rows ≤ 10; keep the component server-safe (no `"use client"`) and keep untrusted metadata as escaped text (D-02, D-07)
  - [ ] 2.4 [panel] In `AuditReportPanel.module.css`, cap the table's scroll container at `max-height: 40vh; overflow-y: auto`, set on the scroll container, not on `<details>`; style `<summary>` with existing §2 tokens and keep a visible focus ring (D-07)
  - [ ] 2.5 [panel] Add `min-height: 240px` to `.section` in `RunDetailLogSection.module.css` (D-07)
  - [ ] 2.3a [panel] (verifier F-3, confirmed by D-12) The default-open threshold uses **rendered rows** (`view.rows.length`), not `view.totalFindings`. Add test EC-245-2: `totalFindings=50`, 8 rows → open
  - [ ] 2.6 [panel] (verifier F-2) Extend `panel/tests/e2e/fixtures/seed.ts::seedArtifact` with an optional `metadata` JSON param (default `null`; existing callers unchanged), then add an E2E fixture: a run with a 50-finding `audit_report` artifact
  - [ ] 2.7 [panel] Add an E2E scenario at 1280×720: with the disclosure closed and open, the steps panel, log toolbar, and log viewer are visible, the log viewer scrolls, and the log section is ≥ 240px tall; if it fails with the table open, lower the cap (for example `min(40vh, …)`) and record the change in DESIGN.md
  - [ ] 2.8 [repo root] Update `DESIGN.md` §5.3: the disclosure, the 10-row default-open threshold, the 40vh cap, the 240px log-section floor; add changelog row 1.11
  - [ ] 2.9 Verify Acceptance Criterion AC1: no content is pushed off-screen at 1280×720 with 50 findings (E2E and manual)
  - [ ] 2.10 Verify Acceptance Criterion AC2: mouse and keyboard (Enter/Space) toggling; the expanded state is announced by a screen reader (manual); table semantics are intact
  - [ ] 2.11 Verify Acceptance Criterion AC3: boundary at 10/11 rows; the log section stays usable with the table open
  - [ ] 2.12 Verify Acceptance Criterion AC4: the empty state, fallback, and truncation notice are unchanged apart from the wrapper
  - [ ] 2.13 Verify Acceptance Criterion AC5: the new component tests pass; the existing `AuditReportPanel`, `run-detail`, and `RunDetailLogSection` tests pass
  - [ ] 2.14 Verify Acceptance Criterion AC6: the DESIGN.md §5.3 diff and changelog row are present
  - [ ] 2.15 Run Tests: `pnpm run lint`, `pnpm run format:check`, `pnpm run typecheck`, `pnpm run test`, `pnpm run test:e2e`, then `make validate`
  - [ ] 2.16 AC-to-test mapping: record AC1→E2E, AC2→component+manual, AC3→component+E2E, AC4/AC5→component, AC6→DESIGN.md review, in the PR body

- [ ] 3.0 Implement Issue #244 - https://github.com/llipe/dev-tasks-agent-fleet/issues/244: feat(panel): refresh run detail when a live run reaches a terminal state

  - [ ] 3.1 [panel] Write failing wiring tests first (fake timers, mocked `EventSource`, `vi.mock("next/navigation")` following the `Sidebar.test.tsx` pattern): `closed` frame → `router.refresh` is called exactly once after 500ms; a second `closed` or a stream error/reconnect → no extra call; `authStopped` → no call; unmount before 500ms → no call (D-08)
  - [ ] 3.2 [panel] Write a failing test in `run-detail-page-wiring.test.tsx`: an already-terminal render mounts no refresh effect and makes no `router.refresh` call
  - [ ] 3.3 [panel] Write a failing test: the step/level filter selected in `RunDetailLogSection` is still applied after the live viewer is replaced by `LogViewer` (D-03)
  - [ ] 3.4 [panel] Implement the refresh effect (in `LiveLogViewer` or a new `RunRefreshOnTerminal` client component mounted only on the live branch): trigger on `closedReason` becoming non-null, never on `authStopped`; a ref flag ensures one refresh per mount; a 500ms timer is cleared on unmount; no retry (D-08)
  - [ ] 3.5 [panel] Add an E2E scenario on the local stack: open a running run, drive it to terminal with artifacts (including an `audit_report`), and assert that within 5s the status pill, outcome tag, `finished` metadata, artifact pills, and findings summary line appear without a reload. Assert the summary line, not table rows, because #245's disclosure may be closed
  - [ ] 3.6 Verify Acceptance Criterion AC1: the summary updates within 5s of `closed` (E2E); manually watch a real `security-analyst` `audit_only` run to completion on the deployed panel
  - [ ] 3.7 Verify Acceptance Criterion AC2: an already-terminal run makes no refresh call and no extra server render
  - [ ] 3.8 Verify Acceptance Criterion AC3: at most one refresh per mount; errors, reconnects, and `authStopped` never trigger it
  - [ ] 3.9 Verify Acceptance Criterion AC4: the wiring test covers once-only, already-terminal, and unmount-before-debounce
  - [ ] 3.10 Verify Acceptance Criterion AC5: the filter state persists across the refresh
  - [ ] 3.11 Verify Acceptance Criterion AC6: the existing `run-detail`, `live-log-viewer`, `use-run-stream`, `run-detail-page-wiring`, and `stream-route` tests pass
  - [ ] 3.12 Run Tests: `pnpm run lint`, `pnpm run format:check`, `pnpm run typecheck`, `pnpm run test`, `pnpm run test:e2e`, then `make validate`
  - [ ] 3.13 AC-to-test mapping: record AC1→E2E+manual, AC2–AC5→component/wiring, AC6→existing suites, in the PR body

- [ ] 4.0 Batch close-out (planner)
  - [ ] 4.1 [repo root] In `docs/roadmap.md`, set the "Issue batch: CI audit gates + run-detail follow-ups" row to `Done` (or `In progress` if 1.17's redeploy is still pending), fill Issues/PRs, rewrite What's missing, and set Last updated
  - [ ] 4.2 Run the mandatory `verifier` audit over the batch; route drift findings to `product-engineer`
  - [ ] 4.3 Record `coverage_gate` via `qa-engineer`
  - [ ] 4.4 Hand off to the #217 planner run (Next 16.4.0 upgrade), which starts immediately after this batch merges (D-09)

## Decisions Consumed

| ID   | Decision (short form) |
| ---- | --------------------- |
| D-01 | Both gates fail; root causes are `sharp`/`source-map-js` via `next`, and PyJWT 2.13.0 |
| D-02 | #245 uses native `<details>`; the component stays server-safe |
| D-03 | The filter state persists across `router.refresh()`; a test asserts it |
| D-05 | The `next` advisories are fixed by the #217 Next 16.4.0 upgrade |
| D-06 | #252 = PyJWT 2.15.1 + transitive overrides, `next` untouched |
| D-07 | Open at ≤10 rows; 40vh cap; 240px log-section floor |
| D-08 | 500ms debounce, one refresh, no retry |
| D-09 | Batch order #252 → #245 → #244; #217 runs immediately after |
| D-10 | Post-merge redeploy of both agents; gates #252 closure |
| D-12 | #245 threshold counts rendered rows |
