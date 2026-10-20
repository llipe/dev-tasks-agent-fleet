# Traceability Matrix — Issue #217 (Next.js 16.4.1 + Node 26 + `proxy.ts`)

> **Mode:** Design (pre-implementation). **Agent:** verifier.
> **Companion:** `workstream/test-plan-issue-217.md`.
> **`Result` column is intentionally blank** — populated in Audit Mode after implementation.
> Mapping rule (verifier §Non-Negotiable 4): every AC maps to ≥1 positive **and** ≥1
> negative/edge test. Test IDs reference the plan's §3 (E2E), §4 (SEC), §5 (CON), §7 (RT),
> §8 (V).

## AC → Test Coverage

| AC | Positive tests | Negative / edge tests | Layer(s) | Result |
| -- | -------------- | --------------------- | -------- | ------ |
| **AC1** (pins / Node 26 / engines) | V-01, V-02, V-03 | F-02 (CI runs on 26, not just edited); F-08 (`@types/node` range) | diff / CI | |
| **AC2** (`proxy.ts` gates identically; suites pass retargeted) | E2E-02, E2E-07, SEC-07, SEC-11, SEC-15, SEC-16, CON-05 | SEC-01, SEC-02, SEC-03, SEC-04, SEC-05, SEC-06, SEC-09, SEC-10, SEC-12, SEC-14, SEC-20, CON-01, CON-02, CON-07 | unit, component | |
| **AC3** (`validate` + `test:e2e` + `make validate` on Node 26) | E2E-01..E2E-09 (pass), V-04 | E2E-03 (off-origin redirect), E2E-04 (invalid creds), E2E-06 (loop guard) | local + CI | |
| **AC4** (native flat config; zero downgrades; SD2) | V-05, V-06 | SEC-10 (SD2 scope boundary via fixtures), F-04 (behavior-affecting fix needs test), V-11 | lint + unit | |
| **AC5** (image smoke on `node:26-slim`) | V-07 (build + `:8080` + uid/gid 1001 + `setpriv`) | V-07 missing-`/.fly/api` path; F-06 (trace completeness beyond `/`) | CI image smoke | |
| **AC6** (audit: no `next` / no new high-crit) | V-08 | V-08 unreachable-registry soft-pass (failure-mode edge) | audit | |
| **AC7** (CDK member on Node 26) | V-09 | V-09 install failure fails the job | CDK tests | |
| **AC8** (ADR-008 + doc refs) | V-10 (ADR-008 present; `proxy.ts`/Node 26 refs) | V-10 grep for stale `middleware.ts` references = none | doc review | |
| **AC9** (post-merge release; live invoke) | V-12 (checks 1–5 + OIDC `status=200 token=present`; invoke → `running`) | SEC-13, SEC-17, SEC-18, SEC-19 (live release-gate negatives) | release gate (human-only) | |

## Contract Scenarios → AC

| Contract ID | Description | AC | Result |
| ----------- | ----------- | -- | ------ |
| CON-01 | every `classifyRoute` value has a `proxy.ts` branch | AC2 | |
| CON-02 | unknown/empty/non-string path → `ui` (fail-closed) | AC2 | |
| CON-03 | four policy classes partition matched path space | AC2 | |
| CON-04 | gate calls only `getClaims`, never `getSession` | AC2 | |
| CON-05 | success returns the factory response (cookie threading) | AC2 | |
| CON-06 | `createMiddlewareClient` `{supabase,response}` shape unchanged on Node | AC2 | |
| CON-07 | `internal` branch pass-through, never a 200 body | AC2 | |
| CON-08 | handler denies on missing/empty/wrong/unconfigured secret | AC2, AC9 | |
| CON-09 | reason strings never surface secret material | AC2 | |
| CON-10 | live `/api/internal/**` → 401 (CON-07 + CON-08 composed) | AC9 | |

## Security-Negative Set → AC (Edge → Node runtime move)

| SEC ID | Condition | AC | Result |
| ------ | --------- | -- | ------ |
| SEC-01 | `getClaims` error, UI → 302 | AC2 | |
| SEC-02 | `getClaims` error, API → 401 | AC2 | |
| SEC-03 | `getClaims` throws, UI → 302 (caught) | AC2 | |
| SEC-04 | `getClaims` throws, API → 401 (caught) | AC2 | |
| SEC-05 | `getClaims` never resolves / timeout → deny (see F-05) | AC2 | |
| SEC-06 | expired/invalid/garbage cookie → denied | AC2 | |
| SEC-07 | refreshed cookie carried on returned response | AC2 | |
| SEC-08 | concurrent near-expiry: verify once, no thrash | AC2 | |
| SEC-09 | zero `getSession()` in authz surface (`proxy.ts` named) | AC2 | |
| SEC-10 | matcher excludes static assets | AC2 | |
| SEC-11 | matcher gates pages/api/SSE/`/api/internal/**` | AC2 | |
| SEC-12 | `internal` declines gate, never returns 200 | AC2, AC9 | |
| SEC-13 | live unauth POST `/api/internal/**` → 401 | AC9 | |
| SEC-14 | `/api/internalish` stays `api` | AC2 | |
| SEC-15 | `/login` public short-circuit, no `getClaims` | AC2 | |
| SEC-16 | exact `/api/auth/logout` public; siblings stay `api` | AC2 | |
| SEC-17 | live unauth protected GET → 302 | AC9 | |
| SEC-18 | live unauth SSE GET → 401 | AC9 | |
| SEC-19 | live attempted signUp rejected | AC9 | |
| SEC-20 | redirect same-origin, no `0.0.0.0` leak under Node | AC2 | |

## Randomized Tactics → AC

| RT ID | Property | Seed | AC | Result |
| ----- | -------- | ---- | -- | ------ |
| RT-01 | route-policy fuzz: total function, fail-closed to `ui` | 217 | AC2 | |
| RT-02 | matcher ↔ policy coherence (no gated-but-unclassified; no excluded-but-sensitive) | 217 | AC2 | |
| RT-03 | secret-check fuzz: `ok` iff exact, no throw, no secret leak | 217 | AC2, AC9 | |

## Existing Test Inventory → Retarget Action

| File | Current target | Retarget action | Logic change? |
| ---- | -------------- | --------------- | ------------- |
| `tests/component/middleware-gate.test.ts` | `@/middleware`, `config` | import from `@/proxy` (name only) | none |
| `tests/unit/auth-route-policy.test.ts` | `@/lib/auth/route-policy` | none (policy unchanged) | none |
| `tests/unit/auth-no-getsession.test.ts` | `AUTHZ_FILES = ["middleware.ts", …]` | change literal to `"proxy.ts"` | none |
| `tests/unit/internal-secret.test.ts` | `@/lib/auth/internal-secret` | none | none |
| `tests/unit/eslint-server-import.test.ts` | `eslint.config.mjs` (SD2) | none; must pass under native flat config | none |
| `tests/e2e/auth.spec.ts` | behavior via browser | none (behavioral) | none |
| `tests/e2e/global-setup.ts` | prose comment only (F-01) | comment edit at most — **no import** | none |
| `.github/workflows/ci.yml` smoke step | `node:22`-built image → 26 | bump `setup-node` + base to 26 (F-02) | n/a |
| `scripts/verify-panel-auth.sh` checks 1–5 | deployed app | none; must pass post-rename (check 5 = SEC-13) | none |

## Coverage Status

- **Covered (pre-merge, mechanically):** AC1, AC2, AC3, AC4, AC5, AC6, AC7, AC8.
- **Uncovered pre-merge by design:** AC9 (live, human-only release + invoke — F-03).
- Every mechanically-testable AC has ≥1 positive and ≥1 negative/edge test. No blocking gaps.
