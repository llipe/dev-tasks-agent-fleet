# Implementation Plan - Issue #172: Migrate panel client auth off legacy anon key to publishable API keys

> Source: GitHub issue #172 — https://github.com/llipe/dev-tasks-agent-fleet/issues/172
> Refinement: `workstream/issue-migrate-publishable-api-keys.md`
> Mode: Issue Mode (single refined issue). Execution: pre-approved autonomous sequential.

## Migration opt-out (documented)

No schema/data-model change. Auth state remains in Supabase-managed `auth.*` plus session
cookies; this is a client-credential env-name migration only. Migration lifecycle tasks are
therefore intentionally omitted per the documented opt-out.

## Compatibility note (verified during planning)

`@supabase/ssr` is pinned/installed at **0.12.7** and `@supabase/supabase-js` at **2.114.0** — both
well past `sb_publishable_…` support, which is accepted in the same key position as the anon key. **No
dependency bump is required**, so the `audit`-after-bump AC is satisfied by the existing green `audit`.

## Server-client invariant (must hold)

`panel/lib/supabase/server.ts` (service-role data client, SD2/D15) MUST remain **byte-unchanged**
(`git diff --exit-code panel/lib/supabase/server.ts`). Migrating the server data client to a new
*secret* API key is explicitly out of scope.

## Relevant Files

- `panel/lib/supabase/auth-env.ts` - `readAuthEnv()`: resolve `NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY` first, fall back to legacy `NEXT_PUBLIC_SUPABASE_ANON_KEY` with a one-time deprecation warning; `AuthConfigError` only when neither is set.
- `panel/lib/supabase/browser.ts` - consumes `readAuthEnv()`; rename local binding away from `anonKey` semantics (publishable key).
- `panel/lib/supabase/auth-server.ts` - consumes `readAuthEnv()`; same key-name update.
- `panel/scripts/panel-auth-check.mjs` - `REQUIRED_AUTH_ENV_NAMES` / env-name check accepts **either** publishable or legacy anon name.
- `panel/tests/unit/auth-env.test.ts` - new-name preferred, legacy fallback + deprecation, neither → `AuthConfigError`.
- `panel/tests/unit/panel-auth-check.test.ts` - either env name satisfies the client-key-present check.
- `panel/tests/unit/panel-auth-check-cli.test.ts` - CLI contract still passes with the new env name.
- `panel/playwright.config.ts` - forward the publishable name (prefer new, fall back to legacy).
- `panel/tests/e2e/global-setup.ts` - export the publishable name for the webServer.
- `panel/tests/integration/auth-login.test.ts` - set the publishable name for the auth clients.
- `panel/.env.local` - guidance/example prefers the new name (value not committed).
- `panel/README.md` - env table documents publishable key preferred, anon key legacy/deprecated.
- `docs/runbooks/panel-deployment.md` - env-delivery note + Supabase checklist #5 document the publishable key.
- `panel/lib/supabase/server.ts` - MUST be byte-unchanged (invariant check only).

## Tasks

- [x] 1.0 Implement Issue #172 - https://github.com/llipe/dev-tasks-agent-fleet/issues/172: Migrate panel client auth off legacy anon key to publishable API keys

  - [x] 1.1 Update `readAuthEnv()` in `auth-env.ts`: resolve `NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY` first, fall back to `NEXT_PUBLIC_SUPABASE_ANON_KEY` with a one-time deprecation warning, throw `AuthConfigError` only when neither is present. Keep URL validation unchanged. Return a `publishableKey` field (retain `anonKey` alias if needed for callers) and update the doc comment.
  - [x] 1.2 Update `browser.ts` and `auth-server.ts` to consume the resolved publishable key from `readAuthEnv()` without behavior change; refresh doc comments to publishable-first wording.
  - [x] 1.3 Update `panel-auth-check.mjs` so the env-name check accepts **either** `NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY` or `NEXT_PUBLIC_SUPABASE_ANON_KEY` as satisfying the client-key-present check (names only, never values — SD2 preserved). Keep fail-closed behavior.
  - [x] 1.4 Update `auth-env` unit tests: new-name preferred, legacy fallback emits deprecation + still resolves, neither → `AuthConfigError`. (Test-first for the resolution behavior.)
  - [x] 1.5 Update `panel-auth-check` + `panel-auth-check-cli` unit tests: either env name satisfies the gate; correct-deployment fixtures pass under the new name; missing-both still fails closed.
  - [x] 1.6 Update E2E/integration env wiring to prefer the new name: `playwright.config.ts` (`webServer.env` forward), `tests/e2e/global-setup.ts` (export), `tests/integration/auth-login.test.ts` (set for the auth clients), falling back to the legacy name.
  - [x] 1.7 Update `panel/.env.local` guidance and `panel/README.md` env table: publishable key preferred, anon key legacy/deprecated (no key values committed).
  - [x] 1.8 Update `docs/runbooks/panel-deployment.md`: env-delivery note + Supabase config checklist document the publishable key as preferred, anon as legacy, and add the post-cutover "revoke the legacy anon key" step. (Also updated `scripts/verify-panel-auth.sh` to prefer the publishable env var.)
  - [x] 1.9 Verify AC: `readAuthEnv()` resolves publishable → legacy fallback → `AuthConfigError` (unit tests green — `tests/unit/auth-env.test.ts`, 11 tests).
  - [x] 1.10 Verify AC: `createBrowserAuthClient()` / `createAuthServerClient()` work with an `sb_publishable_…` key (Layer 2.5 `auth-login` ran live with `NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY` set — 4/4; login + cookie round-trip via `getClaims()` + wrong-password + RLS-deny-all-unchanged).
  - [x] 1.11 Verify AC: `panel/lib/supabase/server.ts` is byte-unchanged (`git diff --exit-code` clean), SD2 boundary holds (no publishable/secret key crosses the client/server line).
  - [x] 1.12 Verify AC: the auth-release gate accepts the new name (unit + CLI + parser fixture: publishable → exit 0, legacy anon → exit 0, neither → exit 1). Live `scripts/verify-panel-auth.sh` private-host probe is operator-gated (runbook Phase A step 5).
  - [x] 1.13 Verify AC: docs (`README.md`, runbook) document publishable preferred / anon legacy.
  - [x] 1.14 Verify AC: `audit` green at `--audit-level=high` (no dependency bump needed — `@supabase/ssr` 0.12.7 / `supabase-js` 2.114.0 already support publishable keys).
  - [x] 1.15 Verify AC: migration opt-out documented (this file).
  - [x] 1.16 Run quality gates: `pnpm run validate` (lint, format:check, typecheck, test — 957 passed / 49 Docker-gated skips, audit) and `pnpm run build` (green; `/login` dynamic).
  - [x] 1.17 Run E2E: `pnpm run test:e2e` with the local stack — 19/19 passed (Node 22 via nvm, `PW_CHANNEL=chrome`).
  - [x] 1.18 AC-to-tests mapping recorded (see below).

## Acceptance-criteria → verification mapping

| Issue AC | Verified by |
| --- | --- |
| Publishable key created (operator, name-only) | Operator action — documented in runbook checklist #6; not code |
| `readAuthEnv()` publishable → legacy fallback + deprecation → error-if-neither | `tests/unit/auth-env.test.ts` (11 tests, incl. one-time deprecation + neither→`AuthConfigError`) |
| Browser/auth-server clients work with `sb_publishable_…` | `tests/integration/auth-login.test.ts` (Layer 2.5, ran live, 4/4) + E2E auth flow (19/19) |
| `server.ts` byte-unchanged, SD2 holds | `git diff --exit-code panel/lib/supabase/server.ts` (clean) |
| Auth-release gate accepts new name; wrapper exits 0 (private) | `tests/unit/panel-auth-check.test.ts` + `panel-auth-check-cli.test.ts` + live parser fixtures; wrapper prefers publishable env var (live private probe operator-gated) |
| README + runbook document publishable preferred / anon legacy | `panel/README.md` env table, `docs/runbooks/panel-deployment.md` (env note + checklist #6 + revoke step) |
| `.env.local`, playwright config, global-setup, auth-login prefer new name | Edited; E2E + Layer 2.5 ran live under the new name |
| Tests updated (auth-env + panel-auth-check either-name) | `tests/unit/{auth-env,panel-auth-check,panel-auth-check-cli}.test.ts` |
| `audit` green at `--audit-level=high` | `pnpm run audit` (no advisories ≥ high); no dependency bump needed |
| `validate` + `build` + `test:e2e` pass | `pnpm run validate` green; `pnpm run build` green; `pnpm run test:e2e` 19/19 |
| Migration opt-out documented | This file (no schema/data-model change; auth state in Supabase `auth.*` + cookies) |

## Environment note

Local Node is v26.7.0, which is outside the panel's `engines.node >=22 <25`. Gates were run under
Node **v22.23.2** via the existing nvm install (`.nvmrc` pins `22`); pnpm 10.11.0. E2E used
`PW_CHANNEL=chrome` because the bundled `chromium_headless_shell` was not provisioned locally (full
`chromium-1194` was) — functionally equivalent per the Playwright config note.

## Untracked-artifact note (pre-existing, not from this work)

Two untracked files unrelated to #172 exist in the working tree — `panel/scripts/fly-privacy-check 2.mjs`
and `panel/tests/unit/fly-privacy-check-cli.test 2.ts` (accidental " 2" copies of S-115 privacy-gate
files that S-122 removed). Left untouched and unstaged; flagged for cleanup outside this issue.
