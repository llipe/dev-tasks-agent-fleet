# Issue Refinement: #217 - Upgrade Next.js to 16 and Node.js to the newest LTS

## Changelog

| Version | Date       | Summary            | Author           |
| ------- | ---------- | ------------------ | ---------------- |
| 1.1     | 2026-10-15 | Folded the verifier Design Mode findings: D-13 retarget scope, D-14 exact `@types/node` 26.6.5, D-15 5s fail-closed `getClaims()` timeout (AC2), D-16 route-level image smoke test + `node -v` assertion (AC5) | product-engineer |
| 1.0     | 2026-10-15 | Initial refinement. Supersedes the 2026-09-15 issue body (16.3.5 / Node 24) and the 2026-10-13 scope comment (16.4.0) | product-engineer |

## Summary

- Goal: move the panel to **Next.js 16.4.1** on **Node 26** and modernize its lint config. The auth chokepoint and every deploy guard must keep behaving identically.
- Primary user impact: none intended, since the UI and behavior are unchanged. The two moderate `next <15.5.27` advisories handed over by #252 are cleared (D-01).
- Non-goals:
  - TypeScript 7, ESLint 10, Vitest 5 / coverage-v8 5, `@vitejs/plugin-react` 6 (follow-up #299, D-11)
  - React Compiler, Cache Components / `use cache`, Turbopack-only features
  - any UI change
  - agent (Python) runtimes

## Refined Scope

1. **Next.js (D-01).** `next` and `eslint-config-next` → **16.4.1**, the same exact pin for both.
2. **Companion bumps (D-11).** All exact pins:
   - `react` / `react-dom` → 19.3.1
   - `@types/react` / `@types/react-dom` → 19.3.0
   - `@playwright/test` → 1.64.1
   - `@supabase/supabase-js` → 2.117.3
   - `@types/node` → 26.x

   Nothing else is bumped unless forced by peers; anything forced is noted in the PR.
3. **Node (D-02, D-06).**
   - Pin **26** in `.nvmrc` (root and `panel/`), `.github/workflows/ci.yml` `setup-node`, and `Dockerfile.panel` `ARG NODE_VERSION`.
   - `engines.node` → **`>=24 <27`** in the root and panel `package.json` (`engine-strict=true` stays).
   - Fall back to 24 only if 26 breaks validate / E2E / image smoke / CDK in a way that is unfixable in scope; the evidence goes in the PR.
4. **Auth chokepoint (D-03, D-10, D-12).** Rename `panel/middleware.ts` → `panel/proxy.ts`. It now runs on the Node.js runtime instead of Edge. Preserve verbatim:
   - fail-closed behavior
   - `getClaims()`, never `getSession()`
   - the `config.matcher`
   - the `internal` route-policy branch for `/api/internal/**` (the session gate is declined there, and the handler's shared-secret check authorizes)
   - SD2 (no `lib/supabase/server` import)

   Retarget the tests that name the file: `tests/unit/auth-no-getsession.test.ts` (`AUTHZ_FILES`), `tests/component/middleware-gate.test.ts`, `tests/unit/auth-route-policy.test.ts`, and any E2E/global-setup reference. Test logic stays the same; only file targets and names change.
5. **ESLint (D-04, D-08).** Replace the `FlatCompat` / `@eslint/eslintrc` bridge in `panel/eslint.config.mjs` with v16's native flat config, and drop `@eslint/eslintrc` if it becomes unused. Keep the SD2 `no-restricted-imports` rule and `eslint-server-import.test.ts` passing. **Fix every new finding** (react-hooks v7 included); no rule may be downgraded or disabled. Each behavior-affecting fix needs a test or an explicit PR note.
6. **Other Next 16 breaking changes.** Address each one the build or tests surface, and record any that do not apply:
   - async request APIs (`cookies()` / `headers()` / `params` / `searchParams` already awaited)
   - the inline route-segment configs (`dynamic`, `revalidate`, `fetchCache`) still honored
   - `next.config.ts` keys removed in 16
   - Turbopack as the default `next build`
7. **Carry-over checks (D-05, D-07).**
   - The #280 entrypoint's `setpriv` works on `node:26-slim` (verified to exist: util-linux 2.41.5).
   - The CI image smoke test (PID 1 = uid 1001, serves `:8080`) passes. It also serves as the CI-gated `next build`.
   - Keep the root `pnpm.overrides` unless the regenerated lockfile proves them redundant (16.4.1 still allows `sharp` 0.35.4).
   - The `agents/dependency-update/agentcore/cdk` workspace member installs and tests on Node 26.
8. **Docs.**
   - **ADR-008** (proxy on the Node runtime, with the preserved invariants including the internal-route branch)
   - a `docs/technical-guidelines.md` pin row
   - `panel/README.md` and the runbooks (`middleware.ts` → `proxy.ts`, the Node version)
   - a TESTING.md mention only if commands change
9. **Delivery (D-09).** Merge, then the human-only `scripts/release-panel.sh` tag, then `deploy-panel.yml`. The auth gate (checks 1–5) and the OIDC token probe guard the release.

## Acceptance Criteria

- [ ] AC1: `next` and `eslint-config-next` are 16.4.1. The companion pins match the scope. `.nvmrc` ×2, `ci.yml`, and `Dockerfile.panel` read 26. Both `engines.node` fields read `>=24 <27`. Validation: diff review plus `node -v` in CI logs.
- [ ] AC2: `panel/middleware.ts` no longer exists. `panel/proxy.ts` gates identically: an unauthenticated UI request → 302 `/login`, an unauthenticated SSE request → 401, an authenticated session works, and an unauthenticated `/api/internal/**` request reaches the handler, which returns 401 without the secret. A hung `getClaims()` fails closed within 5s (D-15). The existing gate suites (`middleware-gate`, `auth-route-policy`, `auth-no-getsession`, `internal-secret`) pass with only target or name changes. Validation: unit/component tests plus E2E `auth.spec.ts`.
- [ ] AC3: `pnpm --filter panel run validate` (lint, format:check, typecheck, test, audit) and `pnpm --filter panel run test:e2e` pass on Node 26. `make validate` passes on both branches. Validation: local plus CI.
- [ ] AC4: The ESLint config uses native flat config (no `FlatCompat`). Lint passes with **zero** disabled or downgraded rules relative to `eslint-config-next` 16's recommended set. SD2 is still enforced (`eslint-server-import.test.ts`). Validation: lint plus config diff.
- [ ] AC5: The CI image smoke test passes on `node:26-slim`: the build succeeds, PID 1 runs as uid 1001, the server answers on `:8080`, and a missing `/.fly/api` does not block start; route checks `/`→302, `/login`→200, SSE→401, internal POST→401 (D-16); CI logs `node -v` = v26. Validation: the CI `panel-quality` job.
- [ ] AC6: The panel audit shows **no `next` advisory**, and no new high/critical advisory. Validation: `pnpm --filter panel run audit`.
- [ ] AC7: The CDK workspace member installs and its tests pass on Node 26. Validation: `pnpm --filter ./agents/dependency-update/agentcore/cdk test`.
- [ ] AC8: ADR-008 exists. `technical-guidelines.md`, `panel/README.md`, and the runbooks reference `proxy.ts` and Node 26. Validation: doc review.
- [ ] AC9 (post-merge): the release pipeline deploys, `deploy-panel.sh` exits 0 (auth gate checks 1–5 plus the OIDC probe `status=200 token=present`), and an invoke from the deployed panel reaches `running`. Validation: the release log plus a live run id on #217.

## Constraints

- Exact version pins (repo convention). `pnpm` only.
- The auth gate is the panel's security boundary (ADR-007). Any behavior difference in `proxy.ts` is a blocker, not a deviation.
- No rule downgrades to get green (D-08).
- Release tags and production deploys are human-only.

## Risks and Edge Cases

- **Edge → Node runtime for the gate.** Cookie handling and `getClaims()` network behavior may differ. Edge-only APIs, if any, must be replaced. The E2E auth suite plus release-gate checks 2, 3, and 5 cover it.
- **react-hooks v7 fixes can change render behavior.** Each one needs a component test or a PR note.
- **Node 26 is pre-LTS until 2026-10-28.** If the release happens before then, it ships on Current; this is accepted (D-06).
- **Turbopack is now the default build.** CSS Modules, `standalone` output, and the monorepo `outputFileTracingRoot` must still produce a working `server.js` (the smoke test catches this).
- **`@aws-sdk/*` 3.1126 and `@supabase/ssr` 0.12.7 on Node 26.** Covered by the unit plus E2E suites.

## Dependencies

- #280 (done), #296 scheduler (merged; its `internal` branch is in scope via D-12).
- #299: toolchain majors (filed with this refinement).

## Testing Notes

- Unit/component: the existing suites, retargeted (gate tests, ESLint SD2 test); new tests for behavior-affecting lint fixes.
- Integration: Layer 2.5 suites in CI.
- E2E: the full Playwright suite on Node 26, with `auth.spec.ts` as the gate's acceptance.
- Image: the CI smoke test on `node:26-slim`.
- Manual: local `next build` plus `next start`; protected route → 302, SSE → 401, internal POST → 401, login works.
- AC-to-test mapping: AC1 → diff/CI; AC2 → gate suites + E2E; AC3 → validate + E2E; AC4 → lint + SD2 test; AC5 → smoke; AC6 → audit; AC7 → CDK tests; AC8 → review; AC9 → release log + live invoke.

## Decisions

| ID   | Decision (short form) |
| ---- | --------------------- |
| D-01 | Target Next/eslint-config-next 16.4.1; clears the handed-over `next` advisories |
| D-02 | Node landscape: 24 is current LTS, 26 is LTS on 2026-10-28 |
| D-03 | Rename `middleware.ts` → `proxy.ts`; the runtime moves Edge → Node |
| D-04 | The ESLint `FlatCompat` bridge must go native; react-hooks v7 brings new rules |
| D-05 | Carry-over: `setpriv` on the new image, overrides kept, CDK member |
| D-06 | Pin Node 26; engines `>=24 <27`; fall back to 24 only with evidence |
| D-07 | The image smoke test covers the CI `next build` |
| D-08 | Fix every lint finding in this PR; no downgrades |
| D-09 | Ship via release tag + pipeline (auth gate + OIDC probe) |
| D-10 | ADR-008 for the proxy/Node-runtime chokepoint |
| D-11 | Split: toolchain majors go to a follow-up issue |
| D-12 | Preserve the scheduler `internal` branch; release-gate check 5 must pass |

## Open Questions

- None.
