# Fidelity Report — Panel Password Authentication (PRD-level rollup, Phase A)

> Audit Mode · grey-box · PRD-level rollup across stories S-116…S-122 on branch
> `integration/v2.1-panel-auth`, before the consolidated PR to `main`.
> This audit is **additive and non-blocking**: drift does not block the PR handoff — it is
> routed to `product-engineer`'s drift-reconciliation flow. The audit itself was mandatory and ran.

## 1. Header / Verdict

| | |
| --- | --- |
| **Overall fidelity** | **High** |
| **Highest drift impact present** | **Minor** |
| **Drift findings** | **4** (0 Critical, 0 Major, 4 Minor) — all classified **Intended** |
| **Scope** | PRD `prd-panel-password-auth.md` (FR1–FR15, AC1–AC17), spec `specification-panel-password-auth.md`, stories S-116…S-122 |
| **Branch / integration** | `integration/v2.1-panel-auth` (7 story commits: S-116 #163, S-118 #164, S-117 #165, S-119 #166, S-120 #167, S-121 #168, S-122 #169) |
| **Phase B (S-123, go-public)** | **Correctly NOT present** — no public exposure shipped |
| **Verification** | 142 auth unit+component tests pass locally; `server.ts` byte-unchanged; no `NEXT_PUBLIC_` service-role exposure; `getSession()` absent from every authz path; `fly.toml` private-only; old privacy gate removed & replaced |

**One-line verdict:** the integrated Phase A auth boundary holds as designed — a single fail-closed
middleware chokepoint (`getClaims()`, 302-UI/401-API split, refreshed-cookie preservation), an
anti-enumeration login with server-side redirect sanitization, a POST-only idempotent logout, a
terminal-stop live-tail on 401, a URL-preserving route-group move, and an auth release gate that
*replaces* (not deletes) the privacy gate and mechanically blocks a public release unless auth is
enforcing and signups are disabled — with the app still private. The four Minor drifts are all
deliberate, documented design choices.

## 2. Human-Readable Summary (what changed and why)

The panel used to have no login at all; the only thing stopping a stranger from reaching it was that
it was never put on the public internet. This feature adds a real email-and-password login and makes
that login the thing standing between the internet and the panel.

The way it's built, there is exactly one "gate" that every request goes through. If you are not
signed in and you ask for a page, it sends you to the login screen; if you are not signed in and some
script or the live-log stream asks for data, it gets a flat "not authorized" instead of a confusing
web page. Signing in wrong tells you only "invalid email or password" — never whether that email
exists — so an attacker can't fish for valid accounts. After you sign in, the gate quietly keeps your
session fresh so you're not kicked out mid-work. Logging out is a deliberate button press (not
something a stray link can trigger) and always works, even if your session already went stale. If your
session expires while you're watching a live log, the log stops cleanly and tells you to sign in again
instead of hammering the server forever.

Two things were done carefully to avoid breaking what already worked. First, the pages were
reorganized so the login screen can appear without the app's sidebar — but every web address stayed
exactly the same, proven by the existing end-to-end tests still passing untouched. Second, the login
system was added *alongside* the existing data-reading machinery without changing it: the database
still refuses all direct row access, and signing a user in grants them no new data access — login
gates the door, it doesn't hand out keys.

Finally, there's an automatic safety check that must pass before the panel can ever go public. It
doesn't trust a checklist — it actually pokes the deployed app to confirm that an anonymous visitor is
turned away, that the live-stream is closed to anonymous requests, and — most importantly — that
nobody can self-register a new account. If any of those fail, the release is blocked. Crucially, this
feature ships that check while the app is *still private*; actually flipping the app to public is a
separate future step that was deliberately not taken here.

## 3. Per-AC Result Table (FR1–FR15 / AC1–AC17)

| ID | Description | Codebase evidence | Workstream evidence | Test evidence | Result |
| --- | --- | --- | --- | --- | --- |
| **FR1** | `@supabase/ssr` pinned; no deprecated helper | `package.json`, `@supabase/ssr` imports in `auth-*.ts` | S-116 ACs | audit gate green | **Pass** |
| **FR2** | Browser + server anon auth clients, distinct from service-role | `lib/supabase/{browser,auth-server}.ts` | S-116 report (implicit; no per-story report) | — | **Pass** |
| **FR3** | Middleware token refresh, cookie threaded to req+resp | `auth-middleware.ts` `setAll` mirrors both; `createMiddlewareClient` returns single response | S-117 | `middleware-gate` cookie-preservation case | **Pass** |
| **FR4 / AC1 / AC2** | Route gating: 302 UI / 401 API+SSE | `middleware.ts` `loginUrlFor`/`unauthorizedJson`; `route-policy.ts` | S-117 High | `middleware-gate` (20); E2E `auth.spec` | **Pass** |
| **FR5 / AC10** | Login page per Nocturne mockup, outside AppShell | `app/login/page.tsx`, `LoginForm.tsx`, `login.module.css`; `app/login/layout.tsx` shell-free | S-119 High; DESIGN §5.5 | `LoginForm` component suite | **Pass** |
| **FR6 / AC3** | Login action: signIn, set cookie, redirect | `app/login/actions.ts` `resolveSignIn`/`signIn` | S-119 | `login-action` (16); `auth-login` integration | **Pass** |
| **FR7 / AC6** | POST-only logout, clears cookie, → /login | `app/api/auth/logout/route.ts` (POST only, no GET export) | S-120 High | `logout-route` (5); E2E logout | **Pass** |
| **FR8 / AC8** | `getClaims()` not `getSession()` for authz | `middleware.ts` line 80; grep confirms no `getSession()` call anywhere | S-117 | `auth-no-getsession` (3) | **Pass** |
| **FR9 / AC15** | Sidebar Log out: below System health, above Collapse; icon-only collapsed; authed-only | `Sidebar.tsx` footer order; `LogOutItem.tsx`; `AppShell` `authenticated` prop | S-120 High; DESIGN §4.1 | `LogOutItem` + `panel-layout-wiring` | **Pass** |
| **FR10 / AC9** | `NEXT_PUBLIC_SUPABASE_*` env; service key stays server-only | `auth-env.ts` reads anon pair only; grep: no `NEXT_PUBLIC_` service-role | S-116 | `bundle-secrets` (CT-7) | **Pass** |
| **FR11 / AC4** | Redirect sanitized to same-origin, applied server-side | `redirect.ts` `safeRedirectTarget`; applied in action + page before use | S-116/S-119 | `auth-redirect` (25) | **Pass** |
| **FR12 / AC11** | Public exposure isolated; gate replaces privacy gate; app still private | `verify-panel-auth.sh` + `panel-auth-check.mjs`; `fly.toml` private-only; privacy gate removed | S-122 High | `panel-auth-check` (30) + CLI (4) | **Pass** |
| **FR13 / AC13** | Password SHOW toggle, `aria-pressed`, defaults masked, keyboard | `PasswordField.tsx` (`type="button"`, `aria-pressed`, `type` toggles) | S-119 | `LoginForm` toggle assertions; E2E AC13 | **Pass** |
| **FR14 / AC14** | 12h inactivity → denial (consequence testable) | Supabase project setting; middleware denies expired/invalid cookie | S-117 | `middleware-gate` expired-session case | **Pass** (config-dependent — see D2) |
| **FR15 / AC17** | Public signups disabled, mechanically verified; success blocks release | `panel-auth-check.mjs` `checkSignupRejected`; wrapper POSTs signup + fail-closed | S-122 High; `s122-negative-demos.md` | `panel-auth-check` signup fixtures | **Pass** |
| **AC5** | Generic credential error, no enumeration, no password echo, button re-enabled | `errors.ts` collapse to one code/message; action never returns password; `LoginForm` `useFormStatus` | S-119 | `auth-errors` (10) identical-message assertion; `login-action` | **Pass** |
| **AC7** | Token refresh, no spurious logout | `createMiddlewareClient` returns cookie-handler response; middleware returns it verbatim | S-117 | `middleware-gate` cookie-preservation | **Pass** |
| **AC12** | `make validate` + tests + E2E | root `make validate`; E2E `auth.spec` + `auth.setup` | S-119/S-120/S-122 (reported green) | 142 auth tests pass locally this audit | **Pass** |
| **AC16** | "Forgot password?" is a dead, non-activatable link | `LoginForm.tsx` `<span aria-disabled="true">`, not `<a>` | S-119 | `LoginForm` dead-link assertion | **Pass** |

**Coverage: 17/17 ACs covered and passing; 15/15 FRs covered. No uncovered AC.**

## 4. Drift Catalog

All drift is **Minor** and **Intended**. Drift is **non-blocking to completion** by design.

- **D1 — `/api/auth/logout` is classified `public`, not `api`.** Spec §7.3 tabled `/api/auth/logout`
  as `api` (session required); the shipped `route-policy.ts` classifies the **exact** path as
  `public`. **Impact: Minor. Intent: Intended** — a session-ending POST must reach the handler even
  with an expiring/invalid session, or the gate would 401 it before cookies clear (logout would be
  self-defeating). Match is exact (siblings stay `api`) and the route is POST-only (a GET is a 405),
  so no read surface is widened. This is the S-120 recorded decision, documented in the code and the
  S-120 report. Evidence: `route-policy.ts` public-exact-path comment; `auth-route-policy.test.ts`.
  **Route:** `product-engineer` — reconcile spec §7.3 table to match the shipped (safer) decision.

- **D2 — 12h inactivity expiry is a Supabase project setting, not panel code.** FR14/AC14's real
  enforcement lives in the Supabase dashboard (refresh-token inactivity), out of the repo; the panel
  only enforces the *consequence* (an expired/invalid cookie is denied). **Impact: Minor. Intent:
  Intended** — spec §7.5 states this explicitly and the testable surface is the denial, which is
  covered. Consequence: the "12h" value cannot be asserted by code and depends on operator config
  applied in Phase B. **Route:** `product-engineer` / runbook — ensure the Phase B checklist verifies
  the dashboard setting.

- **D3 — Signup auto-deletion in the gate is best-effort, conditional on a service-role key.** The
  release gate's `checkSignupRejected` blocks the release unconditionally on a successful signup, but
  the *cleanup* of any account it creates needs `SUPABASE_SERVICE_ROLE_KEY`; absent, it WARNs to
  delete manually. **Impact: Minor. Intent: Intended** — the release-blocking verdict is
  unconditional; only cleanup is conditional, and the disposable address is clearly marked. Carried
  from the S-122 report (its D3). Evidence: `verify-panel-auth.sh` admin-DELETE branch. **Route:**
  `product-engineer` — no action needed; note in runbook.

- **D4 — Login `page.tsx` already-authenticated check fails *open* to the form.** If `getClaims()`
  throws on the already-signed-in redirect check, the page falls through to rendering the login form
  rather than redirecting to `/`. **Impact: Minor. Intent: Intended** — documented in-code as safe
  because the middleware gate still protects every real destination; showing the form to an
  already-authed user is a cosmetic redundancy, not an exposure. The S-119 already-authed→`/` redirect
  also lacks a dedicated automated test (verifier D2 from the S-119 report). Evidence:
  `app/login/page.tsx` catch block. **Route:** `qa-engineer` — add the already-authenticated redirect
  test; `product-engineer` — no spec change needed.

**No Critical or Major drift. No Unintended or Undetermined drift.**

## 5. Independent Coverage-Rollup & Security Confirmation

Confirmed independently (not merely trusting the per-story reports), as requested:

| Security-critical property | Real (non-vacuous) coverage? | Evidence |
| --- | --- | --- |
| Fail-closed route classification (302/401/public) | ✅ | `auth-route-policy.test.ts` (16) incl. unknown→ui fail-closed |
| Open-redirect prevention (server-side, before use) | ✅ | `auth-redirect.test.ts` (25): `//`, `://`, `javascript:`, `/\`, control chars, `/login` loop |
| Anti-enumeration (unknown-email ≡ wrong-password) | ✅ | `auth-errors.test.ts` (10): asserts **identical** message + single code |
| `getClaims()` not `getSession()` for authz | ✅ | `auth-no-getsession.test.ts` (3) + grep: `getSession` only in comments |
| 302-UI / 401-JSON split + refreshed-cookie preservation | ✅ | `middleware-gate.test.ts` (20), injected fake client |
| Release gate: 302-on-protected / 401-on-SSE / signup-REJECTED / env-name / fail-closed | ✅ | `panel-auth-check.test.ts` (30) + CLI (4), each violation direction |
| Live-tail 401 → terminal (no reconnect storm); mid-stream drop still reconnects w/ seq dedupe | ✅ | `use-run-stream-auth.test.ts` (6); `relay.ts` sequencing untouched |
| RLS stays deny-all under an authenticated session | ✅ | `integration/rls-deny-all.test.ts` + `auth-login.test.ts` §14.3 (non-vacuous: rows confirmed via service role first) |

- **`fly.toml` declares no public exposure:** confirmed — no `[http_service]`, no `[[services]]`
  with public ports, no public `[[services.ports]]`; private-only banner present. **PRIVATE.**
- **`server.ts` byte-unchanged** since before the auth wave (`git diff 90c3450 HEAD` empty).
- **No `NEXT_PUBLIC_` service-role exposure** (only a doc comment forbidding it).
- **Old privacy gate removed** (`fly-privacy-check.mjs`, `verify-fly-private.sh` gone) and **replaced**
  (not just deleted) by `panel-auth-check.mjs` + `verify-panel-auth.sh`.
- **S-116 first-pass attention** (no prior per-story report): SA1 separation holds (auth clients use
  anon key only; data client untouched), pure modules (`route-policy`/`redirect`/`errors`/`auth-env`)
  fully unit-tested — no gaps found.
- **Documentation coherence:** ADR-007 records the D16 reversal / SR2→auth-gate flip;
  technical-guidelines §5/§6/§13 updated; DESIGN §5.5 (login) + §4.1 (sidebar Log out) present. Coherent.
- **OQ resolution:** OQ1 (getClaims local/network) — middleware awaits `getClaims()`, correct for the
  project's ES256 keys (local JWKS) and safe if that changes. OQ3 (401-before-open) — resolved as
  designed: plain 401 before stream opens, hook treats never-opened as terminal.

142 auth unit+component tests passed locally during this audit (11 files). Layer 2.5 integration
suites (`auth-login`, `rls-deny-all`) are Docker-gated and were verified present with non-vacuous
assertions; per-story reports and CI record them running live.

## 6. Recommendations (per drift item)

| Item | Recommended next step | Owner |
| --- | --- | --- |
| D1 | Reconcile spec §7.3 route-policy table to the shipped `public`-for-`/api/auth/logout` decision | `product-engineer` (drift-reconciliation) |
| D2 | Add the 12h-inactivity dashboard setting to the Phase B verification checklist | `product-engineer` / runbook |
| D3 | No action needed; note best-effort cleanup in the runbook | `product-engineer` |
| D4 | Add an automated test for the already-authenticated `/login`→`/` redirect | `qa-engineer` |
| — | Phase B (S-123) remains a separate, operator-gated PR — do not bundle with this consolidated PR | `planner` / operator |

**This audit is additive and non-blocking. The consolidated Phase A PR to `main` may proceed;
the four Minor/Intended drift items are routed above, not gated here.**
