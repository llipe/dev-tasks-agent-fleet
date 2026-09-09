# Implementation Plan - Panel Password Authentication (Wave 1: Foundation)

**Scope:** S-116 (#155), S-117 (#156), S-118 (#157) — the auth foundation, the middleware gate, and the route-group restructure.
**Phase:** A (app stays private throughout).
**Source:** [`user-stories-panel-password-auth.md`](user-stories-panel-password-auth.md) · [`specification-panel-password-auth.md`](specification-panel-password-auth.md)

> Migration note: all three stories are a documented **migration opt-out** — no schema or data-model change. Auth state lives in Supabase's platform-managed `auth.*` schema and in browser cookies. The canonical migration and `supabase/seed.sql` are untouched, so no migration artifact, rollback note, apply-confirmation gate, or seed data applies to this wave.

## Relevant Files

- `panel/package.json` - Add pinned `@supabase/ssr` dependency
- `panel/lib/supabase/auth-env.ts` - Validate `NEXT_PUBLIC_SUPABASE_*`, throw named `AuthConfigError`
- `panel/lib/supabase/auth-server.ts` - Cookie-backed anon-key server client (`server-only`)
- `panel/lib/supabase/browser.ts` - Anon-key browser client
- `panel/lib/supabase/auth-middleware.ts` - Request/response cookie-threading client factory
- `panel/lib/supabase/server.ts` - MUST remain byte-unchanged (service-role data client)
- `panel/lib/auth/route-policy.ts` - Pure `classifyRoute(pathname)` → `public | ui | api`
- `panel/lib/auth/redirect.ts` - Pure, total `safeRedirectTarget(raw)`
- `panel/lib/auth/errors.ts` - Auth error taxonomy (spec §8.2)
- `panel/middleware.ts` - The single authorization chokepoint
- `panel/app/layout.tsx` - Stops wrapping `AppShell`
- `panel/app/(panel)/layout.tsx` - New authenticated layout owning `AppShell`
- `panel/app/(panel)/page.tsx` - Relocated dashboard
- `panel/app/(panel)/agents/**` - Relocated run-history routes
- `panel/app/(panel)/runs/**` - Relocated run-detail routes
- `panel/app/(panel)/dev/**` - Relocated dev-only routes
- `panel/tests/unit/auth-env.test.ts` - Env fail-fast tests
- `panel/tests/unit/auth-route-policy.test.ts` - Route classification table
- `panel/tests/unit/auth-redirect.test.ts` - Open-redirect rejection table
- `panel/tests/unit/auth-errors.test.ts` - Anti-enumeration mapping
- `panel/tests/unit/auth-no-getsession.test.ts` - AC8 grep guard
- `panel/tests/component/middleware-gate.test.ts` - Gate behavior with injected fake client
- `panel/README.md` - Document new env vars

## Tasks

- [x] 1.0 Implement Story S-116 - https://github.com/llipe/dev-tasks-agent-fleet/issues/155: Auth client foundation and pure policy modules

  > Note: No user-visible change. Security-relevant pure functions are built and exhaustively tested before anything depends on them. Rule SA1: auth logic never uses the service-role client; data queries never use the auth clients.

  - [x] 1.1 Verify `@supabase/ssr` latest stable version is audit-clean, then pin it in `panel/package.json` and run `pnpm install` (do NOT add the deprecated `@supabase/auth-helpers-nextjs`)
  - [x] 1.2 Create `panel/lib/supabase/auth-env.ts` with `AuthConfigError` and validation of `NEXT_PUBLIC_SUPABASE_URL` + `NEXT_PUBLIC_SUPABASE_ANON_KEY`, following the existing `readSupabaseEnv` fail-fast pattern
  - [x] 1.3 Create `panel/lib/supabase/auth-server.ts` — cookie-backed anon-key server client with `import "server-only"`
  - [x] 1.4 Create `panel/lib/supabase/browser.ts` — anon-key browser client, no service-role reference
  - [x] 1.5 Create `panel/lib/auth/route-policy.ts` — pure `classifyRoute(pathname)` returning `public | ui | api`, unknown paths default to `ui` (fail-closed)
  - [x] 1.6 Create `panel/lib/auth/redirect.ts` — pure, total `safeRedirectTarget(raw)` per spec §8.1 rules, never throws, always returns a local path
  - [x] 1.7 Create `panel/lib/auth/errors.ts` — the spec §8.2 error table with identical messaging for unknown-email and wrong-password
  - [x] 1.8 Document `NEXT_PUBLIC_SUPABASE_URL` and `NEXT_PUBLIC_SUPABASE_ANON_KEY` in `panel/README.md` and local `.env.local` guidance
  - [x] 1.9 Write `tests/unit/auth-env.test.ts` — missing, blank, and malformed URL each throw `AuthConfigError`
  - [x] 1.10 Write `tests/unit/auth-route-policy.test.ts` — `/login`→public; `/`, `/agents/x`, `/runs/y`→ui; `/api/**`→api; `/api/auth/logout`→api; unknown→ui
  - [x] 1.11 Write `tests/unit/auth-redirect.test.ts` — reject `//evil.com`, `https://evil.com`, `http://x`, `javascript:alert(1)`, `/\evil`, newline/control chars, `/login` loop, empty/null/undefined; preserve valid path+query+hash
  - [x] 1.12 Write `tests/unit/auth-errors.test.ts` — unknown-email and wrong-password produce an identical user-facing message; no raw Supabase text leaks
  - [x] 1.13 Edge-case validation: empty string, whitespace-only, `undefined`, unicode/percent-encoded redirect payloads, very long path, encoded `%2F%2F`
  - [x] 1.14 Verify Acceptance Criterion: `@supabase/ssr` pinned and `pnpm run audit` green at `--audit-level=high`
  - [x] 1.15 Verify Acceptance Criterion: `auth-server.ts` exports a cookie-backed anon server client carrying `import "server-only"`
  - [x] 1.16 Verify Acceptance Criterion: `browser.ts` exports an anon-only browser client with no service-role reference
  - [x] 1.17 Verify Acceptance Criterion: `auth-env.ts` throws named `AuthConfigError` on missing/blank/malformed values
  - [x] 1.18 Verify Acceptance Criterion: `classifyRoute` is pure and fail-closed on unknown paths
  - [x] 1.19 Verify Acceptance Criterion: `safeRedirectTarget` is total, never throws, only returns same-origin relative paths
  - [x] 1.20 Verify Acceptance Criterion: unknown-email and wrong-password are indistinguishable
  - [x] 1.21 Verify Acceptance Criterion: `lib/supabase/server.ts` byte-unchanged — run `git diff --exit-code panel/lib/supabase/server.ts`
  - [x] 1.22 Map each AC to its test evidence and record the mapping in the issue
  - [x] 1.23 Run Tests: `pnpm run test:unit`, then `pnpm run validate` (lint, format:check, typecheck, test, audit)
  - [x] 1.24 Manual verification: `pnpm run build` succeeds
  - [x] 1.25 Update issue #155 checklist and mark the story complete

- [ ] 2.0 Implement Story S-117 - https://github.com/llipe/dev-tasks-agent-fleet/issues/156: Middleware auth gate (the chokepoint)

  > Note: Two failure modes to avoid — (a) using `getSession()` for authorization (its user object is not re-validated, therefore spoofable), and (b) discarding the refreshed-cookie response, which causes intermittent logouts. Depends on Task 1.0.

  - [ ] 2.1 Create `panel/lib/supabase/auth-middleware.ts` — client factory threading a single response object so refreshed cookies land on both request and response
  - [ ] 2.2 Create `panel/middleware.ts` with the spec §7.2 matcher excluding `_next/static`, `_next/image`, favicon, and image assets
  - [ ] 2.3 Wire `classifyRoute` and short-circuit `public` routes before any auth work
  - [ ] 2.4 Verify identity with `getClaims()` (never `getSession()`); branch to `302` for `ui` and `401` JSON for `api`
  - [ ] 2.5 Return the cookie-handler response on success so refreshed tokens reach the browser
  - [ ] 2.6 Treat any auth-call error as unauthenticated (fail-closed)
  - [ ] 2.7 Make the client factory injectable so the gate is testable without live Supabase (same DI posture as `lib/sse/relay.ts`)
  - [ ] 2.8 Write `tests/component/middleware-gate.test.ts` — no session + UI → 302 with correct `redirect` param; no session + `/api/...` → 401 JSON; valid session → pass-through preserving cookies; auth error → unauthenticated; expired session → denied
  - [ ] 2.9 Write `tests/unit/auth-no-getsession.test.ts` — grep guard proving no authorization path calls `getSession()`
  - [ ] 2.10 Edge-case validation: deeply nested path; path with query + hash; `/api` exactly; static asset not gated; concurrent requests sharing a near-expiry token (refresh must not thrash); malformed/garbage cookie
  - [ ] 2.11 Verify Acceptance Criterion (AC1): unauthenticated UI route → `302` to `/login?redirect=<encoded path>`
  - [ ] 2.12 Verify Acceptance Criterion (AC2): unauthenticated `/api/**` incl. SSE path → `401` with `content-type: application/json`, never an HTML redirect
  - [ ] 2.13 Verify Acceptance Criterion (AC8): authorization uses `getClaims()`; no `getSession()` in any authz path
  - [ ] 2.14 Verify Acceptance Criterion (AC7): authenticated request passes through with refreshed auth cookies preserved
  - [ ] 2.15 Verify Acceptance Criterion (AC14): a session past the 12h inactivity window is denied (302 UI / 401 API), asserted via an expired/invalid cookie rather than waiting
  - [ ] 2.16 Verify Acceptance Criterion: fail-closed on unexpected auth errors
  - [ ] 2.17 Map each AC to its test evidence and record the mapping in the issue
  - [ ] 2.18 Manual verification: with no session, visit `/` → lands on `/login?redirect=%2F`; run `curl -i localhost:3000/api/runs/<uuid>/events/stream` → `401` JSON
  - [ ] 2.19 Run Tests: `pnpm run test:unit`, `pnpm run test`, then `pnpm run validate`
  - [ ] 2.20 Update issue #156 checklist and mark the story complete

- [ ] 3.0 Implement Story S-118 - https://github.com/llipe/dev-tasks-agent-fleet/issues/157: Route-group restructure for login layout

  > Note: A pure mechanical restructure — any behavioral difference is a defect. Route-group parentheses do not appear in URLs, so the unmodified E2E suite is the regression proof. Rejected alternative: conditionally rendering `AppShell` by pathname (a server layout cannot read the pathname reliably and it would reintroduce the S-106 hydration concern).

  - [x] 3.1 Create `panel/app/(panel)/` and move `page.tsx`, `agents/`, `runs/`, `dev/` into it, leaving `app/api/` in place
  - [x] 3.2 Create `panel/app/(panel)/layout.tsx` rendering `AppShell`
  - [x] 3.3 Strip `AppShell` from `panel/app/layout.tsx`, keeping `<html>`/`<body>`, fonts, metadata, and global CSS imports
  - [x] 3.4 Preserve inline route-segment config (`dynamic`/`revalidate`/`fetchCache`) verbatim in every moved page — never re-export it
  - [x] 3.5 Fix `@/` alias imports and relative CSS-module imports broken by the move
  - [x] 3.6 Update test import paths only (no test logic changes)
  - [ ] 3.7 Edge-case validation: dev gallery still 404s in production; SSE route still streams; unknown-run-id `not-found` behavior unchanged
  - [ ] 3.8 Verify Acceptance Criterion: all four route trees relocated with content otherwise unchanged
  - [ ] 3.9 Verify Acceptance Criterion: `(panel)/layout.tsx` renders `AppShell`; root layout no longer does
  - [ ] 3.10 Verify Acceptance Criterion: every existing URL resolves as before (`/`, `/agents/[slug]`, `/runs/[id]`, `/api/...`)
  - [ ] 3.11 Verify Acceptance Criterion: inline route-segment config preserved verbatim
  - [ ] 3.12 Verify Acceptance Criterion: the SD2 ESLint rule still applies to the moved tree — `tests/unit/eslint-server-import.test.ts` passes
  - [ ] 3.13 Verify Acceptance Criterion: full existing test suite and E2E suite pass unmodified except import paths
  - [ ] 3.14 Map each AC to its test evidence and record the mapping in the issue
  - [ ] 3.15 Manual verification: visit `/`, an agent run-history page, and a run detail page — all render identically with the shell intact
  - [ ] 3.16 Run Tests: `pnpm run build`, `pnpm run test`, `pnpm run test:e2e`, then `pnpm run validate`
  - [ ] 3.17 Update issue #157 checklist and mark the story complete

- [ ] 4.0 Wave 1 completion gate

  - [ ] 4.1 Confirm all three issue checklists (#155, #156, #157) are fully checked and mirrored locally
  - [ ] 4.2 Run the full aggregate gate from the repo root: `make validate` (Python branch + JS/TS branch must both pass)
  - [ ] 4.3 Confirm `pnpm run test:e2e` passes with the gate active (E2E must authenticate or target public routes as appropriate)
  - [ ] 4.4 Confirm the app is still private — no `fly.toml` change and no public IP was introduced in this wave
  - [ ] 4.5 Record `coverage_gate` result (PASS / FAIL / SKIPPED with non-empty reason) from the `qa-engineer` pass
  - [ ] 4.6 Run `verifier` in audit mode against the delivered implementation and post the summary to the issues/PR (mandatory, non-blocking on drift)
  - [ ] 4.7 Run `technical-writer` drift/stale-doc check and resolve any unresolved drift
  - [ ] 4.8 Convert the PR from draft to ready for review and notify the user for approval and merge into `main`
