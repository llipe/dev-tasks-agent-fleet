# Implementation Plan - Issue #241: render `audit_report` artifact metadata on the run detail page

> Source: https://github.com/llipe/dev-tasks-agent-fleet/issues/241 (refined issue; no PRD).
> Scope: panel only (`panel/`). No agent changes, no schema changes, no migrations.
> Existing codebase (Next.js 16 / React, Vitest, Playwright). No Task 0.
>
> Note: `run_artifacts.metadata` is agent-authored and **untrusted** (panel spec §12 / security guard #5 applies to `url`; the same posture applies to every metadata field here). Render as text only — React's default escaping, never `dangerouslySetInnerHTML`, never a link built from metadata.
>
> Known shapes to support:
> - **security-analyst** (`agents/security-analyst/app/securityAnalyst/main.py` `build_audit_report()` / `build_fix_audit_report()`): `{ total_findings, by_bucket: { mechanical: [...], manual: [...], unscannable: [...] }, by_tool: {tool: n}, by_severity: {sev: n}, findings_before?, findings_after? }`, each finding `{ tool, bucket, rule_id, severity, file_path, line_start, line_end, message, cwe_or_category, remediation_kind?, reported_by? }`.
> - **dependency-update** (`agents/dependency-update`, "Audit Report"): a flat summary object with different keys — treat as **unknown shape** and render the generic key/value fallback.

## Relevant Files

- `panel/lib/domain/audit-report.ts` - NEW. Pure, framework-free parser: `parseAuditReport(metadata: Json | null): AuditReportView | null`. Recognizes the security-analyst shape, normalizes each finding into a row, tolerates missing/odd fields, returns `null` for unknown shapes. Also exports `flattenForFallback(metadata)` → `[key, string][]` for the generic view.
- `panel/tests/unit/audit-report.test.ts` - NEW. Layer 1 tests for the parser (both shapes, unknown, malformed, hostile strings, size caps).
- `panel/components/run-detail/AuditReportPanel.tsx` - NEW. Presentational, server-safe: summary line (total, by tool, by severity, before/after when present) + findings table (tool · severity · bucket · `file_path:line_start` · rule id · message), or the generic key/value fallback; empty state when `total_findings === 0`.
- `panel/components/run-detail/AuditReportPanel.module.css` - NEW. Token-only styles; reuses the semantic-table-on-CSS-grid pattern (`RunHistoryTable`) and §2 table header/row tokens.
- `panel/tests/component/AuditReportPanel.test.tsx` - NEW. Layer 2 tests: rows render, text-only rendering of hostile metadata, fallback for unknown shape, empty state, `pull_request` artifacts untouched.
- `panel/components/run-detail/ArtifactLinks.tsx` - MODIFY. `ArtifactView` gains `metadata: Json | null` (pill rendering unchanged).
- `panel/components/run-detail/RunSummary.tsx` (+ `.module.css`) - MODIFY. Renders `AuditReportPanel` for each `audit_report` artifact below the artifact pills.
- `panel/app/(panel)/runs/[id]/page.tsx` - MODIFY. `toArtifactView` passes `metadata` through.
- `panel/tests/component/run-detail-page-wiring.test.tsx` - MODIFY. Assert `metadata` is passed through and an `audit_report` renders its findings on the page.
- `panel/tests/component/run-detail.test.tsx` - VERIFY unchanged behavior (existing suite must still pass).
- `panel/tests/e2e/stale-and-artifact.spec.ts` - OPTIONAL. Extend with a seeded `audit_report` if the e2e harness supports seeding artifacts cheaply; otherwise skip with reason.
- `DESIGN.md` - MODIFY. §5.3 Run Detail: add the audit-report findings block to the summary spec + changelog row (rule 14: new visible element on an existing screen).
- `docs/` - technical-writer pass at the documentation gate (panel user-facing docs, if any, describing the run detail page).

## Tasks

- [x] 1.0 Implement Issue #241 - https://github.com/llipe/dev-tasks-agent-fleet/issues/241: render `audit_report` artifact metadata on the run detail page

  - [x] 1.1 Branch `issue/241-audit-report-artifact-viewer` off `main`; first commit = the parser test file (test-first) so the Draft PR (`Closes #241`) can open immediately.
  - [x] 1.2 Test-first: write `panel/tests/unit/audit-report.test.ts` covering — security-analyst shape → rows in bucket order (mechanical, manual, unscannable) with all columns; `findings_before`/`findings_after` surfaced when present and absent otherwise; `total_findings: 0` → empty view (not `null`); dependency-update-style / arbitrary object → `null`; non-object (`null`, string, array) → `null`; finding with missing optional fields → row with `—` placeholders, no throw; hostile strings (`<script>`, `javascript:` URLs, very long message) pass through untouched as strings; more than 500 findings → rows capped at 500 with `truncated: n`. Run `pnpm run test:unit` — confirm they fail for the right reason (module missing).
  - [x] 1.3 Implement `panel/lib/domain/audit-report.ts` to make 1.2 pass. Pure functions, no React, no `any` escaping the module; export `AuditReportView`, `FindingRow`, `parseAuditReport`, `flattenForFallback`, `MAX_ROWS`.
  - [x] 1.4 Test-first: write `panel/tests/component/AuditReportPanel.test.tsx` — renders one `<tr>` per finding with tool/severity/bucket/`path:line`/rule/message; summary line shows totals and before/after; `<script>alert(1)</script>` in a message renders as literal text (query the DOM: no `script` element, text present); unknown shape renders a `<dl>` key/value fallback with the raw keys; `total_findings: 0` renders the empty-state text; component receives only the artifact's `metadata` + `title` (no run status), mirroring `ArtifactLinks`' AC14 stance. Confirm failing.
  - [x] 1.5 Implement `AuditReportPanel.tsx` + `.module.css`: `<section aria-label="Audit report">`, `<table>` with `<caption>`/`<th scope="col">`, DESIGN §2 table header tokens (`500 10px uppercase .08em`) and row padding, mono font for `file_path:line` and rule id, severity rendered via the existing `Tag`/status tint tokens if a matching primitive exists (else plain text — do not invent a new variant); no `dangerouslySetInnerHTML`; row cap notice when `truncated > 0`.
  - [x] 1.6 Wire it: extend `ArtifactView` with `metadata`, pass through in `page.tsx` `toArtifactView`, render `<AuditReportPanel>` in `RunSummary` for each `audit_report` artifact (pills remain for all artifacts). Update `run-detail-page-wiring.test.tsx` to assert `metadata` reaches the summary and an `audit_report` finding's message is visible on the page. Run `pnpm run test`.
  - [x] 1.7 DESIGN.md: add the findings block to §5.3 Run Detail (summary → artifact pills → audit-report findings table) and a changelog row; confirm no new token or component variant was introduced (or document it if one was).
  - [x] 1.8 Verify Acceptance Criterion: an `audit_report` with security-analyst `by_bucket`/`by_tool` metadata renders a findings table with one row per finding (component test 1.4 + wiring test 1.6; manual: open `/runs/3cb5f3b6-870d-4042-bf64-43785a40ee54` against the linked project and see the two Gitleaks rows).
  - [x] 1.9 Verify Acceptance Criterion: messages and paths render as plain text — no HTML injection possible from metadata (component test 1.4 hostile-string case; manual: none needed).
  - [x] 1.10 Verify Acceptance Criterion: an `audit_report` with an unknown metadata shape renders a generic fallback, not an error (unit 1.2 + component 1.4; manual: open a `dependency-update` run with an "Audit Report" artifact).
  - [x] 1.11 Verify Acceptance Criterion: `pull_request` artifacts are unchanged (existing `ArtifactLinks`/`run-detail` tests unmodified and passing; wiring test asserts the PR pill still renders).
  - [x] 1.12 Verify Acceptance Criterion: component test covers ACs 1–3 and the existing `run-detail` tests still pass — AC→test mapping: AC1 → 1.4 "rows" + 1.6 wiring; AC2 → 1.4 hostile string; AC3 → 1.2 unknown-shape + 1.4 fallback; AC4 → 1.11; AC5 → `pnpm run test` green.
  - [x] 1.13 Run Tests: `pnpm run validate` in `panel/` (`lint`, `format:check`, `typecheck`, `test`, `audit`) — all green. Optional: extend `tests/e2e/stale-and-artifact.spec.ts` with a seeded `audit_report` if the harness supports it; otherwise record `SKIPPED(<reason>)`. — Result: `pnpm run validate` green (1175 tests); e2e extension SKIPPED(harness seeds runs/artifacts only via the integration Supabase project; the page-wiring component test already covers the artifact→page path). Manual: verified on the live dev server — `/runs/3cb5f3b6…` (security-analyst, 2 Gitleaks rows) and `/runs/aa61ba0f…` (dependency-update, key/value fallback + PR pill intact).
  - [x] 1.14 Completion gate: `qa-engineer` coverage/gap report (`coverage_gate`), `verifier` audit (post summary to the PR), `technical-writer` docs pass (delta + drift), memo outcome entry if `memo` is configured, then convert the Draft PR to Ready for Review.
