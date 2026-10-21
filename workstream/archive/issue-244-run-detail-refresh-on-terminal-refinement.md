# Issue Refinement: #244 - feat(panel): refresh run detail when a live run reaches a terminal state

## Changelog

| Version | Date       | Summary            | Author           |
| ------- | ---------- | ------------------ | ---------------- |
| 1.0     | 2026-10-13 | Initial refinement | product-engineer |

## Summary

- Goal: when a watched run finishes, re-render the server-rendered summary so that `finished_at`, the outcome, the artifact pills, and the audit-report findings appear without a manual reload.
- Primary user impact: the operator reviews findings on `/runs/<id>` at the moment the run ends, not after pressing F5.
- Non-goals: pushing summary data over the SSE channel; changing the stream route's `closed` frame contract; turning `RunSummary` into a client component.

## Refined Scope

- Add a client effect, either in `LiveLogViewer` or in a small sibling `RunRefreshOnTerminal` client component mounted by the live branch. When `useRunStream`'s `closedReason` becomes non-null, it waits 500ms and then calls `router.refresh()` from `next/navigation` exactly once per mount (D-08).
- One refresh, no retry. If the refreshed render still derives a non-terminal `effectiveStatus`, nothing further happens. After a terminal re-read, the page renders the terminal `LogViewer`, which has no stream, so there is no second trigger and no loop (D-08).
- The refresh never fires on `authStopped` (S-121 session-expired stop) or on stream errors and reconnects (S-110 AC4).
- The debounce timer is cleared on unmount, so navigating away within 500ms does not refresh a page that is no longer shown.
- The log step and level filter persists across the refresh: it is `useState` in `RunDetailLogSection`, which stays mounted. A test asserts this (D-03).

## Acceptance Criteria

- [ ] AC1: Given `/runs/<id>` open on a running run, when the stream emits the terminal `closed` frame (`succeeded`, `failed`, `canceled`, `timed_out`, `failed_to_start`), then the status pill, outcome tag, `finished` metadata, artifact pills, and audit-report findings block update without a manual reload within 5 seconds. Validation: Playwright E2E against the local stack, plus manual check on a real run.
- [ ] AC2: Given `/runs/<id>` opened on an already-terminal run, then no `router.refresh()` call and no extra server render occur. Validation: component/wiring test.
- [ ] AC3: The refresh fires at most once per mount; a second `closed`, a stream error or reconnect, or `authStopped` never triggers it. Validation: component test with a mocked `EventSource`.
- [ ] AC4: A wiring test where a mocked `EventSource` emits `closed` asserts `router.refresh` is called exactly once after 500ms (fake timers); a second `closed`/error does not call it again; an already-terminal render does not call it; unmounting before 500ms does not call it.
- [ ] AC5: The step and level filter selected before the refresh is still applied after the viewer swaps to `LogViewer`. Validation: component test (D-03).
- [ ] AC6: The existing `run-detail`, `live-log-viewer`, `use-run-stream`, and `run-detail-page-wiring` tests still pass.

## Constraints

- No change to the stream route or the `closed` frame contract.
- `router.refresh()` is the only mechanism; no polling.
- Mock `next/navigation` following the existing pattern (`tests/component/Sidebar.test.tsx`, `run-history-page-wiring.test.tsx`).

## Risks and Edge Cases

- A writer race (artifacts or `finished_at` not yet visible after 500ms) leaves a stale summary. This is accepted per D-08 (no retry); the operator can still reload.
- A run that becomes terminal through the reaper (`timed_out`) emits `closed` the same way, so it is covered by AC1.
- After #245, the refreshed summary may render the findings disclosure closed (more than 10 rows). The E2E assertion checks the summary line, not the table rows.

## Dependencies

- After #252 (green CI) and #245 (same page; the AC1 E2E asserts against the disclosure summary line).

## Testing Notes

- Unit/component: new wiring test (AC2–AC5) using fake timers and a mocked `EventSource` plus `next/navigation`.
- E2E: live-run-to-terminal scenario on the local stack (AC1).
- Manual: watch a real `security-analyst` `audit_only` run to completion on the deployed panel.
- AC-to-test mapping: AC1 → E2E and manual; AC2–AC5 → component/wiring; AC6 → existing suites.

## Decisions

| ID   | Decision (short form) |
| ---- | --------------------- |
| D-03 | The filter state persists across `router.refresh()`; a test asserts it |
| D-08 | 500ms debounce, exactly one refresh, no retry |

## Open Questions

- None.
