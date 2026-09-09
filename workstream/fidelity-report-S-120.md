# Fidelity Report — Story S-120 (Logout route and sidebar Log out affordance)

## Verdict

- **Overall fidelity: High**
- **Highest drift impact present: Minor**
- **Scope:** Story S-120 · issue #159 · PR #167 · branch `story/S-120-logout` · repo `llipe/dev-tasks-agent-fleet`
- **Mode:** Audit (grey-box) — cross-checked codebase, `/workstream` artifacts, test suite, and spec/PRD intent.
- **Migration:** documented opt-out (no schema/data-model change) — honored.

## What changed and why (plain language)

This story finishes the login/logout lifecycle for the operator panel. Before it, an operator could sign in but had no way to sign out from the UI.

Two things were delivered:

1. **A logout endpoint** at `POST /api/auth/logout`. Pressing "Log out" submits a plain HTML form to this address; the server ends the Supabase session, wipes the session cookies, and sends the operator to the login page. It is deliberately **POST-only** — a clickable GET link could be triggered by a browser prefetcher or a hostile page and log someone out without their intent. It is also **forgiving**: logging out when you're already logged out still just lands you on the login page instead of showing an error.
2. **A "Log out" button in the sidebar footer**, sitting between "System health" and the "Collapse" control, with a power-style icon. It only appears when you're actually signed in, and it shrinks to icon-only when the sidebar is collapsed.

A subtle but important safety property was preserved: the sidebar itself does no security work. Whether you're logged in is decided once, on the server, and handed to the shell as a simple yes/no flag — the shell never talks to the auth system directly. And the logout address is deliberately marked "public" in the gatekeeper so that a session that is *already expiring* can still be ended (a session-ending action must not require a perfectly valid session, or logout could get stuck).

Everything the story asked for is present, tested, and passing. The only observations are minor and intentional refinements beyond the letter of the story, plus a documentation nuance — none affects behavior.

## Per-AC results

| AC | Description | Codebase evidence | Workstream evidence | Test evidence | Result |
|----|-------------|-------------------|---------------------|---------------|--------|
| AC6-a | `POST /api/auth/logout` calls `signOut`, clears cookies, redirects to `/login` | `app/api/auth/logout/route.ts` — `POST` builds cookie-writable `createAuthServerClient`, `await signOut()`, `302 → /login` | Task 6.1, 6.8 `[x]` | `logout-route.test.ts` "calls signOut and redirects (302) to /login"; E2E logout scenario | **Pass** |
| AC6-b | `GET /api/auth/logout` does not exist as a route | route module exports only `POST`; no `GET` | Task 6.9 `[x]` | `logout-route.test.ts` "does NOT export GET"; "exports POST" | **Pass** |
| AC6-c | Idempotent — no session still redirects to `/login` without error | `signOut` in try/catch, redirect emitted unconditionally | Task 6.8 `[x]` | `logout-route.test.ts` idempotent + "still redirects when signOut throws (never a 500)" | **Pass** |
| AC6-d | After logout, revisiting a protected route redirects to `/login` | middleware `getClaims()` fail-closed → 302 for `ui`; cookies cleared by route | Task 6.8, 6.13 `[x]` | E2E "re-gates protected routes" (goto `/` → `/login`) | **Pass** |
| AC15-a | Sidebar footer shows Log out below "System health" and above "Collapse", power-style Phosphor icon | `Sidebar.tsx` footer renders `<LogOutItem>` between System-health `DisabledNavItem` and Collapse toggle; `icons.tsx` `LogOutIcon = Power` | Task 6.4, 6.10 `[x]` | `LogOutItem.test.tsx` DOM-order (`compareDocumentPosition`) assertion; E2E visible | **Pass** |
| AC15-b | Icon-only when collapsed | `LogOutItem` hides `.label` when `collapsed`; `.collapsed` CSS single-column grid | Task 6.3 `[x]` | `LogOutItem.test.tsx` "icon-only when collapsed"; E2E collapsed edge | **Pass** |
| AC15-c | Absent when unauthenticated | `Sidebar.tsx` `{authenticated && <LogOutItem/>}` | Task 6.10 `[x]` | `LogOutItem.test.tsx` "does NOT render Log out when unauthenticated" | **Pass** |
| BR/AC | AppShell/Sidebar remain presentational — no Supabase/auth I/O (SD2 preserved) | Shell components take `authenticated` as a prop; only `(panel)/layout.tsx` (server) calls `getClaims()` | Task 6.11 `[x]` | `panel-layout-wiring.test.tsx` (auth computed in layout, threaded as prop); shell tests pass plain props | **Pass** |
| AC | `pnpm run validate` passes | — | Task 6.15 `[x]` | Reported: `make validate` exit 0 (Python 452; panel 898; lint/format/typecheck/audit green); build green | **Pass** (trusted evidence) |

**Coverage: 9/9 ACs Pass. No Partial, no Fail.**

## Reachability contract — verified

Traced `middleware.ts` → `lib/auth/route-policy.ts`:

- `createMiddleware` calls `classifyRoute(request.nextUrl.pathname)` **first**, and `if (policy === "public") return NextResponse.next();` short-circuits **before** `createMiddlewareClient` or any `getClaims()` call.
- `classifyRoute` returns `"public"` for the **exact** paths `/login` and `/api/auth/logout`. `/api/auth/logout/extra` and `/api/auth/whoami` fall through to `"api"` (unit-tested in `auth-route-policy.test.ts`).
- **Conclusion:** the public-classified logout POST reaches its handler even on an expiring/invalid session, and the exact-match narrowness means no read surface is widened. Contract holds. This is the correct design and is directly asserted by the route-policy unit tests.

## Drift catalog

All drift is **non-blocking** to PR/issue completion.

- **D1 — E2E "double-submit" edge case not directly exercised. Impact: Minor. Intent: Intended.**
  The story's Edge-Case Matrix lists "double-submit." The route's idempotency (try/catch + unconditional redirect) makes a double-submit safe by construction, and the unit suite covers the no-session/throwing paths that a second submit would hit, but there is no explicit E2E double-click scenario. Evidence: `auth.spec.ts` logout block covers click, re-gate, and collapsed-keyboard; not a rapid double-submit. Low risk — the behavior is provably idempotent server-side. Recommendation: `no action needed` (optionally note as a covered-by-construction edge).

- **D2 — `GET` returns 405, not a 404 "route does not exist." Impact: Minor. Intent: Intended.**
  AC wording is "`GET /api/auth/logout` does not exist as a route." Because the module exports only `POST`, Next.js serves a framework **405 Method Not Allowed** for `GET` on that path (not a 404). This fully satisfies the security intent (a GET cannot log out) and the test asserts the absence of a `GET` export directly. The literal phrase "does not exist" reads as 404 but the delivered (and correct) behavior is 405. Recommendation: `no action needed`; optional spec wording tightening to "GET does not log out (no GET handler)" → `product-engineer`.

- **D3 — Layout hardening beyond the stated `authenticated = !error && claims != null`. Impact: Minor. Intent: Intended.**
  The prompt describes `authenticated = !error && claims != null`; the implementation uses `data?.claims != null` (optional-chained on a possibly-null `data`) and verifies via `getClaims()` (not the spoofable `getSession()`), matching the S-117 posture. This is a strictly safer superset. Recommendation: `no action needed`.

- **D4 — DESIGN.md documents an accessibility detail (persistent "Log out" accessible name in both states) not called out in the story ACs. Impact: Minor. Intent: Intended.**
  `LogOutItem` keeps `aria-label="Log out"` when collapsed so the icon-only control stays labeled; DESIGN §4.1 documents this. It is an over-delivery on accessibility, consistent with prior stories. Recommendation: `no action needed`.

## Edge-case & manual outcomes (from delivered tests + reported evidence)

- Already-expired session logout → 302 `/login` (unit: throwing/no-session; middleware fail-closed). **Pass.**
- Collapsed + keyboard activation (Enter on submit button) → POST → `/login` (E2E). **Pass.**
- `GET` to logout path → no logout (no `GET` export; framework 405). **Pass** (see D2).
- Unauthenticated → Log out absent; Collapse still present (component). **Pass.**

## Recommendations (per item, no changes applied)

- D1 → `no action needed` (idempotency covers it by construction; optional E2E double-submit if desired).
- D2 → optional spec wording clarification → `product-engineer` (405 vs "does not exist").
- D3, D4 → `no action needed` (safe/beneficial over-delivery).

No `developer` fix is required. No spec gap blocks completion. Drift findings, if any write-back is desired, route to `product-engineer`'s `activity-drift-reconciliation` flow.
