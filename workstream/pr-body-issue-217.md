## What

Upgrade the panel to **Next.js 16.4.1** on **Node 26**, rename the auth
chokepoint `panel/middleware.ts` → `panel/proxy.ts` (Edge → Node runtime, with a
new 5s fail-closed `getClaims()` timeout), and migrate ESLint to
`eslint-config-next` 16's native flat config — fixing every lint finding with no
rule disabled or downgraded.

Closes #217 (sub-tasks 1.1–1.19; 1.20–1.21 are post-merge/human-only).

## Why

Next 15.5 carried two moderate advisories handed over by #252, and the repo's
Node pin (`>=22 <25`) rejected the maintainer's local Node. Next 16 also
deprecates `middleware` in favor of `proxy` on the Node.js runtime. The auth gate
is the panel's security boundary (ADR-007); the rename must preserve its behavior
verbatim (ADR-008).

## How

- **Pins (AC1):** `.nvmrc` ×2, `ci.yml` `setup-node`, `Dockerfile.panel`
  `ARG NODE_VERSION` → `26`; both `engines.node` → `>=24 <27` (fallback to 24
  needs no engines change, D-06). Exact companion pins per D-11/D-14.
- **`proxy.ts` (AC2, ADR-008):** `git mv` + the Next 16 `proxy` export; fail-closed,
  `getClaims()` never `getSession()`, identical matcher, the `internal` branch
  verbatim, SD2 — all preserved. New injectable 5s `getClaims()` timeout races a
  hung call to a fail-closed deny (D-15).
- **ESLint (AC4):** native flat config, `FlatCompat`/`@eslint/eslintrc` removed;
  SD2 `no-restricted-imports` block kept; every finding fixed (see ledger).
- **Docs (AC8):** ADR-008; `technical-guidelines.md` pin row; `panel/README.md`
  and runbook `middleware.ts` → `proxy.ts` + Node 26.

## Testing

- `make validate` (both branches) on Node 26.
- `pnpm --filter panel run test:e2e` against the local Supabase stack.
- Image smoke on `node:26-slim` with route assertions (`/`→302, `/login`→200,
  SSE→401, internal POST→401) + `node -v`=v26.
- verifier Audit Mode on the PR head; technical-writer drift check.

### AC-to-test mapping

| AC | Evidence |
| -- | -------- |
| AC1 | pin diff + CI `node -v` / Assert Node 26 step |
| AC2 | `proxy-gate` (retargeted) + `auth-route-policy` + `auth-no-getsession` + `internal-secret` + E2E `auth.spec.ts` + timeout tests |
| AC3 | `make validate` + `test:e2e` on Node 26 |
| AC4 | `lint` green, native flat config, `eslint-server-import` SD2 test |
| AC5 | image smoke (routes + uid 1001 + `node -v`) |
| AC6 | `pnpm --filter panel run audit` |
| AC7 | CDK member install + test on Node 26 |
| AC8 | ADR-008 + doc references |
| AC9 | post-merge release log + live invoke (human-only) |

### Overrides re-evaluation (D-05)

With the Next 16 tree, all five overridden packages resolve to safe versions
natively (sharp 0.35.5, source-map-js 1.2.2, fast-uri 3.1.8, postcss
8.5.23/8.5.26, vite 6.4.3). The overrides are therefore **redundant for the
current tree** but **retained as a regression floor** against a future transitive
downgrade, per D-05 ("keep unless the lockfile proves them redundant" — kept
conservatively; each is now a no-op pin).

### Lint fix ledger (D-08)

Every finding fixed; no rule disabled or downgraded. `react-hooks` v7 (brought by
`eslint-config-next` 16) added `purity`, `set-state-in-effect`, `refs`, and
`immutability`. 17 errors + 1 warning, all resolved:

| Rule | File(s) | Behavior-affecting? | Fix / test note |
| ---- | ------- | ------------------- | --------------- |
| `react-hooks/purity` | `app/(panel)/page.tsx`, `agents/[slug]/page.tsx`, `runs/page.tsx`, `runs/[id]/page.tsx`, `dev/gallery/page.tsx` (server) | No | Read the clock via `lib/time/render-instant.ts` `renderInstantMs()` instead of a bare `Date.now()` in the render body. Identical (one read per render). Covered by existing `*-page-wiring` tests. |
| `react-hooks/purity` | `NotificationsFeed.tsx`, `NotificationBell.tsx`, `SchedulesClient.tsx` (client) | No | Replaced `useMemo(() => Date.now(), [])` with a lazy `useState(() => renderInstantMs())` — captures once on mount, same value. Covered by `notifications-feed`/`schedules-table` tests. |
| `react-hooks/purity` | `LiveLogViewer.tsx` | No | `Date.now()` → `renderInstantMs()`; keeps the intentional per-render read. Covered by `live-log-viewer` tests. |
| `react-hooks/set-state-in-effect` | `components/dashboard/Ledger.tsx` | No | Derived the clamped selection during render instead of a setState-in-effect. Covered by `dashboard` tests (keyboard nav). |
| `react-hooks/set-state-in-effect` | `components/runs/RunFilterBar.tsx` | No | React "adjust state on prop change during render" (prev-prop tracker) instead of a sync effect. Covered by `RunFilterBar` tests. |
| `react-hooks/set-state-in-effect` | `AddRepositoryForm.tsx` | No | Prev-state-during-render against an identity-tracked action result. Covered by `AddRepositoryForm` tests. |
| `react-hooks/set-state-in-effect` | `RepositoryTable.tsx` | No | Derived dialog-open (closes on success during render); kept only `router.refresh()` in the effect. Covered by `RepositoryTable` tests. |
| `react-hooks/set-state-in-effect` | `DashboardClient.tsx` (density), `AppShell.tsx` (collapsed) | Yes (refactor, behavior preserved) | Replaced the mount-reconcile + persist effects with `lib/hooks/useLocalStorageState.ts` (`useSyncExternalStore`): server/first-client render = default (hydration-safe), reconcile to stored after, persist on change, cross-tab sync. New `tests/component/use-local-storage-state.test.tsx` (6 cases) + existing `AppShell`/`dashboard`/`density.spec.ts` E2E. |
| `react-hooks/refs` | `lib/hooks/useRunStream.ts` | No | Moved the `factoryRef` latest-value sync out of render into an effect. Covered by `use-run-stream` tests. |
| `react-hooks/immutability` | `lib/hooks/useRunStream.ts` | No | Recursive reconnect now hops through `connectRef` instead of a forward self-reference. Covered by `use-run-stream` reconnect tests. |
| `react-hooks/exhaustive-deps` | `AppShell.tsx` | No | Added the now-stable `setCollapsed` callback to the keydown effect deps. |
| `@typescript-eslint/no-unused-vars` | `tests/integration/schedule-mutations.test.ts` | No | Removed the unused `randomUUID` import. |

## Checklist

- [x] Conventional Commit title
- [ ] `make validate` green (both branches)
- [ ] E2E green on Node 26
- [ ] verifier Audit Mode posted
- [ ] technical-writer drift check
- [ ] ADR-008 added
