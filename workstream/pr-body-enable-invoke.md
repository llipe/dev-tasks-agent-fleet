## Enable the Invoke action on the dashboard

A small follow-up to Wave 4. The dashboard's Invoke action was rendered **disabled** by a placeholder flag from Wave 3 (task 2.11), because the invoke route did not exist yet. Wave 4 / S-113 shipped that route (`/agents/[slug]/invoke`, PR #143), so the flag is now stale and the button should link through.

### What changed

- **`panel/app/page.tsx`** — `INVOKE_ROUTE_AVAILABLE` flipped `false → true`; the two stale "does not exist yet / task 2.11" comments refreshed to state the route shipped.
- **`panel/components/dashboard/DashboardClient.tsx`** — refreshed the `invokeRouteAvailable` prop doc (the disabled path is retained and still test-covered as a guard, but the page now passes `true`).
- **Tests:**
  - `dashboard.test.tsx` — added an enabled-path assertion (Invoke renders as a `<Link href="/agents/dependency-update/invoke">` wrapping an enabled button) and its negative (no `/invoke` link when unavailable). The existing `true`/`false` `DashboardClient` coverage is unchanged.
  - `dashboard-page-wiring.test.tsx` (new) — renders `app/page.tsx` with the data layer mocked and asserts the page passes `invokeRouteAvailable=true`, so a future silent regression of the flag fails a test.
- **`workstream/tasks-prd-agent-fleet-panel-v2-wave4-plan.md`** — marked the Wave 4 plan checkboxes complete for the delivered work; the three runtime/geometry-dependent items are marked `[~]` with recorded rationale (1.17 + 1.27 + OQ2 → recorded BLOCKED for S-115; 2.18 geometry → deferred to S-114).

### Behavior

- Enabled path is fleet-wide across all three dashboard variants (dense/cards/ledger) and the ledger `Enter` shortcut, since they all route through the same `invokeHref`.
- The disabled rendering path is retained (prop kept) so it stays exercisable and available as a future route-gate.

### Testing

`pnpm run lint`, `format:check`, `typecheck` clean. `pnpm run test` green (626 passed / 9 Docker-gated skips). `pnpm run audit` clean (exit 0). No new dependencies.

### Migration lifecycle

**Not applicable** — a one-line flag flip, comment refresh, tests, and a plan-doc update. No schema, data-model, or API change.

### Scope note

This does **not** enable live invocation against the deployed runtime — that still needs real AWS credentials in the runtime environment and is S-115 territory. This only makes the dashboard button link to the (already shipped) invoke form route instead of rendering disabled.
