# Implementation Plan — Agent Fleet Control Panel, Phase 2 (Wave 2)

## Scope

This plan covers **Wave 2 — platform**: the three stories that are unblocked by Wave 1 and mutually independent. Together they land the server-side data boundary, the visual system, and the credential provider — everything Wave 3's screens and Wave 4's invocation compose from.

| Task | Story | Issue | Size | Title |
| ---- | ----- | ----- | ---- | ----- |
| 1.0 | S-104 | [#117](https://github.com/llipe/dev-tasks-agent-fleet/issues/117) | M | Server-side data layer and `effectiveStatus` parity |
| 2.0 | S-105 | [#118](https://github.com/llipe/dev-tasks-agent-fleet/issues/118) | L | Design token layer, Nocturne primitives, and data formatters |
| 3.0 | S-111 | [#124](https://github.com/llipe/dev-tasks-agent-fleet/issues/124) | M | AWS credential provider — Fly OIDC and local chain |

Sources: [`user-stories-prd-agent-fleet-panel-v2.md`](user-stories-prd-agent-fleet-panel-v2.md) v1.0 (S-104, S-105, S-111), [`specification-prd-agent-fleet-panel-v2.md`](specification-prd-agent-fleet-panel-v2.md) v1.2 (SD2, SD4, SD9, SD10, SD12, §13, §14, §16), [`/DESIGN.md`](../DESIGN.md) v1.0 (§2, §6, §7, §10, §11.2).

Wave 1 predecessor: [`tasks-prd-agent-fleet-panel-v2-plan.md`](tasks-prd-agent-fleet-panel-v2-plan.md) — S-101/S-102/S-103, merged and closed.

### Published GitHub artifacts

Every task checklist below is mirrored into its issue body, and the Design Mode compliance test plan is posted as an issue comment. GitHub is the source of truth for execution status.

| Story | Issue | Task checklist | Compliance test plan (Design Mode) |
| --- | --- | --- | --- |
| S-104 | https://github.com/llipe/dev-tasks-agent-fleet/issues/117 | in issue body — 31 items (1.1–1.31) | https://github.com/llipe/dev-tasks-agent-fleet/issues/117#issuecomment-5527052056 |
| S-105 | https://github.com/llipe/dev-tasks-agent-fleet/issues/118 | in issue body — 28 items (2.1–2.28) | https://github.com/llipe/dev-tasks-agent-fleet/issues/118#issuecomment-5527052417 |
| S-111 | https://github.com/llipe/dev-tasks-agent-fleet/issues/124 | in issue body — 30 items (3.1–3.30) | https://github.com/llipe/dev-tasks-agent-fleet/issues/124#issuecomment-5527052764 |

Local test-plan artifact: [`test-plan-wave2-S-104-S-105-S-111.md`](test-plan-wave2-S-104-S-105-S-111.md) — 12 contract scenarios, 20 edge cases, all 22 ACs mapped.

**Flagged-gap status.** The test plan raised six gaps. **G1** (Fly OIDC boundary has no verified provider) and **G2** (Docker-gated Layer 2.5 skip turns the SR3 parity test and the RLS deny-all test into no-ops) are **deferred by decision** and are not carried as tasks in this plan — both are recorded in the test plan and in the issue comments so they are not lost. G2 affects what "done" means for tasks 1.11 and 1.12, and G1 affects how AC-111.2 must be reported at close, so both should be revisited before the respective story closes. G3 (sentinel key for the bundle-secret test), G4 (make the token-discipline check mechanical), G5 (AC-111.6 is route-level verifiable only in S-112), and G6 (derived-status-to-`StatusPill` composition is Wave 3) are actioned inline in tasks 1.14, 2.10, 3.11/3.26, and the Deferred section respectively.

**Project type:** existing codebase. The `panel` package, pnpm workspace, gates, and Layer 2.5 harness all exist from Wave 1, so there is **no Task 0** — every dependency and script this wave needs is already wired.

### Dependency state

All three stories' declared dependencies are satisfied:

| Story | Depends on | State |
| ----- | ---------- | ----- |
| S-104 | S-101, S-102 | ✅ merged (#114, #115) |
| S-105 | S-101 | ✅ merged (#114) |
| S-111 | S-101 | ✅ merged (#114) |

**The three tasks are parallelizable.** The critical path in the user stories file reads `S-104 → S-105`, but that is a serialization convenience, not a real dependency — S-105 depends only on S-101. Task order below (S-104, S-105, S-111) reflects unblocking value: S-104 releases S-107/S-108, S-105 releases S-106, S-111 is off the critical path and releases S-112. They may be executed in any order or on parallel branches.

### Execution rules

One sub-task at a time, marked `[x]` locally **and** in the GitHub Issue checklist, then stop for approval. Branch per story (`story/S-1xx-<short-description>`), draft PR opened after the first commit with `Closes #<n>`, quality gates before completion. `pnpm` throughout; canonical scripts only.

### Wave-level notes carried from Wave 1

- **Dependency pinning is a re-confirm-then-pin step, not a transcribe step.** S-101 found the spec's `next@15.5.4` pin was the subject of a critical RCE advisory and shipped `15.5.25` instead. Both S-104 (`@supabase/supabase-js`) and S-111 (four `@aws-sdk/*` packages) add dependencies; each must be re-confirmed current and audit-clean before pinning.
- **The four `@aws-sdk/*` packages MUST share a minor** (spec §16, verbatim requirement — they are deliberately unpinned in the spec to avoid triple-copies of `@smithy/core` in the lockfile). S-111 is where that pin is decided.
- **Layer 2.5 is Docker-gated.** `panel/tests/integration/db.ts` exposes `probeLocalDb`; a suite that cannot reach the local Supabase Postgres skips with a recorded reason rather than failing `make validate`. S-104's new integration tests must use the same guard.
- **No migrations in this wave.** All three stories are read-only or additive-code-only. Each records an explicit migration opt-out rationale (plan activity rule 8).

## Relevant Files

### Server-side data layer (S-104)

- `panel/lib/supabase/server.ts` — per-request client factory, server-only env validation (SD2)
- `panel/lib/supabase/queries.ts` — the eight typed query helpers
- `panel/lib/supabase/types.ts` — row types for the six read objects
- `panel/lib/domain/status.ts` — `effectiveStatus(run, now)`, the TypeScript mirror of `v_runs` (SD4)
- `panel/tests/unit/status.test.ts` — truth table incl. exact-boundary rows
- `panel/tests/unit/bundle-secrets.test.ts` — build-artifact grep, security-negative
- `panel/tests/integration/status-parity.test.ts` — SQL↔TS parity (SR3)
- `panel/tests/integration/rls-deny-all.test.ts` — anon-key zero rows, security-negative
- `panel/tests/integration/queries.test.ts` — helper shapes against seeded data
- `panel/eslint.config.mjs` — SD2 restricted-import rule (exists; now gains a test proving it fires)
- `panel/README.md` — `force-dynamic` convention, server-only read boundary
- `.env.example` — anon key added for the deny-all test only (local stack)

### Design system (S-105)

- `panel/styles/tokens.css` — every `/DESIGN.md` §2 token incl. the four SD10 `--st-*` colors
- `panel/styles/globals.css` — `pulse`/`spin`/`rise` keyframes, `:focus-visible`, hover rules (§6)
- `panel/components/{KLabel,Tag,Button,Input,StatusDot,StatusPill,Toggle,Breadcrumb,NavItem,StatusBar,RunStrip,LogLine}.tsx` — the §11.2 inventory
- `panel/lib/format.ts` — `/DESIGN.md` §7 formatters
- `panel/tests/unit/format.test.ts` — table-driven formatter tests
- `panel/tests/component/*.test.tsx` — one suite per primitive
- `panel/app/dev/gallery/page.tsx` — dev-only variant gallery, excluded from production build
- `panel/app/layout.tsx` — imports the token sheet
- `/DESIGN.md` — impact notes if any prototype detail cannot be reproduced

### AWS credentials (S-111)

- `panel/lib/aws/credentials.ts` — adopted from `docs/reference/credentials.ts` with the three SD9 corrections
- `panel/lib/aws/invoke.ts` — `InvokeAgentRuntime` wrapper against `runtime_arn` + `runtime_qualifier` (consumed by S-112)
- `panel/lib/aws/errors.ts` — `FlyOidcShapeError`, `CREDENTIALS_UNAVAILABLE` / `INVOCATION_FAILED` taxonomy (§13)
- `panel/tests/unit/credentials.test.ts` — branch detection, every rejection shape, cache, single-flight
- `docs/reference/credentials.ts` — replaced by a pointer link (same treatment as the S-102 SQL stubs)
- `.env.example` — `AWS_REGION`, `AGENT_RUNTIME_ROLE_ARN` (present) plus any new required var
- `panel/README.md` — local SSO verification procedure, `credentialSource()` diagnostic

## Tasks

- [ ] 1.0 Implement Story S-104 ([#117](https://github.com/llipe/dev-tasks-agent-fleet/issues/117)): Server-side data layer and `effectiveStatus` parity

  > Note: resolves **F2** (SD2) and **F4** (SD4). RLS is deny-all with zero policies, so the browser cannot read Supabase at all — this story establishes that boundary in code before any screen exists. It also lands `effectiveStatus`, the TypeScript mirror of the `v_runs` `case` expression, plus the Layer 2.5 test that pins the two implementations to each other (**SR3**). Read-only story: no migration.

  - [x] 1.1 Create branch `story/S-104-server-data-layer` from latest `main`; confirm #117 is open
  - [x] 1.2 Write `effectiveStatus` and its unit truth table **first** (test-first, implementation step 2): `lib/domain/status.ts` pure, `now`-injected, mirroring `v_runs` lines 240–248 exactly — `running` past `started_at + max_runtime + grace` → `timed_out`; `queued` past `queued_at + start_timeout` → `failed_to_start`; otherwise pass through
  - [x] 1.3 First commit; open draft PR against `main` with `Closes #117`
  - [x] 1.4 Add `lib/supabase/types.ts` — row types for `agents`, `repositories`, `v_runs`, `run_steps`, `run_events`, `run_artifacts` (hand-written or CLI-generated; record which and why)
  - [x] 1.5 Add `lib/supabase/server.ts` — per-request client factory reading `SUPABASE_URL` + `SUPABASE_SERVICE_ROLE_KEY`, with fail-fast env validation (a missing or malformed variable throws a named startup error, never yields an `undefined` client)
  - [x] 1.6 Re-confirm and pin `@supabase/supabase-js` (spec §16 names `2.58.0` — verify it is current and audit-clean before pinning, per the S-101 precedent); run `pnpm run audit`
  - [x] 1.7 Add the eight typed query helpers to `lib/supabase/queries.ts`: enabled agents; one agent by slug; enabled non-archived repositories; runs by agent slug (newest-first, from `v_runs`); one run by id; `run_steps` by run; `run_events` by run (bounded, `seq`-ordered); `run_artifacts` by run
  - [x] 1.8 Surface PostgREST failures as `DATABASE_ERROR` (500) with the Postgres code logged and never returned (spec §13); add the error shape to a shared module
  - [x] 1.9 Establish the `export const dynamic = "force-dynamic"` convention for run routes and document it in `panel/README.md`; introduce no Next.js data cache for run data
  - [x] 1.10 Add the anon key to `.env.example` as a **test-only, local-stack** variable with a comment stating it exists solely for the deny-all test and is never read by application code
  - [x] 1.11 Write the Layer 2.5 parity test `tests/integration/status-parity.test.ts` — `effectiveStatus` vs `v_runs.effective_status` over a shared fixture matrix including exact-boundary rows; use the `probeLocalDb` Docker guard from `tests/integration/db.ts`
  - [x] 1.12 Write the Layer 2.5 security-negative test `tests/integration/rls-deny-all.test.ts` — an anon-key client reads **zero rows** from every table **and** from `v_runs`
  - [x] 1.13 Write `tests/integration/queries.test.ts` — each helper returns the expected shape against seeded data
  - [x] 1.14 Add the security-negative build-artifact test `tests/unit/bundle-secrets.test.ts` — no built client chunk contains the service role key. **Build with a sentinel value** (e.g. `SUPABASE_SERVICE_ROLE_KEY=SENTINEL_MUST_NOT_APPEAR_IN_BUNDLE`) and grep the real build output for the sentinel plus the variable identifier — G3: a grep for a key that does not exist in CI is a test that cannot fail, which is worse than no test
  - [x] 1.15 Add a test proving the SD2 ESLint restricted-import rule actually fires when `lib/supabase/server` is imported from a client component (the rule exists from S-101 but has never been proven to trigger)
  - [x] 1.16 Add the manual verification path: a placeholder route rendering a server-fetched agent count (proves the read boundary end-to-end with no UI)
  - [x] 1.17 Run Tests — unit: `pnpm run test:unit` — `effectiveStatus` truth table (`queued` fresh/stale, `running` fresh/stale, each terminal status pass-through, `running` with null `started_at`, exact-boundary equality, negative and zero `grace_seconds`)
  - [x] 1.18 Run Tests — integration: `pnpm run test:integration` against the local stack (parity matrix, anon deny-all across all tables and the view, helper shapes)
  - [x] 1.19 Run Tests — edge cases: empty result sets; a run whose agent has `requires_repository = false` (no repository); empty `run_events`; absent or malformed `SUPABASE_*` env var → clear startup error, not a silent `undefined` client; a row with null `max_runtime_seconds` must **not** silently derive `timed_out`
  - [x] 1.20 Manual verification: `pnpm --filter panel dev`, confirm the placeholder route renders the server-fetched agent count from the local stack
  - [x] 1.21 Verify Acceptance Criterion: `lib/supabase/server.ts` creates a per-request client from a server-only env var, and importing it from a client component fails lint
  - [x] 1.22 Verify Acceptance Criterion: all eight typed query helpers exist and are covered
  - [x] 1.23 Verify Acceptance Criterion: `lib/domain/status.ts` implements SD4 exactly
  - [x] 1.24 Verify Acceptance Criterion: the Layer 2.5 parity test proves agreement with `v_runs.effective_status` across the fixture matrix including exact-boundary rows
  - [x] 1.25 Verify Acceptance Criterion: the anon-key client reads zero rows from every table and from `v_runs`
  - [x] 1.26 Verify Acceptance Criterion: no client chunk contains the service role key
  - [x] 1.27 Verify Acceptance Criterion: run routes are `force-dynamic` and no Next.js data cache is introduced for run data
  - [x] 1.28 Map acceptance criteria to test evidence and record the mapping in the PR: AC1 → lint-rule test + import failure; AC2 → helper unit/integration tests; AC3 → `status.test.ts`; AC4 → `status-parity.test.ts`; AC5 → `rls-deny-all.test.ts`; AC6 → `bundle-secrets.test.ts`; AC7 → route config assertion
  - [x] 1.29 Run quality gates: `pnpm run lint`, `pnpm run format:check`, `pnpm run typecheck`, `pnpm run test`, `pnpm run audit`, then `make validate`
  - [x] 1.30 Migration lifecycle: **not applicable** — read-only story, no schema or data-model change (the panel writes nothing in S-104). Opt-out rationale recorded here and in the issue
  - [ ] 1.31 Mark PR ready for review, notify the user, and close #117 only after the PR is approved and merged

- [ ] 2.0 Implement Story S-105 ([#118](https://github.com/llipe/dev-tasks-agent-fleet/issues/118)): Design token layer, Nocturne primitives, and data formatters

  > Note: `/DESIGN.md` §2 defines the token set and §11.2 enumerates the twelve-component inventory the four screens compose from. **SD10** is the trap this story exists to avoid: the four app-level status colors (`--st-ok`, `--st-fail`, `--st-timeout`, plus accent for `running` and muted for `failed_to_start`) are **not** in the Nocturne stylesheet — they are prototype-page-local and must be defined explicitly. Every status pill and dot depends on them. Largest story in the phase (L).

  - [ ] 2.1 Create branch `story/S-105-design-tokens-primitives` from latest `main`; confirm #118 is open
  - [ ] 2.2 Transcribe `/DESIGN.md` §2 into `panel/styles/tokens.css` — core colors, neutral 100–900, accent 100–900, the four SD10 `--st-*` status colors, utility aliases (`--rule`, `--muted`, `--faint`), typography, spacing, radii, shadows; import it in the root layout
  - [ ] 2.3 First commit; open draft PR against `main` with `Closes #118`
  - [ ] 2.4 Write the formatter unit tests **first**, then `panel/lib/format.ts` implementing `/DESIGN.md` §7: 24h `HH:MM:SS`, relative times, `Xm XXs` durations, `running · Xm`, short uppercase-mono run IDs, step progress `n/m`, event counts, status legends
  - [ ] 2.5 Add `panel/styles/globals.css` with the `pulse`, `spin`, and `rise` keyframes and the hover/focus rules from `/DESIGN.md` §6, including `:focus-visible` as a 2px accent outline at 2px offset with browser default rings suppressed
  - [ ] 2.6 Build the primitives in dependency order (test-first per component): `KLabel`, `Tag`, `Button`, `Input`, `StatusDot`, `StatusPill`, `Toggle`, `Breadcrumb`, `NavItem`, `StatusBar`, `RunStrip`, `LogLine`
  - [ ] 2.7 Keep components presentational and server-render-safe; mark only the interactive ones (`Toggle`, `NavItem`) as client components
  - [ ] 2.8 Implement `LogLine` as the 4-column grid (`82px 46px 108px minmax(0,1fr)`) with `pre-wrap`, never truncating message content (`/DESIGN.md` §7.5)
  - [ ] 2.9 Wire `@phosphor-icons/react` icons per `/DESIGN.md` §10, rendered on `currentColor`; remove any Unicode glyph stand-in inherited from the prototype
  - [ ] 2.10 Add a **mechanical** token-discipline check — a stylelint rule or grep-based unit test over `components/**` and `styles/**` rejecting `#[0-9a-f]{3,8}`, `font-family:` literals, and bare `px` in spacing properties. G4: AC2's "where practical" is where this becomes review-only, and review does not scale past twelve components into Wave 3's screens — land a rule, not a judgment, and record anything genuinely not mechanizable
  - [ ] 2.11 Document the `color-mix()` browser floor (Chrome 111+, Safari 16.2+, Firefox 113+) in `panel/README.md`
  - [ ] 2.12 Add the dev-only `panel/app/dev/gallery/page.tsx` rendering every component variant side by side; confirm it is excluded from the production build
  - [ ] 2.13 Run Tests — unit: `pnpm run test:unit` — table-driven formatter tests including zero, negative, and sub-second durations, exactly-1-minute boundaries, far-past relative times, and short-ID casing
  - [ ] 2.14 Run Tests — component (Layer 2): `pnpm run test` — each component renders all its variants; `StatusPill` renders accessible text for every status; `Toggle` fires `onChange` and is keyboard-operable; `LogLine` wraps rather than truncates an 8 KB message
  - [ ] 2.15 Run Tests — edge cases: unknown status value renders a neutral fallback instead of crashing; `RunStrip` with fewer than 24 runs renders 33%-height placeholders; `StatusBar` with all-zero segments; an extremely long agent name gets single-line ellipsis, and the card variant gets a 2-line clamp
  - [ ] 2.16 Manual/UI verification: `pnpm --filter panel dev` → `/dev/gallery`, compared side by side against the prototype at `docs/prototype/` (`_ds` stylesheet plus the six screen files)
  - [ ] 2.17 Verify Acceptance Criterion: `styles/tokens.css` defines every `/DESIGN.md` §2 token, including the four SD10 status colors
  - [ ] 2.18 Verify Acceptance Criterion: no component contains a hardcoded hex, font family, or pixel spacing value
  - [ ] 2.19 Verify Acceptance Criterion: all twelve `/DESIGN.md` §11.2 components exist and are unit-tested, with the documented variant sets (`Button` primary/secondary/ghost × sm/md/default + disabled; `Tag` accent/neutral/outline)
  - [ ] 2.20 Verify Acceptance Criterion: `StatusPill`/`StatusDot` cover all six statuses including `failed_to_start` (hollow dot) and the `running`/`queued` pulse animation
  - [ ] 2.21 Verify Acceptance Criterion: status meaning is conveyed by text and never by color alone; `:focus-visible` is a 2px accent outline at 2px offset and default rings are suppressed
  - [ ] 2.22 Verify Acceptance Criterion: `lib/format.ts` implements every `/DESIGN.md` §7 convention
  - [ ] 2.23 Verify Acceptance Criterion: icons come from `@phosphor-icons/react` on `currentColor`, with no Unicode stand-ins remaining
  - [ ] 2.24 Record `/DESIGN.md` impact notes in the PR — any prototype detail that could not be reproduced, and any token or component clarification added
  - [ ] 2.25 Map acceptance criteria to test evidence and record the mapping in the PR: AC1–AC2 → token file review + stylelint output; AC3–AC5 → component tests; AC6 → `format.test.ts`; AC7 → import audit
  - [ ] 2.26 Run quality gates: `pnpm run lint`, `pnpm run format:check`, `pnpm run typecheck`, `pnpm run test`, `pnpm run audit`, then `make validate`
  - [ ] 2.27 Migration lifecycle: **not applicable** — presentational story, no schema or data-model change. Opt-out rationale recorded here and in the issue
  - [ ] 2.28 Mark PR ready for review, notify the user, and close #118 only after the PR is approved and merged

- [ ] 3.0 Implement Story S-111 ([#124](https://github.com/llipe/dev-tasks-agent-fleet/issues/124)): AWS credential provider — Fly OIDC and local chain

  > Note: implements **FR15**/**D12** and resolves **F5** via **SD9**. `docs/reference/credentials.ts:59-62` carries the defect that matters: `parsed.value ?? parsed.token ?? parsed.aud` would send the *audience* string (`sts.amazonaws.com`) to STS as a web identity token, producing a misleading auth error instead of a clear parse failure — and `data.trim()` does the same for unparseable bodies. **SR1** (the real socket response shape is unverified) is precisely why the failure mode must name what it actually received.

  - [ ] 3.1 Create branch `story/S-111-aws-credential-provider` from latest `main`; confirm #124 is open
  - [ ] 3.2 Re-confirm and pin the four `@aws-sdk/*` packages — `client-sts`, `client-bedrock-agentcore`, `credential-providers`, `types` — **all to the same minor** (spec §16 requirement); record the chosen minor and verify the lockfile holds a single `@smithy/core` version
  - [ ] 3.3 First commit; open draft PR against `main` with `Closes #124`
  - [ ] 3.4 Move `docs/reference/credentials.ts` to `panel/lib/aws/credentials.ts`; replace the reference file with a pointer link (same treatment the S-102 SQL stubs received, so the two copies cannot drift)
  - [ ] 3.5 Add `panel/lib/aws/errors.ts` with `FlyOidcShapeError` and the `CREDENTIALS_UNAVAILABLE` (500) / `INVOCATION_FAILED` (502) taxonomy from spec §13, kept distinct because the runbooks differ (**R6**)
  - [ ] 3.6 Replace the token-extraction chain: accept `value` or `token` only; any other shape throws `FlyOidcShapeError` naming the keys actually received. Remove the `parsed.aud` fallback and the `data.trim()` raw-body fallback
  - [ ] 3.7 Retain unchanged: `FLY_APP_NAME` + socket-existence branch detection, the in-memory cache with 60-second refresh margin, the single-flight promise, and the `credentialSource()` diagnostic
  - [ ] 3.8 Confirm the local branch uses `fromNodeProviderChain()` (SSO profile, shared credentials, or environment variables) with no code change between environments, and that callers receive only a provider — never knowledge of which branch ran
  - [ ] 3.9 Translate all comments to English; **retain** the embedded `curl` verification command (it is the procedure that closes OQ1 in S-115)
  - [ ] 3.10 Keep the module free of Next.js imports so it is unit-testable in isolation; never log the token, the STS response, or the assumed-role credentials — log `credentialSource()` and error codes only
  - [ ] 3.11 Add `panel/lib/aws/invoke.ts` wrapping `InvokeAgentRuntime` against `agents.runtime_arn` + `runtime_qualifier` (consumed by S-112 / #125); log `credentialSource()` on every invoke per AC6
  - [ ] 3.12 Add any newly required environment variable to `.env.example` with a fail-fast startup check (a missing role ARN must produce a clear startup error, not a runtime auth failure)
  - [ ] 3.13 Run Tests — unit: `pnpm run test:unit` — branch detection (env set + socket present, env set + socket absent, env absent); token extraction accepting `value`, accepting `token`, rejecting `{aud}`, rejecting a non-JSON body, rejecting `{}`, each with `FlyOidcShapeError` naming the received keys; cache hit within margin; cache miss past margin; single-flight (two concurrent calls → one STS call); STS failure surfacing `CREDENTIALS_UNAVAILABLE`
  - [ ] 3.14 Run Tests — integration: **none by design** — the real OIDC socket exists only on a Fly Machine (S-115 / #128). Recorded as an explicit non-gap, not an omission
  - [ ] 3.15 Run Tests — edge cases: socket present but connection refused; socket returns 500; expired-token retry; clock skew inside the refresh margin; missing role ARN env var → clear startup error; **secret material absent from all log output, asserted by capturing logs**
  - [ ] 3.16 Manual verification: run locally with an SSO profile, confirm `credentialSource()` reports the local branch and that no AWS environment keys are required
  - [ ] 3.17 Verify Acceptance Criterion: `lib/aws/credentials.ts` exists with `FLY_APP_NAME` + socket-existence branch detection; callers receive a provider and cannot tell which branch ran
  - [ ] 3.18 Verify Acceptance Criterion: the Fly branch requests an OIDC token from `/.fly/api` with `aud=sts.amazonaws.com` and exchanges it via `AssumeRoleWithWebIdentity`
  - [ ] 3.19 Verify Acceptance Criterion: token extraction accepts `value` or `token` only; other shapes throw `FlyOidcShapeError` naming received keys; the `aud` and `data.trim()` fallbacks are gone
  - [ ] 3.20 Verify Acceptance Criterion: the local branch uses `fromNodeProviderChain()` with no code change between environments
  - [ ] 3.21 Verify Acceptance Criterion: credentials are cached in memory with a 60-second refresh margin and a single-flight promise, so concurrent invokes trigger one STS call
  - [ ] 3.22 Verify Acceptance Criterion: `credentialSource()` reports the active branch and is logged on every invoke
  - [ ] 3.23 Verify Acceptance Criterion: all comments are English and the embedded `curl` probe command is retained
  - [ ] 3.24 Verify Acceptance Criterion: `CREDENTIALS_UNAVAILABLE` (500) is defined distinctly from `INVOCATION_FAILED` (502) in the error taxonomy — noting that the taxonomy's *route-level* test lands in S-112 (#125)
  - [ ] 3.25 Record the deferrals explicitly rather than passing them silently: **PRD AC8** ("no static AWS keys", per the publication report) can only be closed by a live Fly Machine probe in S-115 / #128; **OQ1** (socket response shape, `sub` claim normalization, `DurationSeconds: 900` vs the role's `MaxSessionDuration`) stays open until the same probe; and per **G5**, AC6 is assertable here only at the `invoke.ts` boundary — its route-level guarantee, like AC8's taxonomy test, lands with S-112 (#125), so neither is reported as fully complete on this story
  - [ ] 3.26 Map acceptance criteria to test evidence and record the mapping in the PR: AC1–AC5 → `credentials.test.ts`; AC6 → log assertion; AC7 → file review; AC8 → definition here, route-level test in S-112
  - [ ] 3.27 Verify no secret material appears in any log output
  - [ ] 3.28 Run quality gates: `pnpm run lint`, `pnpm run format:check`, `pnpm run typecheck`, `pnpm run test`, `pnpm run audit`, then `make validate`
  - [ ] 3.29 Migration lifecycle: **not applicable** — no schema or data-model change. Opt-out rationale recorded here and in the issue
  - [ ] 3.30 Mark PR ready for review, notify the user, and close #124 only after the PR is approved and merged

## Wave 2 Exit Criteria

- [ ] Every Supabase read happens server-side; no `NEXT_PUBLIC_SUPABASE_*` variable exists and no client chunk contains the service role key
- [ ] `effectiveStatus` is pinned to `v_runs.effective_status` by a passing Layer 2.5 parity test, including exact-boundary rows (**SR3** mitigated)
- [ ] An anon-key client provably reads zero rows from every table and from `v_runs` (the test that would have caught **F2**)
- [ ] `/DESIGN.md` §2 exists as tokens, including the four SD10 status colors, and all twelve §11.2 primitives are implemented and tested
- [ ] Formatters implement `/DESIGN.md` §7; the dev gallery renders every variant for visual comparison against `docs/prototype/`
- [ ] The credential provider has no `aud`/raw-body token fallback and fails with `FlyOidcShapeError` naming what it received (**F5** closed)
- [ ] The four `@aws-sdk/*` packages are pinned to one shared minor with a single `@smithy/core` in the lockfile
- [ ] `make validate` green on both branches for all three stories; #117, #118, #124 merged and closed
- [ ] Wave 3 (S-106 → S-107/S-108/S-109) and Wave 4 (S-112) are unblocked

## Deferred to later waves — recorded so it is not mistaken for scope

- **`lib/domain/payload.ts`** (SD5 / F1 / issue #89) belongs to S-112, not S-111, even though both concern the invoke path.
- **The shared `tests/fixtures/agent-invocation-payload.json`** contract fixture (spec §14, **SR4**) lands with S-112.
- **The SSE relay** (`lib/` + route, SD6) lands with S-110; S-104's `run_events` helper is the bounded initial read only (SD11, 2,000 events).
- **`run_steps` steps panel** is deferred to v3 (C8); S-104 still exposes the helper because step names label log lines.
- **Route-level error-taxonomy tests** for `CREDENTIALS_UNAVAILABLE` vs `INVOCATION_FAILED` land with S-112's route handler.
- **Derived status reaching `StatusPill`** (test plan **G6**) is not provable in Wave 2. CT-1 proves `effectiveStatus` is correct and AC-105.4 proves the pill renders six statuses, but the composition happens in Wave 3 — recorded as a required scenario for the S-107 (#120) and S-108 (#121) plans rather than something to discover mid-Wave-3.
