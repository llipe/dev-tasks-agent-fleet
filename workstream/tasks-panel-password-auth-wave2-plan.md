# Implementation Plan - Panel Password Authentication (Wave 2: Screens, Lifecycle, Gate)

**Scope:** S-119 (#158), S-120 (#159), S-121 (#160), S-122 (#161) — the login screen + sign-in action, the logout route + sidebar affordance, live-tail 401 handling, and the auth release gate that replaces the privacy gate.
**Phase:** A (app stays private throughout — no public exposure in this wave).
**Source:** [`user-stories-panel-password-auth.md`](user-stories-panel-password-auth.md) · [`specification-panel-password-auth.md`](specification-panel-password-auth.md)
**Companion:** [`tasks-panel-password-auth-wave1-plan.md`](tasks-panel-password-auth-wave1-plan.md) (S-116/117/118 — dependencies of this wave)

> Migration note: all four stories are a documented **migration opt-out** — no schema or data-model change. Auth state lives in Supabase's platform-managed `auth.*` schema and in browser cookies. The canonical migration and `supabase/seed.sql` are untouched, so no migration artifact, rollback note, apply-confirmation gate, or seed data applies to this wave. (S-122 touches infrastructure config only — `fly.toml` stays private; the public-exposure apply step belongs to S-123, which is out of scope for this run.)

## Relevant Files

- `panel/app/login/page.tsx` - Public login screen (outside AppShell, inline route config, redirects when already authenticated)
- `panel/app/login/layout.tsx` - Shell-bypass layout for the login route
- `panel/app/login/login.module.css` - Token-only login screen styles
- `panel/app/login/actions.ts` - `"use server"` sign-in action (validate, sanitize redirect, `signInWithPassword`, map errors)
- `panel/components/auth/LoginForm.tsx` + `.module.css` - Client form with pending/disabled state via `useFormStatus`
- `panel/components/auth/PasswordField.tsx` + `.module.css` - SHOW toggle, `aria-pressed`, defaults masked
- `panel/app/api/auth/logout/route.ts` - POST-only logout, inline route config
- `panel/components/shell/LogOutItem.tsx` + `.module.css` - Sidebar footer Log out control (POST form)
- `panel/components/shell/Sidebar.tsx` - Render Log out between System health and Collapse, gated on `authenticated`
- `panel/components/shell/AppShell.tsx` - Thread the `authenticated` prop
- `panel/components/icons.tsx` - Add `LogOutIcon` (Phosphor `Power`, `/ssr`)
- `panel/lib/hooks/useRunStream.ts` - Open-tracking + terminal auth stop (no reconnect on never-opened 401)
- `panel/components/run-detail/LiveLogViewer.tsx` - Session-expired notice
- `panel/scripts/panel-auth-check.mjs` - Pure, unit-tested gate parser (no I/O)
- `scripts/verify-panel-auth.sh` - Live wrapper supplying HTTP probes, `fly secrets list` names, signup attempt
- `scripts/verify-fly-private.sh` - REMOVED (replaced by the auth gate)
- `panel/scripts/fly-privacy-check.mjs` - REMOVED (replaced by `panel-auth-check.mjs`)
- `panel/fly.toml` - SR2 banner updated; remains PRIVATE in this wave
- `.github/workflows/ci.yml` - Parser unit tests + `shellcheck` on the new wrapper
- `docs/runbooks/panel-deployment.md` - Phase A/B procedure, Supabase config checklist, rollback
- `docs/technical-guidelines.md` - §5/§6/§13/§18 write-back (changelog row)
- `DESIGN.md` - Login screen spec + sidebar Log out item (changelog rows)
- `panel/tests/component/LoginForm.test.tsx` - Component suite
- `panel/tests/integration/auth-login.test.ts` - Layer 2.5 (Docker-gated) login round-trip
- `panel/tests/component/LogOutItem.test.tsx` - Logout affordance component suite
- `panel/tests/unit/use-run-stream-auth.test.ts` - Terminal-auth-stop unit suite
- `panel/tests/component/LiveLogViewer.test.tsx` - Session-expired notice assertion
- `panel/tests/unit/panel-auth-check.test.ts` - Gate parser tests (pass + per-violation fail fixtures)
- `panel/tests/e2e/auth.spec.ts` - E2E auth scenarios (redirect, valid login, tampered redirect, invalid creds, SHOW toggle, logout)
- `panel/tests/e2e/auth.setup.ts` - Playwright auth setup project (signs in the operator once, saves storageState so existing protected-route specs run authenticated under the active gate)
- `panel/tests/e2e/fixtures/auth.ts` - Test operator credentials + admin-API provisioning
- `panel/tests/e2e/fixtures/storage.ts` - Authenticated storageState file location
- `panel/tests/e2e/global-setup.ts` - Provision the test operator user

## Tasks

- [x] 5.0 Implement Story S-119 - https://github.com/llipe/dev-tasks-agent-fleet/issues/158: Login screen and sign-in action

  > Note: The only new screen. Security-critical parts: generic credential error (no user enumeration) and redirect sanitization. No signup, reset, confirmation, or magic link. Depends on S-116, S-117, S-118.

  - [x] 5.1 Add `app/login/page.tsx` (public, inline `force-dynamic`/`revalidate=0`/`fetchCache="force-no-store"`, redirects to `/` when already authenticated) and `app/login/layout.tsx` to bypass the shell
  - [x] 5.2 Add `app/login/actions.ts` with the `signIn` server action: validate fields, sanitize redirect via `safeRedirectTarget` before use, `signInWithPassword`, map errors via `lib/auth/errors.ts`
  - [x] 5.3 Add `components/auth/LoginForm.tsx` + `.module.css` reusing `Input`/`Button`/`KLabel`, with `useFormStatus` pending/disabled state
  - [x] 5.4 Add `components/auth/PasswordField.tsx` + `.module.css` — SHOW toggle, keyboard-operable, `aria-pressed`, defaults masked
  - [x] 5.5 Reuse the `Sidebar` brand markup pattern for the mark + wordmark; render heading, invitation-only subtitle, footer dead "Forgot password?" link, region tag, session-expiry fine print per spec §10.1
  - [x] 5.6 Add `tests/e2e/global-setup.ts` provisioning the test operator user via the admin API against the local stack
  - [x] 5.7 Add E2E scenarios in `tests/e2e/auth.spec.ts`: unauthenticated redirect, valid login, tampered redirect, invalid credentials, SHOW toggle
  - [x] 5.8 Add `tests/integration/auth-login.test.ts` (Layer 2.5, Docker-gated): seed a user; `signInWithPassword` succeeds + sets cookies; wrong password fails; cookie round-trips and verifies via `getClaims`; include the RLS-deny-all-unchanged assertion (spec §14.3)
  - [x] 5.9 Add `tests/component/LoginForm.test.tsx`: mockup elements present; labels associated; SHOW toggle + `aria-pressed`; `role="alert"` error region; button disabled while pending; "Forgot password?" not activatable
  - [x] 5.10 Edge-case validation: empty submit; email with surrounding whitespace; very long password; double-click submit; `redirect=/login` (no loop); `redirect=//evil.com`; already-signed-in visit; Supabase unreachable
  - [x] 5.11 Verify Acceptance Criterion (AC10): `/login` renders publicly, outside `AppShell`, matching the spec §10.1 element list
  - [x] 5.12 Verify Acceptance Criterion (AC3): valid credentials set an HttpOnly session cookie and redirect to the sanitized target, or `/` when absent
  - [x] 5.13 Verify Acceptance Criterion (AC4): absolute/off-origin `redirect` lands on `/`
  - [x] 5.14 Verify Acceptance Criterion (AC5): invalid credentials show generic "Invalid email or password." in `role="alert"`; password not echoed; button re-enabled; unknown-email and wrong-password indistinguishable
  - [x] 5.15 Verify Acceptance Criterion (AC13): SHOW toggle reveals/re-masks, keyboard-operable, reports `aria-pressed`, defaults masked
  - [x] 5.16 Verify Acceptance Criterion (AC16): "Forgot password?" is a styled non-link with `aria-disabled`, not `<a href="#">`
  - [x] 5.17 Verify Acceptance Criterion: already-authenticated visit to `/login` redirects to `/`; fields label-associated; focus rings visible; `token-discipline` test passes
  - [x] 5.18 Map each AC to its test evidence and record the mapping in the issue
  - [x] 5.19 Manual verification: compare rendered `/login` against the mockup; sign in with a real seeded user; confirm redirect; bad password; toggle SHOW; tab for focus rings
  - [x] 5.20 Update `DESIGN.md` with the login screen spec (changelog row required)
  - [x] 5.21 Run Tests: `pnpm run test`, `pnpm run test:integration`, `pnpm run test:e2e`, then `pnpm run validate`
  - [x] 5.22 Update issue #158 checklist and mark the story complete

- [x] 6.0 Implement Story S-120 - https://github.com/llipe/dev-tasks-agent-fleet/issues/159: Logout route and sidebar Log out affordance

  > Note: Logout MUST be POST-only (a GET logout is CSRF-triggerable and prefetch-firable). The shell stays presentational — it performs no auth I/O; `authenticated` is passed in as a prop (SD2 preserved). Depends on S-117, S-118 (S-119 recommended first for end-to-end manual verification).

  - [x] 6.1 Add `app/api/auth/logout/route.ts` exporting only `POST`, with inline route config; `signOut`, clear session cookies, redirect to `/login`
  - [x] 6.2 Add `LogOutIcon` to `components/icons.tsx` mapped to Phosphor `Power`, imported from `@phosphor-icons/react/ssr`
  - [x] 6.3 Add `components/shell/LogOutItem.tsx` + `.module.css` as a plain `<form method="post" action="/api/auth/logout">` using the existing footer-control `.toggle` grid pattern (icon + label; icon-only when collapsed)
  - [x] 6.4 Render it in `Sidebar.tsx` between System health and Collapse, gated on an `authenticated` prop threaded from the authenticated layout via `AppShell.tsx`
  - [x] 6.5 Add `tests/component/LogOutItem.test.tsx`: POST form with correct action; ordering after System health / before Collapse; icon-only when collapsed; absent when unauthenticated
  - [x] 6.6 Add the E2E logout scenario in `tests/e2e/auth.spec.ts`
  - [x] 6.7 Edge-case validation: logout with an already-expired session; double-submit; logout while collapsed; keyboard activation; `GET` to the logout path must not log out
  - [x] 6.8 Verify Acceptance Criterion (AC6): `POST /api/auth/logout` clears cookies and redirects to `/login`; after logout a protected route redirects to `/login`; idempotent with no session
  - [x] 6.9 Verify Acceptance Criterion: `GET /api/auth/logout` does not exist as a route
  - [x] 6.10 Verify Acceptance Criterion (AC15): Log out item below "System health", above "Collapse", power-style icon; icon-only when collapsed; absent when unauthenticated
  - [x] 6.11 Verify Acceptance Criterion: `AppShell`/`Sidebar` do not call Supabase (SD2 preserved)
  - [x] 6.12 Map each AC to its test evidence and record the mapping in the issue
  - [x] 6.13 Manual verification: sign in, confirm Log out in the footer, click it, land on `/login`, confirm `/` re-gates; collapse the sidebar and confirm icon-only rendering
  - [x] 6.14 Update `DESIGN.md` with the sidebar Log out item (changelog row required)
  - [x] 6.15 Run Tests: `pnpm run test`, `pnpm run test:e2e`, then `pnpm run validate`
  - [x] 6.16 Update issue #159 checklist and mark the story complete

- [ ] 7.0 Implement Story S-121 - https://github.com/llipe/dev-tasks-agent-fleet/issues/160: Live-tail 401 handling (stop infinite reconnect)

  > Note: Gating the SSE route turns `useRunStream`'s reconnect-on-drop into an infinite loop against a 401. `EventSource` cannot send headers, so a denied connection surfaces as `onerror` with the stream never having opened — that "never opened" signal distinguishes auth failure from a recoverable drop (resolves spec OQ3: gate returns plain `401` before the stream opens, not a `closed` frame). Do not alter `lib/sse/relay.ts` sequencing. Depends on S-117.

  - [ ] 7.1 Add open-tracking state to `useRunStream` (did `onopen` fire for the current attempt)
  - [ ] 7.2 Branch `onerror`: never-opened + `readyState === CLOSED` → terminal stop (no reconnect); previously-opened → existing reconnect path with the highest rendered `seq`
  - [ ] 7.3 Expose a terminal-auth-stop state from the hook
  - [ ] 7.4 Render a session-expired notice in `LiveLogViewer.tsx` using existing Nocturne tokens (no new component library)
  - [ ] 7.5 Add `tests/unit/use-run-stream-auth.test.ts`: errored-before-open → no reconnect scheduled; opened-then-dropped → reconnect with correct `after_seq`; repeated failures do not accumulate timers
  - [ ] 7.6 Add the notice assertion in `tests/component/LiveLogViewer.test.tsx`
  - [ ] 7.7 Edge-case validation: 401 on the very first connection; 401 on a reconnect after a successful period; rapid open/close flapping; run reaching terminal state simultaneously with a 401
  - [ ] 7.8 Verify Acceptance Criterion: an `onerror` with `readyState === CLOSED` and no successful open is terminal — no reconnect
  - [ ] 7.9 Verify Acceptance Criterion: a genuine mid-stream drop still reconnects with the highest rendered `seq` (S-110 behavior preserved)
  - [ ] 7.10 Verify Acceptance Criterion: the UI surfaces a session-expired notice rather than silently freezing; no line lost or duplicated on legitimate reconnect (`seq` dedupe intact)
  - [ ] 7.11 Map each AC to its test evidence and record the mapping in the issue
  - [ ] 7.12 Manual verification: open a run detail page with a live run, clear the session cookie in devtools, observe the tail stop once with a notice and no reconnect storm in the network panel
  - [ ] 7.13 Run Tests: `pnpm run test:unit`, `pnpm run test`, `pnpm run test:integration` (existing `stream-e2e` still passes), then `pnpm run validate`
  - [ ] 7.14 Update issue #160 checklist and mark the story complete

- [ ] 8.0 Implement Story S-122 - https://github.com/llipe/dev-tasks-agent-fleet/issues/161: Auth release gate replacing the privacy gate

  > Note: `verify-fly-private.sh` fails the release if the app is PUBLIC — the mechanized form of the decision this feature reverses. It must be REPLACED, not deleted, so no mechanical check is ever absent. The signup check is the most important: an open signup on an internet-reachable panel lets anyone self-register into agent invocation. This story ships the gate and the still-private `fly.toml`; it does NOT make the app public. Depends on S-119, S-120, S-121.

  - [ ] 8.1 Write `panel/scripts/panel-auth-check.mjs` — pure verdict logic + CLI entry, no I/O, mirroring `fly-privacy-check.mjs`'s parser/wrapper split
  - [ ] 8.2 Write `scripts/verify-panel-auth.sh` — collect live inputs (HTTP probes against a hostname arg, `fly secrets list` names, a signup attempt with a clearly-marked disposable address that deletes any account it creates), exit non-zero on any failure
  - [ ] 8.3 Add `tests/unit/panel-auth-check.test.ts` — passing fixture; failing fixtures for `200` on a protected path, `200` on SSE, successful signup, missing env name, malformed/garbage input; fail-closed default
  - [ ] 8.4 Remove `scripts/verify-fly-private.sh` and `panel/scripts/fly-privacy-check.mjs`; re-point their unit tests to the new parser
  - [ ] 8.5 Update `.github/workflows/ci.yml`: run the parser unit tests and `shellcheck` on the new wrapper
  - [ ] 8.6 Update the `panel/fly.toml` comment banner (app remains PRIVATE in this story — no public service, no public IP)
  - [ ] 8.7 Record RED-then-reverted evidence for both gate directions in `workstream/` (pass on correct deployment; fail on each violation)
  - [ ] 8.8 Update `docs/runbooks/panel-deployment.md` with the Phase A/B procedure, the Supabase config checklist, and rollback
  - [ ] 8.9 Update `docs/technical-guidelines.md` §5/§6/§13/§18 (D16 reversed, SR2 replaced, R1 resolved) with a changelog row
  - [ ] 8.10 Edge-case validation: redirect to a non-`/login` location (must fail); `401` with an HTML body; network timeout; unexpected Supabase signup error shape; empty output
  - [ ] 8.11 Verify Acceptance Criterion: parser is pure and unit-tested (no I/O); wrapper supplies live inputs and exits non-zero on any failure
  - [ ] 8.12 Verify Acceptance Criterion: gate asserts auth env var NAMES present (never values); unauthenticated protected UI path → `302 /login` not `200`; unauthenticated SSE → `401` not `200`
  - [ ] 8.13 Verify Acceptance Criterion (AC17): attempted `signUp` is rejected; a successful signup fails the release
  - [ ] 8.14 Verify Acceptance Criterion: gate is fail-closed (unreadable/unparseable/unconfirmable → non-zero exit); old privacy gate removed and its tests re-pointed; `fly.toml` remains private; CI runs parser tests + `shellcheck`
  - [ ] 8.15 Map each AC to its named fixture case; record both-directions RED-then-reverted evidence
  - [ ] 8.16 Manual verification: run `scripts/verify-panel-auth.sh` against the local dev server with and without a session; confirm verdicts
  - [ ] 8.17 Run Tests: `pnpm run test:unit`, `bash scripts/verify-panel-auth.sh <host>`, then `pnpm run validate`
  - [ ] 8.18 Update issue #161 checklist and mark the story complete

- [ ] 9.0 Phase A completion gate (S-116 … S-122)

  - [ ] 9.1 Confirm all Phase A issue checklists (#155–#161) are fully checked and mirrored locally
  - [ ] 9.2 Run the full aggregate gate from the repo root: `make validate` (Python branch + JS/TS branch must both pass)
  - [ ] 9.3 Confirm `pnpm run test:e2e` passes with the gate active (authenticated flows + public `/login`)
  - [ ] 9.4 Confirm the app is still PRIVATE — no public service and no public IP introduced anywhere in Phase A (`fly.toml` unchanged except banner text)
  - [ ] 9.5 Invoke `qa-engineer` at PRD scope for a coverage rollup; record `coverage_gate` (PASS / FAIL / SKIPPED with non-empty reason)
  - [ ] 9.6 Invoke `verifier` in audit mode for a PRD-level rollup against the integrated Phase A scope; post the summary to the milestone issue (mandatory, non-blocking on drift)
  - [ ] 9.7 Invoke `technical-writer` for a drift/stale-doc pass; resolve any unresolved drift (blocks handoff)
  - [ ] 9.8 Open ONE consolidated Phase A PR from the integration branch to `main`; do NOT merge; notify the user for review and approval
  - [ ] 9.9 Record in the runbook that S-123 (Phase B / go-public) remains outstanding as a separate, operator-executed, separately-merged PR — never bundled with Phase A

## Out of Scope for This Run

- **S-123 (#162) — Go public (Phase B).** Explicitly excluded. It performs real, hard-to-reverse cloud actions (public IP allocation, public Fly service) behind a mandatory operator-confirmation gate and MUST NOT share a PR with any Phase A story. Its full procedure is captured in `docs/runbooks/panel-deployment.md` for operator execution after Phase A is merged, deployed, and verified private.
