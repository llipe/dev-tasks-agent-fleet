# Implementation Plan - Webhook Triggers (Phase 1)

> Execution plan for [`prd-webhook-triggers`](../docs/requirements/prd-webhook-triggers.md) /
> [`specification-prd-webhook-triggers`](specification-prd-webhook-triggers.md) (v1.1) /
> [`user-stories-prd-webhook-triggers`](user-stories-prd-webhook-triggers.md) (v1.0) /
> [`decisions-webhook-triggers`](decisions-webhook-triggers.md) (D-W1…D-W15).
> GitHub issues **#309–#311, #313–#324** (S-165…S-179), milestone `v4.0 — Phase 1 Webhook Triggers`.
>
> **Ordering is dependency-correct**, grouped by wave. Each story is a branch → reviewed PR into
> `integration/webhook-triggers`; the integration branch goes to `main` via one reviewed PR at the end
> (human review is the gate; no agent merges to `main`). **Test-first:** `[T]` tasks precede their `[I]`
> tasks. `make validate` must pass before a PR is marked ready; `verifier` audit is mandatory pre-PR.

## Changelog

| Version | Date       | Summary                                    | Author           |
| ------- | ---------- | ------------------------------------------ | ---------------- |
| 1.0     | 2026-10-19 | Initial task list for all 15 stories (S-165–S-179). | product-engineer |
| 1.1     | 2026-10-19 | B-4 decided (D-W16): tasks 1.1, 1.2, 5.3, 5.6 updated for the verified-only `dedup_key`. | product-engineer |

## Conventions

- **Branches:** `story/S-165-webhook-schema`, … Integration branch: `integration/webhook-triggers` (cut from `main`).
- **Commits:** Conventional Commits (`feat(webhooks): …`, `test(webhooks): …`, `docs(webhooks): …`).
- **Package brackets:** `[panel]` is the pnpm workspace package. `[supabase]`, `[scripts]`, and `[docs]` are repo-root directories, not workspace packages.
- **Layers** (`TESTING.md`): L1 unit, L2 component, L2.5 integration (live local Supabase, `REQUIRE_LOCAL_DB=1`), E2E (Playwright).
- **Env constraint:** prefix pnpm/node commands with `export PATH="$HOME/.nvm/versions/node/v22.23.2/bin:$PATH"`. For L2.5/E2E, export the local Supabase env (incl. the `NEXT_PUBLIC_*` trio for E2E) **before** launching the runner.
- **DoD per story:** tests first and passing · `make validate` green · `coverage_gate` recorded · `verifier` audit (drift routed to product-engineer) · DESIGN.md match for UI stories · PR → `integration/webhook-triggers` via `--body-file`.
- **Merge discipline:** stacked story PRs merge **bottom-up, in order**, with `--no-ff` (out-of-order merges strand commits; this happened twice on the scheduler).
- **Migration gate:** every `[I]` migration is applied locally freely; applying to the **live** project (`supabase db push`) needs explicit user confirmation each time. That happens at task 16.4, not per story.

## Relevant Files

- `supabase/migrations/<ts>_webhook_schema.sql` - enums + `webhook_endpoints`/`webhook_rules`/`webhook_deliveries`, RLS (S-165)
- `supabase/migrations/<ts>_webhook_vault_config.sql` - `webhook` schema, Vault wrappers, `webhook.config` (S-166)
- `supabase/migrations/<ts>_webhook_prune.sql` - `webhook.prune_deliveries()` + daily cron (S-167)
- `supabase/migrations/<ts>_webhook_g3_notify.sql` - rule auto-disable notification kind + FK (S-173)
- `supabase/migrations/<ts>_webhook_notify_generalize.sql` - notify-sweep for `webhook:*` runs (S-174)
- `panel/lib/auth/webhook-signature.ts` - HMAC verify + dedup key (S-168)
- `panel/lib/auth/route-policy.ts` - classify `/api/webhooks/**` (S-169)
- `panel/app/api/webhooks/[token]/route.ts` - inbound route (S-169, S-171, S-172)
- `panel/lib/domain/webhook-routing.ts` - pure routing engine + bot guard (S-170)
- `panel/lib/domain/webhook-resolve.ts` - route resolution (S-171)
- `panel/lib/domain/invoke-resolved-run.ts` - shared invoke core (S-172, S-173)
- `panel/lib/domain/run-insert.ts` - `webhook` TriggerDescriptor variant (S-172)
- `panel/app/api/internal/schedules/[id]/fire/route.ts` - refactor onto the shared core (S-172)
- `panel/lib/supabase/queries.ts`, `panel/lib/supabase/types.ts` - webhook queries + row types (S-165…S-178)
- `panel/app/(panel)/webhooks/page.tsx`, `actions.ts`, `[id]/page.tsx` - UI + Server Actions (S-176…S-178)
- `panel/components/webhooks/*` (+ CSS modules) - list, endpoint form, `RuleEditor`, `DeliveryLog` (S-176…S-178)
- `panel/components/shell/Sidebar.tsx`, `panel/components/icons.tsx` - nav item (S-176)
- `scripts/verify-panel-auth.sh`, `panel/scripts/panel-auth-check.mjs` - release-gate check (S-175)
- `docs/runbooks/webhook-deployment.md` - operator runbook (S-166, extended by S-167/S-175)
- `DESIGN.md` - `/webhooks` screen, rule-editor row, delivery row (S-176…S-178)
- Tests: `panel/tests/{unit,component,integration,e2e}/webhook*` (per story)

## Tasks

## Wave A — Schema foundation + retention

- [ ] 1.0 Implement Story S-165 (#309): webhook_endpoints / webhook_rules / webhook_deliveries schema, enums, RLS · branch `story/S-165-webhook-schema`
  - [ ] 1.1 `[T]` [panel] L2.5 `panel/tests/integration/webhook-schema.test.ts`: migration applies on `db reset`; anon deny-all on all three tables (non-vacuous seeded guard); `(endpoint_id, position)` and `(endpoint_id, dedup_key)` uniques reject duplicates; two rows sharing a `delivery_id` with null `dedup_key` are both accepted (D-W16); repo_mode CHECK rejects `fixed`+null repo and `payload_field`+null field; deleting a run nulls `webhook_deliveries.run_id` (D-W4)
  - [ ] 1.2 `[I]` [supabase] Migration `<ts>_webhook_schema.sql`: enums `webhook_source`, `webhook_outcome`; the three tables with all columns/indexes/constraints from spec §5, including nullable `dedup_key` with the `(endpoint_id, dedup_key)` unique and the non-unique `(endpoint_id, delivery_id)` index (D-W16); `set_updated_at` triggers; `enable row level security` on each (D-W4)
  - [ ] 1.3 `[I]` [panel] Row types in `panel/lib/supabase/types.ts` (`WebhookEndpointRow`, `WebhookRuleRow`, `WebhookDeliveryRow`, `WebhookOutcome`, `WebhookCondition`)
  - [ ] 1.4 [supabase] Document rollback in the migration header (additive; drop tables + enums)
  - [ ] 1.5 [supabase] Seed: one disabled sample endpoint + rule in `supabase/seed.sql` targeting `security-analyst`, so local dev and E2E have a fixture
  - [ ] 1.6 Verify AC: enums, three tables, uniques, CHECK, deny-all RLS, set-null FK (map each to a 1.1 case)
  - [ ] 1.7 Run tests: `pnpm --filter panel run test:integration`; `make validate`; record `coverage_gate`
  - [ ] 1.8 `verifier` audit; open PR → `integration/webhook-triggers`

- [ ] 2.0 Implement Story S-166 (#310): per-endpoint Vault secret + webhook.config · branch `story/S-166-webhook-vault-config`
  - [ ] 2.1 `[T]` [panel] L2.5 `panel/tests/integration/webhook-vault.test.ts`: `webhook.set_endpoint_secret(id, value)` then `webhook.read_endpoint_secret(id)` round-trips; absent → null; `webhook.config` getters return `delivery_retention_days=30` and the seeded `bot_login`; no `webhook_*` table column holds the secret (D-W4)
  - [ ] 2.2 `[I]` [supabase] Migration `<ts>_webhook_vault_config.sql`: `webhook` schema; `security definer` + pinned `search_path` wrappers over Vault keyed `webhook_endpoint_<id>` (mirror `scheduler.read_secret`/`set_secret`); `webhook.config` table + typed getters; local-dev bootstrap only (D-W4, D-W15)
  - [ ] 2.3 `[I]` [supabase] Seed `bot_login` as `<app_slug>[bot]`, matching the bug-fix spec's identity rule (`user.login == <app_slug>[bot]` and `user.type == "Bot"`) (D-W12)
  - [ ] 2.4 `[I]` [panel] `queries.ts`: `getEndpointSecret` via RPC (server-only, SD2), never selected into a row type
  - [ ] 2.5 `[I]` [docs] New `docs/runbooks/webhook-deployment.md` (same PR, FR-49a): generate a secret, store it via the wrapper, paste URL + secret into GitHub, set `bot_login` for prod, rotation procedure
  - [ ] 2.6 Verify AC: Vault round-trip, config getters, no secret in a column or log line
  - [ ] 2.7 Run tests: `pnpm --filter panel run test:integration`; `make validate`; `coverage_gate`
  - [ ] 2.8 `verifier` audit; open PR

- [ ] 3.0 Implement Story S-167 (#311): prune_deliveries() + daily pg_cron retention · branch `story/S-167-webhook-prune`
  - [ ] 3.1 `[T]` [panel] L2.5 `panel/tests/integration/webhook-prune.test.ts`: rows older than the horizon are deleted, newer kept; a pruned `fired` delivery's `runs` row survives; batch cap respected (insert > cap aged rows, one call deletes exactly cap); a horizon change via `webhook.config` takes effect (D-W14)
  - [ ] 3.2 `[I]` [supabase] Migration `<ts>_webhook_prune.sql`: `webhook.prune_deliveries(p_batch int default 5000)` (`security definer`, pinned `search_path`, `delete … where id in (select … limit p_batch)`); daily `cron.schedule('webhook-prune-deliveries', …)` in the do-block-unschedule + top-level-select style (D-W14)
  - [ ] 3.3 [supabase] Rollback note: `cron.unschedule` + drop function
  - [ ] 3.4 `[I]` [docs] Runbook: add the cron to the post-deploy `cron.job` check
  - [ ] 3.5 Verify AC: horizon-bounded delete, batching, run survival, cron registered (`select * from cron.job`)
  - [ ] 3.6 Run tests: `pnpm --filter panel run test:integration`; `make validate`; `coverage_gate`
  - [ ] 3.7 `verifier` audit; open PR

## Wave B — Inbound endpoint

- [ ] 4.0 Implement Story S-168 (#313): verifyHmacSignature module · branch `story/S-168-webhook-signature`
  - [ ] 4.1 `[T]` [panel] L1 `panel/tests/unit/webhook-signature.test.ts`: valid GitHub fixture (known secret/body/header triple); wrong secret; one-byte body tamper; missing/empty header; uppercase hex; wrong length; `sha1=` prefix; empty secret → deny; never throws on garbage input (D-W1, D-W15)
  - [ ] 4.2 `[T]` [panel] L1 `deliveryDedupKey`: header present → header value; absent → `body:<sha256>`; header name matched case-insensitively (D-W15)
  - [ ] 4.3 `[T]` [panel] Security-negative: forged signature over a different body, truncated digest, timing-path test that a length mismatch returns false without throwing
  - [ ] 4.4 `[I]` [panel] `panel/lib/auth/webhook-signature.ts`: `verifyHmacSignature(rawBody, presented, secret)` and `deliveryDedupKey(...)`; reuse `constantTimeEqual` from `internal-secret.ts`; fixed `sha256=` + lowercase-hex format guard; secret-free reason strings (D-W1, D-W15)
  - [ ] 4.5 Verify AC: algorithm/format fixed, constant-time, fail-closed, dedup fallback
  - [ ] 4.6 Run tests: `pnpm --filter panel run test:unit`; `make validate`; `coverage_gate`
  - [ ] 4.7 `verifier` audit; open PR

- [ ] 5.0 Implement Story S-169 (#314): POST /api/webhooks/[token] verify + dedup + record · branch `story/S-169-webhook-route`
  - [ ] 5.1 `[T]` [panel] L1 route-policy: `/api/webhooks/x` → session-bypass class; `/api/webhooksx` stays `api` (D-W2)
  - [ ] 5.2 `[T]` [panel] L1 `panel/tests/unit/webhook-route.test.ts` (mocked queries): ordering is token → size → signature → dedup → allowlist; 404 unknown/disabled token writes no row; 401 writes `unauthorized`; 413 over cap; duplicate → 200 with no second row; non-allowlisted → 202 `ignored`; log lines contain no secret or signature (D-W3, D-W11)
  - [ ] 5.3 `[T]` [panel] L2.5 `panel/tests/integration/webhook-route.test.ts`: a real signed POST against the local DB records `received`; replaying the same `X-GitHub-Delivery` yields one `received` row and one `duplicate` response; concurrent duplicate inserts resolve to one claimed key via the unique index; a forged POST with a real delivery id is recorded `unauthorized` and the genuine signed POST with that id still fires (D-W16)
  - [ ] 5.4 `[I]` [panel] `route-policy.ts`: classify `/api/webhooks/**` as `internal` (session-bypass; the handler is the authorization). `proxy.ts` needs no change; confirm it never short-circuits 200 for this class (D-W2)
  - [ ] 5.5 `[I]` [panel] `panel/app/api/webhooks/[token]/route.ts`: Node runtime, `force-dynamic`, no cache; reject on `Content-Length` > cap, then read the stream with a byte limit (a missing `Content-Length` must not bypass the cap); default cap 5 MiB constant `WEBHOOK_MAX_BODY_BYTES` (D-W3)
  - [ ] 5.6 `[I]` [panel] Verify with S-168, record `unauthorized` rows with `delivery_id` set and `dedup_key` null; for verified deliveries set `dedup_key` and insert with `on conflict (endpoint_id, dedup_key) do nothing` (D-W16), event allowlist, structured `at: "webhook_delivery"` log (D-W11)
  - [ ] 5.7 `[I]` [panel] `queries.ts`: `getEndpointByToken`, `insertDelivery`, `updateDeliveryOutcome`
  - [ ] 5.8 Edge cases: empty body, non-JSON body after valid signature (record `ignored` with reason `invalid_json`), header case variants, token with path traversal characters
  - [ ] 5.9 Verify AC: public-but-gated, 413/404/401/200/202 shapes, recording, secret-free logs
  - [ ] 5.10 Run tests: `pnpm --filter panel run test:unit && pnpm --filter panel run test:integration`; `make validate`; `coverage_gate`
  - [ ] 5.11 `verifier` audit; open PR

## Wave C — Routing, resolution, shared invoke core

- [ ] 6.0 Implement Story S-170 (#315): pure routing engine + bot guard · branch `story/S-170-webhook-routing`
  - [ ] 6.1 `[T]` [panel] L1 `panel/tests/unit/webhook-routing.test.ts`: `selectField` dotted/indexed paths, depth limit, missing path → undefined, `__proto__`/`constructor` keys never traversed; each op true/false; length caps; event-type scoping; first-match by `position`; disabled rules skipped; default fallthrough; `no_match` (D-W7)
  - [ ] 6.2 `[T]` [panel] L1 bot guard: `sender.login == bot_login` **and** `sender.type == "Bot"` excluded when `ignore_bot_author`; a human with the same login text but `type: "User"` is not excluded; explicit `author is not <bot>` condition works with the toggle off (D-W12)
  - [ ] 6.3 `[T]` [panel] Property test: fuzz `selectField`/`routeDelivery` with generated payloads (fixed seed); never throws, always returns a valid result shape
  - [ ] 6.4 `[I]` [panel] `panel/lib/domain/webhook-routing.ts`: `selectField`, `evaluateCondition`, `evaluateRule`, `routeDelivery`; own-property access only (`Object.hasOwn`), no regex, no `eval` (D-W7, D-W12)
  - [ ] 6.5 `[I]` [panel] Zod/Ajv schema for the stored `conditions` jsonb, shared later with the rule editor (S-177)
  - [ ] 6.6 Verify AC: safe language, first-match, default, bot guard
  - [ ] 6.7 Run tests: `pnpm --filter panel run test:unit`; `make validate`; `coverage_gate`
  - [ ] 6.8 `verifier` audit; open PR

- [ ] 7.0 Implement Story S-171 (#316): route resolution · branch `story/S-171-webhook-resolve`
  - [ ] 7.1 `[T]` [panel] L1 `panel/tests/unit/webhook-resolve.test.ts`: fixed vs payload-field repo; declared-key interpolation fills params; undeclared key dropped and reported; schema-invalid → `route_rejected` with a secret-free reason (D-W8, D-W9)
  - [ ] 7.2 `[T]` [panel] L2.5: `getRepositoryByFullName` matches enabled, non-archived only; archived/disabled/unknown → `route_rejected`; no `repositories` row is ever inserted (count before = after) (D-W8)
  - [ ] 7.3 `[T]` [panel] Security-negative: payload names a repo outside the allowlist; payload tries to set an undeclared param; payload value fails the agent schema
  - [ ] 7.4 `[I]` [panel] `queries.ts`: `getRepositoryByFullName` (case-insensitive `full_name`, enabled, `archived_at is null`) (D-W8)
  - [ ] 7.5 `[I]` [panel] `panel/lib/domain/webhook-resolve.ts`: agent enabled check, repo resolution, params merge (`params.static` + `params.from_payload: {key: path}` limited to keys declared in `params_schema.properties`), `validateParams` (D-W9)
  - [ ] 7.6 `[I]` [panel] Route wiring: allowlist → `routeDelivery` → resolve → record `no_match`/`route_rejected` (202). No invoke yet (S-172)
  - [ ] 7.7 Verify AC: allowlist enforcement, params validation, no auto-create
  - [ ] 7.8 Run tests: `pnpm --filter panel run test:unit && pnpm --filter panel run test:integration`; `make validate`; `coverage_gate`
  - [ ] 7.9 `verifier` audit; open PR

- [ ] 8.0 Implement Story S-172 (#317): shared invokeResolvedRun() + webhook TriggerDescriptor · branch `story/S-172-invoke-core`
  - [ ] 8.1 `[T]` [panel] Baseline: run the existing fire-route L1 + scheduler L2.5 suites on the branch **before** refactoring and record the pass count
  - [ ] 8.2 `[T]` [panel] L1 `run-insert.test.ts`: webhook descriptor → `webhook`/`webhook:<endpoint>:<rule>`; manual/schedule shapes byte-identical (D-W5)
  - [ ] 8.3 `[T]` [panel] L1 `panel/tests/unit/invoke-resolved-run.test.ts` (mocked deps): insert-then-invoke ordering; invoke throw → `markRunFailedToStart` + typed error returned; `markRunFailedToStart` throw leaves the run queued for the reaper (D-W6)
  - [ ] 8.4 `[I]` [panel] `run-insert.ts`: add the `webhook` variant (D-W5)
  - [ ] 8.5 `[I]` [panel] `panel/lib/domain/invoke-resolved-run.ts`: extract steps 5–8 of the fire route (payload build → `buildRunInsert` → `insertQueuedRun` → `invokeAgentRuntime` → `markRunFailedToStart`) (D-W6)
  - [ ] 8.6 `[I]` [panel] Refactor `fire/route.ts` onto the core with no behavior change; the schedule-specific bookkeeping (`recordScheduleFired`/`recordScheduleFireFailure`) stays in the route
  - [ ] 8.7 `[I]` [panel] Webhook route calls the core and records `fired` + `run_id`; returns `202 {run_id}`
  - [ ] 8.8 [panel] Latency check (FR7): measure `invokeAgentRuntime` latency against the local stub and note the live figure. If it can exceed ~5 s (GitHub times out at 10 s), return 202 after the queued insert and finish the invoke in the background; the run is already a visible row and failures still go through `markRunFailedToStart`/the reaper
  - [ ] 8.9 `[T]` [panel] L2.5: a signed delivery produces a `runs` row with `trigger_type='webhook'` and `triggered_by='webhook:<endpoint>:<rule>'`; delivery row links `run_id` and `matched_rule_id` (AC1)
  - [ ] 8.10 Verify AC: one invoke path, fire-route suite count equals the 8.1 baseline
  - [ ] 8.11 Run tests: `pnpm --filter panel run test:unit && pnpm --filter panel run test:integration`; `make validate`; `coverage_gate`
  - [ ] 8.12 `verifier` audit; open PR

- [ ] 9.0 Implement Story S-173 (#318): guardrails on the shared core + G3 per rule · branch `story/S-173-webhook-guardrails`
  - [ ] 9.1 `[T]` [panel] L2.5 `panel/tests/integration/webhook-guardrails.test.ts`: G1 overlap (same agent+repo running) → `skipped:overlap`; G4 cap reached → `skipped:concurrency_cap`; G5 open PR → `skipped:open_pr`; each recorded on the delivery with no run row (AC6) (D-W10)
  - [ ] 9.2 `[T]` [panel] L2.5 G3: `auto_disable_threshold` consecutive fire-time failures disable the rule and write one notification; a success resets the counter; a disabled rule no longer matches (D-W10)
  - [ ] 9.3 `[T]` [panel] Regression: the scheduler guardrail L2.5 suites still pass after the checks move into the core
  - [ ] 9.4 `[I]` [supabase] Migration `<ts>_webhook_g3_notify.sql`: add `notification_kind` value `webhook_rule_auto_disabled`; nullable `notifications.webhook_rule_id` FK `on delete set null`; rollback note (enum values cannot be dropped; document the leave-in-place rollback)
  - [ ] 9.5 `[I]` [panel] Run the G1/G4/G5 checks inside `invokeResolvedRun()` before insert, returning a typed skip; schedule route keeps its existing skip bookkeeping (D-W10)
  - [ ] 9.6 `[I]` [panel] Per-rule counter update + auto-disable + notification on the webhook path (D-W10)
  - [ ] 9.7 [docs] Note in the spec/issue that G2 catch-up is n/a for webhooks
  - [ ] 9.8 Verify AC: shared guardrails, per-rule breaker, skip reasons visible
  - [ ] 9.9 Run tests: `pnpm --filter panel run test:integration`; `make validate`; `coverage_gate`
  - [ ] 9.10 `verifier` audit; open PR

## Wave D — Notifications + release gate

- [ ] 10.0 Implement Story S-174 (#319): generalize notify-sweep (+ #302) · branch `story/S-174-notify-generalize`
  - [ ] 10.1 **Decision gate (user):** resolve #302 before implementing. Should the sweep record notifications for runs whose schedule/rule was deleted (`left join`) or drop them (`join`)? Recommended: `left join`, since a failed run is worth reporting even after its trigger is gone. Record the answer on #302 and in the decisions log
  - [ ] 10.2 `[T]` [panel] L2.5 extend `notify-sweep.test.ts`: webhook run failure → `run_failed`; webhook run with a PR artifact → `pr_opened`; success with opt-in → `run_succeeded`; exactly-once per `(run_id, kind)` over two sweeps; deleted-rule run behaves per 10.1; scheduled-run cases unchanged (D-W11)
  - [ ] 10.3 `[I]` [supabase] Migration `<ts>_webhook_notify_generalize.sql`: sweep resolves the trigger from `triggered_by` prefix (`schedule:` / `webhook:`), sets `schedule_id` or `webhook_rule_id`; applies the #302 join choice; `run_succeeded` opt-in for webhook rules read from a `notify_on_success` column on `webhook_rules` (add here if not in S-165)
  - [ ] 10.4 `[I]` [panel] Notification feed/digest render a webhook-origin notification (title names the endpoint + rule)
  - [ ] 10.5 Verify AC: same kinds for both triggers, idempotent, #302 resolved
  - [ ] 10.6 Run tests: `pnpm --filter panel run test:integration`; `make validate`; `coverage_gate`
  - [ ] 10.7 `verifier` audit; open PR; close #302 with a comment (`--body-file`) referencing the PR

- [ ] 11.0 Implement Story S-175 (#320): release gate asserts unsigned webhook → 401 · branch `story/S-175-gate-webhook`
  - [ ] 11.1 `[T]` [panel] L1 `panel-auth-check.test.ts` + `-cli.test.ts`: new `checkWebhookRejected` probe accepted on 401, rejected on 2xx/404/5xx; `evaluateAuthGate` fails when the probe fails; reason count updated
  - [ ] 11.2 `[I]` [panel] `panel/scripts/panel-auth-check.mjs`: add the probe to the parser and the gate
  - [ ] 11.3 `[I]` [scripts] `verify-panel-auth.sh`: CHECK 6 — unsigned `POST /api/webhooks/<probe-token>` must return 401. The probe needs a real enabled token, or the route returns 404; read it from an env var (`WEBHOOK_PROBE_TOKEN`), and fail the gate when it is unset
  - [ ] 11.4 `[I]` [docs] Runbook: create the probe endpoint and set `WEBHOOK_PROBE_TOKEN` for the gate
  - [ ] 11.5 Verify AC: gate fails non-zero on a non-401
  - [ ] 11.6 Run tests: `pnpm --filter panel run test:unit`; `shellcheck scripts/verify-panel-auth.sh`; `make validate`; `coverage_gate`
  - [ ] 11.7 `verifier` audit; open PR

## Wave E — `/webhooks` UI (DESIGN.md)

- [ ] 12.0 Implement Story S-176 (#321): /webhooks list + endpoint CRUD + secret show-once · branch `story/S-176-webhooks-list`
  - [ ] 12.1 [docs] DESIGN.md: add the `/webhooks` screen section (list + endpoint form) reusing the Schedules table/pill tokens; get a `ux-engineer` pass if a new pattern appears (D-W13)
  - [ ] 12.2 `[T]` [panel] L1 pure action cores (injectable, as in `schedules/actions.ts`): create generates a 32-byte token and secret, stores the secret in Vault, returns it once; rotate replaces it; edit validates the allowlist; delete cascades rules
  - [ ] 12.3 `[T]` [panel] L2 `panel/tests/component/webhooks-list.test.tsx`: list columns, enabled pill, copy-URL control, empty state, secret shown once then gone after dismiss/reload, keyboard-accessible controls
  - [ ] 12.4 `[T]` [panel] L2.5: actions persist and Vault round-trips; the secret never appears in any query result returned to the client
  - [ ] 12.5 `[I]` [panel] `app/(panel)/webhooks/page.tsx`, `actions.ts`, `components/webhooks/WebhooksTable.tsx`, `EndpointForm.tsx` (+ CSS modules); queries (D-W13)
  - [ ] 12.6 `[I]` [panel] Sidebar `Webhooks` nav item after Schedules + icon
  - [ ] 12.7 Manual/UI: `/webhooks` loads behind login; logged out → `/login`
  - [ ] 12.8 Verify AC: CRUD, secret show-once, nav
  - [ ] 12.9 Run tests: `pnpm --filter panel run test && pnpm --filter panel run test:integration`; `make validate`; `coverage_gate`
  - [ ] 12.10 `verifier` audit; open PR

- [ ] 13.0 Implement Story S-177 (#322): rule editor · branch `story/S-177-rule-editor`
  - [ ] 13.1 [docs] DESIGN.md: rule-editor row pattern (D-W13)
  - [ ] 13.2 `[T]` [panel] L1 rule-validation core: reuses the S-170 conditions schema; flags unknown op, missing value, payload-field repo mode without a path, a `from_payload` key not declared in the agent schema, static params failing the schema
  - [ ] 13.3 `[T]` [panel] L2 `panel/tests/component/rule-editor.test.tsx`: add/edit/delete; move up/down updates `position`; condition rows; agent switch rebinds the schema-driven params form; validation shown before save; default-rule toggle (only one default per endpoint)
  - [ ] 13.4 `[T]` [panel] L2.5: reorder persists without violating the `(endpoint_id, position)` unique (renumber in one transaction)
  - [ ] 13.5 `[I]` [panel] `components/webhooks/RuleEditor.tsx` (+ CSS), reusing the invoke/schedule params form; rule mutation actions; reorder via an RPC or deferred-unique constraint (D-W7, D-W13)
  - [ ] 13.6 Verify AC: ordered rules, validation before save, first-match order visible
  - [ ] 13.7 Run tests: `pnpm --filter panel run test && pnpm --filter panel run test:integration`; `make validate`; `coverage_gate`
  - [ ] 13.8 `verifier` audit; open PR

- [ ] 14.0 Implement Story S-178 (#323): delivery log · branch `story/S-178-delivery-log`
  - [ ] 14.1 [docs] DESIGN.md: delivery-row pattern reusing the Notifications feed tokens (D-W13)
  - [ ] 14.2 `[T]` [panel] L1 delivery-view shaper: outcome → label/pill/colour; reason chip; `fired` → run link
  - [ ] 14.3 `[T]` [panel] L2 `panel/tests/component/delivery-log.test.tsx`: every outcome renders; fired links to `/runs/<id>`; a `reason`/event value containing `<script>` or markup renders inert as text; empty state; pagination
  - [ ] 14.4 `[T]` [panel] L2.5: feed query newest-first per endpoint, paginated (keyset on `created_at, id`)
  - [ ] 14.5 `[I]` [panel] `components/webhooks/DeliveryLog.tsx` (+ CSS), shaper, query; mounted on the endpoint detail page (D-W11, D-W13)
  - [ ] 14.6 Verify AC: debuggable outcomes, text-only untrusted fields, bounded window (retention noted)
  - [ ] 14.7 Run tests: `pnpm --filter panel run test && pnpm --filter panel run test:integration`; `make validate`; `coverage_gate`
  - [ ] 14.8 `verifier` audit; open PR

- [ ] 15.0 Implement Story S-179 (#324): E2E · branch `story/S-179-webhooks-e2e`
  - [ ] 15.1 `[T]` [panel] `panel/tests/e2e/webhooks-crud.spec.ts`: create endpoint (capture secret once), add a rule, reorder, delete
  - [ ] 15.2 `[T]` [panel] `panel/tests/e2e/webhooks-delivery.spec.ts`: signed POST (signed in the test with the captured secret) → run in the delivery log and run history with `trigger_type=webhook` (AC1); unsigned → 401 + `unauthorized` row, no run (AC2); replay → no second run (AC2); bot-authored payload → no run (AC7); `/webhooks` logged out → `/login` (AC8)
  - [ ] 15.3 [panel] Reuse `fixtures/local-env.ts` and the AgentCore HTTP stub; state reset per spec
  - [ ] 15.4 [panel] Scenario → AC1–AC9 traceability table in the spec file headers
  - [ ] 15.5 Run tests: `pnpm --filter panel run test:e2e`; `make validate`
  - [ ] 15.6 `verifier` audit; open PR

## Integration & merge

- [ ] 16.0 Integrate Webhook Triggers Phase 1
  - [ ] 16.1 All story PRs merged bottom-up into `integration/webhook-triggers` (`--no-ff`)
  - [ ] 16.2 Pre-merge drift/stale-doc sweep: technical-guidelines current-state rows, `TESTING.md` rows, DESIGN.md confirmed, `product-context.md` §6 (webhooks no longer unbuilt), roadmap rows flipped to Done
  - [ ] 16.3 Full `make validate` + E2E suite on the integration branch; coverage rollup
  - [ ] 16.4 **Operator deploy (each step needs user go-ahead):** `supabase db push`; set `bot_login`; create the GitHub endpoint and its Vault secret; register the webhook in GitHub (URL + secret + events); create the probe endpoint + `WEBHOOK_PROBE_TOKEN`; redeploy the panel; run the release gate (now with the webhook 401 check)
  - [ ] 16.5 Live verification: a real GitHub event (a `pull_request_review_comment` with body `security review`) fires `security-analyst` on that repo; GitHub's delivery page shows 2xx; the panel delivery log shows `fired`; a non-matching event shows `no_match`; a redelivery shows `duplicate`
  - [ ] 16.6 Single reviewed PR `integration/webhook-triggers` → `main` (human merge only)

## Decisions Consumed

| ID | Decision (short form) |
| --- | --- |
| D-W1 | HMAC-SHA256-over-raw-body module, per-endpoint Vault secret, GitHub header default. |
| D-W2 | `/api/webhooks/[token]` public, signature-gated; release gate asserts unsigned → 401. |
| D-W3 | Raw body via the request stream, verify before parse; Node runtime, no cache. |
| D-W4 | Three tables mirroring scheduler conventions; deny-all RLS; secret in Vault only. |
| D-W5 | `TriggerDescriptor` `webhook` variant; `buildRunInsert` unchanged. |
| D-W6 | Shared `invokeResolvedRun()` core for schedule + webhook. |
| D-W7 | Pure bounded routing engine; JSON-path-lite + fixed ops; no regex/code. |
| D-W8 | Payload repo via `getRepositoryByFullName`, allowlist-only, never auto-create. |
| D-W9 | Static params + declared-key interpolation, schema-validated. |
| D-W10 | G1/G4/G5 in the shared core; G3 per rule; G2 n/a. |
| D-W11 | Always-on delivery recording; fast ack; async invoke. |
| D-W12 | Bot-author guard (`<app_slug>[bot]` + type `Bot`) with endpoint toggle default on. |
| D-W13 | `/webhooks` UI reuses schema form, table/pill/feed patterns; sidebar item. |
| D-W14 | Daily prune cron, 30-day default horizon, batched, run FK set-null. |
| D-W15 | Header names configurable; signature fixed to HMAC-SHA256 `sha256=<hex>`; body-hash dedup fallback. |
| D-W16 | Every delivery recorded for tracking; only verified deliveries claim the dedup key. |

## Verifier Design-Mode recommendation

Before implementation, run `verifier` in **Design Mode** against this task list and the spec to produce
the compliance test plan. Weight it toward the hostile-input surface: signature verification and the
size cap (S-168/S-169, AC2/AC3/AC9), the routing engine's adversarial payloads and the bot guard
(S-170, AC4/AC7), allowlist and param-injection rejection (S-171, AC5), and the no-behavior-change
refactor of the live fire route (S-172).
