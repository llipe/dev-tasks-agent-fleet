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
| `test:integration` | Vitest — integration project (Layer 2.5, S-102)                |
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
  state export `export const dynamic = "force-dynamic"` so Next does not statically
  cache operator-facing data. (Applied per-route as data-reading screens land.)
- **SD2 — server-only Supabase.** All Supabase access is server-side. There is no
  `NEXT_PUBLIC_SUPABASE_*` variable anywhere; the service role key is server-only.
  An ESLint restricted-import rule forbids importing `lib/supabase/server.ts` from
  client components.

## Deployment precondition (placeholder)

The panel has no user authentication in v1 (D16). Its only mitigation is that the
Fly app **must remain private** (no public service, no public IP). The full
deployment precondition is documented when Phase 2 deploy work lands.
