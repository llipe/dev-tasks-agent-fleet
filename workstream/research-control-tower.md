# Research: existing panel patterns for the Control Tower (prd-control-tower v1.1)

## Changelog

| Version | Date       | Summary                                                                 | Author     |
| ------- | ---------- | ----------------------------------------------------------------------- | ---------- |
| 1.0     | 2026-11-25 | Initial artifact: webhook precedent, Supabase conventions, release gate, tests, PRD contradictions. | researcher |

## Provenance

- Repository: `/home/user/dev-tasks-agent-fleet`
- Base branch: `claude/control-tower-dashboard-37wozg` (checked out; not switched)
- Commit SHA: `f21fa20d0f7fe756b12eb580db67e9ec7d354adc`
- Uncommitted changes: not inspected
- Invoking agent: direct user request, pre-spec input for `docs/requirements/prd-control-tower.md`
- Research question: map how the panel does, today, (1) the public token-authenticated inbound endpoint, (2) show-once secret issuance and storage, (3) Supabase conventions, (4) scheduled DB jobs and retention, (5) live updates, (6) navigation and page structure, (7) the release gate, (8) tests; plus constraints from the technical guidelines and ADRs, and contradictions with the PRD.
- Date: 2026-11-25
- Package attribution: `panel` is the only Node package in scope (its package manifest and the pnpm workspace file). `supabase/`, `scripts/`, `TESTING.md` and `docs/` are attributed `(repo root)`. `docs/technical-guidelines.md` has no package map (confirmed by grep; the PRD's D-17 says the same). `docs/tech.md` is absent, so the fallback name `docs/technical-guidelines.md` was read. `detectWorkspace` is not present in this repository (not checked further).

## Answer first

1. **Inbound endpoint.** `panel — panel/app/api/webhooks/[token]/route.ts` is a `POST` handler with inline `force-dynamic`/`runtime="nodejs"` config. `panel/lib/auth/route-policy.ts:65-67` classifies `/api/webhooks/**` as `internal`, so `panel/proxy.ts:161-163` skips the session gate. Authorization is the HMAC check in a pure core, `panel/lib/webhooks/receive.ts`. Body cap is 5 MiB, enforced by `panel/lib/webhooks/read-body.ts`.
2. **Secrets are not hashed.** The signing secret is stored in Supabase Vault (`webhook_endpoint_<id>`) and read back by a service_role-only RPC. The URL token is stored in plaintext in `webhook_endpoints.url_token`. Nothing in the repo stores a credential as a one-way hash. This contradicts PRD §9, §12, §17 and FR-2 (see Contradictions C1).
3. **Constant-time compare** exists only for the HMAC digest and the scheduler secret. The webhook URL token is a plain DB equality lookup (C2).
4. **Supabase.** Migrations are `supabase/migrations/YYYYMMDDHHMMSS_snake_name.sql`; the latest is `20261103120000_seed_code_review_agent.sql`. RLS is deny-all with no policies. The panel reads and writes only through the service-role client in `panel/lib/supabase/server.ts`. The only existing `repositories` table is the agent-target table, unique on `(installation_id, full_name)` (C5).
5. **Retention.** Settings live in a `webhook.config` table. `webhook.prune_deliveries()` deletes by `created_at`. pg_cron runs it daily at `17 3 * * *`.
6. **Live updates.** The browser never reads tables. The run live tail uses `EventSource` to `panel/app/api/runs/[id]/events/stream/route.ts`, which holds a server-side Supabase Realtime subscription. The notifications bell has no realtime and no polling; it receives data from the layout and calls `router.refresh()`.
7. **Release gate.** `scripts/verify-panel-auth.sh` has six probes. Check 6 POSTs an unsigned delivery to `/api/webhooks/<WEBHOOK_PROBE_TOKEN>` and requires 401. Unknown tokens return 404, which fails the gate. Verdicts come from `panel/scripts/panel-auth-check.mjs`.
8. **Navigation.** `panel/components/shell/Sidebar.tsx` is a hard-coded list of `NavItem`s. Pages live in `panel/app/(panel)/<route>/page.tsx` with a sibling `page.module.css`.
9. **Not determinable from the repo:** production Supabase grants and Realtime state, whether `WEBHOOK_PROBE_TOKEN` is set on Fly, and whether tests currently pass (not executed).

## Relevance-ranked file map

1. `(repo root)` — `docs/requirements/prd-control-tower.md` — the PRD under review
2. `panel` — `panel/app/api/webhooks/[token]/route.ts:48-150` — inbound POST handler, DB/Vault wiring, 500 path
3. `panel` — `panel/lib/webhooks/receive.ts:27-202` — ordered receive core (404 → 413 → 401 → dedup → 202)
4. `panel` — `panel/lib/webhooks/read-body.ts:11-37` — raw-bytes reader with Content-Length precheck and streamed cut-off
5. `panel` — `panel/lib/auth/webhook-signature.ts:31-93` — HMAC-SHA256 verify (timingSafeEqual) and dedup key
6. `panel` — `panel/lib/auth/route-policy.ts:43-76` — `public` / `internal` / `api` / `ui` classification
7. `panel` — `panel/proxy.ts:146-182` — the single auth gate; `internal` branch at 161-163; 401 JSON for `api` at 172-176
8. `panel` — `panel/lib/auth/internal-secret.ts:37-79` — the only constant-time compare in the repo besides the HMAC digest
9. `panel` — `panel/lib/domain/webhook-endpoint-save.ts:162-228` — create/rotate generate 32-byte token and secret (`randomBytes`)
10. `panel` — `panel/app/(panel)/webhooks/actions.ts:51-92` — Server Actions for create/rotate/delete/toggle (service-role client)
11. `panel` — `panel/lib/supabase/queries.ts:1253-1316, 1508-1619` — secret read RPC, token lookup, dedup claim upsert, admin RPC wrappers, list (selects `url_token`)
12. `panel` — `panel/components/webhooks/SecretReveal.tsx:10-16, 56-64` — show-once dialog
13. `panel` — `panel/components/webhooks/WebhooksClient.tsx:100-115, 160-179` — rotate/delete flows; URL rebuilt from `row.url_token`
14. `supabase` (repo root) — `supabase/migrations/20261019180000_webhook_schema.sql` — enums, endpoint/rule/delivery tables, CHECKs, deny-all RLS
15. `supabase` (repo root) — `supabase/migrations/20261019181000_webhook_vault_config.sql` — `webhook.config`, Vault wrappers, service_role-only grants, `public.webhook_endpoint_secret`
16. `supabase` (repo root) — `supabase/migrations/20261019182000_webhook_prune.sql:17-64` — prune function and daily cron registration
17. `supabase` (repo root) — `supabase/migrations/20261020160000_webhook_endpoint_admin.sql:24-76` — create/rotate/delete RPCs (secret and row in one transaction)
18. `supabase` (repo root) — `supabase/migrations/20260902200101_initial_schema.sql:56-68, 343-357, 212-213` — `repositories`, pg_cron extension and first schedule, deny-all RLS, Realtime publication
19. `panel` — `panel/lib/supabase/server.ts:26` (+ `createServerClient`) — `server-only` guard and service-role client
20. `panel` — `panel/app/api/runs/[id]/events/stream/route.ts:30-33, 98-136` — SSE relay with server-side Realtime `postgres_changes`
21. `panel` — `panel/lib/sse/cursor.ts:1-12` — per-run `seq` ordering the relay depends on
22. `panel` — `panel/app/(panel)/layout.tsx:32-77` — auth check, bell data fetch, `AppShell` wiring
23. `panel` — `panel/components/shell/Sidebar.tsx:46-117` — active-route logic and the NavItem list
24. `(repo root)` — `scripts/verify-panel-auth.sh:17-35, 151-337` — release gate probes 2, 3, 5, 6 and input assembly
25. `panel` — `panel/scripts/panel-auth-check.mjs` (checkWebhookRejected ~321-383; evaluateAuthGate 390-404) — pure verdict parser
26. `(repo root)` — `TESTING.md:58-99, 68-75, 110, 430-457` — layer contract, Layer 2.5 boundary, Docker gating, auth-gate tests
27. `(repo root)` — `docs/technical-guidelines.md` §2 (line ~100), §6 (267-277), §7 (278-371) — RLS, Realtime, panel read boundary, paging
28. `panel` — `panel/tests/integration/rls-deny-all.test.ts:41-61` — anon zero-row assertion over every base table
29. `panel` — `panel/tests/unit/webhook-receive.test.ts` — unit coverage of the receive ordering
30. `(repo root)` — `.github/workflows/ci.yml:168-179` — parser suite run by name; shellcheck of the gate script

Related test files named but not cited for the 30-file budget (integration: webhook-route, webhook-prune, webhook-vault, webhook-schema; E2E: webhooks-crud, webhooks-delivery, live-tail). They sit in `panel/tests/integration/` and `panel/tests/e2e/`.

## Slice findings

### S1 Components and modules

**Pattern 1 — public token-authenticated inbound endpoint (`panel`).**
- Route config is declared inline (`route.ts:48-51`): `force-dynamic`, `revalidate = 0`, `fetchCache = "force-no-store"`, `runtime = "nodejs"`. This follows the S-104 convention.
- Token to endpoint: `route.ts:124-131` passes `params.token` and `readBodyWithLimit(request, WEBHOOK_MAX_BODY_BYTES)` into `receiveWebhook`. `receive.ts:107-113` checks the format `^[A-Za-z0-9_-]{32,64}$` first (no DB call), then `getWebhookEndpointByToken` (`queries.ts:1274-1287`, `.eq("url_token", token)`). Unknown or disabled tokens return **404**, with no row written.
- Size cap: `WEBHOOK_MAX_BODY_BYTES = 5 MiB` (`receive.ts:27`). `read-body.ts:12-15` refuses on a declared `Content-Length` over the cap. `read-body.ts:21-28` cuts the stream when the header is absent or wrong and cancels the reader. The cap check (413) runs after the endpoint lookup and before the signature check (`receive.ts:115-122`).
- Fail-closed signature: `receive.ts:128-144` treats a null secret as `secret_not_configured`, returns **401**, and records an `unauthorized` row with no dedup key. `webhook-signature.ts:46-67` returns a fixed reason token. The digest comparison is `timingSafeEqual` (`webhook-signature.ts:59-66`), and the header must match `^sha256=[0-9a-f]{64}$` (line 31).
- Dedup and idempotency: `webhook-signature.ts:83-93` builds the key as `id:<delivery-id header>` or `body:<sha256>`. `queries.ts:1304-1309` upserts with `onConflict: "endpoint_id,dedup_key", ignoreDuplicates: true`. A conflict returns **200** `{duplicate: true}` (`receive.ts:146-165`). The DB backs this with `uq_webhook_deliveries_dedup` and a CHECK that `unauthorized` rows carry no key (`webhook_schema.sql`).
- Event filter: an event not on the allowlist, or a missing event header, gets **202** `ignored` (`receive.ts:167-176`). Invalid JSON gets 202 `ignored` (`receive.ts:178-186`).
- Error path: any thrown error becomes **500** `{error: "INTERNAL_ERROR"}`, logged with the error name only (`route.ts:137-149`). The comment notes GitHub retries with the same delivery id.
- Logging: `console.info(JSON.stringify(fields))` with fixed fields (`route.ts:62-72`, `receive.ts:98-104`). No payload, secret or signature is logged.

**Pattern 1b — the session gate exemption (`panel`).**
- `route-policy.ts:43-45`: exact `public` paths are `/login` and `/api/auth/logout`.
- `route-policy.ts:60-67`: `/api/webhooks` and `/api/webhooks/**` are `internal`, with the comment "HMAC-signed, NOT session-gated".
- `route-policy.ts:69-73`: any other `/api/**` is `api`. Unknown paths default to `ui` (lines 75-76).
- `proxy.ts:161-163`: `internal` returns `NextResponse.next()`. The gate never authorizes this class.
- `proxy.ts:172-176`: a denied `api` request gets **401 JSON**; a denied `ui` request gets a 302 to `/login`.
- `proxy.ts:5-8` and `ADR-008`: the proxy runs on the Node runtime. `proxy.ts:60` sets a 5 s `getClaims()` bound that fails closed.
- **Implication for the tower:** a path such as `/api/tower/**` is `api` by default. That gives a 401 JSON to a token-bearing CLI push unless `route-policy.ts` gets an explicit entry, as webhooks have.

**Pattern 2 — show-once secret issuance and storage (`panel`).**
- Generation: `lib/domain/webhook-endpoint-save.ts:171-172` (create) and `:221` (rotate) call `randomBytes(32)`. The URL token is base64url. The secret is hex. The `randomBytes` dependency is injected (`webhooks/actions.ts:3, 51-57`).
- Create writes the endpoint and its Vault secret in one RPC transaction (`webhook_endpoint_admin.sql:24-48`, `createWebhookEndpoint` at `queries.ts:1543-1561`). `webhook_vault_config.sql` names Vault entries `webhook_endpoint_<endpoint_id>` (`set_endpoint_secret`, `read_endpoint_secret`, `delete_endpoint_secret`).
- Read path: `public.webhook_endpoint_secret(uuid)` is service_role-only (`webhook_vault_config.sql`, grants at the end of the file). It is called by `getEndpointSecret` (`queries.ts:1253-1262`) from the inbound route only.
- Rotate: `rotateSecretAction` (`actions.ts:69-75`) calls `webhook_rotate_endpoint_secret`. It rotates the **secret only**. There is no action that rotates the URL token (`actions.ts` exports create, update, rotate, delete, toggle).
- Revoke-like flows that exist: `toggleEndpointAction` (`actions.ts:84-92`, sets `is_enabled`; a disabled endpoint returns 404 per `receive.ts:111`); `deleteEndpointAction` (`actions.ts:77-82`, Vault secret deleted first, then the row).
- Show-once UI: `SecretReveal.tsx:10-16` states the secret exists only in parent state while the dialog is open, and there is no Escape or backdrop close. The create and rotate results carry the secret (`webhook-endpoint-save.ts:67-71`). `getWebhookEndpointsForList` (`queries.ts:1508-1525`) selects `url_token` and never the secret.
- **Hashing: none.** Searches of `supabase/migrations/*.sql` for `digest`, `hash` and `crypt` found no credential hashing. In `panel/`, `createHash` appears only in `webhook-signature.ts:92`, for the body-derived dedup key.
- **The URL token is not show-once.** `WebhooksClient.tsx:111` rebuilds the full payload URL from `row.url_token` on the list page. Only the secret has the show-once property.

**Pattern 3 — Supabase reads and writes (`panel`).**
- `lib/supabase/server.ts:26` imports `server-only`. `createServerClient()` uses `SUPABASE_SERVICE_ROLE_KEY` with `autoRefreshToken: false` and `persistSession: false`. The panel makes no user sessions against Supabase.
- The browser client module uses only the publishable key and the auth cookie path. No browser code queries a table.
- Every webhook query takes an explicit `SupabaseClient` and throws `DatabaseError` on failure (`queries.ts` header; the Supabase error module).

### S2 APIs and contracts

- **Webhook URL contract:** `POST /api/webhooks/<token>`, `Content-Type` is not checked. Required headers: the signature header (default `x-hub-signature-256`) and the delivery id header (default `x-github-delivery`). The generic source may choose other header names (`webhook-endpoint-save.ts:18-22, 111-126`). The event header is `x-github-event` (`receive.ts:30`).
- **Status codes in use:** 202 received/ignored/routed, 200 duplicate, 401 unauthorized, 404 unknown or disabled token, 413 too large, 500 internal (`receive.ts`, `route.ts`).
- **Release-gate contract (external):** `scripts/verify-panel-auth.sh` probes `/api/webhooks/<probe>` (lines 301-327). The parser counts 401 as the only pass (`panel-auth-check.mjs`, `checkWebhookRejected`).
- **Read contract precedent:** the only browser-facing JSON or SSE route is `api/runs/[id]/events/stream`, session-gated. The run stream hook (not cited) stops reconnecting after an auth failure.

### S3 UI surfaces

- **`/webhooks` page:** the `/webhooks` server page is an async server component. It reads endpoints with rule counts and passes them to `WebhooksClient`. It takes the origin from the request so the payload URL is correct behind Fly.
- **Dialogs and flows:** `WebhooksClient.tsx:100-115` (rotate: a confirm, then `rotateSecretAction`, then `SecretReveal` with `rotated: true`). `WebhooksClient.tsx:160-179` (delete confirm). `SecretReveal.tsx:63-64` says deliveries signed with the old secret "now return 401".
- **Notification bell:** the bell component (`NotificationBell`, lines 19-25) says initial data is server-fetched in the authenticated layout. `:41-58` marks read via Server Actions and then calls `router.refresh()`. There is no realtime subscription and no interval in the bell or the layout (grep for `setInterval` and `postgres_changes` in `components/shell`, `components/notifications`, `app/(panel)/layout.tsx` returned nothing).
- **Shared styling:** the webhook screens use CSS Modules (`Webhooks.module.css`) with tokens from `/DESIGN.md`. `DESIGN.md` §3.4 (status pill) and §3.7 (`.klabel` section label) are the elements the PRD says to reuse. The status pill, section label and tag components exist under the panel's shared components directory.

### S4 Tests (`panel`, plus `TESTING.md`)

- **Layers (`TESTING.md:58-63`):** Layer 1 unit (`panel/tests/unit/`, 72 files), Layer 2 component (jsdom, `panel/tests/component/`), Layer 2.5 integration (real local Postgres, `panel/tests/integration/`), E2E (Playwright, `panel/tests/e2e/`).
- **Unit, webhook-related:** `webhook-receive.test.ts` (cited), `webhook-signature.test.ts`, `webhook-read-body.test.ts`, `webhook-endpoint-save.test.ts`, `webhook-dispatch.test.ts`, `webhook-secret-query.test.ts`, `auth-route-policy.test.ts`, `panel-auth-check.test.ts` and `panel-auth-check-cli.test.ts`.
- **Integration (real DB):** `webhook-route.test.ts` (the route end to end), `webhook-prune.test.ts` (prune horizon, batch, the cron job and grants), `webhook-vault.test.ts` (grants asserted at SQL and through PostgREST with the anon key), `webhook-schema.test.ts`, `webhook-endpoint-admin.test.ts`. `rls-deny-all.test.ts` (cited) enumerates every `public` base table from `information_schema` and asserts the anon key reads zero rows from each. `EXPECTED_TABLES` (lines 42-50) is a subset check and does not list the webhook tables. A new tower table is therefore covered by the anon assertion without a list edit.
- **E2E:** `webhooks-crud.spec.ts`, `webhooks-delivery.spec.ts`, `live-tail.spec.ts`, and `fixtures/webhook-seed.ts`. Playwright config (`testDir: ./tests/e2e`, `testMatch: *.spec.ts`).
- **Rules from `TESTING.md`:** Layer 2.5 "must not mock the data layer" (line 72). Layer 2.5 suites are Docker-gated through `probeLocalDb` (lines 77-99), and CI boots the stack with `REQUIRE_LOCAL_DB=1`. A security-negative test is "required for every authentication and authorization code path" (line ~433). The auth-gate section (lines 446-457) names the parser suites and the anon RLS test.
- **Layer 2.5 grant gotcha:** `docs/technical-guidelines.md` §7 (lines 71-86) records that a fresh local DB does not reproduce platform SELECT grants for `service_role`. The `queries` integration test applies that grant in setup. A tower integration suite would need the same setup or it fails locally.

### S5 Data model and RLS (`supabase`, repo root)

- **Migration conventions:** file names `YYYYMMDDHHMMSS_snake_name.sql`. Header block: "Story S-### (#issue)", purpose, and a `Rollback:` comment (`webhook_schema.sql:1-7`). Enums via `create type` (`webhook_source`, `webhook_outcome`). Tables are plural snake case. Constraints are named `uq_`, `chk_`, `idx_`. Triggers `trg_<table>_updated` call `set_updated_at()`.
- **RLS:** `alter table <t> enable row level security` with no policies (`webhook_schema.sql` end of file; `initial_schema.sql:351-357`). The comment says only service_role reads and writes (it bypasses RLS). `TECH §6` (lines 267-277) records this as D11.
- **`repositories` (existing, `initial_schema.sql:56-68`):** `id uuid`, `installation_id uuid not null` (FK to `github_installations`), `github_repo_id bigint`, `full_name text`, `default_branch`, `is_enabled`, `metadata jsonb`, `archived_at`, timestamps. Unique on `(installation_id, full_name)`, not on `full_name` alone. Webhook rules resolve agent targets from enabled, non-archived rows in this table.
- **Realtime publication:** only `run_events` and `runs` are added to `supabase_realtime` (`initial_schema.sql:212-213`). A tower table is not published.
- **PostgREST:** the Supabase CLI config exposes `public` and `graphql_public` (lines 12-13) and sets `max_rows = 1000` (line 18). `TECH §7` (lines 87-95) requires paging below that limit.
- **Enum/table naming in webhook tables:** `webhook_endpoints`, `webhook_rules`, `webhook_deliveries`, plus the `webhook` schema for `config` and functions. The `webhook` schema is revoked from `public`, and its usage is granted to `service_role` only.

### S6 Config, env and CI

- **Env names (never values in logs):** `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY` (server), `NEXT_PUBLIC_SUPABASE_URL` and `NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY` (browser auth), `SCHEDULER_TRIGGER_SECRET` (internal), `WEBHOOK_PROBE_TOKEN` (release gate, check 6).
- **Release gate inputs:** `fly secrets list` names (check 1), `PANEL_AUTH_ENV_NAMES` override, `PANEL_AUTH_CONNECT_TIMEOUT` (default 10 s) and `PANEL_AUTH_MAX_TIME` (default 20 s) (`verify-panel-auth.sh:82-83`).
- **CI:** `.github/workflows/ci.yml:173` runs the parser suite by name (`vitest --project unit panel-auth-check`). Line 179 runs `shellcheck scripts/verify-panel-auth.sh`.
- **Settings table pattern:** `webhook.config` (`webhook_vault_config.sql:38-49`) is a key/value table, not GUCs, because "the Supabase migration role cannot ALTER DATABASE SET app.*" (comment in the same file). `webhook.delivery_retention_days()` falls back to 30 for any missing or invalid value.

### S7 Relationships and flow

- Inbound: `POST /api/webhooks/<token>` → `proxy.ts` (internal, pass-through) → `route.ts` → `receiveWebhook` (`receive.ts`) → `getWebhookEndpointByToken` / `getEndpointSecret` (service-role queries; the secret comes from Vault through `public.webhook_endpoint_secret`) → `claimWebhookDelivery` (upsert) → `dispatchDelivery` → invoke.
- Admin: `/webhooks` page → `WebhooksClient` → Server Actions (`actions.ts`) → `webhook-endpoint-save.ts` cores (generate secret, validate) → `queries.ts` RPC wrappers → `webhook_*` SQL functions (`SECURITY DEFINER`, service_role-only grants).
- Scheduled: pg_cron → `webhook.prune_deliveries()` → `webhook.config` read. The runs-side jobs (`reap-stale-runs`, `fire-due-schedules`) use `pg_net` to `/api/internal/**` with `X-Scheduler-Secret` (`internal-secret.ts:25`).
- Live tail: browser `EventSource` (the run stream hook) → `GET /api/runs/[id]/events/stream` (`api` class, session-gated, 401 JSON on denial) → server Realtime channel `run-stream:<id>` → `postgres_changes` on `run_events` (INSERT) and `runs` (UPDATE) filtered by `run_id` / `id` (`route.ts:106-136`). The relay's backfill → subscribe → dedupe ordering depends on the per-run `seq` (`lib/sse/cursor.ts:1-12`).

### S8 Prior history and decisions

- The webhook-triggers PRD and the ADR directory (ADR-007, ADR-008) define the webhook precedent. `technical-guidelines.md` changelog row 1.52 records that webhook signing secrets are "Vault-only (`webhook_endpoint_<id>`)" and "shown once in `/webhooks`". The row does not describe a hash.
- The webhook deployment and rules runbooks exist under `docs/runbooks/` (not read in depth). The release gate's comments point to the deployment runbook for `WEBHOOK_PROBE_TOKEN`.
- `ADR-007` replaced the privacy gate with the auth release gate. `ADR-008` moved the gate to `proxy.ts` on Node.
- The control-tower decisions file exists under `workstream/` but was not read; the PRD's D-numbers are cited only as the PRD states them.

## Relationships

- The tower ingest endpoint would sit beside `panel/app/api/webhooks/[token]/route.ts` by analogy. A new `api`-class path would need an explicit `route-policy.ts` entry; without it, the session gate returns 401 JSON to the CLI.
- Vault-backed secrets are read only through a service_role-only SECURITY DEFINER function. The tower token would be a new credential with its own storage decision; no existing table holds a credential.
- The release gate has one probe per public boundary (`scripts/verify-panel-auth.sh`, positional arguments to `panel-auth-check.mjs`). A new probe changes the shell, the parser's `evaluateAuthGate` input and its CLI argv order, and the parser tests.
- The read contract, if served over HTTP, would be `api` class by default and would match the SSE route's denial behavior (401 JSON, `proxy.ts:172-176`). If served only through server components, it would follow the `queries.ts` helper pattern and the `layout.tsx` auth check.

## Risks and gotchas

- **Unknown-token status code.** The precedent returns 404 for an unknown or disabled token (`receive.ts:111-113`). The release-gate check 6 counts 404 as a failure (`panel-auth-check.mjs`, `checkWebhookRejected`) and needs a real enabled token in `WEBHOOK_PROBE_TOKEN`. A tower probe modeled on check 6 would inherit that requirement unless the status code differs.
- **Retention key.** The webhook prune deletes where `created_at < now() - horizon` (map entry 16, lines 17-30). The PRD keys the 90-day event prune on an issue's ship time and keeps summaries (FR-13, D-15). The precedent does not provide that predicate.
- **Ordering key for live updates.** The SSE relay and its cursor assume one monotonic `seq` per run (`lib/sse/cursor.ts`). Tower events have no equivalent key and are out-of-order by design (FR-9).
- **Realtime publication.** Adding a tower table to live updates requires a migration to `supabase_realtime`. Only `run_events` and `runs` are published today.
- **Relay termination.** The run relay closes on a terminal run status (`route.ts` `isRunTerminal`). A `/tower` stream has no equivalent terminal state.
- **PostgREST `max_rows = 1000`.** Reads above 1000 rows must page with `.range()`. `TECH §7` (lines 87-95) describes the precedent for `run_events`.
- **Service-role SELECT grant.** The local DB needs a test setup grant for `service_role` (`TECH §7` lines 71-86). Production relies on platform defaults, which the guidelines say is proven by inference, not by a live assertion.
- **Vault deletion order.** `webhook_delete_endpoint` deletes the Vault secret before the row (`webhook_endpoint_admin.sql`). A tower "remove repository revokes token" needs the same ordering decision.
- **Runbook rule.** The repository's agent rules require a runbook in the same PR for an `infra-engineer` change kind. The PRD assigns the migration push and deploy to `infra-engineer` (PRD §12). `scripts/verify-panel-auth.sh` is outside the `templates/scripts/`, `templates/workflows/` and `.github/workflows/` paths the rule names.
- **Log hygiene.** The 500 path logs only the error name (`route.ts:137-149`). The tower ingest would need the same discipline, since PRD §17 forbids the token in logs and error messages.

## Contradictions between the PRD and the repository

Each item states what the PRD says and what the repository shows. No position is taken on the resolution.

- **C1 — hashing.** PRD FR-2 ("stores only a hash, following the show-once pattern of webhook signing secrets"), §9 (tower token "a hash"), §12 ("Reuse the show-once and hashed-at-rest approach of webhook endpoints") and §17 ("stored hashed"). Repository: the webhook signing secret is stored in Vault and is decryptable by the service role; the URL token is plaintext in `webhook_endpoints.url_token`; no credential is hashed anywhere. Show-once is a UI and flow property (`SecretReveal.tsx`), not a storage property. The "hashed-at-rest" precedent does not exist in the repo.
- **C2 — constant-time token comparison.** PRD §12 says the ingest endpoint's "constant-time token comparison ... should follow that precedent." Repository: the webhook URL token is matched by `.eq("url_token", token)` (`queries.ts:1282`), which is not constant-time. Constant-time comparison exists for the HMAC digest (`webhook-signature.ts:59-66`) and the scheduler secret (`internal-secret.ts:37-44`).
- **C3 — rejection status.** PRD AC-3 says an unknown, revoked or missing token is "rejected", and §12 says the release gate should assert rejection "as it does for webhooks". Repository: unknown or disabled webhook tokens return 404 (`receive.ts:111-113`); only a bad signature returns 401. The gate asserts 401 (`verify-panel-auth.sh:301-327`).
- **C4 — live updates.** PRD §12: "Supabase Realtime for live updates, as the technical guidelines define." Repository and guidelines (`TECH §2`, line ~100): Realtime is defined for `run_events` and `runs`, consumed only by the server-side relay. The browser never subscribes. No tower table is published. The PRD does not name a relay.
- **C5 — "repository".** PRD §9 "Tower repository", FR-1 ("registered at most once by `owner/name`"). Repository: the existing `repositories` table is unique on `(installation_id, full_name)`, requires an installation FK, and is the agent-target table. The PRD names no table, so a name collision is not resolved in the PRD.
- **C6 — prune predicate.** PRD §12 says the daily prune "follows the webhook-delivery prune." Repository: that prune deletes by `created_at` and a horizon read from `webhook.config` (map entry 16). PRD FR-13 keys deletion on an issue's ship time (90 days after ship), and FR-12 keeps summaries permanently.
- **C7 — release gate scope.** PRD §12 and §17 say the gate asserts both boundaries: unauthenticated push rejected, and unauthenticated read refused (AC-23). Repository: probe 2 requests `PROTECTED_PATH` (default `/`) and expects a 302 (`verify-panel-auth.sh:151-171`). An `api`-class read path returns 401 JSON, not 302, so a read-contract probe would need its own expected status and the parser's `checkProtectedRedirect` would not apply. Probe 3 covers only the SSE path.
- **C8 — public write surfaces.** PRD §17 calls the ingest "the panel's third public write surface, after login and webhooks." Repository: `route-policy.ts:43-45` also lists `/api/auth/logout` as `public` (a POST that ends a session). Minor count difference.
- **C9 — foundation docs.** PRD D-17 and §16 say the technical guidelines have no package map, so the Vocabulary's bounded context "panel" does not resolve. Repository: confirmed (no package map in `docs/technical-guidelines.md`). `docs/tech.md` is absent; the old file name is present.

## External sources (optional)

None consulted.

## Not investigated

- Test bodies beyond their names: the webhook integration suites (route, prune, vault, schema, endpoint admin), the webhook E2E specs and their seed fixture. Tests were not executed.
- The webhook table, delivery log, rule editor and per-endpoint page components.
- The webhook dispatch and fire modules, and the `invokeResolvedRun` path.
- The SSE relay engine beyond its header, and the run stream hook in full.
- `DESIGN.md` token values and the webhook CSS module contents.
- The webhook deployment and rules runbooks (names only).
- The other pg_cron migrations (scheduler family), including the fire-due and digest jobs.
- The seed file, the rest of the Supabase CLI config, the Fly config, the Docker file, and the deploy scripts.
- Live state: production Supabase grants, Realtime publication, pg_cron job status, Fly secrets (names or values). Not reachable from the repository.
- The companion `llipe/dev-tasks` PRD and the control-tower decisions file (not read).
- Whether `detectWorkspace` exists in this repository (not checked).
- Whether the working tree has uncommitted changes (not checked).

## Confidence

- **High** for file, line and symbol facts quoted from source (read directly in this session at SHA `f21fa20d`).
- **High** for the contradictions C1, C2, C3, C5, C6, C9, which compare a PRD sentence to a file.
- **Medium** for C4 and C7, which depend on how the spec chooses to relay live data and to probe a read path.
- **Medium** for the Layer 2.5 grant gotcha and production grant behavior, which the guidelines themselves describe as inference.
- **Not verified:** that any test passes today; that `pg_cron`, Vault or Realtime are enabled on the hosted project.
