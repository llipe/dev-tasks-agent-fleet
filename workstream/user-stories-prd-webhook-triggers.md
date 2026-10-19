# User Stories — Webhook Triggers

## Changelog

| Version | Date       | Summary                                                        | Author           |
| ------- | ---------- | -------------------------------------------------------------- | ---------------- |
| 1.0     | 2026-10-15 | Initial stories for Phase 1 (webhook mechanism) from spec v1.1 / PRD v0.1. S-165–S-179 across waves A–E. | product-engineer |

Source: `docs/requirements/prd-webhook-triggers.md` (v0.1), `workstream/specification-prd-webhook-triggers.md` (v1.1), `workstream/decisions-webhook-triggers.md` (D-W1…D-W15).

---

## Legend

- **ID range:** S-165–S-179 (next free after the scheduler's S-149–S-164).
- **Size:** XS (<½ day), S (½–1 day), M (1–2 days), L (2–3 days). Each story fits one PR.
- **Discipline:** test-first; per-story DoD = `make validate` + L2.5 live where a DB/route is touched; PR per story, stacked, merged bottom-up into `integration/webhook-triggers` with `--no-ff`; only the user merges `integration → main`.
- **Waves map 1:1 to spec §15:** A schema+prune, B verify+route+record, C routing+resolution+invoke-core, D notify-generalization, E UI+gate.

---

## Wave A — Schema foundation + retention (inert until wired)

### S-165 — `webhook_endpoints` / `webhook_rules` / `webhook_deliveries` schema, enums, RLS

**Priority:** Critical **Estimated Size:** M **Dependencies:** none

#### User Story
As the operator, I want the webhook data model in place so endpoints, routing rules, and delivery records have a durable, access-controlled home.

#### Context
Schema-only, mirroring the scheduler's S-149 (enums, `set_updated_at`, deny-all RLS). Inert — no routes, no functions that fire anything.

#### Acceptance Criteria
- [ ] Enums `webhook_source('github','generic')` and `webhook_outcome('received','unauthorized','duplicate','ignored','no_match','route_rejected','skipped','fired')` created.
- [ ] `webhook_endpoints` (url_token unique+indexed, source, signature_header, delivery_id_header, event_allowlist, ignore_bot_author default true, is_enabled, timestamps) created.
- [ ] `webhook_rules` (endpoint_id FK, position, event_types, conditions jsonb, is_default, agent_id FK, repo_mode, repository_id FK nullable, repo_payload_field nullable, params jsonb, consecutive_failures, auto_disable_threshold default 3, is_enabled, timestamps) with `(endpoint_id, position)` unique and the repo_mode CHECK.
- [ ] `webhook_deliveries` (endpoint_id FK, delivery_id, event_type, outcome, matched_rule_id FK nullable, run_id FK `on delete set null`, reason, received_at, timestamps) with `(endpoint_id, delivery_id)` unique and `(endpoint_id, created_at desc)` index.
- [ ] All three tables `enable row level security` with no permissive policy (deny-all), picked up by the enumerated `rls-deny-all` test.
- [ ] `set_updated_at` triggers on endpoints + rules.

#### Technical Notes
Mirror `supabase/migrations/20261013160000_scheduler_schema.sql` conventions (D-W4). FK cascade to `agents`/`repositories`; `run_id` set-null so prune (S-167) never touches `runs`.

#### Testing Requirements
- **Integration (L2.5):** schema applies on `db reset`; deny-all RLS from anon; unique constraints reject dup `position` and dup `(endpoint_id, delivery_id)`; repo_mode CHECK rejects the invalid combos.
- **AC mapping:** each AC → an L2.5 case.
- **Commands:** `supabase db reset` + `pnpm --filter panel test:integration`.

#### Migration Requirements
- Migration artifact: required (new timestamped SQL). Rollback: additive, drop-tables revert. Apply: user-confirmed. Verify: `\d webhook_*` + rls test.

#### Files to Create/Modify
- `supabase/migrations/<ts>_webhook_schema.sql`
- `panel/tests/integration/webhook-schema.test.ts`

#### Definition of Done Checklist
- [ ] Migration written + applied (confirmed) · [ ] L2.5 green · [ ] `make validate` · [ ] AC→evidence mapped · [ ] PR merged into integration branch.

### S-166 — Per-endpoint Vault signing secret + `webhook` helper schema + `webhook.config`

**Priority:** Critical **Estimated Size:** S **Dependencies:** S-165

#### User Story
As the operator, I want each endpoint's signing secret stored in Vault (never a plaintext column) and a config home for webhook settings, mirroring the scheduler's secret posture.

#### Acceptance Criteria
- [ ] `webhook` schema created; generalized `set_secret`/`read_secret` wrappers (or reuse of the scheduler ones) read/write Vault under a derived name `webhook_endpoint_<id>`.
- [ ] `webhook.config` key/value table seeded with `delivery_retention_days=30` and `bot_login` (the GitHub App bot identity), with typed getters.
- [ ] No endpoint signing secret ever lives in a table column or a log line.

#### Technical Notes
Mirror `20261013161000_scheduler_pgnet_vault.sql` (D-W4/D-W15). Local-dev bootstrap value, prod set by operator via runbook.

#### Testing Requirements
- **Integration (L2.5):** set then read a secret round-trips; a missing secret reads null; config getters return seeded defaults.
- **Commands:** `pnpm --filter panel test:integration`.

#### Migration Requirements
- Migration artifact: required. Rollback: drop schema/config. Apply: user-confirmed. Verify: round-trip query.

#### Files
- `supabase/migrations/<ts>_webhook_vault_config.sql` · `panel/tests/integration/webhook-vault.test.ts`

#### DoD
- [ ] Migration applied · [ ] L2.5 green · [ ] no secret in column/log · [ ] `make validate` · [ ] PR merged.

### S-167 — `webhook.prune_deliveries()` + daily `pg_cron` retention job (OQ-2)

**Priority:** High **Estimated Size:** S **Dependencies:** S-165, S-166

#### User Story
As the operator, I want old delivery rows pruned automatically so `webhook_deliveries` doesn't grow unbounded.

#### Acceptance Criteria
- [ ] `webhook.prune_deliveries()` (`security definer`, pinned search_path) deletes rows older than `webhook.config.delivery_retention_days` (default 30), in capped batches.
- [ ] A daily `pg_cron` job registered via the proven do-block-unschedule + top-level-select style (as the scheduler crons).
- [ ] Pruning a `fired` delivery leaves its `runs` row intact (`run_id` set-null, not cascade).

#### Technical Notes
D-W14. Reuse the scheduler cron registration pattern (`20261013163000_scheduler_fire_due.sql`).

#### Testing Requirements
- **Integration (L2.5):** insert aged rows → prune deletes only those past the horizon; a fired delivery's run survives; batch cap respected.
- **Commands:** `pnpm --filter panel test:integration`.

#### Migration Requirements
- Migration artifact: required. Rollback: unschedule job + drop function. Apply: user-confirmed. Verify: `cron.job` row + a manual `select webhook.prune_deliveries()`.

#### Files
- `supabase/migrations/<ts>_webhook_prune.sql` · `panel/tests/integration/webhook-prune.test.ts`

#### DoD
- [ ] Migration applied · [ ] L2.5 green · [ ] `make validate` · [ ] PR merged.

---

## Wave B — Inbound endpoint: verification + delivery recording

### S-168 — `verifyHmacSignature` module (HMAC-SHA256, constant-time, fail-closed)

**Priority:** Critical **Estimated Size:** S **Dependencies:** none (pure)

#### User Story
As the system, I want to verify an inbound signature over the exact raw body so hostile/forged requests are rejected before any work.

#### Acceptance Criteria
- [ ] Pure `verifyHmacSignature(rawBody, presentedHeaderValue, secret)` recomputes `"sha256=" + hex(HMAC_SHA256(secret, rawBody))` and compares constant-time (`timingSafeEqual`, length-guarded).
- [ ] Format guard: presented value must start with `sha256=` and be valid lowercase hex of the expected length; else reject.
- [ ] Fail-closed on empty secret / missing header / mismatch / wrong length; never throws; never logs secret material.
- [ ] A body-hash dedup-key helper `deliveryDedupKey(headers, rawBody, deliveryHeaderName)` returns the header value or a SHA-256 of the body when absent.

#### Technical Notes
Model on `panel/lib/auth/internal-secret.ts`; this is a keyed hash of the body, not an equality check (D-W1/D-W15, spec §7/§9.1).

#### Testing Requirements
- **Unit (L1):** valid; wrong secret; tampered body; missing/empty header; wrong-length hex; non-`sha256=` prefix; empty secret → deny. Dedup key with and without the delivery header.
- **Security-negative category:** forged signature, truncated digest.
- **Commands:** `pnpm --filter panel test:unit`.

#### Files
- `panel/lib/auth/webhook-signature.ts` · `panel/tests/unit/webhook-signature.test.ts`

#### DoD
- [ ] L1 green incl. security-negative · [ ] `make validate` · [ ] PR merged.

### S-169 — `POST /api/webhooks/[token]` route: verify → size cap → dedup → record (no routing yet)

**Priority:** Critical **Estimated Size:** M **Dependencies:** S-165, S-166, S-168

#### User Story
As a GitHub webhook, I want my signed delivery verified, size-checked, deduped, and recorded, with a fast 2xx, before any routing exists.

#### Acceptance Criteria
- [ ] Route is **public** (route policy classifies `/api/webhooks/**` like `/api/internal/**` — through the middleware without the session gate); Node runtime, `force-dynamic`, no cache.
- [ ] Reads raw body via `request.text()`; body over the size cap → `413` (before full processing); unknown/disabled token → `404` (no record).
- [ ] Invalid/missing signature → record `unauthorized`, `401`.
- [ ] Duplicate `(endpoint_id, delivery_id)` (or body-hash key) → record/return `duplicate` `200` no-op.
- [ ] A valid, new, allowlisted-or-not delivery is recorded `received` (routing lands in S-171); non-allowlisted event → `ignored` `202`.
- [ ] Structured, secret-free log line (`at: "webhook_delivery"`).

#### Technical Notes
Mirror the fire route's structure/`logFire` (spec §6.1 steps 1–5, D-W2/D-W3/D-W11). Route-policy change parallels how `/api/internal/**` is classified.

#### Testing Requirements
- **Integration (L2.5):** signed→recorded received/ignored; unsigned→401 recorded unauthorized; oversized→413; replay→200 no-op (one delivery row).
- **Component (L2):** route-policy classifies `/api/webhooks/**` public.
- **Security-negative:** forged sig, oversized, unknown token.
- **Commands:** `pnpm --filter panel test:integration` + `:unit`.

#### Files
- `panel/app/api/webhooks/[token]/route.ts` · `panel/lib/auth/route-policy.ts` (extend) · `panel/lib/supabase/queries.ts` (endpoint-by-token, insert/dedup delivery) · tests alongside.

#### DoD
- [ ] L2.5 + L2 green · [ ] `make validate` · [ ] PR merged.

---

## Wave C — Routing engine + resolution + shared invoke core

### S-170 — Pure routing engine `webhook-routing.ts` (safe condition language + bot guard)

**Priority:** Critical **Estimated Size:** M **Dependencies:** none (pure)

#### User Story
As the operator, I want a deterministic, safe matcher so an event resolves to exactly one rule (or none) with no code-execution risk.

#### Acceptance Criteria
- [ ] `selectField(payload, path)` — dotted keys + `[n]` index, max depth N, returns undefined on miss, never throws on hostile shapes.
- [ ] `evaluateCondition` ops: `equals, not_equals, contains, prefix, suffix, in, exists, matches_event`; string operands length-capped; no regex/code.
- [ ] `routeDelivery(payload, eventType, endpoint, rules)` applies the bot-author guard first (D-W12), then first-match-wins by `position`, returns match / default / `no_match`.
- [ ] Pure over inputs; exhaustively unit-testable.

#### Technical Notes
D-W7/D-W12, spec §8.1. Same testability posture as `checkSchedulerSecret`.

#### Testing Requirements
- **Unit (L1):** every op; depth/length limits; first-match ordering; default fallthrough; bot-author exclusion; adversarial payloads (deep nesting, huge strings, arrays, nulls, prototype-pollution keys).
- **Random/property:** fuzz `selectField` with generated payloads (reproducible seed).
- **Commands:** `pnpm --filter panel test:unit`.

#### Files
- `panel/lib/domain/webhook-routing.ts` · `panel/tests/unit/webhook-routing.test.ts`

#### DoD
- [ ] L1 green incl. adversarial + property · [ ] `make validate` · [ ] PR merged.

### S-171 — Route resolution: agent + repo-allowlist + params interpolation/validation

**Priority:** Critical **Estimated Size:** M **Dependencies:** S-170, S-169

#### User Story
As the operator, I want a matched rule turned into a concrete, validated `(agent, repository, params)` or a recorded rejection — never an unsafe invoke.

#### Acceptance Criteria
- [ ] Agent resolved + must be enabled.
- [ ] Repo: `fixed` → `repository_id`; `payload_field` → `selectField` + new `getRepositoryByFullName` (enabled, non-archived); miss → `route_rejected` `202` (never auto-create).
- [ ] Params: static merged with declared payload-interpolation keys, then `validateParams` vs `params_schema`; invalid → `route_rejected`.
- [ ] Interpolation into an **undeclared** key is ignored/rejected (not silently injected).
- [ ] The route handler now runs allowlist + bot guard + rules + resolution end-to-end, recording the outcome.

#### Technical Notes
D-W8/D-W9, spec §8.2 (OQ-1 kept). Reuse `validateParams` from `panel/lib/schema/validate.ts`.

#### Testing Requirements
- **Integration (L2.5):** payload-repo in allowlist resolves; outside allowlist → route_rejected; invalid params → route_rejected; declared-key interpolation fills params; undeclared key rejected.
- **Security-negative:** payload names a repo outside the allowlist; interpolation of an undeclared key.
- **Commands:** `pnpm --filter panel test:integration`.

#### Files
- `panel/lib/domain/webhook-resolve.ts` · `panel/lib/supabase/queries.ts` (getRepositoryByFullName) · route handler wiring · tests.

#### DoD
- [ ] L2.5 green incl. security-negative · [ ] `make validate` · [ ] PR merged.

### S-172 — Factor the fire route into shared `invokeResolvedRun()` + `webhook` TriggerDescriptor

**Priority:** Critical **Estimated Size:** M **Dependencies:** S-171

#### User Story
As a maintainer, I want one invoke code path shared by the schedule tick and the webhook handler, so a webhook-fired run is machinery-identical to a scheduled one.

#### Acceptance Criteria
- [ ] `invokeResolvedRun({agent, repositoryId, installationId, repositoryFullName, params, trigger})` performs build payload → `buildRunInsert` → `insertQueuedRun` → `invokeAgentRuntime` → on throw `markRunFailedToStart`.
- [ ] `TriggerDescriptor` gains `{ triggerType: "webhook"; triggeredBy: `webhook:${string}` }` (`<endpoint_id>:<rule_id>`); `buildRunInsert` unchanged.
- [ ] The existing fire route is refactored to call the core with **byte-for-byte identical behavior** (existing scheduler L2.5 tests stay green).
- [ ] The webhook handler calls the core → produces a `runs` row with `trigger_type='webhook'`, records delivery `fired` + `run_id`, returns `202 {run_id}`.

#### Technical Notes
D-W5/D-W6, spec §8.3. Refactor-then-reuse; do NOT change the fire route's semantics.

#### Testing Requirements
- **Unit (L1):** TriggerDescriptor webhook variant through `buildRunInsert`.
- **Integration (L2.5):** webhook fire → trigger_type=webhook run linked to the rule; the pre-existing schedule-fire L2.5 suite still passes against the refactor.
- **Commands:** `pnpm --filter panel test:unit` + `:integration`.

#### Files
- `panel/lib/domain/invoke-resolved-run.ts` · `panel/lib/domain/run-insert.ts` (type) · `panel/app/api/internal/schedules/[id]/fire/route.ts` (refactor) · webhook route wiring · tests.

#### DoD
- [ ] L1+L2.5 green incl. unchanged fire-route suite · [ ] `make validate` · [ ] PR merged.

### S-173 — Guardrails on the shared core (G1/G4/G5) + G3 per-rule circuit breaker

**Priority:** High **Estimated Size:** M **Dependencies:** S-172

#### User Story
As the operator, I want webhook-fired runs subject to the same safety rails as scheduled runs, with runaway rules auto-disabled.

#### Acceptance Criteria
- [ ] G1 overlap, G4 concurrency cap, G5 open-PR backoff execute inside `invokeResolvedRun()` for both triggers; a guardrail skip records delivery `skipped` + reason.
- [ ] G3 circuit breaker keyed **per rule**: `webhook_rules.consecutive_failures` increments on fire-time failure, resets on success; crossing `auto_disable_threshold` disables the rule and records a notification.
- [ ] G2 catch-up is documented n/a for webhooks.

#### Technical Notes
D-W10, spec §8.4 (OQ-4 per-rule). Reuse the G1/G4/G5 functions; add rule-scoped G3 counters mirroring `schedules`.

#### Testing Requirements
- **Integration (L2.5):** overlap/cap/open-PR skip recorded on the delivery; N consecutive failures auto-disable the rule + emit notification; success resets.
- **Commands:** `pnpm --filter panel test:integration`.

#### Migration Requirements
- Migration artifact: required if G3 counters need columns (added in S-165 if feasible; else here). Rollback/verify noted.

#### Files
- shared core guardrail wiring · `supabase/migrations/<ts>_webhook_g3.sql` (if needed) · tests.

#### DoD
- [ ] L2.5 green · [ ] `make validate` · [ ] PR merged.

---

## Wave D — Notifications generalization

### S-174 — Generalize notify-sweep from "scheduled run" to "automated run" (+ issue #302)

**Priority:** High **Estimated Size:** M **Dependencies:** S-172

#### User Story
As the operator, I want webhook-fired runs to emit `run_failed` / `pr_opened` / `run_succeeded` notifications through the same sweep as scheduled runs.

#### Acceptance Criteria
- [ ] The notify-sweep resolves the originating trigger from `triggered_by` for both `schedule:*` and `webhook:*` runs and records the same notification kinds.
- [ ] A webhook run's terminal failure → `run_failed`; a produced PR → `pr_opened`; opt-in success → `run_succeeded`; all in `notifications`, feed, and daily digest.
- [ ] Open issue **#302** (join vs left-join for runs whose schedule/rule was deleted) resolved consistently as part of this generalization.

#### Technical Notes
D-W11, spec §9.2/§16. Touches `20261013167000_scheduler_notify_sweep.sql`.

#### Testing Requirements
- **Integration (L2.5):** webhook run_failed/pr_opened/run_succeeded recorded; idempotent per `(run_id, kind)`; a run whose rule was deleted still records per the #302 decision.
- **Commands:** `pnpm --filter panel test:integration`.

#### Migration Requirements
- Migration artifact: required (sweep function update). Rollback/verify noted.

#### Files
- `supabase/migrations/<ts>_webhook_notify_generalize.sql` · `panel/tests/integration/notify-sweep.test.ts` (extend) · note on #302.

#### DoD
- [ ] L2.5 green · [ ] #302 decision recorded · [ ] `make validate` · [ ] PR merged.

### S-175 — Release-gate assertion: `/api/webhooks/<token>` rejects unsigned (401)

**Priority:** High **Estimated Size:** S **Dependencies:** S-169

#### User Story
As the operator, I want the deploy gate to mechanically prove the webhook endpoint is signature-gated, like the internal-endpoint check.

#### Acceptance Criteria
- [ ] `scripts/verify-panel-auth.sh` gains a CHECK that an unsigned `POST /api/webhooks/<probe-token>` returns `401` (fails the release non-zero otherwise).
- [ ] The pure parser (`panel-auth-check.mjs`) + its tests extended for the new probe, mirroring the S-160 internal probe.

#### Technical Notes
FR24/AC8, spec §7. Mirror S-160.

#### Testing Requirements
- **Unit (L1):** parser accepts/rejects the webhook probe like the internal probe. **Shell:** `shellcheck`.
- **Commands:** `pnpm --filter panel test:unit`.

#### Files
- `scripts/verify-panel-auth.sh` · `panel/scripts/panel-auth-check.mjs` · `panel/tests/unit/panel-auth-check*.test.ts`.

#### DoD
- [ ] L1 green · [ ] shellcheck clean · [ ] `make validate` · [ ] PR merged.

---

## Wave E — `/webhooks` management UI (pinned to DESIGN.md)

### S-176 — `/webhooks` list + endpoint CRUD + secret lifecycle (show-once)

**Priority:** High **Estimated Size:** L **Dependencies:** S-166, S-169

#### User Story
As the operator, I want to create, view, edit, enable/disable, and delete webhook endpoints, and generate/rotate the signing secret (shown once).

#### Acceptance Criteria
- [ ] `/webhooks` list: source, enabled pill, event allowlist, rule count, URL (copyable).
- [ ] Create/edit/delete endpoint via Server Actions (service-role, server-only); event allowlist multi-select; `ignore_bot_author` toggle.
- [ ] Generate/rotate secret → shown once, stored in Vault, never re-displayed.
- [ ] New sidebar nav item after Schedules.

#### Technical Notes
D-W13, spec §10. Reuse Schedules list/table + pill patterns; pure injectable action cores (as the schedules actions).

#### Testing Requirements
- **Component (L2):** list render; create/edit/delete flows; secret show-once; empty state.
- **Integration (L2.5):** actions persist + Vault round-trip.
- **Manual/UI:** `/webhooks` reachable behind login; `/webhooks` unauthenticated → `/login`.
- **Commands:** `pnpm --filter panel test` + `test:integration`.

#### Files
- `panel/app/(panel)/webhooks/page.tsx`, `actions.ts` · `panel/components/webhooks/*` + CSS modules · `panel/components/shell/Sidebar.tsx` · `panel/lib/supabase/queries.ts` · tests.

#### DESIGN.md impact
- Add a `/webhooks` screen section; reuse table/pill tokens (no new primitives expected).

#### DoD
- [ ] L2+L2.5 green · [ ] DESIGN.md updated · [ ] `make validate` · [ ] PR merged.

### S-177 — Rule editor (ordered rules, condition rows, agent/repo-mode/params form)

**Priority:** High **Estimated Size:** L **Dependencies:** S-170, S-171, S-176

#### User Story
As the operator, I want to add, reorder, edit, and delete the ordered routing rules with validation before save.

#### Acceptance Criteria
- [ ] Add/reorder (position)/edit/delete rules; event-type select; structured condition rows (`field`/`op`/`value`); agent select; repo mode (fixed select vs payload field); schema-driven params form (reused from invoke/schedule); default-rule toggle.
- [ ] A rule whose resolution can't validate (bad params, unknown repo field) is flagged before save.
- [ ] Reordering persists `position`; first-match semantics visible to the operator.

#### Technical Notes
D-W7/D-W13, spec §10. Reuse the schema-driven params form component.

#### Testing Requirements
- **Component (L2):** add/reorder/edit/delete; condition-row editing; validation-before-save flagging; params form schema binding.
- **Integration (L2.5):** rules persist with correct ordering.
- **Commands:** `pnpm --filter panel test` + `test:integration`.

#### Files
- `panel/components/webhooks/RuleEditor.tsx` (+ CSS) · `actions.ts` (rule mutations) · tests.

#### DESIGN.md impact
- Rule-editor row pattern; reuse form tokens.

#### DoD
- [ ] L2+L2.5 green · [ ] DESIGN.md updated · [ ] `make validate` · [ ] PR merged.

### S-178 — Delivery log (per-endpoint feed, text-only untrusted fields, run links)

**Priority:** High **Estimated Size:** M **Dependencies:** S-169, S-176

#### User Story
As the operator, when a run didn't happen I want to open the delivery log and see exactly why.

#### Acceptance Criteria
- [ ] Per-endpoint newest-first feed: timestamp, event type, delivery id, verification result, matched rule / no-match, outcome (fired→run-detail link / skipped+reason / rejected+reason / ignored).
- [ ] Untrusted payload-derived fields render as **text only** (no HTML), like `notifications.detail`.
- [ ] Pagination or a bounded recent window (ties to retention S-167).

#### Technical Notes
D-W11/D-W13, spec §10/§13. Reuse the Notifications-feed presentation.

#### Testing Requirements
- **Component (L2):** feed render across all outcomes; fired links to run detail; text-only rendering of a payload field containing markup; empty state.
- **Integration (L2.5):** feed query returns deliveries newest-first for an endpoint.
- **Security-negative:** a delivery `reason`/field containing `<script>`-like content renders inert.
- **Commands:** `pnpm --filter panel test` + `test:integration`.

#### Files
- `panel/components/webhooks/DeliveryLog.tsx` (+ CSS) · delivery-view shaper + query · tests.

#### DESIGN.md impact
- Delivery-row pattern; reuse feed tokens.

#### DoD
- [ ] L2+L2.5 green incl. inert-render · [ ] DESIGN.md updated · [ ] `make validate` · [ ] PR merged.

### S-179 — E2E: signed-delivery→run, unsigned→401, replay→no-op, `/webhooks` CRUD

**Priority:** High **Estimated Size:** M **Dependencies:** S-176, S-177, S-178

#### User Story
As a maintainer, I want black-box proof of the whole chain end-to-end.

#### Acceptance Criteria
- [ ] Playwright: operator creates an endpoint + a rule; a signed POST produces a run visible in the delivery log (linked) and in run history with `trigger_type=webhook`.
- [ ] Unsigned POST → 401, recorded `unauthorized`, no run.
- [ ] Replayed delivery id → no second run.
- [ ] `/webhooks` unauthenticated → `/login`.
- [ ] Scenario→spec traceability table (AC1–AC9) in the spec file header.

#### Technical Notes
Reuse the scheduler E2E harness (`panel/tests/e2e/fixtures/local-env.ts`); export the `NEXT_PUBLIC_*` trio before Playwright (known harness requirement).

#### Testing Requirements
- **E2E:** the four scenarios above + state reset.
- **Commands:** `pnpm --filter panel test:e2e`.

#### Files
- `panel/tests/e2e/webhooks-crud.spec.ts` · `panel/tests/e2e/webhooks-delivery.spec.ts`.

#### DoD
- [ ] E2E green locally · [ ] traceability recorded · [ ] `make validate` · [ ] PR merged.

---

## Coverage Validation

### Summary
- **Total PRD FRs:** 24 (FR1–FR24) + 9 ACs + 6 design decisions (A–F baked as FRs).
- **Total User Stories:** 15 (S-165–S-179).
- **Coverage:** 100% of in-scope FRs/ACs.
- **Status:** Complete.

### FR → Story
| FR | Story | FR | Story |
| --- | --- | --- | --- |
| FR1 unguessable URL | S-165, S-169 | FR13 repo allowlist | S-171 |
| FR2 signature verify | S-168, S-169 | FR14 params validation | S-171 |
| FR3 replay dedup | S-168, S-169 | FR15 default/no-match | S-170, S-171 |
| FR4 size+timeout caps | S-169 | FR16 trigger descriptor | S-172 |
| FR5 event allowlist | S-169 | FR17 guardrails | S-173 |
| FR6 raw-body integrity | S-168, S-169 | FR18 notifications | S-174 |
| FR7 fast ack | S-169 | FR19 self-trigger guard | S-170 |
| FR8 no secret logged | S-166, S-168, S-169 | FR20 `/webhooks` screen | S-176 |
| FR9 ordered first-match | S-170 | FR21 endpoint CRUD + secret | S-176 |
| FR10 condition language | S-170 | FR22 rule editor | S-177 |
| FR11 event-type match | S-170 | FR23 delivery log | S-178 |
| FR12 route resolution | S-171 | FR24 boundary + gate | S-169, S-175 |

### AC → Story
| AC | Story | AC | Story |
| --- | --- | --- | --- |
| AC1 signed→run | S-172, S-179 | AC6 guardrail skip + run_failed | S-173, S-174 |
| AC2 bad-sig 401 / replay no-op | S-168, S-169, S-179 | AC7 bot-author excluded | S-170, S-179 |
| AC3 oversized/non-allowlisted | S-169, S-179 | AC8 UI + boundary + gate | S-175, S-176, S-178, S-179 |
| AC4 first-match + payload repo + no_match | S-170, S-171 | AC9 no secret in log/record | S-166, S-168, S-178 |
| AC5 repo/params rejected | S-171 | | |

### OQ resolutions → Story
| Resolution | Story |
| --- | --- |
| OQ-1 declared-key interpolation (keep) | S-171 |
| OQ-2 prune in v1 | S-167 |
| OQ-3 signature scheme defined | S-168 |
| OQ-4 G3 per-rule | S-173 |

### Dependency order (for `plan`)
```
S-165 → S-166 → S-167            (Wave A)
S-168 → S-169                    (Wave B; S-169 needs S-165/166/168)
S-170 → S-171 → S-172 → S-173    (Wave C; S-171 needs S-169)
S-174, S-175                     (Wave D; need S-172 / S-169)
S-176 → S-177, S-178 → S-179     (Wave E; need Wave B/C)
```
Waves land in order; stories within a wave stack bottom-up and merge into `integration/webhook-triggers` with `--no-ff`.

### Non-Goals Validation (confirmed NOT in any story)
- [ ] The two new agents (code-review, repo-research) — Phases 2–3.
- [ ] Visual drag-and-drop rule builder (S-177 is a structured form, not a canvas).
- [ ] Non-HMAC auth schemes; base64/bare-hex/SHA1 (deferred fast-follow, S-168 fixes the shape).
- [ ] Auto-registering repositories (S-171 rejects, never creates).
- [ ] Turing-complete condition language (S-170 is bounded).
- [ ] Outbound GitHub posting / new App scopes (Phases 2–3).
- [ ] Fan-out (first-match-wins only, S-170).
- [ ] Panel redelivery/replay of a past delivery.

### DESIGN.md impact (UI stories)
S-176/S-177/S-178 add a `/webhooks` screen, rule-editor row, and delivery-row patterns; all reuse existing table/pill/feed/form tokens — no new primitives expected.

### Test-first note
Every story is written tests-first; L2.5 live verification is required on each DB/route-touching story, matching the scheduler DoD.
