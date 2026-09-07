# Implementation Plan - S-109 Run Detail (Issue #122)

> **Source:** [`user-stories-prd-agent-fleet-panel-v2.md`](user-stories-prd-agent-fleet-panel-v2.md) Story S-109 · Issue [#122](https://github.com/llipe/dev-tasks-agent-fleet/issues/122)
> **Scope:** single story, S-109 only. Read-only screen — no schema/data/API change (documented migration opt-out).
> **Dependencies (all merged):** S-104 (data layer + `effectiveStatus`), S-105 (Nocturne primitives incl. `LogLine`/`StatusPill`/`Tag`/`Breadcrumb`), S-106 (app shell).
> **Package manager:** `pnpm` (workspace root). Canonical scripts only.

## Context Notes

> - Agent-authored `run_events.message` and `run_artifacts.url` are **untrusted input** (spec §12, A10 SSRF/XSS). URL scheme validation before linking and inert text rendering (never `dangerouslySetInnerHTML`) are mandatory — these are the two required security-negative tests (#5, #6).
> - **AC14** is the criterion most likely to be missed: a `failed` run carrying a `pull_request` artifact must surface the link alongside the red pill, not hide it behind the failure state.
> - The data-layer read helpers already exist from S-104: `getRunById`, `getRunSteps`, `getRunEvents` (paged, honours the SD11 2,000-event cap under PostgREST `max_rows=1000`), `getRunArtifacts`. This story adds the **bounded log-window selector + "load earlier"** on top and the presentation layer.
> - The steps *panel* is deferred to v3; `run_steps` is read only to label log lines. Virtualization deferred to v3.
> - Keep an SSE mount point in the log-viewer markup so S-110 (#123) attaches without restructuring.

## Relevant Files

- `panel/app/runs/[id]/page.tsx` - Run Detail route; thin async server component, inline route-segment config (`force-dynamic`/`revalidate=0`/`fetchCache`), reads run/steps/events/artifacts, 404 on unknown id.
- `panel/components/run-detail/RunSummary.tsx` - Status pill (from `effective_status`), outcome tag, run ID, repository, metadata grid (DESIGN §4.2 / §5.3).
- `panel/components/run-detail/ArtifactLinks.tsx` - Pill links for `run_artifacts`, rendered on `failed` runs too (AC14), `rel="noopener noreferrer"`, `https:`-only.
- `panel/components/run-detail/LogViewer.tsx` - 4-column `LogLine` grid ordered by `seq`, level coloring, hover, `aria-live="polite"`, "load earlier" control, SSE mount point.
- `panel/components/run-detail/StateBanner.tsx` - Terminal-state banners for `timed_out` / `failed_to_start` (DESIGN §8.3) carrying reaper explanatory text.
- `panel/components/run-detail/*.module.css` - Token-only CSS Modules per component.
- `panel/lib/domain/artifact-url.ts` - Pure `https:`-only URL scheme validator.
- `panel/lib/domain/log-window.ts` - Pure most-recent-2,000 window selector + "load earlier" prior-window math.
- `panel/lib/supabase/queries.ts` - Add "load earlier" windowed events read if not covered by existing `getRunEvents`; otherwise unchanged.
- `panel/lib/format.ts` - Reuse existing DESIGN §7 formatters (timestamps, duration, run-id); extend only if a needed formatter is missing.
- `panel/tests/unit/artifact-url.test.ts` - URL scheme validation matrix (security-negative #5).
- `panel/tests/unit/log-window.test.ts` - 2,000-window selector + load-earlier math.
- `panel/tests/component/run-detail.test.tsx` - Summary, AC14 artifact-on-failed, inert-text XSS render (security-negative #6), `aria-live`, banner selection.
- `panel/tests/integration/run-detail-queries.test.ts` - Layer 2.5: seeded run w/ steps+events+`pull_request` artifact; 2,500-event run returns exactly the most-recent 2,000 in `seq` order.
- `TESTING.md` - Add S-109 test surface rows.
- `docs/technical-guidelines.md` - §9 `panel/` row + changelog entry (technical-writer at doc gate).

## Tasks

- [ ] 1.0 Implement Story S-109 - [#122](https://github.com/llipe/dev-tasks-agent-fleet/issues/122): Run Detail — summary, artifacts, bounded log viewer

  ### Branch & PR setup
  - [x] 1.1 Verify current branch is not `main`; create feature branch `story/S-109-run-detail` off the wave base (delegate naming/creation to `github-ops`).
  - [x] 1.2 After the first commit, open a **draft PR** targeting the wave base (delegate to `github-ops`); PR body via `--body-file`, includes `Closes #122`; title Conventional Commits (`feat: implement S-109 run detail`).
  - [x] 1.3 Sync issue #122 checklist with this task list (delegate to `github-ops`).

  ### Pure domain layer (test-first)
  - [x] 1.4 Write unit tests for `lib/domain/artifact-url.ts` first: accept `https:`; reject `http:`, `javascript:`, `data:`, relative, empty, whitespace-padded, and mixed-case scheme (`HTTPS:`); assert no throw on malformed input (returns unsafe, not error).
  - [x] 1.5 Implement `lib/domain/artifact-url.ts` — pure `isSafeArtifactUrl(url)` returning true only for a well-formed `https:` URL.
  - [x] 1.6 Write unit tests for `lib/domain/log-window.ts` first: most-recent-2,000 selection at 0 / 1 / 2000 / 2500 events; "load earlier" prior-window offset math; stable `seq` ordering; no duplication across windows.
  - [x] 1.7 Implement `lib/domain/log-window.ts` — pure window selector over `RunEventRow[]` bounded at 2,000 (SD11) plus prior-window computation for "load earlier".
  - [x] 1.8 Confirm/extend `lib/supabase/queries.ts` events read supports fetching an earlier window (offset beyond the newest 2,000); reuse existing paged `getRunEvents` where possible, add a windowed variant only if needed. Keep the SD11 cap on the recent end.

  ### Route & presentation
  - [x] 1.9 Create `app/runs/[id]/page.tsx` as a thin async **server component** with route-segment config declared **inline** (`dynamic="force-dynamic"`, `revalidate=0`, `fetchCache="force-no-store"` — Next.js ignores re-exported config, §12 convention); read run via `getRunById`, steps via `getRunSteps`, events via the bounded window, artifacts via `getRunArtifacts`; return `notFound()` (404) on unknown id.
  - [x] 1.10 Build `RunSummary.tsx` (+ `.module.css`): full-height layout, log region owns scroll, no outer scroll (DESIGN §4.2); status pill from `effective_status`, outcome tag, run ID (short uppercase mono), repository, metadata grid (queued/started/finished/duration/branch) using existing `lib/format.ts` formatters and `StatusPill`/`Tag` primitives.
  - [x] 1.11 Build `ArtifactLinks.tsx` (+ `.module.css`): render `run_artifacts` as pill links **including on `failed` runs** (AC14); `rel="noopener noreferrer"`; render a link only when `isSafeArtifactUrl(url)` is true, otherwise show inert text.
  - [x] 1.12 Build `LogViewer.tsx` (+ `.module.css`): 4-column grid (time/level/step/message) via `LogLine` primitive, ordered by `seq`, level coloring + hover; label lines with step names from `run_steps`; message column `pre-wrap` + `word-break: break-word`, never truncated (DESIGN §7.5); render message as **inert text** (never `dangerouslySetInnerHTML`); add `aria-live="polite"`; add "load earlier" control when earlier events exist; leave a stable SSE mount point for S-110.
  - [x] 1.13 Build `StateBanner.tsx` (+ `.module.css`): terminal-state banners for `timed_out` / `failed_to_start` (DESIGN §8.3) carrying the reaper's explanatory event text.
  - [x] 1.14 Wire components into the page; add focus handling; confirm token-only CSS (no hardcoded hex/font/spacing — Nocturne token-discipline gate).

  ### Tests (test-first / alongside)
  - [x] 1.15 Write component tests (`tests/component/run-detail.test.tsx`): each status/outcome pair in the summary; **AC14** — artifact pill appears on a `failed` run; **security-negative #6** — a message containing `<script>alert(1)</script>` renders as literal text; `aria-live` present on the log region.
  - [x] 1.16 Write Layer 2.5 integration tests (`tests/integration/run-detail-queries.test.ts`) against the local Supabase stack: seeded run with steps + events + a `pull_request` artifact returns expected shapes; a run with 2,500 events returns exactly the most-recent 2,000 in `seq` order.
  - [x] 1.17 Cover the edge-case matrix: zero events; one event; exactly 2,000; > 2,000 (load-earlier path); run with no repository; null `finished_at` on a terminal run; 8 KB message wraps without layout break; event with null `step_id`; `failed_to_start` run with no steps and no events (banner only).

  ### Acceptance-criteria verification
  - [x] 1.18 Verify AC1: `/runs/[id]` renders full-height, no outer scroll, log region owns scroll (component + manual).
  - [x] 1.19 Verify AC2: summary shows status pill (from `effective_status`), outcome tag, run ID, repository, metadata grid.
  - [x] 1.20 Verify AC3 + AC14: artifacts render as pill links including on `failed` runs, `rel="noopener noreferrer"`, `https:`-only (component + `artifact-url` unit tests, security-negative #5).
  - [x] 1.21 Verify AC4: log viewer is a 4-column grid ordered by `seq`, level coloring, hover, step-labeled lines.
  - [x] 1.22 Verify AC5: initial fetch bounded at most-recent 2,000; "load earlier" fetches the prior window (log-window unit + integration).
  - [x] 1.23 Verify AC6: terminal-state banners render for `timed_out` / `failed_to_start` with reaper explanatory text.
  - [x] 1.24 Verify AC7 (security-negative #6): messages render inert; HTML/script content displays literally, never executed.
  - [x] 1.25 Verify AC8: log region is `aria-live="polite"`.
  - [x] 1.26 Verify AC9: unknown run id renders 404.
  - [ ] 1.27 Manual/UI: open a real Phase 1 run from the live database (read-only), compare against `docs/prototype/`; confirm log region scrolls while page does not; record observed events-per-run for the SD11 sizing note.
  - [x] 1.28 Produce the acceptance-criteria → test-evidence mapping (AC1–AC9 incl. AC14) in the PR.

  ### Quality gates & closeout
  - [x] 1.29 Run tests: `pnpm run test` (unit + component) and `pnpm run test:integration` (Layer 2.5; if Docker unavailable, record `SKIPPED(<reason>)` per TESTING.md).
  - [x] 1.30 Run quality gates: `pnpm run lint`, `pnpm run format:check`, `pnpm run typecheck`, `pnpm run audit`; then `make validate` at repo root (both Python and JS/TS branches must pass).
  - [x] 1.31 Confirm `coverage_gate` for new modules (`artifact-url.ts`, `log-window.ts`, run-detail components) via `qa-engineer`; record PASS/FAIL/SKIPPED(reason).
  - [x] 1.32 Update `TESTING.md` with the S-109 test surface (Layer 1 artifact-url/log-window, Layer 2 run-detail, Layer 2.5 run-detail-queries).
  - [x] 1.33 `technical-writer` doc-drift check; update `docs/technical-guidelines.md` §9 `panel/` row + changelog. Note DESIGN §5.3 / §8.3 conformance reviewed.
  - [x] 1.34 Run `verifier` in **audit** mode against the delivered implementation; post the human-readable summary to issue/PR (mandatory, non-blocking on drift).
  - [x] 1.35 Convert PR from draft to ready for review; notify the user for review/merge. Do not close #122 until the PR is approved AND merged.
```

## Notes

- **Migration lifecycle: N/A** — read-only story, documented opt-out (no schema/data/API change).
- **Mandatory security-negative tests:** #5 (artifact URL scheme validation, task 1.4/1.20) and #6 (inert message rendering, task 1.15/1.24) must be present and passing before completion.
- **Forward-compatibility with S-110 (#123):** the log viewer keeps a stable SSE mount point (task 1.12) so the live-tail story attaches without restructuring.
