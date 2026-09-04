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

- **Design system — Nocturne tokens (S-105).** Every color, font, spacing-scale,
  radius, and shadow value comes from a CSS custom property defined in
  `styles/tokens.css` (transcribed from `/DESIGN.md` §2, including the four SD10
  `--st-*` status colors). `styles/globals.css` holds the `pulse`/`spin`/`rise`
  keyframes and the `:focus-visible` accent ring. The twelve primitive components
  live in `components/` with a token-only CSS module each; formatters are in
  `lib/format.ts` (`/DESIGN.md` §7).

  - **`color-mix()` browser floor.** The tokens and component styles use
    `color-mix(in srgb, …)` extensively (tints, dividers, hover states). This
    requires **Chrome/Edge 111+, Safari 16.2+, Firefox 113+** (`/DESIGN.md` §11.1).
    The panel does not ship a fallback for older engines — it targets current
    evergreen browsers only.

  - **Token discipline is a gate, not a review note.**
    `tests/unit/token-discipline.test.ts` mechanically rejects any color hex literal
    and any `font-family:` literal under `components/**` and `styles/globals.css`
    (`tokens.css` is the single exempt home of the literals). **Not mechanized:**
    "bare `px` in spacing" is intentionally _not_ rejected — the Nocturne prototype
    fixes exact pixel dimensions that are not part of the six-step `--space-*` scale
    (grid track sizes like `LogLine`'s `82px 46px 108px`, dot/knob diameters, control
    min-heights, 1–3px radii). A blanket no-`px` rule would reject faithful
    reproduction of the visual contract, so dimensional `px` is allowed and remains a
    review point; the spacing _scale_ is tokenized and used for padding/gap where a
    scale step applies.

- **Icons — `@phosphor-icons/react`.** Icons come from `@phosphor-icons/react/ssr`
  (the SSR entrypoint, so they render in Server Components) on `currentColor`
  (`/DESIGN.md` §10). Import by semantic role from `components/icons.tsx`
  (`AgentsIcon`, `RowChevronIcon`, …) rather than by Phosphor name; no Unicode glyph
  stand-ins from the prototype remain. The `✓ ✕ ⧗` glyphs in `formatStatusLegendCompact`
  are DESIGN §7.3 content, not icon stand-ins.

- **AWS credentials — no static keys (S-111, SD9 / D12).** The panel obtains AWS
  credentials through a single provider, `lib/aws/credentials.ts` (`awsCredentials`),
  with two branches selected automatically — callers receive only a provider and
  never know which branch ran:

  - **On Fly** (`FLY_APP_NAME` set **and** the `/.fly/api` socket exists): an OIDC
    token from the Machine socket is exchanged via STS `AssumeRoleWithWebIdentity`.
    Requires `AGENT_RUNTIME_ROLE_ARN`; a missing value fails fast with a named
    `CredentialsUnavailableError`, not an opaque invoke-time auth error.
  - **Locally**: `fromNodeProviderChain()` resolves an SSO profile,
    `~/.aws/credentials`, or environment variables — no code change between
    environments and **no AWS keys need to be set** for local dev with an SSO profile.

  Credentials are cached in memory with a 60-second refresh margin and a
  single-flight promise, so concurrent invokes trigger one STS call. The module is
  free of Next.js imports (unit-testable in isolation) and **never logs** the token,
  the STS response, or the assumed-role credentials — only `credentialSource()` (the
  active branch, logged on every invoke) and error codes.

  - **`credentialSource()` diagnostic.** Reports `"fly-oidc"` or `"local-chain"`.
    `lib/aws/invoke.ts` logs it on every `InvokeAgentRuntime` call so an operator can
    tell whether a failure came from the Fly OIDC branch or the local chain (R6). The
    error taxonomy keeps `CREDENTIALS_UNAVAILABLE` (500 — the panel could not obtain
    credentials) distinct from `INVOCATION_FAILED` (502 — AgentCore rejected the call)
    because the runbooks differ.

  - **Local SSO verification.** With an SSO profile active
    (`aws sso login --profile <p>` and `AWS_PROFILE=<p>`), start the dev server and
    hit any invoke path; `credentialSource()` logs `local-chain` and no AWS env keys
    are required. The Fly branch cannot be exercised locally — the OIDC socket exists
    only on a Fly Machine, so the socket response shape stays unverified until the
    live probe in S-115 (the `curl --unix-socket /.fly/api …` command is embedded in
    `lib/aws/credentials.ts` for that probe).

- **App shell — hydration-safe collapse persistence (S-106).** The outer frame
  (`components/shell/{AppShell,Sidebar,TopBar,DisabledNavItem}.tsx`, `/DESIGN.md` §4.1) is a
  212px/52px collapsible sidebar + a 38px top bar with a breadcrumb slot, wrapping a content
  region that owns its own scroll (`height:100dvh;overflow:hidden` on the shell; `overflow-y:auto`
  on the content column — the page never scrolls). `AppShell` is the only `"use client"` piece and
  owns the collapse state; `app/layout.tsx` wraps `children` in it.

  - **Hydration contract — do not read storage during render.** `localStorage` is not readable on
    the server, so the shell renders the fixed default (`DEFAULT_COLLAPSED`, expanded) on both the
    server and the first client render, then reconciles the stored preference in a **mount effect**
    (after hydration). Reading storage during render (e.g. `useState(() => readStored())`) would
    reintroduce the exact server/client mismatch the S-106 hydration test asserts against. A standing
    `console.error` trap in `tests/setup.ts` (opt out per-test with `allowConsoleError`) and
    `tests/unit/no-suppress-hydration.test.ts` keep this honest.
  - **Collapse state — closed vocabulary.** `lib/ui/sidebar-state.ts` persists the preference under
    `SIDEBAR_STORAGE_KEY = "panel.sidebar.collapsed"` as one of two literals (`collapsed`/`expanded`),
    defaulting to expanded. Every failure mode — absent storage (SSR), a throwing accessor (private
    mode / quota), or an unrecognized value — returns the default and never throws.
  - **Keyboard shortcut.** `lib/ui/shortcuts.ts` holds pure `KeyboardEvent` predicates:
    `isSidebarToggleShortcut` matches `Cmd+\` on macOS / `Ctrl+\` elsewhere (primary modifier only),
    and `isTypingTarget` suppresses the shortcut while an input/textarea/select/`contenteditable`
    has focus.
  - **Deferred nav destinations.** Only Agents is an enabled link. All runs, Repositories, Settings,
    and System health render as non-link `DisabledNavItem` spans (`aria-disabled`, "not available in
    this phase", not focusable) per PRD §10 — the deferral is meant to be seen, not clicked.
  - **Two derived surface tokens.** `styles/tokens.css` defines `--color-sidebar-bg` (92% `--color-bg`
    over `#000`) and `--color-shell-bg` (88%), so the shell CSS references a token rather than a raw
    `#000` (the token-discipline gate).

- **SD2 lint scope covers `app/**` (S-106).** The `no-restricted-imports` hint that forbids importing
  `lib/supabase/server` from a client component now covers `app/**` in addition to `components/**`
  (the S-104 audit D1 hardening). App Router server entrypoints
  (`page`/`layout`/`route`/`template`/`default`/`error`/`loading`/`not-found`) are excluded — those
  read Supabase on purpose (SD2). `import "server-only"` remains the hard build-time guard.

## Deployment precondition (placeholder)

The panel has no user authentication in v1 (D16). Its only mitigation is that the
Fly app **must remain private** (no public service, no public IP). The full
deployment precondition is documented when Phase 2 deploy work lands.
