## Summary

Migrate the panel's browser/auth Supabase client off the **legacy `anon` JWT key** and onto Supabase's **new publishable API key** (`sb_publishable_…`). Supabase now treats the classic `anon` / `service_role` JWT keys as **legacy** and recommends the new API-key format (publishable for client-side, secret for server-side). New keys can be created at:
https://supabase.com/dashboard/project/hegxeycmbmjfgzqpdiik/settings/api-keys/new

This is a **panel-side tech-debt / hardening** follow-up to the Phase A auth wave (S-116…S-122). It is **not** a Phase A blocker: the panel works today on the legacy `anon` key, and the migration is deliberately sequenced so it can be verified privately before Phase B (go-public, S-123).

## Motivation

- **Alignment with Supabase's current guidance.** The `anon` key is now the *legacy* client credential; publishable keys are the forward path and unlock per-key management.
- **Revocability & rotation.** Legacy `anon`/`service_role` are two coarse, effectively unrotatable JWTs (rotating them rotates the project's JWT secret and invalidates all sessions). Publishable/secret API keys can be created, named, and **revoked individually** without a project-wide session bust — materially better key hygiene ahead of Phase B, when the Auth surface becomes internet-reachable.
- **Clear split of families.** Publishable (client) vs secret (server) makes the panel's existing SA1 boundary — anon/publishable for auth in the browser, service-role/secret for server-only data reads — explicit in the credential names themselves.

## Current state (grounded)

The panel already isolates the client credential behind one read path, so the blast radius is small:

- `panel/lib/supabase/auth-env.ts` — `readAuthEnv()` reads `NEXT_PUBLIC_SUPABASE_URL` + `NEXT_PUBLIC_SUPABASE_ANON_KEY`, throws `AuthConfigError` on missing/blank/malformed. **Single source of the client key.**
- `panel/lib/supabase/browser.ts` — `createBrowserAuthClient()` → `createBrowserClient(url, anonKey)`.
- `panel/lib/supabase/auth-server.ts` — `createAuthServerClient()` → `createServerClient(url, anonKey, …)` (cookie-backed).
- `panel/lib/supabase/server.ts` — the **service-role data client** (SD2/D15). MUST remain byte-unchanged in this migration; its secret-key migration (legacy `service_role` → new **secret** API key) is a *separate* concern and can be split out if desired.
- Env / config references to the anon name: `panel/.env.local`, `panel/README.md`, `panel/playwright.config.ts`, `panel/tests/e2e/global-setup.ts`, `panel/tests/integration/auth-login.test.ts`, `panel/scripts/panel-auth-check.mjs` (`REQUIRED_AUTH_ENV_NAMES`), and the unit tests `panel/tests/unit/{auth-env,panel-auth-check,panel-auth-check-cli}.test.ts`.
- Operator runbook: `docs/runbooks/panel-deployment.md` (env-delivery note + Supabase config checklist item #5) references the anon key by name.

Confirmed the project is still on the **legacy** format: `panel/.env.local` currently holds an `anon`-role JWT (`"role":"anon"`), not an `sb_publishable_…` key.

> Compatibility note to verify during implementation: `@supabase/ssr` `createBrowserClient`/`createServerClient` accept the publishable key in the same key position as the anon key. Confirm the pinned `@supabase/ssr` / `@supabase/supabase-js` versions accept the `sb_publishable_…` format (bump if the installed versions predate publishable-key support).

## Proposed approach

Introduce a **new env name** for the publishable key and accept the legacy anon name as a deprecated fallback for one release, so local/CI/deploy environments can cut over independently without a flag day.

- Preferred new name: `NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY`.
- `readAuthEnv()` resolves `NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY` first, then falls back to `NEXT_PUBLIC_SUPABASE_ANON_KEY` with a one-time deprecation warning; `AuthConfigError` only when **neither** is present.
- The auth-release gate (`panel/scripts/panel-auth-check.mjs` `REQUIRED_AUTH_ENV_NAMES`) accepts **either** name as satisfying the "publishable client key present" check (still names only, never values — SD2 preserved).
- Once all environments (local `.env.local`, CI, Fly `[env]`/secrets) carry the new key, remove the anon fallback in a follow-up and delete the deprecated name.

Explicitly out of scope (may be split into a sibling issue): migrating the **server** data client in `server.ts` from the legacy `service_role` JWT to a new **secret** API key. Keeping this issue client-only keeps the change reviewable and preserves the byte-unchanged `server.ts` invariant.

## Acceptance criteria

- [ ] A new publishable API key is created for project `hegxeycmbmjfgzqpdiik` (operator action, via the dashboard link above) — recorded by **name only**, never the value.
- [ ] `readAuthEnv()` resolves the publishable key from `NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY`, falling back to the legacy `NEXT_PUBLIC_SUPABASE_ANON_KEY` with a deprecation warning; throws `AuthConfigError` only when neither is set.
- [ ] `createBrowserAuthClient()` and `createAuthServerClient()` create working clients with a `sb_publishable_…` key (login, session refresh, logout all verified).
- [ ] The service-role data client (`panel/lib/supabase/server.ts`) is **byte-unchanged** (`git diff --exit-code`), and the SD2 boundary holds — no publishable/secret key crosses the client/server line the wrong way.
- [ ] The auth-release gate accepts the new env name (either name satisfies the client-key-present check); `scripts/verify-panel-auth.sh` still exits 0 against a private host.
- [ ] `panel/README.md` env table + `docs/runbooks/panel-deployment.md` (env-delivery note + Supabase checklist #5) document the publishable key as preferred and the anon key as legacy/deprecated.
- [ ] `panel/.env.local` guidance, `panel/playwright.config.ts`, `panel/tests/e2e/global-setup.ts`, and `panel/tests/integration/auth-login.test.ts` are updated to prefer the new name.
- [ ] Tests updated: `auth-env` covers new-name resolution + legacy fallback + neither-set failure; `panel-auth-check` covers either-name acceptance.
- [ ] `pnpm run audit` green at `--audit-level=high` if `@supabase/ssr`/`supabase-js` are bumped for publishable-key support.
- [ ] `pnpm run validate` (lint, format:check, typecheck, test, audit) and `pnpm run build` pass; `pnpm run test:e2e` passes with the local stack.
- [ ] Migration opt-out documented: no schema/data-model change (auth state stays in Supabase-managed `auth.*` + cookies).

## Testing

- Unit: `panel/tests/unit/auth-env.test.ts` (new-name preferred, legacy fallback + deprecation path, neither → `AuthConfigError`), `panel/tests/unit/panel-auth-check.test.ts` + `panel-auth-check-cli.test.ts` (either env name satisfies the gate).
- Integration/E2E: `auth-login.test.ts` and the Playwright auth flow pass with the publishable key set in `global-setup.ts` / `playwright.config.ts`.
- Manual: sign in → dashboard renders → session refresh across navigation → logout returns to `/login`, all with the `sb_publishable_…` key.

## Operator notes (for the runbook)

- Create the publishable key at the dashboard link; deliver it via `panel/fly.toml [env]` (publishable is browser-safe, RLS-bound) or `fly secrets` — same delivery options as the anon key today.
- Once the deployed panel is confirmed working on the publishable key, **revoke the legacy anon key** as a distinct, recorded step (this is the payoff — individual revocation without a project-wide session bust).

## References

- Supabase API keys (new): https://supabase.com/dashboard/project/hegxeycmbmjfgzqpdiik/settings/api-keys/new
- Related: #161 (S-122 auth release gate), #162 (S-123 go public), `docs/runbooks/panel-deployment.md`, spec §7.1 (auth clients), SA1/SD2/D15 (credential-family boundary).
