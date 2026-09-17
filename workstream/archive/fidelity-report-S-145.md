# Verifier Audit (Audit Mode) — Story S-145

**Fidelity: High**
**Highest drift impact: Minor**

> Note: this report backfills a documentation-completeness gap flagged by
> `qa-engineer`'s PRD-scope coverage rollup
> (`workstream/coverage-report-prd-agent-fleet-panel-v3-ui-depth.md`): S-145
> was audited at merge time (PR #212 comment, posted by `developer` acting in
> `verifier`'s role because no separate subagent-invocation tool was available
> in that execution environment) but no `workstream/fidelity-report-S-145.md`
> file was ever written. This report is a genuine re-audit against the
> delivered code on `integration/panel-v3-ui-depth` @ `8bc29f4` — not a
> transcription of the PR #212 comment — though that comment's AC verdicts and
> drift findings were used as a starting hypothesis and independently
> re-verified against `panel/lib/domain/log-filter.ts`,
> `panel/lib/domain/run-detail.ts` (`buildStepsPanel`),
> `panel/components/run-detail/StepsPanel.tsx`,
> `panel/components/run-detail/RunDetailLogSection.tsx`,
> `panel/lib/hooks/useRunStream.ts`, and the corresponding
> `tests/unit/log-filter.test.ts`, `tests/component/StepsPanel.test.tsx`,
> `tests/component/RunDetailLogSection.test.tsx`, and
> `tests/component/live-log-viewer.test.tsx` files, plus a live
> `pnpm --filter panel run validate` run (see PRD rollup report for the full
> run transcript).

## Scope

Story S-145 (Run Detail — steps panel with step and log-level filtering),
issue #205, against `workstream/user-stories-prd-agent-fleet-panel-v3-ui-depth.md`
(S-145 section), `workstream/specification-prd-agent-fleet-panel-v3-ui-depth.md`
§8.2/§10/§16, and `docs/requirements/prd-agent-fleet-panel-v3-ui-depth.md`
FR9–FR11.

## Acceptance criteria — evidence

| AC | Requirement | Verdict | Evidence |
|---|---|---|---|
| AC1 (FR9) | Steps panel renders each `run_steps` row: colored status dot, mono step name, duration, event count | **Pass** | `StepsPanel.tsx` line ~54 renders `<StatusDot status={step.status} .../>` reusing the existing `StatusDot`/`statusMeta` mapping (no new color logic); `lib/domain/run-detail.ts::buildStepsPanel` builds the row shape from `run_steps` + a caller-supplied event-count map; `StepsPanel.test.tsx` (8 tests) |
| AC2 (FR10) | Clicking a step filters the log viewer to that step's events only (`run_events.step_id` match); "All steps" clears the filter | **Pass** | `lib/domain/log-filter.ts::applyLogFilter` filters on `(line.stepId ?? null) !== stepId`; `RunDetailLogSection.tsx` owns `{ stepId, level }` state and renders an "All steps" control that resets `stepId` to `null`; `log-filter.test.ts` (14 tests, incl. unknown-`stepId` → empty result, not a crash) |
| AC3 (FR11) | Level filter narrows independently of the step filter; both compose | **Pass — as a documented implementation-shape decision** | `applyLogFilter` implements `level` as a **severity threshold** (`debug < info < warn < error`; selecting `"warn"` keeps `warn`+`error`), not an exact-match filter — verified directly in `lib/domain/log-filter.ts` lines 11–16/32–36. This resolves a genuine type-level ambiguity in the story's own Technical Notes (`{ level: LogLevel \| "all" }` plus only the prose example "errors and warnings only," which is itself a compound/threshold selection, not a spec for exact-match semantics). See Drift #1. Composition confirmed: both `stepId` and `level` predicates are applied together in one `filter()` pass, never mutually exclusive. |
| AC4 | Identical behavior on `LogViewer` (terminal) and `LiveLogViewer` (live); step/level click does not break autoscroll/pause-resume | **Pass** | `LogViewer.tsx`/`LiveLogViewer.tsx` both gained an optional `filter` prop defaulting to `NO_LOG_FILTER` (backward-compatible — confirmed no existing pre-S-145 call site/test needed updating for the default); `lib/hooks/useRunStream.ts` line 33/97 carries `step_id` onto live-appended lines so the step filter composes with the SSE tail; `tests/component/live-log-viewer.test.tsx`'s dedicated `describe("LiveLogViewer — step/level filter composition with live tail (Story S-145, AC4)")` block (confirmed present at line 316) tests default backward-compat, a step filter hiding a live-appended line for a different step, autoscroll preserved for the filtered-in step, and a combined step+level composition |
| AC5 | Live-run event counts may under-count until the SSE tail catches up (documented, non-blocking) | **Pass** | No test asserts an under-count as correct behavior (confirmed by inspection — no such assertion exists in `StepsPanel.test.tsx`/`RunDetailLogSection.test.tsx`); documented in the story's own Business Rules and in `docs/technical-guidelines.md` changelog row 1.38 per the PR description |

All 5 story-level ACs (plus the FR9/FR10/FR11 numbered variants): **Pass**.

## Business rules verified

- `run_steps.status` (not `effective_status`) drives the steps-panel dot color — confirmed directly: `StepsPanel.tsx` reads `step.status` (the raw `run_steps` column), never `v_runs.effective_status`. Matches the story's stated rationale (steps are not reaper-computed the way run-level status is).
- No `dangerouslySetInnerHTML` introduced — confirmed by inspection of `StepsPanel.tsx`, `RunDetailLogSection.tsx`, and the unchanged `LogLine` renderer; log message rendering remains an inert text node (security guard #6 preserved).

## Drift

Three items, all classified **Minor / Intended**:

1. **Level-filter semantics is an implementation-shape decision, not literally specified.** The story's Technical Notes give only the type signature and one compound example; "severity threshold" vs. "exact match" was genuinely underspecified at the story level. Resolved as a severity threshold to match the PRD's own example literally ("errors and warnings only" implies both, i.e. at-or-above `warn`). Documented in the PR description and `docs/technical-guidelines.md` row 1.38. This is a reasonable, disclosed interpretation of an ambiguous spec, not a deviation from a clear requirement.
2. **Two files beyond the story's own "Files to Create/Modify" list were required and added:** `components/run-detail/RunDetailLogSection.tsx` (+ `.module.css`) and a change to `lib/hooks/useRunStream.ts`. Both are directly entailed by the story's own ACs/Technical Notes prose (the Technical Notes describe "a small filter-state wrapper... a `use client` parent owning state" without itemizing the file, and AC4's live-tail composition structurally requires `step_id` to propagate through the SSE hook) — confirmed by re-reading the story text and the delivered files side-by-side; this is scope entailed by the story's own acceptance criteria, not unrequested scope expansion.
3. **Test file paths deviate from the story's colocated suggestion** (e.g., `panel/lib/domain/log-filter.test.ts` in the story's file list) to the codebase's actual convention (`tests/unit/`, `tests/component/`, per `vitest.config.ts`'s `include` globs) — confirmed the delivered test files live under `tests/unit/log-filter.test.ts` and `tests/component/StepsPanel.test.tsx`/`RunDetailLogSection.test.tsx`, not colocated. This is the same drift class already precedented for S-144, and follows the codebase's actual established convention rather than the story's own colocated suggestion — a correction toward consistency, not a regression.

No Critical or Major drift. No Unintended drift — every item is either an entailed necessity, a defensible resolution of a genuinely ambiguous spec point, or a correction toward the codebase's existing test-location convention.

## Quality gates

Re-run live in this audit session (not trusted from the PR description alone): `pnpm --filter panel run validate` on `integration/panel-v3-ui-depth` @ `8bc29f4`, Node 22.23.2, local Supabase stack up —
`lint: PASS`, `format:check: PASS`, `typecheck: PASS`,
`test: 100 files / 1205 tests passed, 1 file / 4 tests skipped (the pre-existing, unrelated `RUN_BUNDLE_SECRET_TEST=1`-gated suite)`,
`audit: PASS`. This story introduces no new Layer 2.5 integration tests (correct per its own Technical Notes — both filters are client-side-only reducers over an already-loaded window, no new server read), consistent with the "Integration Tests: None new (no new server read)" line in the story's own Testing Requirements.

## Manual verification

Not independently re-performed in this audit session (this pass is a grey-box code/test audit, not a fresh manual click-through). The PR #212 comment records a manual pass against the real local Supabase stack: a seeded `failed` run with two `run_steps` and five mixed-level `run_events`, read back through the actual `getRunSteps`/`getRunEvents` path, confirming `buildStepsPanel`/`applyLogFilter` produce the expected shapes (event counts 2/3, step-filter narrowing, step+level composition, "All steps" full-tail restore). This is carried forward as recorded manual evidence, not independently re-executed browser verification.

## Known limitations (not drift — documented risk acceptance)

- Live-run event counts may under-count until the SSE tail catches up — explicitly accepted per spec §16, not a bug (AC5).
- No new Playwright E2E spec was added for this story (`run-detail-steps.spec.ts`, named in `workstream/test-plan-prd-agent-fleet-panel-v3-ui-depth.md` E2E-5/E2E-6, was never created). This is one instance of the PRD-wide 0/11 E2E finding — see the PRD-level rollup report (`workstream/fidelity-report-prd-agent-fleet-panel-v3-ui-depth-rollup.md`) for the aggregate judgment call; it is not re-litigated per-story here.
- No full interactive browser-based manual click-through was performed for this story, at merge time or in this audit pass, beyond the direct-data-layer manual validation recorded in the PR comment.

## Recommendation

No developer action required — all three drift items are Intended and non-blocking; recommended for `product-engineer`'s `activity-drift-reconciliation` PRD/spec changelog write-back (Drift #1's severity-threshold decision is worth confirming as the intended PRD semantics going forward, since the PRD/story prose itself was ambiguous). No action needed on Drift; this report itself is the remediation for the "missing fidelity report" gap the coverage rollup flagged.
