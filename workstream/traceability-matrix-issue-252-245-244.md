# Traceability Matrix — CI audit gates (#252) and run-detail follow-ups (#245, #244)

**Mode:** Design Mode (pre-implementation)
**Companion:** `workstream/test-plan-issue-252-245-244.md`

## Changelog

| Version | Date       | Summary                       | Author   |
| ------- | ---------- | ----------------------------- | -------- |
| 1.0     | 2026-10-13 | Initial AC → test mapping     | verifier |

**Coverage:** 18/18 ACs mapped to ≥1 positive and ≥1 negative/edge test. The `Result` column stays `—` until Audit Mode.

Test-case file targets: `TC-252-*` live in agent `tests/` or are CI/pipeline checks. `TC-245-*` live in `panel/tests/component/AuditReportPanel.test.tsx`, `RunDetailLogSection.test.tsx`, and `panel/tests/e2e/run-detail-layout.spec.ts` (new). `TC-244-*` live in `panel/tests/component/live-log-viewer.test.tsx`, `run-detail-page-wiring.test.tsx`, and `panel/tests/e2e/live-tail.spec.ts`.

| AC-ID | Task | Positive test-case(s) | Negative / edge test-case(s) | Observed result | Pass/Fail/Drift |
| --- | --- | --- | --- | --- | --- |
| AC-252-1 | 1.2, 1.6, 1.9 | SC-252-1 panel audit exit 0, only 2 moderate `next` advisories left | SC-252-1N revert `sharp` override → exit 1; EC-252-1 transport soft-pass is not AC evidence; CT-10 wrapper unchanged | — | — |
| AC-252-2 | 1.1, 1.3, 1.4, 1.10 | SC-252-2 pip-audit green ×4 matrix cells | EC-252-4 no new PyJWT deprecation warnings fail the suite | — | — |
| AC-252-3 | 1.5, 1.11 | TC-252-3a (new, F-1) real `jwt.encode` → `jwt.decode` round-trip: RS256 header, `iat`/`exp`/`iss`, 600s window, both agents; CT-1, CT-2 | CT-3 malformed PEM → `CredentialError`; existing mocked suites (insufficient alone, F-1) | — | — |
| AC-252-4 | 1.13 | SC-252-4 both CI jobs green | SC-252-4N audit log shows a real verdict, not a soft-pass; EC-252-2 frozen-lockfile install | — | — |
| AC-252-5 | 1.7, 1.8, 1.12 | SC-252-5 `next build` + Docker build + E2E + auth-gate parser green | EC-252-3 no downgrade, `pnpm why sharp` = 0.35.5 | — | — |
| AC-252-6 | 1.16, 1.17 | SC-252-6 real invocation of both agents passes GitHub App auth, hash recorded | SC-252-6N no access-token 401, rollback path; EC-252-5 image resolves PyJWT 2.15.1 | — | — |
| AC-245-1 | 2.4, 2.5, 2.7, 2.9 | SC-245-1 closed state, 50 findings at 1280×720: log visible and scrolls; SC-245-1b open state, no outer scroll | EC-245-4 5k-char unbroken message; EC-245-6 1280×600 viewport | — | — |
| AC-245-2 | 2.3, 2.10 | SC-245-2 Enter/Space toggle + focus ring; TC-245-2 `<caption>`/`th[scope=col]` preserved, summary line inside `<summary>` | EC-245-5 / RT-2 markup in metadata renders as text, one `details`/`summary` per report; manual screen-reader check | — | — |
| AC-245-3 | 2.1, 2.3, 2.11 | TC-245-3 10 rows → `open`; SC-245-3 3 findings open; RT-1 property over n ∈ [0,600] | EC-245-1 11 rows → closed; EC-245-2 total ≠ rows (F-3); EC-245-3 two reports; SC-245-1b log ≥240px; CT-9 600 findings | — | — |
| AC-245-4 | 2.2, 2.12 | TC-245-4 existing empty/fallback/truncation cases unchanged | SC-245-3N 0 findings → no `<details>`; CT-7 extra fields; CT-8 type mismatch → fallback; CT-9 truncation notice inside the body | — | — |
| AC-245-5 | 2.1, 2.13 | TC-245-5 50-row: default closed, toggle, `open` attribute, 50 rows in DOM | Existing `AuditReportPanel`, `run-detail`, `RunDetailLogSection` suites (regression) | — | — |
| AC-245-6 | 2.8, 2.14 | DESIGN.md §5.3 diff documents disclosure, 10-row threshold, 40vh cap, 240px floor | Changelog row 1.11 present; no new token or variant introduced (review) | — | — |
| AC-244-1 | 3.4, 3.5, 3.6 | SC-244-1 live → succeeded: summary updates ≤5s, no reload; SC-244-4 reaper-paused timed_out | EC-244-5 terminal by connect time; EC-244-7 / CT-4 `not_found` → 404; EC-245-7 disclosure state after refresh pinned; manual real-run check | — | — |
| AC-244-2 | 3.2, 3.7 | TC-244-2 already-terminal render mounts no refresh effect | SC-244-2 no RSC refresh request in 3s | — | — |
| AC-244-3 | 3.4, 3.8 | TC-244-3 exactly one refresh after `closed` | EC-244-3 double `closed`; EC-244-4 / SC-244-3 401 or `authStopped` → none; EC-244-6 failing server render → no storm; EC-244-2 no retry; CT-5 late frames; CT-6 empty reason; RT-3 random walk | — | — |
| AC-244-4 | 3.1, 3.9 | TC-244-4 fake timers: called once at ≥500ms, not at 499ms | EC-244-1 unmount at 499ms → none; RT-3 never before 500ms | — | — |
| AC-244-5 | 3.3, 3.10 | TC-244-5 step + level filter still applied after the viewer swap | SC-244-1b E2E filter persists across the real refresh | — | — |
| AC-244-6 | 3.11 | Existing `run-detail`, `live-log-viewer`, `use-run-stream`, `run-detail-page-wiring`, `stream-route` suites green | Stream route and `closed`-frame contract unchanged (diff shows no edit to `app/api/runs/[id]/events/stream/` or `lib/sse/`) | — | — |

## Design Findings Carried Into Audit

| ID | Summary | Impact | Intent | Route |
| --- | --- | --- | --- | --- |
| F-1 | #252 AC3 vacuous: credential tests mock `jwt` | Major | Unintended | Folded: task 1.5a |
| F-2 | `seedArtifact` cannot seed `metadata` | Minor | Unintended | Folded: task 2.6 |
| F-3 | #245 threshold input ambiguous (rows vs total) | Minor | Resolved | D-12 (rendered rows), task 2.3a |
