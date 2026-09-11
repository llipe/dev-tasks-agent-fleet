# Fidelity Report — S-119 (Login screen and sign-in action)

## 1. Header / Verdict

- **Overall fidelity verdict:** **High**
- **Highest drift impact present:** **Minor**
- **Scope:** Story S-119 · Issue #158 · Draft PR #166 · branch `story/S-119-login-screen` (base `integration/v2.1-panel-auth`)
- **Mode:** Audit (grey-box) · Phases 1–4 complete
- **Sources cross-checked:** codebase (delivered files, read directly) · `/workstream` (story + task file) · test suite (unit / component / integration / E2E) · PRD AC3/AC4/AC5/AC10/AC13/AC16 + spec §8/§10.1/§10.4/§11 + DESIGN §5.5

**Bottom line:** The delivered implementation matches the requested behavior on every audited acceptance criterion and every security-critical business rule. Anti-enumeration and redirect safety — the two highest-risk properties — are correctly implemented *and* backed by tests that would fail if the property regressed. Reused modules are genuinely imported, not re-implemented. Scope is clean: no protected file was touched. All drift is Minor and Intended (documentation/mockup-wording granularity), non-blocking.

---

## 2. Human-readable summary (what changed and why)

This story adds the panel's only public screen — the `/login` page — and the server-side action that signs an operator in. Before this, every route was gated by the middleware (S-117) but there was nowhere to actually log in.

What an operator now sees: a single centered "Agent Fleet" card with a "Sign in" heading, an invitation-only note, EMAIL and PASSWORD fields with a SHOW/HIDE reveal button, and a full-width Sign in button. If they mistype their password — or type an email that does not exist — they get the exact same generic "Invalid email or password." message, on purpose: the system never reveals whether an email is registered. On success they are sent to wherever the gate originally wanted them, unless that destination was tampered with to point off-site, in which case they safely land on the home page instead. "Forgot password?" is shown but deliberately inert (there is no reset flow in this product), and it is built so a keyboard or screen-reader user cannot activate a dead control.

Why it is trustworthy: the two security-sensitive behaviors — "unknown email and wrong password look identical" and "a malicious redirect can't send you off-site" — are not just implemented, they are proven by tests that assert the two failure cases produce byte-identical results, that the password never appears in the response, and that off-origin/`/login`-loop targets collapse to `/`. The screen also reuses the existing hardened building blocks (redirect sanitizer, error mapper, cookie-backed auth client) rather than re-writing them, so it inherits their prior test coverage. The only differences from the written specs are wording/granularity nits in DESIGN.md and the spec's mockup table — not behavioral gaps.

---

## 3. Per-AC result table

| AC | Description | Codebase evidence | Workstream evidence | Test evidence | Result |
| --- | --- | --- | --- | --- | --- |
| **AC10** | `/login` renders publicly, outside `AppShell`, matching §10.1 element list | `app/login/page.tsx` (brand mark+dot+wordmark, "Sign in" h1, invitation subtitle, faded rule, `LoginForm`); `app/login/layout.tsx` renders shell-free (`<>{children}</>`); route is outside `(panel)` group | Story AC #1; task 5.0 | `LoginForm.test.tsx` (all mockup elements, labels associated, region tag, fine print); E2E `auth.spec.ts` asserts no primary `navigation` present | **Pass** |
| **AC3** | Valid creds set HttpOnly session cookie + redirect to sanitized target or `/` | `actions.ts` `signIn` wires `createAuthServerClient` (cookie-backed) → `signInWithPassword` → `redirect(result.redirect)`; cookie written by `@supabase/ssr` adapter | Story AC #2 | Layer 2.5 `auth-login.test.ts` (real stack: sign-in sets cookies, cookies round-trip, verified via `getClaims`); E2E valid-login → `/agents/dependency-update` | **Pass** |
| **AC4** | Off-origin/absolute `redirect` lands on `/` | `actions.ts` calls `safeRedirectTarget(raw.redirect)` **first**, before any use, on both success and failure branches; page pre-sanitizes too | Story AC #3; §8.1 rules | `login-action.test.ts` (`//evil.com`→`/` on success, `https://evil.com`→`/` on failure, `/login`→`/`, valid path+query+hash preserved); E2E tampered-redirect + `/login`-loop scenarios | **Pass** |
| **AC5** | Generic error in `role="alert"`; password not echoed; button re-enabled; unknown-email ≡ wrong-password | `errors.ts` `classifySignInError` collapses all 4xx → `AUTH_INVALID_CREDENTIALS`; `actions.ts` returns only message+code+sanitized redirect (never password); `LoginForm.tsx` renders `role="alert"`, remounts password field on failure | Story AC #4/#5; §8.2 anti-enumeration note | `login-action.test.ts` (400-wrong-pw ≡ 400-unknown-email identical code+message; 404→same; no raw Supabase text; password never in `JSON.stringify(result)`); `LoginForm.test.tsx` (`role="alert"`, button disabled while pending); E2E invalid-creds shows alert, password value empty, button enabled | **Pass** |
| **AC13** | SHOW toggle reveal/re-mask, keyboard-operable, `aria-pressed`, defaults masked | `PasswordField.tsx` `<button type="button">` with `aria-pressed={revealed}`, `aria-controls`, toggles `type` password↔text, defaults `revealed=false` | Story AC #6; §10.1 SHOW row | `LoginForm.test.tsx` (defaults masked, toggles both ways, `aria-pressed` flips, `type=button` so never submits); E2E SHOW/HIDE scenario | **Pass** |
| **AC16** | "Forgot password?" is a non-activatable `<span aria-disabled>`, not `<a href="#">` | `LoginForm.tsx` renders `<span className={styles.deadLink} aria-disabled="true">`; no anchor | Story AC #7; §10.1 dead-link note | `LoginForm.test.tsx` (tag ≠ `A`, `aria-disabled=true`, no `link` role, no `a[href="#"]`) | **Pass** |
| **AC (extra)** | Already-authenticated visit to `/login` redirects to `/` | `page.tsx` `getClaims()` check → `redirect("/")` when claims present | Story AC #8 | Verified by inspection; not covered by a dedicated automated test (see Drift D2) | **Pass** |
| **AC (extra)** | Inline no-cache route config | `page.tsx` inline `dynamic="force-dynamic"`, `revalidate=0`, `fetchCache="force-no-store"` (not re-exported) | §11 / §12 convention | Confirmed by inspection; `next build` reports `/login` dynamic (qa-engineer) | **Pass** |
| **AC (extra)** | Fields label-associated, semantic form, visible focus rings | `LoginForm.tsx`/`PasswordField.tsx` `<label htmlFor>`; global `:focus-visible` ring (S-105) | Story AC #9 | `LoginForm.test.tsx` label association | **Pass** |
| **AC (extra)** | Token-only CSS; `token-discipline` passes | `LoginForm.module.css` + `PasswordField.module.css` tokens only (`color-mix` on `--st-fail`, `var(--space-*)`, etc.) | Story AC #10 | `make validate` green incl. token-discipline (qa-engineer) | **Pass** |

### Business rules

| Rule | Result | Evidence |
| --- | --- | --- |
| No signup / reset / confirmation / magic link | **Pass** | Only `signInWithPassword` used; "Forgot password?" inert; no signup/reset code paths |
| Server-side authoritative validation (client hints only) | **Pass** | `actions.ts` re-validates field shape server-side; form is `noValidate`; `required`/`type=email` are hints |
| Password never stored / logged / echoed | **Pass** | Password read from `FormData`, forwarded to Supabase, never returned/logged; `login-action.test.ts` asserts absence in result; uncontrolled field (React never holds plaintext in state) |
| No Zod added | **Pass** | No Zod import anywhere in delivered files; hand validation in the action |
| Reuse (not re-implement) `redirect.ts`, `errors.ts`, `auth-server.ts`, S-117 middleware | **Pass** | All imported via `@/lib/...`; branch diff shows none of these files modified |

---

## 4. Drift catalog

> All drift below is **non-blocking to PR/issue completion** by policy — Audit Mode is additive and does not gate the existing quality gates (`test`/`lint`/`format:check`/`typecheck`/`audit`), which are reported green.

### D1 — DESIGN §5.5 / spec §10.1 pin the card max-width and mark dimensions; impl values match but are literal `px`
- **Impact:** Minor · **Intent:** Intended
- **Detail:** `login.module.css` uses bare dimensional `px` for the card (`max-width: 360px`), brand mark (`18px`/`6px`), and heading (`25px`), consistent with DESIGN §5.5 ("~360px", h3-scale 25px) and the documented S-105 token-discipline carve-out (dimensional `px` outside the `--space-*` scale is allowed and not gated). `login.module.css` also lives under `app/`, outside the gate's `components/**` scope — correctly annotated in the file header.
- **Evidence:** `login.module.css`; DESIGN §5.5; technical-guidelines §12 token-discipline carve-out.
- **Recommendation:** No action needed. Consistent with the existing, documented convention.

### D2 — "Already-authenticated visit to `/login` → `/`" has no dedicated automated test
- **Impact:** Minor · **Intent:** Unintended
- **Detail:** The behavior is implemented (`page.tsx` `getClaims()` → `redirect("/")`) and exercised indirectly (the E2E setup project signs in through `/login`, and re-visiting while authed would redirect), but there is no explicit assertion that an authed visit to `/login` lands on `/`. Every other AC clause has direct test evidence.
- **Evidence:** `page.tsx` (verified by inspection); no matching case in `auth.spec.ts`.
- **Recommendation:** `qa-engineer` — add one E2E case (authed context visits `/login`, expect redirect to `/`). Low effort; closes the last inspection-only gap.

### D3 — Page's already-authed branch is documented as "fail-open to the form"
- **Impact:** Minor · **Intent:** Intended
- **Detail:** In `page.tsx`, a thrown `getClaims()` error is swallowed and the form renders (comment: "fail-open to the form is safe here — the middleware gate still protects every real destination"). This is the correct posture for *this* screen (the login form is itself public; the authoritative fail-closed decision lives in the S-117 middleware, which was verified separately and is not modified here), but it is a deliberate local deviation from the "fail-closed" phrasing used elsewhere in the feature and worth recording so a future reader does not read it as an inconsistency.
- **Evidence:** `page.tsx` try/catch around `getClaims()`; spec §7.2 req 4 (fail-closed is the *middleware's* contract, not the login page's).
- **Recommendation:** No action needed. Correct as designed; noted for traceability.

### D4 — Region tag default `"us-east-1"` vs spec example `· us-east-1`
- **Impact:** Minor · **Intent:** Intended
- **Detail:** Spec §10.1 shows `· us-east-1` as a non-secret display value "from a non-secret region value." Impl reads `process.env.AWS_REGION ?? "us-east-1"`. The literal shown in the spec is an example, and the impl derives it from a non-secret env var with that same fallback — faithful to intent.
- **Evidence:** `page.tsx` `regionLabel()`; spec §10.1 region row.
- **Recommendation:** No action needed.

---

## 5. Edge-case & security spot-checks (grey-box)

- **Redirect sanitization ordering:** confirmed applied **before** use in both the page (pre-sanitize for the hidden field) and authoritatively in the action's pure core (`safeRedirectTarget` is the first statement in `resolveSignIn`). Protocol-relative `//`, `/\`, `://`, absolute-URL-parse, control chars, and `/login`-loop are all rejected by `redirect.ts` and tested. **No leak path found.**
- **Anti-enumeration:** no branch in `actions.ts` or `errors.ts` inspects *which* credential was wrong; all 4xx collapse to one code; only 5xx/429/network diverge (to a service-unavailable message, which does not leak account existence). Timing parity is structural (same code path), consistent with the §8.2 requirement. Raw Supabase `message` is never forwarded — asserted by test. **No enumeration vector found.**
- **Password handling:** uncontrolled input; read once from `FormData`; never placed in React state, never returned, never logged. Failed-attempt field reset is a client-side remount (fresh `key`), not an echo. **Clean.**
- **Scope discipline:** branch diff touches only S-119 files + the wave2 task file + DESIGN.md (+`.gitignore`). `lib/supabase/server.ts`, `middleware.ts`, `(panel)/**`, and `lib/sse/relay.ts` are **not** modified. No `planner.md` stash present. **Clean.**

---

## 6. Recommendations summary

| Item | Owner | Action |
| --- | --- | --- |
| D1 (px literals) | — | No action needed (documented carve-out) |
| D2 (missing already-authed E2E assertion) | `qa-engineer` | Add one E2E case; low effort |
| D3 (login-page fail-open note) | — | No action needed (correct by design) |
| D4 (region tag example) | — | No action needed |

No `developer` code fix and no `product-engineer` spec escalation are required. The single actionable item (D2) is a test-coverage top-up routed to `qa-engineer`, and is non-blocking. Drift routing to `product-engineer`'s `activity-drift-reconciliation` is optional given all drift is Minor/Intended except D2.

**Verification status (reported by qa-engineer; confirmed consistent with audited code, not re-run):** `make validate` green both branches (Python 452 + panel 915 / 4 gated skips); `next build` green with `/login` dynamic; E2E 17 passed incl. 7 auth scenarios; Layer 2.5 `auth-login` ran live; `coverage_gate` PASS.
