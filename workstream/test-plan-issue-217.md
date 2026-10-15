# Test Plan — Issue #217 (Next.js 16.4.1 + Node 26 + `proxy.ts`)

> **Mode:** Design (pre-implementation). **Agent:** verifier.
> **Repository:** llipe/dev-tasks-agent-fleet · **Issue:** #217 · **Branch target:** `main`.
> **Sources:** `workstream/issue-217-nextjs-16-node-upgrade-refinement.md` (AC1–AC9),
> `workstream/decisions-nextjs-16-upgrade.md` (D-01..D-12),
> `workstream/tasks-issue-217-nextjs-16-node-upgrade.md`.
> **Companion artifact:** `workstream/traceability-matrix-issue-217.md`.

This plan is **black-box / behavior-first**: assertions derive from observable behavior
(status codes, headers, cookies, exit codes, file presence, lint findings), not internal
structure. The one deliberate exception is the file-shape assertions the upgrade itself
mandates (`middleware.ts` absent / `proxy.ts` present, native flat config, pin values),
which are the observable deliverables of this issue.

The highest-risk surface is the **auth chokepoint's Edge → Node runtime move** (D-03).
The security-negative set in §4 is built around that move and is **mandatory**.

---

## 1. Source Input Summary

- **Change:** bump `next` + `eslint-config-next` → 16.4.1; companion pins; Node 26 pins +
  `engines.node >=24 <27`; rename `panel/middleware.ts` → `panel/proxy.ts` on the **Node.js
  runtime** (was Edge); native ESLint flat config; fix every new lint finding; ADR-008 + docs.
- **Hard invariant (ADR-007/ADR-008):** the auth gate is the panel's security boundary. Any
  behavior difference in `proxy.ts` vs. the former `middleware.ts` is a **blocker**, not a
  deviation.
- **Non-goals (out of scope here):** TS 7 / ESLint 10 / Vitest 5 / plugin-react 6 (→ #299,
  D-11), React Compiler, Cache Components, any UI change, agent Python runtimes.

---

## 2. Acceptance-Criteria Extraction

| AC | Observable behavior to verify |
| -- | ------------------------------ |
| **AC1** | `next` + `eslint-config-next` = exactly `16.4.1`; companions pinned exactly (`react`/`react-dom` 19.3.1, `@types/react`/`@types/react-dom` 19.3.0, `@playwright/test` 1.64.1, `@supabase/supabase-js` 2.117.3, `@types/node` 26.x). `.nvmrc` ×2, `ci.yml` `setup-node`, `Dockerfile.panel ARG NODE_VERSION` all read `26`. Both `engines.node` = `>=24 <27`. |
| **AC2** | `panel/middleware.ts` **absent**; `panel/proxy.ts` present and gates **identically**: unauth UI → 302 `/login`; unauth SSE → 401; valid session → pass-through; unauth `/api/internal/**` → reaches handler → 401 without the secret. Gate suites (`middleware-gate`, `auth-route-policy`, `auth-no-getsession`, `internal-secret`) pass with **target/name changes only**. |
| **AC3** | `pnpm --filter panel run validate` (lint, format:check, typecheck, test, audit) and `pnpm --filter panel run test:e2e` pass on Node 26; `make validate` passes on both branches. |
| **AC4** | ESLint uses **native flat config** (no `FlatCompat`, no `@eslint/eslintrc` if unused). Lint passes with **zero** disabled/downgraded rules relative to `eslint-config-next` 16 recommended. SD2 still enforced (`eslint-server-import.test.ts`). |
| **AC5** | CI image smoke test passes on `node:26-slim`: build succeeds (Turbopack), PID 1 = uid/gid 1001, server answers on `:8080`, missing `/.fly/api` does not block startup, `setpriv` present. |
| **AC6** | `pnpm --filter panel run audit`: **no `next` advisory**, no new high/critical advisory. |
| **AC7** | CDK workspace member installs and its tests pass on Node 26. |
| **AC8** | ADR-008 exists; `technical-guidelines.md`, `panel/README.md`, runbooks reference `proxy.ts` + Node 26. |
| **AC9** *(post-merge, human-only)* | Release pipeline deploys; `deploy-panel.sh` exits 0 (auth gate checks 1–5 + OIDC probe `status=200 token=present`); a live invoke reaches `running`. |

Business rules / constraints: exact pins, `pnpm` only, `engine-strict=true` stays, no rule
downgrades, human-only release tags/deploys. Non-goals per §1.

---

## 3. E2E Scenarios (Playwright, Node 26)

The existing `tests/e2e/auth.spec.ts` is the gate's acceptance suite. It MUST pass verbatim
on Node 26 against `proxy.ts` (only test *targets/names* may change, never assertions). Each
scenario below is a behavior contract that must hold after the runtime move.

| ID | Scenario | Expected | AC |
| -- | -------- | -------- | -- |
| E2E-01 | Unauth visit to `/` | 302 → `/login?redirect=/`; login heading visible; no primary nav | AC2, AC3 |
| E2E-02 | Valid credentials with `redirect=%2Fagents%2Fdependency-update` | signed in, lands on `/agents/dependency-update`, off `/login` | AC2, AC3 |
| E2E-03 | Tampered off-origin `redirect=%2F%2Fevil.com` | lands on `/`, never off-origin | AC2, AC3 |
| E2E-04 | Invalid credentials | generic error in `role=alert`; still on `/login`; password cleared; button re-enabled | AC3 |
| E2E-05 | Password SHOW/HIDE toggle | type flips `password`↔`text` | AC3 |
| E2E-06 | `redirect=%2Flogin` loop guard | valid login lands on `/`, no loop | AC2, AC3 |
| E2E-07 | Authenticated logout from sidebar footer | POST `/api/auth/logout`, session cleared, lands on `/login`; revisit re-gates | AC2, AC3 |
| E2E-08 | Logout operable while sidebar collapsed (keyboard) | POST-logout path fires, lands on `/login` | AC3 |
| E2E-09 | **Cookie refresh survives the Node-runtime gate** (behavior parity probe) | after sign-in, navigating protected routes keeps the session (no intermittent re-login) across ≥2 navigations | AC2 (security-negative, see §4) |

> **E2E-09 is the headline parity scenario** for the runtime move: the former Edge gate
> returned the cookie-handler response to thread refreshed cookies; the Node-runtime gate
> must do the same. A regression here is the "intermittent random logouts" failure the
> `auth-middleware.ts` design comment warns about.

---

## 4. Security-Negative Set — Edge → Node Runtime Move (MANDATORY)

These are the non-negotiable negative/edge assertions tied directly to D-03/D-12. They are
split between the Layer-2 component suite (`middleware-gate` retargeted to `proxy.ts`, with
an injected fake client) and the live release gate (`verify-panel-auth.sh` checks 1–5).

| ID | Negative condition | Expected (fail-closed) | Layer | AC |
| -- | ------------------ | ---------------------- | ----- | -- |
| SEC-01 | `getClaims()` returns `{error}` on a UI route | 302 → `/login` (treated unauthenticated) | component | AC2 |
| SEC-02 | `getClaims()` returns `{error}` on an API route | 401 JSON | component | AC2 |
| SEC-03 | `getClaims()` **throws** (network down) on a UI route | caught → 302 `/login` | component | AC2 |
| SEC-04 | `getClaims()` throws on an API route | caught → 401 JSON | component | AC2 |
| SEC-05 | `getClaims()` **never resolves** / times out | gate must not hang indefinitely nor pass through; a timeout/rejection resolves fail-closed (deny) — *see Finding F-05 on the absence of an explicit timeout* | component | AC2 |
| SEC-06 | Expired / invalid / garbage cookie → no claims | denied exactly like no session (302 UI / 401 API) | component | AC2 |
| SEC-07 | Refreshed auth cookie is written by the client factory on success | the **returned response carries the refreshed cookie** (no fresh `NextResponse.next()`) | component | AC2 |
| SEC-08 | Concurrent near-expiry requests | each verifies once, no thrash, all succeed, each carries the cookie | component | AC2 |
| SEC-09 | `getSession()` appears anywhere in the authorization surface | **zero** matches (`auth-no-getsession` grep, `AUTHZ_FILES` must name `proxy.ts`) | unit | AC2 |
| SEC-10 | Matcher excludes static assets | `_next/static`, `_next/image`, `favicon.ico`, `*.svg/png/jpg/jpeg/gif/webp/ico` are **not** gated | component | AC2 |
| SEC-11 | Matcher gates everything else | `/`, `/agents/x`, `/runs/y`, `/api/runs/z/events/stream`, `/login`, **and `/api/internal/**`** are matched (gate runs) | component | AC2 |
| SEC-12 | `/api/internal/**` classified `internal` | session gate **declined**, handler reached, **middleware never returns 200** | unit + component | AC2, AC9/check5 |
| SEC-13 | Unauth POST `/api/internal/schedules/<uuid>/fire` (live) | **401** before route resolves the id (secret-gated, not open) | release gate check 5 | AC9 |
| SEC-14 | `/api/internalish` sibling | stays `api` (not `internal`) — no accidental gate-skip widening | unit | AC2 |
| SEC-15 | `/login` and `/login?redirect=/` | `public` short-circuit, `getClaims` **not called** | component | AC2 |
| SEC-16 | `/api/auth/logout` exact | `public` (session-ending reachable); `/api/auth/logout/extra`, `/api/auth/whoami` stay `api` | unit | AC2 |
| SEC-17 | Live unauth protected GET (deployed) | 302 → `/login` (check 2) | release gate check 2 | AC9 |
| SEC-18 | Live unauth SSE GET (deployed) | 401 (check 3) | release gate check 3 | AC9 |
| SEC-19 | Live attempted signUp (deployed) | **rejected**; a successful signup FAILS the release (check 4) | release gate check 4 | AC9 |
| SEC-20 | Redirect never leaks internal bind address | `Location` is same-origin, never contains `0.0.0.0` (built from `nextUrl`, not raw `request.url`) — **re-verify under Node runtime** where `request.url` host behavior may differ | component | AC2 |

> **Why SEC-20 is called out for the runtime move:** on Edge, `request.nextUrl` normalization
> and the raw `request.url` host differ from the Node.js server runtime. The redirect is built
> from `nextUrl.clone()`; this must still produce a same-origin, non-`0.0.0.0` `Location`
> under Node. The existing `middleware-gate` test already asserts the no-`0.0.0.0` invariant —
> keep it and treat it as runtime-sensitive.

---

## 5. Contract Scenarios

Three internal contracts hold the chokepoint together. Each must survive the rename + runtime
move unchanged.

### C-1 — `proxy.ts` ↔ `route-policy.classifyRoute`
- **Provider:** `classifyRoute(pathname): "public" | "ui" | "api" | "internal"`.
- **Consumer:** `proxy.ts` branch order — `public` short-circuit → `internal` pass-through →
  auth check → `api` 401 / `ui` 302.
- **Contract tests:** CON-01 every policy value returned by `classifyRoute` has a matching
  branch in `proxy.ts`; CON-02 unknown/empty/non-string path → `ui` (fail-closed) → gated;
  CON-03 the four policy classes partition the matched path space (no path yields `undefined`).

### C-2 — `proxy.ts` ↔ Supabase `getClaims()` (via `MiddlewareClientFactory`)
- **Provider:** injectable `MiddlewareClientFactory` returning a client exposing `auth.getClaims`.
- **Consumer:** `proxy.ts` reads only `auth.getClaims()` and treats `!error && data?.claims != null`
  as authenticated.
- **Contract tests:** CON-04 the gate calls **only** `getClaims` (never `getSession`, SEC-09);
  CON-05 the success path returns the **factory's** response object (cookie-threading contract,
  SEC-07); CON-06 the factory contract (`createMiddlewareClient` returns `{supabase, response}`
  with `response` = `NextResponse.next({request:{headers: new Headers(...)}})`) is unchanged —
  this is the Supabase-SSR pattern that must still hold on the Node runtime.

### C-3 — internal-route branch ↔ handler secret check
- **Provider:** `authorizeInternalRequest(req, env)` / `checkSchedulerSecret` (constant-time,
  fail-closed) in `lib/auth/internal-secret.ts`.
- **Consumer:** the `internal` branch in `proxy.ts` declines the session gate and lets the
  request reach the handler, which calls the secret check.
- **Contract tests:** CON-07 `internal` branch returns `NextResponse.next()` (pass-through),
  **never** a 200 success body; CON-08 handler denies with 401 on missing/empty/wrong secret
  and on `secret_not_configured` (misconfig = deny, not bypass); CON-09 reason strings never
  surface secret material; CON-10 the live boundary (check 5) returns 401 — the end-to-end
  composition of CON-07 + CON-08.

---

## 6. Edge-Case Catalog (all nine categories)

| Category | Edge cases |
| -------- | ---------- |
| **Input domain** | `/api` exactly; `/api/` trailing slash; `/apiary` (not api); `/agents/login-service` (not public); `/login/extra` (not public); `/api/internal` exactly; `/api/internalish`; empty string path; non-string path (defensive) |
| **State transition** | unauthenticated → login → authenticated → logout → re-gated (E2E-01/02/07); expired session mid-navigation → denied; token refresh on success path (cookie threading) |
| **Timing** | `getClaims()` slow/never-resolving (SEC-05, F-05); concurrent near-expiry refresh with no thrash (SEC-08); release-gate HTTP connect/max timeouts fail the gate (checks 2/3/4/5) |
| **Idempotency** | repeated protected-route navigation yields consistent gate decision; concurrent requests each verify once (SEC-08) |
| **Failure modes** | `getClaims` error / throw → fail-closed (SEC-01..04); misconfigured secret → deny (CON-08); unreachable npm advisory registry in `audit` soft-passes with warning (do not redden on blip) |
| **Auth / permissions** | the entire security-negative set §4; `getSession` ban (SEC-09); anon-key-only auth (never service role) in the factory |
| **Data boundaries** | matcher regex boundary: static-asset extensions excluded vs. gated routes (SEC-10/11); SD2 scope — `components/**` + `app/**` minus server entrypoints/`actions.ts` (eslint-server-import fixtures) |
| **Resource exhaustion** | standalone build output size / tracing root (`outputFileTracingRoot`) under Turbopack still yields a runnable `server.js` (AC5 smoke); image starts and binds within the 30×1s smoke poll |
| **API versioning** | Next 16 async request APIs (`cookies()`/`headers()`/`params`/`searchParams` already awaited); route-segment configs (`dynamic`/`revalidate`/`fetchCache`) still honored; `next.config.ts` keys removed in 16; Turbopack default build; react-hooks v7 new rules; `@types/node` 26 typings |

---

## 7. Randomized / Property Tactics

Reproducible, **no new dependency** — use Vitest's loop + a seeded PRNG written inline
(mulberry32 or `cyrb128`-seeded), seed printed on failure for deterministic replay.

| ID | Tactic | Property | Seed policy |
| -- | ------ | -------- | ----------- |
| RT-01 | **Route-policy classification fuzz.** Generate path shapes from a grammar: random segment counts, prefixes drawn from `{"/api","/api/internal","/api/auth","/login","/agents","/runs","/apiary","/api/internalish"}`, random trailing slashes, random casing, injected `.svg/.png` suffixes, empty/`"/"`. | For every generated path, `classifyRoute` returns one of the four policy values and **never throws**; any path not provably `public`/`api`/`internal` is `ui` (fail-closed — never silently unprotected). | Fixed seed (e.g. `217`) committed in the test; on failure, log seed + minimized path and replay. |
| RT-02 | **Matcher ↔ policy coherence.** For each RT-01 path, if the matcher regex matches (gate runs), then `classifyRoute` must yield a protected class for everything except the public exacts; if the matcher excludes (static asset), the gate must not run. | No path is both matcher-excluded **and** a sensitive route; no gated path classifies to a value with no `proxy.ts` branch. | Same seed as RT-01. |
| RT-03 | **Secret-check fuzz** (optional, bounded). Random header values vs. a fixed configured secret. | `checkSchedulerSecret` returns `ok:true` **iff** exact match; never throws; reason never contains the secret. | Fixed seed; constant-time path exercised with length-mismatched inputs. |

Failure triage per the verifier contract: capture seed + minimized input → classify spec-gap
vs. defect vs. flaky → ≤3 non-reproducing retries then `inconclusive`.

---

## 8. Non-Code Verification (pins, build, docs, release)

| ID | Check | Method | AC |
| -- | ----- | ------ | -- |
| V-01 | Exact version pins in `panel/package.json` + root `package.json` | diff / grep for each pin value | AC1 |
| V-02 | `.nvmrc` ×2 = `26`; `ci.yml setup-node` node-version = `26`; `Dockerfile.panel ARG NODE_VERSION=26` | diff review (**note: `ci.yml` currently reads `22` — Finding F-02**) | AC1 |
| V-03 | both `engines.node` = `>=24 <27`; `engine-strict=true` retained | diff review | AC1 |
| V-04 | `make validate` green on both branches under Node 26 | run locally + CI | AC3 |
| V-05 | native flat config, no `FlatCompat`/`@eslint/eslintrc` import; effective ruleset diffed against `eslint-config-next` 16 recommended; **zero** disabled/downgraded | config diff + `eslint --print-config` compare | AC4 |
| V-06 | `eslint-server-import.test.ts` (SD2) green under the new config | run (120 s timeout per case) | AC4 |
| V-07 | image smoke on `node:26-slim`: build (Turbopack) + PID 1 uid/gid 1001 + `:8080` + no `/.fly/api` + `setpriv` present | CI `panel-quality` smoke step | AC5 |
| V-08 | `pnpm --filter panel run audit`: no `next` advisory, no new high/critical | run | AC6 |
| V-09 | CDK member installs + tests on Node 26 | `pnpm --filter ./agents/dependency-update/agentcore/cdk test` | AC7 |
| V-10 | ADR-008 present; `technical-guidelines.md` pin row; `panel/README.md` + runbooks say `proxy.ts` + Node 26 | doc review; grep for stale `middleware.ts` references | AC8 |
| V-11 | each behavior-affecting react-hooks v7 fix has a test or an explicit PR note | review the fix set vs. tests/PR body — **Finding F-04** | AC4 |
| V-12 | release-gate checks 1–5 + OIDC probe `status=200 token=present`; live invoke → `running` | post-merge release log (human-only) | AC9 |

---

## 9. Execution Checklist (for `developer` / `qa-engineer`)

1. Baseline `make validate` on Node 26 (task 1.1) — record pre-existing vs. upgrade-induced.
2. **Retarget gate tests to `proxy.ts` first** (test-first): `AUTHZ_FILES` in
   `auth-no-getsession.test.ts`, `@/middleware` → `@/proxy` imports in `middleware-gate.test.ts`,
   any `auth-route-policy`/E2E/global-setup reference. Confirm red before `proxy.ts` exists.
3. Run SEC-01..SEC-20 (component + unit) against `proxy.ts`.
4. Run RT-01..RT-03 with the committed seed.
5. Run E2E-01..E2E-09 on Node 26 against the real local stack.
6. Run V-01..V-11; V-12 is post-merge, human-only.
7. Confirm `getSession` grep (SEC-09) scans `proxy.ts`, not the deleted `middleware.ts`.

---

## 10. Design Findings

Impact: Critical / Major / Minor. Intent: Intended / Unintended / Undetermined.
Route: `developer` (fix), `product-engineer` (spec clarify / drift write-back), or no-action.

| ID | Finding | Impact | Intent | Route |
| -- | ------- | ------ | ------ | ----- |
| **F-01** | **`global-setup.ts` has no `middleware.ts` *import* — only a prose comment match.** The task list (1.5) and D-03 both list a "global-setup reference" to retarget. The grep shows `global-setup.ts` matches `middleware`/`proxy` once, but it is a doc comment ("the middleware gate (S-117)"), not an import or a path. The retarget is a comment edit at most; the task's framing could lead `developer` to hunt for a non-existent import. Also `auth-middleware.ts` (18 matches) and `auth-server.ts` (3) reference "middleware" by *concept/filename in prose* — only the **gate file rename** and the `@/middleware` **import** in `middleware-gate.test.ts` + the `AUTHZ_FILES` literal in `auth-no-getsession.test.ts` are true retargets. | Minor | Unintended | product-engineer (clarify task 1.5 scope: it is a comment, not an import) |
| **F-02** | **`ci.yml` `setup-node` currently reads `22`, not `24`.** D-02 and task 1.2 describe the *current* pin as `22` in `.nvmrc`/`ci.yml`/Dockerfile; the refinement body (scope item 3, AC1) says "`ci.yml` … read 26". Confirmed: `ci.yml` `node-version: 22` today. AC1's validation ("`node -v` in CI logs") is satisfiable, but the plan must assert the **CI job actually runs on 26** (the `setup-node` value **and** a `node -v` log line), not merely that the file was edited — otherwise a stale cache or an un-bumped matrix passes vacuously. | Major | Intended (it is the change) | developer (ensure the edit + a `node -v` assertion); qa-engineer (add the log assertion) |
| **F-03** | **AC9 is live/human-only and not mechanically testable pre-merge.** It depends on a deployed app, the OIDC probe, and a human release tag. The plan maps it to release-gate checks 1–5 + the OIDC probe (V-12), but Design Mode cannot assert it. It is correctly post-merge; flagged so the traceability "uncovered pre-merge" status is explicit and not read as a gap. | Minor | Intended | no-action (post-merge release log on #217) |
| **F-04** | **"Fix every lint finding; each behavior-affecting fix needs a test" (D-08/AC4) is only verifiable with the finding set in hand.** react-hooks v7 fixes (purity, refs, set-state-in-effect) can change render behavior. Pre-implementation there is no finding list, so V-11 is a review gate, not an automatable assertion. **Risk the plan surfaces:** a mechanical fix that silently changes behavior with no component test and no PR note would pass `lint` green yet violate D-08. qa-engineer must gate each behavior-affecting fix on a new/extended component test; verifier Audit Mode must cross-check the fix set vs. tests/PR notes. | Major | Undetermined | qa-engineer (per-fix test); verifier (Audit Mode cross-check) |
| **F-05** | **No explicit `getClaims()` timeout in the gate (SEC-05).** `proxy.ts` awaits `getClaims()` with no timeout; it relies on `try/catch` for *thrown* errors and on `data?.claims != null` for *resolved* ones. On the **Node runtime**, if signing keys ever become symmetric (OQ1 notes this is a network call) a hung Auth server could stall the gate — Edge had platform-level time budgets the Node server runtime does not impose the same way. Today keys are ES256 (local verification), so this is latent, not active. The plan asserts fail-closed on error/throw (SEC-01..04) but **cannot assert a bounded hang** because the code has no timeout. | Major | Undetermined | product-engineer (decide: is a bounded `getClaims` timeout in scope for the runtime move, or explicitly deferred with a note in ADR-008?) |
| **F-06** | **Turbopack-as-default + `output: "standalone"` + `outputFileTracingRoot` interaction is only covered by the smoke test (AC5).** The refinement risk list names it; the plan maps it to V-07. But the smoke test asserts *the server starts and binds* — it does **not** assert the standalone trace included every needed dependency (a missing-trace bug can still boot and 500 only on a specific route). No route-level post-build assertion exists. | Major | Undetermined | product-engineer / qa-engineer (consider one authenticated route fetch in the smoke step beyond `/` returning non-000) |
| **F-07** | **Node 26 is pre-LTS until 2026-10-28 (D-06).** `engines.node >=24 <27` admits the fallback to 24 with no engines change, which is good. But if the release ships before 2026-10-28 it runs on *Current*, accepted by @llipe. No test can assert "LTS"; the plan records it so the Audit Mode verdict notes the accepted pre-LTS posture rather than flagging it as drift. | Minor | Intended | no-action (recorded; D-06 accepts it) |
| **F-08** | **`@types/node 26.x` is a non-exact pin in a repo whose convention is exact pins (AC1 / Constraints).** The refinement itself writes "`@types/node` → 26.x". Every other companion is exact; `@types/node` is a range. This may be deliberate (patch-floating the types), but it contradicts "Exact version pins (repo convention)" and should be confirmed, not assumed, so the AC1 pin diff is unambiguous. | Minor | Undetermined | product-engineer (confirm `26.x` range is intentional vs. an exact `26.0.0`-style pin) |

---

## 11. Blocking Gaps

None for Design Mode. All nine ACs are covered by at least one positive + one negative/edge
test (AC9 pre-merge is **uncovered-by-design** — live/human-only, F-03). The traceability
matrix records the full mapping; the `Result` column is intentionally blank (pre-implementation).
