## Enable the Invoke action on the dashboard and the run-history screen

A small follow-up to Wave 4. The Invoke actions were rendered **disabled** by placeholder flags from Wave 3 (dashboard, task 2.11) and Wave 3 (run-history, task 3.8), because the invoke route did not exist yet. Wave 4 / S-113 shipped that route (`/agents/[slug]/invoke`, PR #143), so both flags are now stale and the buttons should link through.

There are **two independent entry points**, each with its own flag:
- the **dashboard** (`app/page.tsx`) — the per-agent Invoke action in all three variants + the ledger `Enter` shortcut;
- the **run-history screen** (`app/agents/[slug]/page.tsx`) — the header Invoke action and the empty-state "Invoke on one repo" CTA.

Both are flipped here.

### What changed

- **`panel/app/page.tsx`** — `INVOKE_ROUTE_AVAILABLE` flipped `false → true`; stale task-2.11 comments refreshed.
- **`panel/app/agents/[slug]/page.tsx`** — `INVOKE_ROUTE_AVAILABLE` flipped `false → true`; stale task-3.8 comment refreshed. *(Added after the first commit — this second flag was the reason `/agents/dependency-update`'s Invoke button was still disabled.)*
- **`panel/components/dashboard/DashboardClient.tsx`** — refreshed the `invokeRouteAvailable` prop doc (disabled path retained as a guard).
- **Tests:**
  - `dashboard.test.tsx` — enabled-path link assertion + negative.
  - `dashboard-page-wiring.test.tsx` (new) — asserts `app/page.tsx` passes `invokeRouteAvailable=true`.
  - `run-history-page-wiring.test.tsx` (new) — asserts `app/agents/[slug]/page.tsx` passes a real `invokeHref` so the CTA links to the invoke route.
  - Existing `DashboardClient` / `AgentHeader` / `RunHistoryTable` true/false coverage unchanged.
- **`workstream/tasks-prd-agent-fleet-panel-v2-wave4-plan.md`** — Wave 4 plan checkboxes marked complete; the three runtime/geometry-dependent items marked `[~]` with recorded rationale (1.17 + 1.27 + OQ2 → S-115; 2.18 geometry → S-114).

### Behavior

- Invoke is now enabled fleet-wide from both the dashboard and the run-history screen; all paths route through the already-shipped `/agents/[slug]/invoke` form.
- The disabled rendering paths are retained (props kept) so they stay exercisable and available as future route-gates.

### Testing

`pnpm run lint`, `format:check`, `typecheck` clean. `pnpm run test` green (627 passed / 9 Docker-gated skips). `pnpm run audit` clean (exit 0). No new dependencies.

### Migration lifecycle

**Not applicable** — flag flips, comment refreshes, tests, and a plan-doc update. No schema, data-model, or API change.

### Noted (not in this PR's scope)

Stray macOS-style duplicate files are tracked in the repo and are dead (no imports reference them): `panel/components/runs/{AgentHeader,RunHistoryRow,RunHistoryTable} 2.tsx` and `panel/lib/domain/run-row 2.ts`. They came in with S-108 and should be removed in a separate housekeeping change rather than bundled here.

### Scope note

This does **not** enable live invocation against the deployed runtime — that still needs real AWS credentials in the runtime environment and is S-115 territory. This only makes the buttons link to the (already shipped) invoke form route instead of rendering disabled.
