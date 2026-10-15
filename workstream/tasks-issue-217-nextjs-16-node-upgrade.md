# Implementation Plan - Issue #217: Next.js 16.4.1 + Node 26

> Source: `workstream/issue-217-nextjs-16-node-upgrade-refinement.md`; decisions: `workstream/decisions-nextjs-16-upgrade.md` (D-01..D-12). Single issue, so it runs through `developer` Execute Mode against `main`.

## Relevant Files

- `panel/package.json`, `package.json` - pins, `engines.node`
- `pnpm-lock.yaml` - regenerated
- `.nvmrc`, `panel/.nvmrc` - Node 26
- `.github/workflows/ci.yml` - `setup-node` 26
- `Dockerfile.panel` - `ARG NODE_VERSION=26`; entrypoint/`setpriv` comment
- `panel/middleware.ts` → `panel/proxy.ts` - auth chokepoint
- `panel/lib/auth/route-policy.ts`, `panel/lib/auth/internal-secret.ts`, `panel/lib/supabase/auth-middleware.ts` - read-only unless forced
- `panel/eslint.config.mjs` - native flat config
- `panel/tests/unit/auth-no-getsession.test.ts`, `panel/tests/component/middleware-gate.test.ts`, `panel/tests/unit/auth-route-policy.test.ts`, `panel/tests/e2e/auth.spec.ts`, `panel/tests/e2e/global-setup.ts` - retarget
- `panel/tests/unit/eslint-server-import.test.ts` - must stay green
- `panel/next.config.ts` - Next 16 key changes, if any
- `docs/adr/ADR-008-proxy-node-runtime-auth-chokepoint.md` - new
- `docs/technical-guidelines.md`, `panel/README.md`, `docs/runbooks/panel-deployment.md` - references

## Tasks

- [x] 1.0 Implement Issue #217 - https://github.com/llipe/dev-tasks-agent-fleet/issues/217: Upgrade Next.js to 16.4.1 and Node.js to 26

  - [x] 1.1 [repo root] Baseline: on `main`, under Node 26, run `make validate` and record the current pass state plus the lint baseline. This separates pre-existing failures from upgrade-induced ones (D-06)
  - [x] 1.2 [repo root] Node pins: `.nvmrc` ×2 → `26`; `ci.yml` `setup-node` → `26`; `Dockerfile.panel` `ARG NODE_VERSION=26` (and the `node:22-slim` mention in the entrypoint comment); root and panel `engines.node` → `>=24 <27` (D-06)
  - [x] 1.3 [panel] Bump `next` and `eslint-config-next` to 16.4.1 (exact). Bump the companions: `react`/`react-dom` 19.3.1, `@types/react`/`@types/react-dom` 19.3.0, `@playwright/test` 1.64.1, `@supabase/supabase-js` 2.117.3, `@types/node` **26.6.5** (exact, D-14). Run `pnpm install`, resolve peer warnings, and record any forced extra bump in the PR (D-01, D-11)
  - [x] 1.4 [repo root] Re-evaluate the root `pnpm.overrides` (`sharp`, `source-map-js`, `fast-uri`, `postcss`, `vite`) against the new lockfile. Keep any whose removal would reintroduce an advisory; justify each kept or removed entry in the PR (D-05)
  - [x] 1.5 [panel] Retarget the gate tests to `proxy.ts` **first**: only the real references, i.e. `AUTHZ_FILES` in `auth-no-getsession.test.ts` and the `@/middleware` import + name in `middleware-gate.test.ts` (prose-only mentions in `global-setup.ts`, `auth-middleware.ts`, `auth-server.ts`: comment edits at most; do **not** rename `auth-middleware.ts`). Confirm they fail while `proxy.ts` does not exist (test-first) (D-03, D-13)
  - [x] 1.6 [panel] `git mv panel/middleware.ts panel/proxy.ts`. Apply Next 16's `proxy` export/name requirements. Preserve fail-closed, `getClaims()`, the matcher, the `internal` route-policy branch (`/api/internal/**` declines the session gate and never authorizes), and SD2. Remove any Edge-only API usage (D-03, D-12)
  - [x] 1.6a [panel] Test-first: add `getClaims()` timeout tests to `middleware-gate` (renamed). A never-resolving `getClaims` fails closed within the bound: UI → 302 `/login`, API/SSE → 401; `/api/internal/**` is unaffected; the timer is cleared on settle (no open handle). Then implement the race in `proxy.ts` with an injectable timeout (default 5000 ms) (D-15)
  - [x] 1.6b [repo root] Tighten the CI image smoke test (keep the fake env): `GET /` → 302 to `/login`; `GET /login` → 200; `GET /api/runs/00000000-0000-0000-0000-000000000000/events/stream` → 401; `POST /api/internal/schedules/00000000-0000-0000-0000-000000000000/fire` → 401. Any other code fails. If `/login` cannot 200 without network, apply D-16's fallback and record it. Also add a `node -v` step asserting `v26.` in `panel-quality` (verifier F-02) (D-16)
  - [x] 1.7 [panel] ESLint: replace `FlatCompat`/`@eslint/eslintrc` with `eslint-config-next` 16's native flat exports. Keep the SD2 `no-restricted-imports` block. Remove `@eslint/eslintrc` if unused. `eslint-server-import.test.ts` must pass (D-04)
  - [x] 1.8 [panel] Run `pnpm --filter panel run lint` and **fix every finding**, react-hooks v7 included, with **no rule downgraded or disabled**. For each behavior-affecting fix, add or extend a component test proving the behavior is unchanged, or note the intended change in the PR. Keep a fix ledger in the PR body (rule → file → behavior-affecting? → test/PR note) for the verifier Audit Mode cross-check (D-08, verifier F-04)
  - [x] 1.9 [panel] Resolve Next 16 build/runtime breakages surfaced by `pnpm --filter panel run typecheck` and `next build` (Turbopack): `next.config.ts` keys, async request APIs, route-segment configs, `standalone` + `outputFileTracingRoot`. Record each one that does not apply
  - [x] 1.10 [repo root] Build the image on `node:26-slim` locally and run the CI smoke-test assertions: PID 1 is uid 1001, `:8080` serves, a missing `/.fly/api` does not block startup, and `setpriv` is present (D-05, D-07)
  - [x] 1.11 [agents/dependency-update/agentcore/cdk] `pnpm --filter ./agents/dependency-update/agentcore/cdk install && … test` on Node 26 (AC7)
  - [x] 1.12 [repo root] Docs: write **ADR-008** (proxy.ts on the Node runtime; the preserved invariants, including the internal-route branch and release-gate check 5). Add a `technical-guidelines.md` pin row. Update `panel/README.md` and `docs/runbooks/panel-deployment.md` (`middleware.ts` → `proxy.ts`, Node 26). Update TESTING.md only if commands change (D-10)
  - [x] 1.13 Verify Acceptance Criterion AC1: the pins, `.nvmrc`, CI, Dockerfile, and engines diff
  - [x] 1.14 Verify Acceptance Criterion AC2: the gate suites pass with target/name changes only; a local `next build && next start` manual check (protected route → 302 `/login`, SSE → 401, unauthenticated POST `/api/internal/schedules/<uuid>/fire` → 401, login works)
  - [x] 1.15 Verify Acceptance Criterion AC3: `pnpm --filter panel run validate`, `pnpm --filter panel run test:e2e` (local Supabase stack; Docker available), and `make validate` pass on Node 26
  - [x] 1.16 Verify Acceptance Criterion AC4: native flat config; zero disabled/downgraded rules (diff the effective config against `eslint-config-next` 16's recommended set); SD2 test green
  - [x] 1.17 Verify Acceptance Criterion AC5 and AC6: the CI smoke test passes; the panel audit has no `next` advisory and no new high/critical advisory
  - [x] 1.18 Verify Acceptance Criterion AC8: ADR-008 and the doc references
  - [x] 1.19 AC-to-test mapping recorded in the PR body (AC1→diff/CI, AC2→gate suites+E2E+manual, AC3→validate+E2E, AC4→lint+SD2, AC5→smoke, AC6→audit, AC7→CDK, AC8→review, AC9→release)
  - [ ] 1.20 **Post-merge (human-only tag):** `scripts/release-panel.sh` → approve the production deployment → `deploy-panel.sh` exit 0 (auth gate checks 1–5 plus OIDC probe `status=200 token=present`) (D-09)
  - [ ] 1.21 Verify Acceptance Criterion AC9: an invoke from the deployed panel reaches `running`; record the run id on #217 and close it

## Decisions Consumed

| ID   | Decision (short form) |
| ---- | --------------------- |
| D-01 | Target Next/eslint-config-next 16.4.1 |
| D-03 | `middleware.ts` → `proxy.ts`; Edge → Node runtime |
| D-04 | ESLint `FlatCompat` → native flat config |
| D-05 | Carry-over: `setpriv`, overrides, CDK member |
| D-06 | Node 26 pins; engines `>=24 <27`; fall back to 24 with evidence |
| D-07 | The image smoke test is the CI `next build` |
| D-08 | Fix every lint finding; no downgrades |
| D-09 | Ship via release tag + pipeline |
| D-10 | ADR-008 |
| D-11 | Toolchain majors go to #299 |
| D-12 | Preserve the scheduler `internal` branch; release-gate check 5 |
| D-13 | Retarget only real gate-file references |
| D-14 | `@types/node` exact 26.6.5 |
| D-15 | 5s fail-closed `getClaims()` timeout in `proxy.ts`; recorded in ADR-008 |
| D-16 | Route-level image smoke test + `node -v` assertion |
