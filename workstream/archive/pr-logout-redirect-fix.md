## What

Three related panel fixes discovered during the Phase A live deploy:

1. **Auth redirects use a relative `Location`** so **logout** (and the middleware's unauthenticated `/login` redirect) work behind Fly's reverse proxy.
2. **Node pinned to 22** via `.nvmrc` + tightened `engines` so the toolchain can't run on Node 26 (which breaks the Next.js 15.5 CLI).
3. **Runbook marks `SUPABASE_URL` as required** (docs) — the missing-env that crashed the dashboard after login.

No product behavior change beyond the redirect fix; no schema/data/API change (migration is an N/A opt-out).

## 1. Auth redirect fix (`fix(panel)`)

On the deployed panel, clicking **Log out** sent the browser to `http://0.0.0.0:8080/login` — unreachable — instead of `/login`.

Root cause: the logout handler built `new URL("/login", request.url)` and the middleware built `new URL("/login", request.nextUrl.origin)`. Behind a reverse proxy like Fly, the Node server binds to `HOSTNAME=0.0.0.0:8080`, so that origin is the **internal listener**, not the public host the browser used, and `request.url` does not carry the forwarded host. A relative `Location` is same-origin by definition and immune to the bind address.

- `panel/app/api/auth/logout/route.ts` — return a relative `Location: /login`; the handler no longer needs `request`.
- `panel/middleware.ts` — `loginUrlFor` → `loginTargetFor`, returning a relative `"/login?redirect=<encoded original path+query>"`. The `redirect` capture + downstream `safeRedirectTarget` sanitization (S-119) are unchanged. The middleware had the same latent bug (worked only via Next's middleware-redirect normalization); hardened for consistency.
- Tests parse a relative `Location` (dummy base) and assert it has **no host component** and never contains `0.0.0.0` — a direct regression guard.

## 2. Node 22 pin (`chore(panel)`)

`pnpm dev` crashed on Node 26.7 (`TypeError: Cannot read properties of undefined (reading 'join')` in the Next CLI bootstrap; a mixed-version `node_modules` also left `@swc/helpers/package.json` missing). CI and the Docker image run Node 22.

- Add repo-root and `panel/.nvmrc` (`22`) so `nvm use` selects the supported LTS.
- Tighten `engines.node` from `>=22` to `>=22 <25` in root + panel `package.json` (panel had no `engines` field).
- Add `.npmrc` `engine-strict=true` so an install on an unsupported Node **fails with a clear message** instead of silently producing a broken tree.

## 3. Runbook `SUPABASE_URL` (`docs(runbook)`)

`docs/runbooks/panel-deployment.md` Impl Step 3 framed `SUPABASE_URL` as optional and implied it lives in `fly.toml [env]`. The server-side data client reads `SUPABASE_URL` and throws `SupabaseConfigError` (digest `3101215328`) if unset — crashing the dashboard after login while login itself works (auth client uses `NEXT_PUBLIC_SUPABASE_URL`). Rewrote the step to require it, explain the exact failure, and distinguish it from the `NEXT_PUBLIC_` auth-client URL.

## Scope / not included

- **No `fly.toml` change.** A local uncommitted `panel/fly.toml` edit that adds a public `[http_service]` (go-public / Phase B / S-123) was deliberately left out — out of scope, explicitly excluded from the auth wave, and per the runbook must be its own operator-confirmed PR.
- No schema/data/API change.

## Testing

- `pnpm run validate` (panel) — green: lint, format:check, typecheck, **915 passed / 49 skipped**, audit clean.
- `pnpm run build` (panel) — green; `/api/auth/logout`, `/login`, middleware all compile.
- Targeted: `tests/unit/logout-route.test.ts` (6) + `tests/component/middleware-gate.test.ts` (20) pass, including the new relative-`Location` / no-`0.0.0.0` regression assertions.
- Manual (post-merge, deployed): sign in → **Log out** → lands on `/login` (not `0.0.0.0`); protected route → `/login`.

## Checklist

- [x] Conventional Commit titles (fix / chore / docs)
- [x] Relative-Location regression guard added
- [x] Node 22 pin + engine-strict guardrail
- [x] `SUPABASE_URL` required in runbook
- [x] `validate` + `build` green
- [x] `fly.toml` / go-public change intentionally excluded
- [ ] Reviewed and merged by the user (I must not merge to `main`)
