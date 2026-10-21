# Issue Refinement: #245 - fix(panel): run detail becomes unscrollable when the summary grows

## Changelog

| Version | Date       | Summary            | Author           |
| ------- | ---------- | ------------------ | ---------------- |
| 1.0     | 2026-10-13 | Initial refinement | product-engineer |

## Summary

- Goal: keep the run-detail contract from /DESIGN.md §4.2/§5.3 ("no outer scroll; the log viewer owns the scroll") by bounding the only part of the summary that can grow without limit: the audit-report findings table.
- Primary user impact: on a run with a large `audit_report`, the operator can still reach the steps panel, log toolbar, and log viewer.
- Non-goals: pagination or virtualization of findings; server-side findings filtering; changing `MAX_ROWS` (500); changes to artifact pills or `pull_request` artifacts; making the summary column its own scroll region.

## Refined Scope

- Wrap the findings table of `AuditReportPanel` in a native `<details>`/`<summary>` element (D-02). The summary line (`N findings`, per-tool and per-severity counts, before → after) is the `<summary>` content and is always visible. The component stays presentational and server-safe: no `"use client"`.
- Default state, server-rendered via the `open` attribute: open when the report has 10 rows or fewer, closed when it has more (D-07).
- When open, the table body is capped at `max-height: 40vh` with `overflow-y: auto`. The `<table>` keeps `<caption>` and `<th scope="col">` semantics (D-07).
- `RunDetailLogSection` `.section` gets `min-height: 240px` so the steps panel, toolbar, and viewer can never collapse to zero (D-07).
- The empty state ("No findings."), the generic key/value fallback, and the "N more not shown." notice keep their current rendering. The empty state and fallback get no disclosure, because they have no table.
- /DESIGN.md §5.3: document the disclosure, the 10-row default-open threshold, the 40vh cap, and the 240px log-section floor; add a DESIGN.md changelog row. Reuse existing tokens and the §2 typography; no new component variant.

## Acceptance Criteria

- [ ] AC1: Given `/runs/<id>` with an `audit_report` of 50 findings at a 1280×720 viewport, then the steps panel, log toolbar, and log viewer are visible, the log viewer scrolls, and nothing is pushed off-screen. This holds with the disclosure both closed and open. Validation: Playwright E2E with a seeded 50-finding artifact, plus manual check.
- [ ] AC2: The findings summary line is always visible; the table toggles with mouse and keyboard (Enter/Space on `<summary>`); the open/closed state is exposed natively (`<details open>`); the table keeps its `<caption>` and column-header semantics. Validation: component test plus manual keyboard and screen-reader check.
- [ ] AC3: Given a report with 10 rows or fewer, it renders open by default; given 11 or more rows, it renders closed by default. With the table open, the log section is still at least 240px tall. Validation: component test at the 10/11 boundary, plus E2E height assertion.
- [ ] AC4: Zero findings, the generic fallback, and the "N more not shown." notice render unchanged apart from the disclosure wrapper. Validation: existing `AuditReportPanel.test.tsx` cases still pass, plus a new case for the notice inside the open body.
- [ ] AC5: A component test with a 50-row report asserts the default closed state, toggling it, the `open` attribute, and that all 50 rows are in the DOM once open. The existing `AuditReportPanel`, `run-detail`, and `RunDetailLogSection` tests pass.
- [ ] AC6: /DESIGN.md §5.3 is updated and a changelog row is added.

## Constraints

- No outer page scroll (DESIGN.md §4.2). The S-110 AC6 auto-scroll/pause model of the log viewer must be unaffected.
- `AuditReportPanel` stays a server component (no client JS added).
- Untrusted-metadata guarantees (spec §12) unchanged: everything still renders as escaped text.

## Risks and Edge Cases

- At 720px height, the header, summary metadata, artifact pills, the open 40vh table (~288px), and the 240px log floor may together exceed the viewport. AC1 is the arbiter: if it fails with the table open, lower the cap (for example with `min(40vh, …)`), record the change in DESIGN.md, and note it in the PR.
- Multiple `audit_report` artifacts on one run: each gets its own disclosure, and the threshold applies per report.
- Exactly 10 rows → open; 11 → closed (boundary case under AC3).
- A table with `display: block` (current CSS grid pattern) inside `<details>`: the `max-height` must sit on the scroll container (tbody or a wrapper), not on `<details>` itself, so the summary line stays visible.

## Dependencies

- After #252 (green CI). Before #244, which touches the same page and reuses this disclosure in its refresh assertion.

## Testing Notes

- Unit/component: `tests/component/AuditReportPanel.test.tsx` (default state at 10/11/50 rows, toggling, `open`, row count, notice, empty state, fallback); `RunDetailLogSection.test.tsx` (no regression).
- E2E: Playwright run-detail spec with a 50-finding seeded artifact at 1280×720 (AC1, AC3 height floor).
- Manual: keyboard toggle and screen-reader announcement of the expanded state.
- AC-to-test mapping: AC1 → E2E; AC2 → component and manual; AC3 → component and E2E; AC4/AC5 → component; AC6 → DESIGN.md diff review.

## Decisions

| ID   | Decision (short form) |
| ---- | --------------------- |
| D-02 | Native `<details>`/`<summary>`; the component stays server-safe |
| D-07 | Open at ≤10 rows, closed above; 40vh cap; 240px log-section floor |

## Open Questions

- None.
