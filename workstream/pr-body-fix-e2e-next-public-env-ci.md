## What

Make the `NEXT_PUBLIC_SUPABASE_*` anon pair reach the Playwright E2E `webServer` (`next dev`) deterministically in **both** CI and local, so the auth clients (S-116) can construct the cookie-backed client and `/login` renders instead of 500-ing.

Two scoped changes:

- **`.github/workflows/ci.yml`** — the "Export local Supabase env" step now also exports `NEXT_PUBLIC_SUPABASE_URL` and `NEXT_PUBLIC_SUPABASE_ANON_KEY` to `$GITHUB_ENV`, so the whole job — including the spawned `next dev` — inherits them. This is the authoritative CI fix.
- **`panel/playwright.config.ts`** — `webServer.env` now explicitly forwards the Supabase vars (both the `NEXT_PUBLIC_*` anon pair and the server-only names), merging with (never dropping) the existing `AWS_*` + AgentCore stub vars. A small `forwardEnv` helper forwards only non-empty values so it never clobbers a value that `global-setup.ts` sets on `process.env` after config-load (the local path).

## Why

CI run **34406811655**, job "Panel quality gate (JS/TS)", step "E2E (Playwright)" was RED (everything else on PR #170 was green).

Root cause: the `webServer` returned HTTP 500 on `GET /login` with `Error [AuthConfigError]: NEXT_PUBLIC_SUPABASE_URL is not set` (thrown at `lib/supabase/auth-env.ts:49` via `createAuthServerClient` in `app/login/page.tsx`). The middleware worked only because CI exported the **server-only** names (`SUPABASE_URL`/`SUPABASE_ANON_KEY`/`SUPABASE_SERVICE_ROLE_KEY`) at the job level; the `NEXT_PUBLIC_*` anon pair the auth clients need was set **only** on `global-setup.ts`'s in-process `process.env`, which the spawned server did not reliably inherit in CI. With `/login` never rendering, `tests/e2e/auth.setup.ts` timed out on the email field, failing the `setup` project and the whole E2E run.

Timing note (documented in the config comment): Playwright constructs `webServer.env` when the config module **loads**, before `globalSetup` runs. So the `$GITHUB_ENV` export is the durable CI fix (present at config-load); locally, `global-setup.ts` writes the values onto `process.env` and the spawned server still inherits them. The config forward + `$GITHUB_ENV` export are belt-and-braces and each is independently correct.

## How

- `forwardEnv({...})` returns only the entries whose resolved value is non-empty, then spreads them into `webServer.env` alongside the existing `AWS_ENDPOINT_URL_BEDROCK_AGENTCORE` / `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY` / `AWS_REGION` stub vars.
- `NEXT_PUBLIC_SUPABASE_URL` falls back to `SUPABASE_URL`, `NEXT_PUBLIC_SUPABASE_ANON_KEY` falls back to `SUPABASE_ANON_KEY`, so a single resolved source populates both name families.
- CI exports the anon pair with a one-line comment noting SD2 is not weakened.

**SD2 guardrail preserved:** only the anon URL + anon key are ever `NEXT_PUBLIC_*`. `SUPABASE_SERVICE_ROLE_KEY` is **never** given a `NEXT_PUBLIC_` twin — verified across `panel/**` and `.github/**`.

This is a **test-harness + CI-config fix only** — no product code touched (`lib/supabase/*`, `middleware.ts`, `app/**` unchanged). No schema/migration change.

## Testing

Run locally against the real local Supabase stack, reproducing the CI env (server-only names + the newly-exported `NEXT_PUBLIC_*` pair, `CI=true`, `REQUIRE_LOCAL_DB=1`):

- `pnpm --filter panel run test:e2e` — **PASS**, 19/19 (setup + chromium). `GET /login` now returns `200`; `auth.setup.ts` authenticates the operator; all 7 auth scenarios (incl. logout) + invoke/live-tail/stale/artifact scenarios pass. (Locally the bundled `chromium_headless_shell` was unavailable, so the run used the project's documented `PW_CHANNEL=chrome` fallback; CI uses the pinned bundled chromium.)
- `pnpm --filter panel run validate` — **PASS** (lint + format:check + typecheck + test 950/4-skip + audit); Layer 2.5 integration suites ran for real under `REQUIRE_LOCAL_DB=1`.
- `pnpm --filter panel run build` — **PASS** (`next build` green).
- `make validate` (repo root) — **PASS** both branches: Python 452 passed (ruff/mypy clean), JS/TS 951 passed / 4 skipped, `validate: all gates passed`.

No `stream-e2e`/SD6 cold-Realtime flake observed (Realtime warmed as in CI).

## Checklist

- [x] Conventional Commit title
- [x] Scoped to `panel/playwright.config.ts` + `.github/workflows/ci.yml` only (no product code)
- [x] SD2 preserved (no `NEXT_PUBLIC_` twin for the service-role key)
- [x] E2E `setup` project + authenticated scenarios verified green locally
- [x] `pnpm --filter panel run validate`, `build`, and repo-root `make validate` all pass
- [x] No schema/migration change

## Notes

- Base branch is `integration/v2.1-panel-auth` (this feeds the consolidated PR #170 → `main`). Do not merge into `main` directly.
- CI reference: failing run https://github.com/llipe/dev-tasks-agent-fleet/actions/runs/34406811655
