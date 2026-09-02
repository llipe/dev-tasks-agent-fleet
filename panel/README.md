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

| Service             | Port   |
| ------------------- | ------ |
| Next.js dev / start | `3000` |

(Supabase local-stack ports are recorded here in S-102 when the CLI stack lands.)

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
