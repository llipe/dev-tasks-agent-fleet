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

- [ ] 1.0 Implement Issue #172 - https://github.com/llipe/dev-tasks-agent-fleet/issues/172: Migrate panel client auth off legacy anon key to publishable API keys

  - [ ] 1.1 Update `readAuthEnv()` in `auth-env.ts`: resolve `NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY` first, fall back to `NEXT_PUBLIC_SUPABASE_ANON_KEY` with a one-time deprecation warning, throw `AuthConfigError` only when neither is present. Keep URL validation unchanged. Return a `publishableKey` field (retain `anonKey` alias if needed for callers) and update the doc comment.
  - [ ] 1.2 Update `browser.ts` and `auth-server.ts` to consume the resolved publishable key from `readAuthEnv()` without behavior change; refresh doc comments to publishable-first wording.
  - [ ] 1.3 Update `panel-auth-check.mjs` so the env-name check accepts **either** `NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY` or `NEXT_PUBLIC_SUPABASE_ANON_KEY` as satisfying the client-key-present check (names only, never values — SD2 preserved). Keep fail-closed behavior.
  - [ ] 1.4 Update `auth-env` unit tests: new-name preferred, legacy fallback emits deprecation + still resolves, neither → `AuthConfigError`. (Test-first for the resolution behavior.)
  - [ ] 1.5 Update `panel-auth-check` + `panel-auth-check-cli` unit tests: either env name satisfies the gate; correct-deployment fixtures pass under the new name; missing-both still fails closed.
  - [ ] 1.6 Update E2E/integration env wiring to prefer the new name: `playwright.config.ts` (`webServer.env` forward), `tests/e2e/global-setup.ts` (export), `tests/integration/auth-login.test.ts` (set for the auth clients), falling back to the legacy name.
  - [ ] 1.7 Update `panel/.env.local` guidance and `panel/README.md` env table: publishable key preferred, anon key legacy/deprecated (no key values committed).
  - [ ] 1.8 Update `docs/runbooks/panel-deployment.md`: env-delivery note + Supabase config checklist #5 document the publishable key as preferred, anon as legacy, and add the post-cutover "revoke the legacy anon key" step.
  - [ ] 1.9 Verify AC: `readAuthEnv()` resolves publishable → legacy fallback → `AuthConfigError` (unit tests green).
  - [ ] 1.10 Verify AC: `createBrowserAuthClient()` / `createAuthServerClient()` work with an `sb_publishable_…` key (Layer 2.5 `auth-login` — login/refresh/logout).
  - [ ] 1.11 Verify AC: `panel/lib/supabase/server.ts` is byte-unchanged (`git diff --exit-code`), SD2 boundary holds (no publishable/secret key crosses the client/server line).
  - [ ] 1.12 Verify AC: the auth-release gate accepts the new name (unit + CLI); `scripts/verify-panel-auth.sh` still exits 0 against a private host (parser fixture path, live probe operator-gated).
  - [ ] 1.13 Verify AC: docs (`README.md`, runbook) document publishable preferred / anon legacy.
  - [ ] 1.14 Verify AC: `audit` green at `--audit-level=high` (no dependency bump needed — versions already support publishable keys).
  - [ ] 1.15 Verify AC: migration opt-out documented (this file).
  - [ ] 1.16 Run quality gates: `pnpm run validate` (lint, format:check, typecheck, test, audit) and `pnpm run build`.
  - [ ] 1.17 Run E2E: `pnpm run test:e2e` with the local stack (Docker-gated; record result).
  - [ ] 1.18 AC-to-tests mapping: confirm every AC has an automated or documented-manual verification and record it.
