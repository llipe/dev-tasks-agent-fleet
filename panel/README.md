# Panel — Agent Fleet Control Panel

Phase 2 Next.js (App Router) front-end for the Agent Fleet Control Plane. This
package is the `panel` member of the repo-root pnpm workspace.

## Stack

- Next.js 15 (App Router), React 19, TypeScript strict
- Vitest + React Testing Library (+ `@vitest/coverage-v8`)
- Playwright (E2E — scenario suite shipped in S-114)
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

- **SD2 — server-only Supabase _data_ boundary.** All **data** access is server-side.
  The service role key (`SUPABASE_SERVICE_ROLE_KEY`, which bypasses RLS) is server-only
  and has **no** `NEXT_PUBLIC_` twin. Data reads go through `lib/supabase/server.ts`
  (`createServerClient` — a per-request factory with fail-fast env validation) and the
  typed helpers in `lib/supabase/queries.ts`, only from Server Components or route
  handlers. An ESLint restricted-import rule forbids importing `lib/supabase/server.ts`
  from client components, and `tests/unit/eslint-server-import.test.ts` proves the rule
  fires. PostgREST failures surface as `DATABASE_ERROR` (500) with the Postgres code
  logged, never returned to the client (`lib/supabase/errors.ts`).

  Authentication (S-116+) uses a **separate** anon-key client family — cookie-backed,
  `NEXT_PUBLIC_`-configured, RLS-bound — that never touches the service-role client
  (rule SA1). RLS stays deny-all (D11): authenticating a user grants no row access.

- **Auth clients + environment (S-116; publishable-key migration #172).** The auth
  path reads the publishable client-key pair, which — unlike the service-role key — is
  safe in the browser:

  | Variable                               | Scope                | Used by                                                       |
  | -------------------------------------- | -------------------- | ------------------------------------------------------------- |
  | `NEXT_PUBLIC_SUPABASE_URL`             | public               | `lib/supabase/{auth-server,browser}.ts`                       |
  | `NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY` | public (publishable) | `lib/supabase/{auth-server,browser}.ts` — **preferred**       |
  | `NEXT_PUBLIC_SUPABASE_ANON_KEY`        | public (legacy)      | `lib/supabase/{auth-server,browser}.ts` — deprecated fallback |
  | `SUPABASE_URL`                         | server               | `lib/supabase/server.ts` (unchanged)                          |
  | `SUPABASE_SERVICE_ROLE_KEY`            | server secret        | `lib/supabase/server.ts` (unchanged)                          |

  `lib/supabase/auth-env.ts` validates the public pair with a named `AuthConfigError`
  at first use (same fail-fast pattern as `readSupabaseEnv`). It resolves
  `NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY` first and falls back to the **legacy**
  `NEXT_PUBLIC_SUPABASE_ANON_KEY` with a one-time deprecation warning; it throws only
  when neither is set. Supabase now treats the classic anon JWT as a legacy client
  credential and recommends the new publishable API key (`sb_publishable_…`), which is
  individually revocable without a project-wide session bust. The service-role key MUST
  NOT gain a `NEXT_PUBLIC_` twin. For local dev, add both `NEXT_PUBLIC_SUPABASE_*` values
  to `panel/.env.local` (the URL is the same project URL as `SUPABASE_URL`; the client key
  is the project's **publishable** key from the Supabase dashboard → Project Settings → API
  keys — the legacy anon key still works as a fallback for one release).
  The pure policy modules `lib/auth/{route-policy,redirect,errors}.ts` are the
  security-relevant decision logic (route classification, open-redirect guard, and the
  anti-enumeration error mapping) and carry exhaustive unit suites.

- **Authorization chokepoint — the middleware gate (S-117).** `panel/middleware.ts` is the
  single place authorization is decided, so a new page or route handler cannot forget to add
  a check (the same "one enforceable control" posture as the SD2 `server-only` guard). It runs
  on every non-static request — the matcher excludes `_next/static`, `_next/image`, the favicon,
  and image assets, so the gate never fires on static files, but pages, `/api/**`, and the SSE
  stream are all gated. The flow:

  1. `classifyRoute(pathname)` (the pure S-116 policy) short-circuits `public` routes **before**
     any auth work — `/login` stays reachable with no session.
  2. Otherwise it verifies identity with `getClaims()` — **never** `getSession()`, whose user
     object is not re-validated against the Auth server and must not drive an authorization
     decision.
  3. On denial: a `ui` route → `302` to `/login?redirect=<encoded original path+query>`; an
     `api` route (including the SSE path) → `401 {"error":"UNAUTHORIZED"}` with
     `content-type: application/json`, so `fetch`/`EventSource` see a clean failure rather than
     an HTML redirect. For the SSE stream this `401` is returned **before** the
     `text/event-stream` response opens, so the client live-tail hook (`lib/hooks/useRunStream.ts`,
     S-121) treats a never-opened, `CLOSED` connection as a **terminal** auth stop — no reconnect
     loop — and `LiveLogViewer` shows a session-expired notice (this is what settles spec OQ3).
  4. It is **fail-closed**: any error from the auth call is treated as unauthenticated, and an
     unknown route class defaults to `ui`.

  On success the gate returns the cookie-handler `NextResponse` (never a fresh
  `NextResponse.next()`), so a refreshed token reaches the browser and does not cause
  intermittent logouts. The cookie-threading client lives in `lib/supabase/auth-middleware.ts`
  (`createMiddlewareClient`, injectable factory for testing) and uses the anon key only — never
  the service-role data client (SA1). The login/logout UI the redirect points at ships in
  S-119/S-120 (both now merged — see the Login and Sign-out bullets below); this story is the
  gate mechanism only. Auth reads for local dev still require the `NEXT_PUBLIC_SUPABASE_*` pair
  documented above.

- **Login screen (S-119).** `/login` is the panel's only **public** route — it lives at
  `app/login/` **outside** the `(panel)` route group, so it renders shell-free (no sidebar/top
  bar). `page.tsx` is a server component (inline `force-dynamic`/`revalidate=0`/`fetchCache` — an
  auth response can carry a refreshed `Set-Cookie`, so it must never be cached) that redirects an
  already-authenticated visitor (`getClaims()`, never `getSession()`) to `/` and pre-sanitizes
  `?redirect`. `actions.ts` is the `"use server"` `signIn` action over a pure, injectable
  `resolveSignIn` core: **validate → `safeRedirectTarget` before use → `signInWithPassword` →
  generic error mapping**, redirecting to the sanitized target on success. `components/auth/`
  holds `LoginForm` (`useActionState` + `useFormStatus` pending/disabled double-submit guard,
  `role="alert"` generic error, clears the password on a failed attempt) and `PasswordField` (the
  keyboard-operable `SHOW`/`HIDE` toggle — `aria-pressed`, `type="button"`, defaults masked),
  reusing the S-105 `Input`/`Button`/`KLabel` primitives with token-only CSS. It **reuses, does
  not reimplement,** the S-116 `lib/auth/{redirect,errors}` policy and `lib/supabase/auth-server`,
  and is protected by the S-117 gate. Load-bearing security properties: **anti-enumeration**
  (unknown-email ≡ wrong-password, one generic "Invalid email or password." message via
  `classifySignInError`), **redirect safety** (`safeRedirectTarget` server-side before use), and
  the password is never stored/logged/echoed. No signup/reset/confirmation/magic-link; accounts are
  invitation-only (provisioned in the Supabase dashboard, never seeded).

- **Sign-out (S-120).** The operator ends a session from the **sidebar footer "Log out"** control
  (`components/shell/LogOutItem.tsx`, rendered below "System health" and above "Collapse", only when
  the request is authenticated — see `/DESIGN.md` §4.1). It is a plain
  `<form method="post" action="/api/auth/logout">` submit button — **POST-only, no client JS** (a
  `GET` logout is CSRF-triggerable). The route handler `app/api/auth/logout/route.ts` builds the
  S-116 cookie-backed anon auth client, calls `signOut` best-effort/idempotent, and **always**
  redirects `302 → /login` (it never 500s; no `GET` export, so a `GET` is a 405). `route-policy.ts`
  classifies the **exact** path `/api/auth/logout` as `public` so the session-ending POST reaches
  the handler even with an expiring/invalid session (siblings stay `api`). Whether "Log out" renders
  is decided server-side — the `(panel)` layout resolves `authenticated` via `getClaims()`
  (fail-closed) and threads it as a static prop into `AppShell → Sidebar`, so the shell performs no
  auth I/O (SA1 preserved, S-106 hydration contract untouched). RLS stays deny-all (D11).

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
  owns the collapse state; as of S-118 the authenticated route group's `app/(panel)/layout.tsx`
  wraps `children` in it (the root `app/layout.tsx` keeps only `<html>`/`<body>`, the Inter fonts,
  metadata, and the global CSS, so the public `/login` screen can render outside the shell).

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

- **SD2 lint scope covers `app/**`(S-106).** The`no-restricted-imports`hint that forbids importing`lib/supabase/server`from a client component now covers`app/**`in addition to`components/**`
(the S-104 audit D1 hardening). App Router server entrypoints
(`page`/`layout`/`route`/`template`/`default`/`error`/`loading`/`not-found`) are excluded — those
read Supabase on purpose (SD2). `import "server-only"` remains the hard build-time guard.

## Deployment boundary — authentication (auth wave, S-116…S-122; ADR-007)

> **This is a precondition for deploying the panel, not an implementation detail.**

The panel now requires a **Supabase password login** (auth wave, S-116…S-122).
The v1 "no auth, keep it private" decision (D16) has been **reversed**: the
security boundary that protects the invoke surface is now **authentication** — a
fail-closed `middleware.ts` gate, the `/login` screen, POST logout, and a `401`
on the SSE route. That boundary is mechanized as a **release gate** that proves
it by observation on the deployed app.

> **This story (S-122) keeps the app PRIVATE.** Going public is the separate,
> operator-executed, separately-merged **Phase B (S-123)**. Until then
> `panel/fly.toml` still declares no `[http_service]` and no public IP.

Before and after every deploy:

1. **Configure Supabase (operator, out-of-band):** enable the Email provider,
   **disable public signups** (release blocker), set the 12h inactivity timeout,
   create the operator user. See the runbook checklist.
2. **The auth release gate MUST pass.** After deploy (Phase A: over the private
   network via `fly proxy`; Phase B: publicly), run:

   ```bash
   NEXT_PUBLIC_SUPABASE_URL=… NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY=… \
     scripts/verify-panel-auth.sh <base-url> -a dt-agent-fleet-panel
   ```

   It probes the deployed app and **exits non-zero (fails the release)** unless
   the auth env-var **names** are present (names only), an unauthenticated
   protected UI path returns `302 → /login` (not 200), an unauthenticated SSE
   request returns `401` (not 200), and an attempted `signUp` is **rejected** (a
   successful signup fails the release — PRD AC17 / R9). Its decision logic is
   the pure, unit-tested `panel/scripts/panel-auth-check.mjs` (see
   `tests/unit/panel-auth-check.test.ts`), and it is **fail-closed** — anything
   unreadable/unparseable/unconfirmable fails.

This replaces the S-115 privacy gate (`scripts/verify-fly-private.sh` +
`panel/scripts/fly-privacy-check.mjs`), which is removed: a release must never
run with no mechanical boundary check.

The full deploy procedure, the recorded OIDC socket probe, IAM/OIDC setup, Fly
secrets, and rollback are in
[`docs/runbooks/panel-deployment.md`](../docs/runbooks/panel-deployment.md).
