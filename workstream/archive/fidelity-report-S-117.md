# Fidelity Report — S-117 Middleware auth gate (the chokepoint)

## 1. Header / Verdict

| Field | Value |
| ----- | ----- |
| **Overall fidelity** | **High** |
| **Highest drift impact** | **Minor** |
| **Scope** | Story S-117 · Issue #156 · PR #165 (draft, base `integration/v2.1-panel-auth`) · branch `story/S-117-middleware-gate` |
| **Mode** | Audit (grey-box) |
| **Result summary** | 5 PRD ACs Pass, 2 story-level ACs Pass, AC14 Pass (by consequence) — 0 Fail, 0 Partial |
| **Blocking gaps** | None. Audit is additive and non-blocking on drift. |

The delivered middleware gate matches the requested intent across every acceptance criterion, spec §7.2 normative ordering, and the reused-module boundary. Drift is limited to Minor, Intended documentation/scope observations that are already tracked for downstream stories.

---

## 2. Human-Readable Summary — what changed and why

The panel previously had no login: anyone who could reach it could use it, and its only protection was that the app was not on the public internet. This story installs a single "front door" that every request must pass through before reaching any page, API, or live-log stream. If you are signed in, you pass through unchanged. If you are not, the door turns you away — a browser page bounces you to the login screen (remembering where you were headed), and a programmatic/API request gets a clean "not authorized" answer instead of a confusing web page.

Two well-known ways to get this subtly wrong were both explicitly avoided:

- **Trusting a spoofable identity.** The gate checks identity using the method that actually re-verifies the login token (`getClaims()`), never the convenience method (`getSession()`) that just trusts whatever the browser cookie says. A permanent automated guard now fails the build if anyone ever wires the weaker method into the security path.
- **Silently logging people out.** Auth tokens get refreshed as you browse. The gate is careful to hand back the exact response object that carries the refreshed token, so sessions don't randomly drop.

The door is also "fail-closed": if the identity check errors out, or a brand-new page is added that nobody classified, the default is to deny (redirect to login) rather than let it through.

Two things are expected and not defects: the login page itself currently returns a 404 because the actual login screen ships in the next story (S-119), and the "12-hour inactivity" expiry is a Supabase dashboard setting rather than panel code — this story proves the *consequence* (an expired cookie is denied), which is the only part that lives in code.

---

## 3. Per-AC Result Table

| AC | Description | Codebase evidence | Workstream evidence | Test evidence | Result |
| -- | ----------- | ----------------- | ------------------- | ------------- | ------ |
| **AC1** (PRD) | Unauth UI route → 302 `/login?redirect=<encoded original path>` | `middleware.ts` `loginUrlFor()` builds `/login` + `redirect=path+search`; denial branch returns `NextResponse.redirect(..., {status:302})` for non-`api` | Story AC row 2; task 2.11; spec §6.2 | `middleware-gate.test.ts`: "302 to /login" + deeply-nested + query round-trip cases (live run: 20/20 pass) | **Pass** |
| **AC2** (PRD) | Unauth `/api/**` incl. SSE → 401 JSON, `content-type: application/json`, never HTML redirect | `unauthorizedJson()` = `NextResponse.json({error:"UNAUTHORIZED"},{status:401})`; api branch selected via `classifyRoute` | Story AC row 3; task 2.12; spec §6.2 | gate suite: `/api/...`, SSE path, `/api` exactly → 401, `content-type` contains `application/json`, `location` null, body `{error:"UNAUTHORIZED"}` | **Pass** |
| **AC7** (PRD) | Authenticated pass-through preserves refreshed cookies | Success path returns `response` (the cookie-handler `NextResponse.next`), **not** a fresh `NextResponse.next()`; `auth-middleware.ts` `setAll` writes onto both request and the returned response | Story AC row 5; spec §7.2 req 2; task 2.5/2.14 | gate suite: refreshed `sb-access-token` present on returned response; concurrent-refresh no-thrash case | **Pass** |
| **AC8** (PRD) | `getClaims()` drives authz; `getSession()` in no authz path | `middleware.ts` calls `supabase.auth.getClaims()` only | Story AC row 4; spec §12; task 2.13 | `auth-no-getsession.test.ts` grep guard (falsifiable + vacuity guards); independent grep across `panel/**` confirms **no** real `.getSession(` call exists (only the guard's own assertions) | **Pass** |
| **AC14** (PRD) | Session past 12h inactivity → denied (302 UI / 401 API) | Expired/invalid cookie yields no claims → same denial branch as no-session | Story AC row 7 + Technical Note (setting, not code); task 2.15 | gate suite: EXPIRED session → 302 (UI) and 401 (SSE); garbage cookie → 302 | **Pass (by consequence)** — see §4 D1 |
| **Story AC** | Matcher excludes `_next/static`, `_next/image`, favicon, image assets; still gates pages/api/SSE | `config.matcher` regex per spec §7.2 verbatim | Story AC row 1; task 2.2 | gate suite asserts the exported matcher regex directly: excludes static/image, matches `/`, `/agents/x`, `/runs/y`, SSE, `/login` | **Pass** |
| **Story AC** | Fail-closed: auth error → unauthenticated; unknown route → `ui` | `try/catch` around `getClaims`; `classifyRoute` returns `ui` for unknown/empty/non-string | Story Business Rules; spec §7.2 req 4, R11; task 2.6/2.16 | gate suite: auth-error → 302/401; thrown `getClaims` → 302; `route-policy` unit suite (S-116) covers unknown→ui | **Pass** |

---

## 4. Drift Catalog

All drift below is **non-blocking to completion** (audit is additive; it does not gate PR/issue completion or replace `test`/`lint`/`format:check`/`typecheck`/`audit`).

### D1 — AC14 verified only by consequence, not by the live 12h setting — **Minor / Intended**
- **Description:** The 12-hour inactivity expiry is a Supabase project (dashboard) setting, not panel code. The delivered tests assert the *code-side consequence* (an expired/invalid cookie yields no claims → denial), never that the live project's inactivity window is actually 12h.
- **Evidence:** `middleware-gate.test.ts` "expired / invalid session (AC14 consequence)" block; spec §7.5 FR14 note; story Technical Note explicitly scopes the testable surface to the consequence.
- **Why Intended:** This is the design decision recorded in the story and spec, not a shortfall. The live-setting confirmation is correctly deferred to the S-123 Supabase checklist and the S-122 release gate.
- **Recommendation:** No action in S-117. Ensure the S-123 operator checklist and `verify-panel-auth.sh` confirm the 12h window on the live project.

### D2 — `/login` returns 404 (login page not yet built) — **Minor / Intended**
- **Description:** The gate correctly classifies `/login` as `public` and short-circuits before any auth work, but the route itself 404s because the login screen lands in S-119.
- **Evidence:** Manual verification (`GET /login` → 404, passed the gate); gate suite proves `/login` is public and `getClaims` is not called; `classifyRoute` returns `public` for `/login`.
- **Why Intended:** Story dependency graph sequences S-119 after S-117; the 404 is a pre-S-119 artifact, not a gate defect.
- **Recommendation:** No action. Resolves naturally when S-119 merges.

### D3 — Production client factory (`defaultMiddlewareClientFactory`) not unit-covered — **Minor / Intended**
- **Description:** `coverage_gate` reports 100% on `middleware.ts`; the only uncovered region is the declarative `defaultMiddlewareClientFactory` in `auth-middleware.ts` (the real `@supabase/ssr` cookie adapter), an accepted documented gap requiring live Supabase.
- **Evidence:** qa-engineer `coverage_gate: PASS`; the injectable-factory DI seam (spec §7.2 testing requirement) deliberately isolates the untestable-without-network adapter.
- **Why Intended:** Matches the project's established DI-for-testability posture (same as `lib/sse/relay.ts`); the adapter is exercised by the Layer 2.5 `auth-login` integration suite scheduled in S-119.
- **Recommendation:** No action in S-117. The S-119 Layer 2.5 login suite exercises the production adapter against the local stack.

### D4 — OQ1 handling is broader than strictly required — **Minor / Intended (over-delivery)**
- **Description:** `getClaims()` is awaited (network-agnostic) even though spec OQ1 was resolved to asymmetric ES256/EC keys (local JWKS verification, no per-request network call). The code comment documents both paths.
- **Evidence:** `middleware.ts` OQ1 docstring; spec §11 / §17 OQ1 (resolved 2026-09-09).
- **Why Intended:** Defensive correctness — the awaited call remains correct if the project ever moves to symmetric HS256 keys. No cost on the hot path today.
- **Recommendation:** No action.

**No Unintended or Undetermined drift was found.**

---

## 5. Grey-Box Cross-Check (four sources)

| Source | Finding |
| ------ | ------- |
| **Codebase implementation** | The four artifacts are the only code changed vs base (`git diff --name-status integration/v2.1-panel-auth...`): `middleware.ts`, `auth-middleware.ts`, and two test files, plus the task-list checkbox update. Normative spec §7.2 ordering (classify → public short-circuit → cookie client → `getClaims` → 302/401 → success returns cookie response) is implemented exactly. |
| **`/workstream` artifacts** | Task 2.0 subtasks 2.1–2.19 checked; only 2.20 (issue-checklist update / story-complete) open — consistent with an in-flight draft PR. Story ACs, spec §6.2/§7.2/§7.3/§8.4/§11/§12/§12.1 all trace to delivered behavior. |
| **Test suite vs ACs** | Verified live: `pnpm run test:unit` → 607 passed / 4 skipped; full `pnpm run test` → 844 passed / 44 skipped; `middleware-gate.test.ts` 20/20; `auth-no-getsession.test.ts` 3/3. Skipped suites are Docker-gated Layer 2.5 + the `RUN_BUNDLE_SECRET_TEST`-gated bundle test (expected locally). Each AC maps to at least one positive and one negative/edge case. |
| **PRD/spec intent** | Claims 1–7 all confirmed. Independent grep confirms `getClaims` is the sole authz call and no real `getSession()` call exists. `server.ts`, `lib/sse/relay.ts`, and the `app/(panel)/` route group are byte-untouched by this branch (S-118 owns the route-group move). |

### Verification of the seven stated claims
1. **getClaims drives authz; getSession absent (falsifiable guard).** Confirmed — grep + live guard test (guard proves it bites a real call and ignores prose).
2. **Fail-closed (thrown/errored → unauthenticated; unknown route → `ui`).** Confirmed — `try/catch` + `classifyRoute` default; reused from S-116, not reimplemented.
3. **Success returns cookie-handler response (AC7).** Confirmed — returns `response`, not a fresh `NextResponse.next()`.
4. **Matcher excludes static/image, gates pages/api/SSE.** Confirmed — matcher regex asserted directly in tests.
5. **401 carries JSON content-type + `{"error":"UNAUTHORIZED"}`; never HTML redirect for api.** Confirmed.
6. **Reuses S-116 `classifyRoute`; does not touch `server.ts`, `(panel)` group, or `relay.ts` sequencing.** Confirmed by diff.
7. **OQ1: `getClaims()` awaited (network-agnostic).** Confirmed.

### Developer evidence re-verification (verify, don't trust)
- `pnpm run test:unit` and `pnpm run test` re-run live in this audit — both green, counts consistent with the developer's "846 panel tests" (the small delta is the 4 gated `bundle-secrets` tests + integration skips).
- `middleware.ts` structure (factory + default export + config matcher) confirmed programmatically.
- Manual 302/401 and `/login` 404 outcomes are consistent with the code paths audited; the login 404 is expected pre-S-119.

---

## 6. Recommendations (per drift item)

| Item | Recommended next step | Owner |
| ---- | --------------------- | ----- |
| D1 (AC14 live setting) | Confirm 12h inactivity on the live project via the S-123 checklist + `verify-panel-auth.sh` | `product-engineer` (route to S-123 checklist) — no code change |
| D2 (`/login` 404) | None — resolves when S-119 ships the login screen | — |
| D3 (production factory coverage) | Exercise the real adapter via the S-119 Layer 2.5 `auth-login` suite | `qa-engineer` in S-119 — no action here |
| D4 (OQ1 breadth) | None — accepted defensive over-delivery | — |

No `developer` remediation and no `product-engineer` spec-clarification are required for S-117 itself. The gate is faithful to the requested intent.
