# Panel — Agent Fleet Control Panel

Phase 2 Next.js (App Router) front-end for the Agent Fleet Control Plane. This
package is the `panel` member of the repo-root pnpm workspace.

## Stack

- Next.js 15 (App Router), React 19, TypeScript strict
- Vitest + React Testing Library (+ `@vitest/coverage-v8`)
- Playwright (E2E — scenario suite lands in S-114)
- ESLint (`next/core-web-vitals` + `next/typescript`) + Prettier
- Ajv 8 for `params_schema` validation (used in later stories)

## Setup

From the **repo root** (the workspace root):

```bash
pnpm install --frozen-lockfile
```

## Scripts

Run from the repo root, scoped to this package with `pnpm --filter panel run <script>`,
or from `panel/` directly with `pnpm run <script>`:

| Script             | Purpose                                                        |
| ------------------ | -------------------------------------------------------------- |
| `dev`              | Start the Next.js dev server                                   |
| `build`            | Production build                                               |
| `lint`             | ESLint                                                         |
| `lint:fix`         | ESLint with autofix                                            |
| `format`           | Prettier write                                                 |
| `format:check`     | Prettier check                                                 |
| `typecheck`        | `tsc --noEmit`                                                 |
| `test`             | Vitest (all projects)                                          |
| `test:unit`        | Vitest — unit project (Layer 1)                                |
| `test:integration` | Vitest — integration project (Layer 2.5, S-102/S-104)          |
| `test:e2e`         | Playwright (Layer E2E, S-114)                                  |
| `test:coverage`    | Vitest with v8 coverage                                        |
| `audit`            | `pnpm audit` (prod, high+)                                     |
| `validate`         | Aggregate gate: lint + format:check + typecheck + test + audit |

The repo-root `make validate` runs this package's `validate` alongside the
Python agent gate.

## Local ports

| Service                       | Port    |
| ----------------------------- | ------- |
| Next.js dev / start           | `3000`  |
| Supabase API (PostgREST/auth) | `54321` |
| Supabase DB (Postgres)        | `54322` |
| Supabase Studio               | `54323` |
| Supabase Inbucket (email)     | `54324` |
| Supabase Analytics            | `54327` |
| Supabase DB pooler            | `54329` |

These are the Supabase CLI defaults declared in `supabase/config.toml`. Adjust
there if any collide with something you already run locally.

## Local Supabase stack (S-102)

The schema and seed are Supabase CLI migrations (`supabase/migrations/`,
`supabase/seed.sql`). To run a local Postgres that mirrors the live project:

```bash
supabase start        # boots the local stack (requires Docker running)
supabase db reset     # applies all migrations, then runs supabase/seed.sql
```

`db reset` recreates the database from `migrations/` and applies the seed
idempotently (`on conflict` paths), so it is safe to re-run. Requires Docker;
if Docker is unavailable the Layer 2.5 integration tests are skipped with a
recorded reason (see `TESTING.md`).

## Conventions

- **Server Components by default.** Add `"use client"` only when a component needs
  state, effects, browser APIs, or event handlers.
- **`force-dynamic` for data routes.** Pages and route handlers that read live run
  state must not be statically cached, and must not introduce a Next.js Data Cache
  for run data (run status changes second-to-second — a cached read would show a
  stale status, the exact failure SD4's read-time derivation prevents). Declare the
  route config **inline** in each data route — Next.js does **not** honor
  route-segment config re-exported from another module (it silently falls back to
  defaults), so copy the canonical values from `lib/supabase/route-config.ts` directly:

  ```ts
  export const dynamic = "force-dynamic";
  export const revalidate = 0;
  export const fetchCache = "force-no-store";
  ```

  `dynamic = "force-dynamic"` opts out of static rendering; `revalidate = 0` and
  `fetchCache = "force-no-store"` ensure no data-cache layer. `lib/supabase/route-config.ts`
  holds these as the single documented source of truth. Applied per-route as
  data-reading screens land.

- **SD2 — server-only Supabase read boundary.** All Supabase access is server-side.
  There is no `NEXT_PUBLIC_SUPABASE_*` variable anywhere; the service role key
  (`SUPABASE_SERVICE_ROLE_KEY`, which bypasses RLS) is server-only. Reads go through
  `lib/supabase/server.ts` (`createServerClient` — a per-request factory with
  fail-fast env validation) and the typed helpers in `lib/supabase/queries.ts`, only
  from Server Components or route handlers. An ESLint restricted-import rule forbids
  importing `lib/supabase/server.ts` from client components, and
  `tests/unit/eslint-server-import.test.ts` proves the rule fires. PostgREST failures
  surface as `DATABASE_ERROR` (500) with the Postgres code logged, never returned to
  the client (`lib/supabase/errors.ts`).

## Deployment precondition (placeholder)

The panel has no user authentication in v1 (D16). Its only mitigation is that the
Fly app **must remain private** (no public service, no public IP). The full
deployment precondition is documented when Phase 2 deploy work lands.
