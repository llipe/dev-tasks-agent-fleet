# Implementation Plan - S-110 SSE Relay and Live Log Tail (Issue #123)

> **Source:** [`user-stories-prd-agent-fleet-panel-v2.md`](user-stories-prd-agent-fleet-panel-v2.md) Story S-110 · Issue [#123](https://github.com/llipe/dev-tasks-agent-fleet/issues/123)
> **Scope:** single story, S-110 only. Adds the server SSE relay + client live-tail on top of the S-109 run-detail screen. Read-only story — no schema/data/API-table change (documented migration opt-out; the SSE endpoint is a new *route*, not a data-model change).
> **Dependencies (all merged):** S-109 (#122 — run-detail screen, `LogViewer` with the `data-sse-mount="run-log"` hook + `aria-live="polite"`), S-104 (data layer, `effectiveStatus`, `getRunEvents`), S-105 (primitives).
> **Wave:** first story of the post-S-109 sequence (S-110 → S-114 → S-115).
> **Package manager:** `pnpm` (workspace root). Canonical scripts only.

## Context Notes

> - **Why a relay and not a browser subscription:** RLS is deny-all (D11) and there is no browser Supabase client / no `NEXT_PUBLIC_SUPABASE_*` (SD2, F2). The **server** holds the service-role connection, subscribes to Supabase Realtime, and re-publishes over SSE. The browser only ever talks to our own route.
> - **Gap-free by `seq`, not timestamp (SD6):** the agent buffers (D5), so arrival order ≠ emission order. The resume cursor and dedupe are on `seq`. Backfill `seq > after_seq` happens **first**, then the live subscription opens, and any pushed row at or below the highest `seq` already sent is dropped — no duplicate, no gap.
> - **`effectiveStatus` on the push path (SD4/AC5):** a Realtime `run` push carrying `status='running'` must never overwrite a derived `timed_out`. Recompute through the shared `lib/domain/status.ts` `effectiveStatus`, never trust the raw pushed column.
> - **Subscription-leak is the top operational risk (SR5):** the server-side subscription MUST be unsubscribed on request `abort`, and open/close MUST be logged as a pair (`run_id`, last `seq`) so an imbalance is visible.
> - **S-109 left the seams:** `LogViewer` already has `data-sse-mount="run-log"`, `aria-live="polite"`, and a `seq`-ordered `dedupeBySeq`. S-110 extends `LogViewer`'s props to accept a live stream + auto-scroll; it does not restructure the markup.
> - **Auto-scroll is DESIGN §6.6:** append-scroll only when within 24px of the bottom; scrolling up pauses and shows the paused state; clicking "live tail" resumes and re-scrolls. The 24px threshold is a pure predicate, unit-tested at 0/23/24/25px.
> - **Reuse, don't reinvent:** backfill uses the existing `getRunEventsInRange`/`getRunEvents`; the `run_events` row → `LogLineView` projection reuses `buildLogLines` (S-109). Do not duplicate the shaper.

## Relevant Files

- `panel/lib/sse/cursor.ts` - Pure backfill-then-push dedupe/cursor reducer (`SeqCursor` + `dedupeAndOrder`): tracks highest `seq` sent, drops overlaps, monotonic cursor. The heart of SD6. **(added)**
- `panel/lib/sse/serialize.ts` - Pure SSE frame serializer/parser (`event:`/`data:`/`\n\n`) for the four event types; newline-safe. **(added)**
- `panel/lib/sse/autoscroll.ts` - Pure auto-scroll threshold predicate (within 24px of bottom → follow) per DESIGN §6.6. **(added)**
- `panel/lib/sse/relay.ts` - Dependency-injected relay core (`createStreamResponse`, `RealtimeLike`, `StreamDeps`, `isTerminalStatus`): backfill→subscribe→dedupe sequencing (SD6), heartbeat, `closed`, abort cleanup, SR5 open/close log pair. Free of Next.js/Supabase specifics so it is unit-testable. **(added; replaces the planned `lib/supabase/realtime.ts` — the Supabase channel wrapper lives inline in the route adapter, and the injectable core is what made the relay testable and the integration test reuse it)**
- `panel/app/api/runs/[id]/events/stream/route.ts` - `GET` SSE route handler (first `app/api/**` route): inline route-segment config (`force-dynamic`/`revalidate=0`/`fetchCache`/`runtime="nodejs"`), `parseAfterSeq` (coerce-to-0), backfill via `getRunEventsAfterSeq`, server-side Supabase Realtime subscription wrapper, structured open/close log. **(added)**
- `panel/lib/hooks/useRunStream.ts` - Client `EventSource` hook: highest-`seq` tracking, reconnect with `after_seq` on unexpected drop, stop after `closed`, forwards raw `run` status (viewer derives). Guards a missing `EventSource`. **(added)**
- `panel/components/run-detail/LiveLogViewer.tsx` - Client live viewer: joins `useRunStream` to the S-109 LogLine grid, derives live status via `effectiveStatus` (AC5), DESIGN §6.6 auto-scroll/pause/resume, inert message render. **(added; the S-109 server `LogViewer` is unchanged — the page selects LiveLogViewer for live runs and LogViewer for terminal runs, preserving "load earlier")**
- `panel/components/run-detail/LiveTailButton.tsx` + `.module.css` - Live/paused pill (DESIGN §6.6: green pulsing dot when following, muted when paused), token-only CSS. **(added)**
- `panel/components/run-detail/LogViewer.module.css` - **Modified:** added the `.liveBar` rule.
- `panel/app/runs/[id]/page.tsx` - **Modified:** selects LiveLogViewer (live) vs LogViewer (terminal) via `effectiveStatus`.
- `panel/lib/supabase/queries.ts` - **Modified:** added `getRunEventsAfterSeq` (unbounded, `integer`-safe backfill — no `MAX_SAFE_INTEGER` ceiling, which overflows the `seq` `integer` column, a bug caught by the live Layer 2.5 run).
- `panel/tests/unit/{sse-cursor,sse-serialize,autoscroll,after-seq}.test.ts` - Layer 1 (incl. RT-1/RT-2/RT-3 property tests). **(added)**
- `panel/tests/component/{stream-route,use-run-stream,live-log-viewer}.test.tsx` - Layer 2. **(added)**
- `panel/tests/component/run-detail-page-wiring.test.tsx` - **Modified:** added the live-run LiveLogViewer wiring assertion.
- `panel/tests/integration/stream-e2e.test.ts` - Layer 2.5, **ran live** (insert-after-open, exactly-once, seq-ordered). **(added)**
- `TESTING.md` - Add the S-110 test surface rows (qa-engineer at the closeout gate).
- `docs/technical-guidelines.md` - §9 `panel/` row + changelog entry (technical-writer at the doc gate).

## Tasks

- [ ] 1.0 Implement Story S-110 - [#123](https://github.com/llipe/dev-tasks-agent-fleet/issues/123): SSE relay and live log tail

  ### Branch & PR setup
  - [x] 1.1 Verify HEAD is not `main`; create feature branch `story/S-110-sse-live-tail` off the latest `main` (delegate naming/creation to `github-ops`).
  - [x] 1.2 After the first commit, open a **draft PR** targeting `main` (delegate to `github-ops`); PR body via `--body-file`, includes `Closes #123`; title Conventional Commits (`feat: implement S-110 SSE relay and live log tail`).
  - [x] 1.3 Sync issue #123 checklist with this task list (delegate to `github-ops`).

  ### Pure SSE core (test-first — this is where gaps/dupes come from, Impl Step 1)
  - [x] 1.4 Write unit tests for `lib/sse/cursor.ts` first: backfill emits `seq > after_seq` ascending; a push at or below the highest sent `seq` is dropped; an out-of-order push is placed by `seq`; a duplicate `seq` is dropped; a `seq` regression never rewinds the cursor; property test — the merged output is strictly `seq`-monotonic with no gap and no duplicate across a randomized backfill+push interleaving (seeded, replayable).
  - [x] 1.5 Implement `lib/sse/cursor.ts` — the pure reducer holding `highestSeqSent`, deciding accept/drop for each candidate row and computing the resume `after_seq`.
  - [x] 1.6 Write unit tests for `lib/sse/serialize.ts` first: each of the four event types serializes to a valid SSE frame (`event:` line + `data:` JSON + terminating blank line); a message with embedded `\n` is framed as multiple `data:` lines and round-trips; `closed` carries `{ reason }`.
  - [x] 1.7 Implement `lib/sse/serialize.ts` and `lib/sse/types.ts` (the `StreamEvent` union shared by serializer/route/hook).
  - [x] 1.8 Write unit tests for `lib/sse/autoscroll.ts` first: `shouldFollow(distanceFromBottom)` is true at 0/23/24px and false at 25px (DESIGN §6.6 boundary); pausing/resuming is a pure state transition.
  - [x] 1.9 Implement `lib/sse/autoscroll.ts` — the threshold predicate + follow/pause state helper.

  ### Server relay (Impl Step 2)
  - [x] 1.10 Implement `lib/supabase/realtime.ts` — a thin server-side subscription wrapper over Supabase Realtime for `run_events` and `runs` filtered by `run_id`, returning an explicit `unsubscribe()` handle (mockable; no Next.js imports).
  - [x] 1.11 Implement `app/api/runs/[id]/events/stream/route.ts` (`GET`): inline route-segment config (`dynamic="force-dynamic"`, `fetchCache="force-no-store"`, `runtime="nodejs"` — the service-role client is server-only, SD2/§12 convention); parse `after_seq` (integer, default 0, reject non-integer); **backfill `seq > after_seq` first** via the existing query layer, then open the Realtime subscription, dedupe pushes through `lib/sse/cursor.ts`, emit `event`/`run`/`heartbeat`(15s)/`closed`; recompute `run` status through `effectiveStatus` before emitting (SD4/AC5); build the body as a `ReadableStream`.
  - [x] 1.12 Register cleanup on `request.signal`'s `abort`: call `unsubscribe()` and close the stream; log the open/close as a pair with `run_id` and last `seq` (SR5, spec §13). Emit `closed` with `{ reason }` when the run reaches a terminal effective status.

  ### Client hook + component wiring (Impl Steps 3–5)
  - [x] 1.13 Implement `lib/hooks/useRunStream.ts` — `EventSource` against the stream URL; track the highest rendered `seq`; on `event` append (via the caller's dedupe), on `run` recompute status through `effectiveStatus`, on `closed` stop reconnecting, on unexpected drop reconnect with the highest rendered `seq` as `after_seq`.
  - [x] 1.14 Modify `components/run-detail/LogViewer.tsx`: add an optional live-stream mode (props for the stream URL + initial highest `seq` + whether the run is terminal); append pushed `LogLineView`s through the existing `dedupeBySeq`; keep `data-sse-mount="run-log"` and `aria-live="polite"`; preserve the existing "load earlier" behavior unchanged. A terminal run renders static (no stream opened).
  - [x] 1.15 Build `components/run-detail/LiveTailButton.tsx` (+ token-only `.module.css`): green pulsing dot + "live" text while following (reuse the `pulse` keyframe / `StatusDot` conventions), muted "paused" state when scrolled up; clicking resumes and re-scrolls to bottom (DESIGN §6.6).
  - [x] 1.16 Wire auto-scroll into `LogViewer` using `lib/sse/autoscroll.ts`: follow on append when within 24px of the bottom; scrolling up sets paused; the `LiveTailButton` resume re-scrolls and clears paused.
  - [x] 1.17 Modify `app/runs/[id]/page.tsx` (minimal): pass the stream URL and the run's terminal-ness into `LogViewer`; a run that is already terminal at load does not open a stream (immediate static render). Confirm token-only CSS (Nocturne token-discipline gate).

  ### Tests (test-first / alongside)
  - [x] 1.18 Write component tests (`tests/component/stream-route.test.ts`) with Supabase + Realtime mocked: backfill precedes push; dedupe across the backfill/push boundary; `closed` emitted on terminal status; heartbeat cadence (~15s, use fake timers); **unsubscribe called on `abort` (SR5)**; the open/close log pair is emitted with `run_id` + last `seq`; and the `useRunStream` client reconnects with the correct `after_seq` after a drop.
  - [x] 1.19 Write the Layer 2.5 integration test (`tests/integration/stream-e2e.test.ts`) against the local Supabase stack: open the stream on a seeded run, insert `run_events` after the stream is open, assert every inserted event arrives exactly once in `seq` order (SD6). Docker-gated; **state in the PR whether it ran live or `SKIPPED(<reason>)`**.
  - [x] 1.20 Cover the edge-case matrix: run already terminal at connect (immediate `closed`, no subscription opened); `after_seq` beyond the highest existing `seq` (no backfill, subscription only); unknown run id (404 before streaming); two concurrent clients on one run (two independent subscriptions, both cleaned up); client disconnects mid-backfill (no leaked subscription — assert unsubscribe); a 2 KB single-line message (framed intact); a burst of 200 events in one flush (D5 buffering — all delivered, ordered, deduped).

  ### Acceptance-criteria verification
  - [x] 1.21 Verify AC1: `GET /api/runs/[id]/events/stream` returns `text/event-stream` and accepts `after_seq` (integer, default 0).
  - [x] 1.22 Verify AC2: backfill `seq > after_seq` precedes the subscription; pushes at/below the highest sent `seq` are dropped — no duplicate, no gap (cursor unit + integration).
  - [x] 1.23 Verify AC3: the four event types (`event`/`run`/`heartbeat`/`closed`) are emitted; heartbeat every 15s; `closed` carries `{ reason }`.
  - [x] 1.24 Verify AC4: the client stops reconnecting after `closed`; on an unexpected drop it reconnects with its highest rendered `seq` as `after_seq`.
  - [x] 1.25 Verify AC5: a `run` push carrying `status='running'` cannot overwrite a derived `timed_out` — status recomputed through `effectiveStatus` on the push path (SD4).
  - [x] 1.26 Verify AC6 (auto-scroll, DESIGN §6.6): appends scroll when within 24px of bottom; scrolling up pauses + shows paused state; clicking "live tail" resumes + re-scrolls (autoscroll unit + manual).
  - [x] 1.27 Verify AC7 (SR5): the server-side subscription is unsubscribed on `abort`; open/close logged as a pair with `run_id` + last `seq`. Record the subscription-leak check result.
  - [x] 1.28 Verify AC8 (PRD AC6): the Layer 2.5 `stream-e2e` test **ran live** against the local Supabase stack (Realtime) — events inserted after the stream opened arrived exactly once in `seq` order with no reload (the automated core of AC8). The browser scroll/pause/resume + network-kill reconnect are the S-114 Playwright scenario (PRD AC6); the DOM hooks (`data-sse-mount`, `aria-pressed` on the live-tail button) are in place for it.
  - [x] 1.29 Produce the acceptance-criteria → test-evidence mapping (AC1–AC8) in the PR.

  ### Quality gates & closeout
  - [x] 1.30 Run tests: `pnpm run test` (unit + component) and `pnpm run test:integration` (Layer 2.5; if Docker unavailable, record `SKIPPED(<reason>)` per TESTING.md). To run integration live: `eval "$(supabase status -o env | sed 's/^/export /')" && export SUPABASE_URL="$API_URL"` first.
  - [x] 1.31 Run quality gates: `pnpm run lint`, `pnpm run format:check`, `pnpm run typecheck`, `pnpm run audit`; then `make validate` at the repo root (both Python and JS/TS branches must pass).
  - [ ] 1.32 `qa-engineer` pass — confirm `coverage_gate` for the new modules (`lib/sse/*`, `lib/hooks/useRunStream.ts`, the route handler, `LiveTailButton`); record PASS/FAIL/SKIPPED(reason). Update `TESTING.md` with the S-110 test surface (Layer 1 sse-cursor/sse-serialize/autoscroll, Layer 2 stream-route, Layer 2.5 stream-e2e).
  - [ ] 1.33 `technical-writer` doc-drift check; update `docs/technical-guidelines.md` §9 `panel/` row + changelog (current-state, no new ADR expected — the relay-not-browser-subscription is the pre-existing SD2/SD6 decision). Note DESIGN §6.6 conformance reviewed.
  - [ ] 1.34 Run `verifier` in **audit** mode against the delivered implementation; post the human-readable summary to issue/PR (mandatory, non-blocking on drift).
  - [ ] 1.35 Convert PR from draft to ready for review; notify the user for review/merge. Do not close #123 until the PR is approved AND merged.

## Notes

- **Migration lifecycle: N/A** — no schema/data-model change. A new SSE *route* is added; documented opt-out.
- **Mandatory security-negative anchor:** SD2 boundary — assert in a test that the stream route path never constructs a browser/anon client and never emits `NEXT_PUBLIC_SUPABASE_*`; the service-role Realtime connection is server-only (Node runtime). Carry this as an explicit negative assertion in `stream-route.test.ts`.
- **Node runtime, not Edge:** the route MUST run on the Node.js runtime (service-role client + long-lived `ReadableStream`); declare `export const runtime = "nodejs"` inline.
- **Forward compatibility with S-114:** S-114 Scenario 2 (live tail) and Scenario 3 (reconnect, SD6) assert this story through Playwright. Keep the stream URL and the paused/live states inspectable from the DOM (stable `data-*` hooks) so the E2E scenarios attach without restructuring.
- **Deferred (recorded, not scope):** full reconciliation for long disconnects is v3 — the durable `seq` cursor is what makes that deferral safe (story Business Rules).
