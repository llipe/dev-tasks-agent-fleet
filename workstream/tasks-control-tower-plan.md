# Implementation Plan - Control Tower, Wave A (Ingest)

## Changelog

| Version | Date       | Summary                                                                 | Author           |
| ------- | ---------- | ----------------------------------------------------------------------- | ---------------- |
| 1.0     | 2026-11-26 | Initial plan for Wave A: stories S-219–S-228, issues #487–#496. Wave B is planned separately. | product-engineer |
| 1.1     | 2026-11-26 | Story IDs renumbered to S-219–S-228 (collision with code-review S-216–S-218 on `main`). Task numbers and content unchanged. | product-engineer |

Source: `workstream/user-stories-control-tower.md` v1.1, `workstream/specification-control-tower.md` v1.1, `docs/requirements/prd-control-tower.md` v1.4.

- **Scope:** Wave A only, selected by the owner. Existing codebase, so there is no Task 0.
- **Order:** tasks run in the order listed; it follows the dependency graph in the stories document. Task 2.0 (S-221) has no dependency and may run first or in parallel.
- **Integration branch:** `integration/control-tower-wave-a`. One PR per story into it; the owner merges the consolidated PR to `main`.
- **Test-first:** in every task, the tests named by a step are written before that step's implementation.
- **Package tags:** the technical guidelines carry no package map, so the bracket names the top-level directory a sub-task changes (`panel`, `supabase`) or `repo root` for documents and scripts.
- **Seed data:** none. The fixtures of task 2.0 serve as sample data for every later task.
- **Infrastructure:** task 10.0 is an `infra-engineer` pass, approval-gated per step. `developer` does not run it.

## Relevant Files

- `supabase/migrations/<ts>_tower_schema.sql`, `<ts>_tower_config.sql`
- `panel/lib/supabase/types.ts`
- `panel/tests/integration/tower-schema.test.ts`
- `panel/lib/tower/names.ts`, `panel/lib/tower/contract.ts`
- `panel/tests/fixtures/tower/*.json`
- `panel/tests/unit/tower-contract.test.ts`
- `docs/reference/tower-ingestion-contract.md`
- `panel/lib/tower/token.ts`, `panel/lib/tower/queries.ts`
- `panel/lib/domain/tower-repository-save.ts`
- `panel/app/(panel)/tower/actions.ts`
- `panel/tests/unit/tower-token.test.ts`, `panel/tests/integration/tower-repository.test.ts`
- `supabase/migrations/<ts>_tower_apply_push.sql`
- `panel/lib/tower/queries.ts` (the RPC call)
- `panel/tests/integration/tower-apply-push.test.ts`
- `panel/lib/tower/ingest.ts`, `panel/app/api/tower/ingest/route.ts`
- `panel/lib/auth/route-policy.ts`
- `panel/tests/unit/tower-ingest.test.ts`, `panel/tests/unit/route-policy.test.ts`, `panel/tests/integration/tower-ingest.test.ts`
- `supabase/migrations/<ts>_tower_prune.sql`
- `panel/tests/integration/tower-prune.test.ts`
- `panel/lib/tower/read.ts`, `panel/lib/tower/queries.ts`
- `panel/app/api/tower/repositories/route.ts`, `panel/app/api/tower/repositories/[owner]/[name]/route.ts`
- `panel/tests/fixtures/tower/read-*.json`, `panel/tests/unit/tower-read.test.ts`, `panel/tests/integration/tower-read.test.ts`
- `docs/reference/tower-read-contract.md`
- `panel/app/(panel)/tower/page.tsx`, `page.module.css`
- `panel/components/tower/RepositoryList.tsx`, `RegisterRepositoryDialog.tsx`, `RepositorySettings.tsx`
- `panel/components/shell/Sidebar.tsx`
- `panel/tests/e2e/tower-repositories.spec.ts`
- `scripts/verify-panel-auth.sh`, `panel/scripts/panel-auth-check.mjs`
- `panel/tests/unit/panel-auth-check.test.ts`
- `docs/runbooks/control-tower.md`, `docs/runbooks/README.md`
- `infra/changes/<date>-control-tower-wave-a/`
- `docs/technical-guidelines.md`, `docs/roadmap.md`, `docs/product-context.md`

## Tasks

- [ ] 1.0 Implement Story S-219: Tower schema: `tower_*` tables, `tower.config`, deny-all RLS — [#487](https://github.com/llipe/dev-tasks-agent-fleet/issues/487)

  > Note: As the owner, I want the Control Tower's data model in place, so that repositories, tokens, pushes, PRDs, waves, issues and raw tower events have a durable, access-controlled home.

  - [ ] 1.1 [supabase, panel] Write the integration tests for constraints and deny-all (D-19, D-22, D-29, D-31)
  - [ ] 1.2 [supabase, panel] Write the schema migration and the `tower.config` migration
  - [ ] 1.3 [supabase, panel] Regenerate `panel/lib/supabase/types.ts`
  - [ ] 1.4 [supabase, panel] Migration: record rollback and impact notes in the PR (additive; rollback is dropping the new objects. No existing data touched)
  - [ ] 1.5 [supabase, panel] Migration: apply locally with `supabase db reset` and verify (integration suite green on a fresh reset). The live apply is task 10.0, after explicit owner confirmation
  - [ ] 1.6 [supabase, panel] Verify Acceptance Criterion: `tower_repositories`, `tower_tokens`, `tower_change_markers`, `tower_pushes`, `tower_prds`, `tower_waves`, `tower_issues`, `tower_events` exist with the columns, keys and indexes of spec §5.1.
  - [ ] 1.7 [supabase, panel] Verify Acceptance Criterion: `tower_repositories.full_name` is unique and rejects a value that is not lowercase `owner/name`.
  - [ ] 1.8 [supabase, panel] Verify Acceptance Criterion: A second active token for one repository is rejected by the partial unique index; a revoked one plus an active one is allowed.
  - [ ] 1.9 [supabase, panel] Verify Acceptance Criterion: `steps` and `stages` reject a key outside the eight names and a `result` outside the five values; a missing key is allowed.
  - [ ] 1.10 [supabase, panel] Verify Acceptance Criterion: `tower.config` exists with `stale_threshold_hours=24`, `event_retention_days=90`, `push_retention_days=30`, `default_window_days=14`.
  - [ ] 1.11 [supabase, panel] Verify Acceptance Criterion: Every new public table has RLS enabled with no policy and is picked up by `rls-deny-all` without editing that test.
  - [ ] 1.12 [supabase, panel] Verify Acceptance Criterion: No existing table is altered.
  - [ ] 1.13 [supabase, panel] Integration Tests: schema applies on `supabase db reset`; each constraint above has a rejecting and an accepting case; anon is denied on every table
  - [ ] 1.14 [supabase, panel] Edge-Case Matrix: uppercase and malformed `full_name`; unknown step key; `skipped` with no reason is accepted by the schema (the contract enforces it, S-221); cascade on repository delete
  - [ ] 1.15 [supabase, panel] Map each acceptance criterion to its test evidence in the PR (each AC → one integration case in `tower-schema.test.ts`)
  - [ ] 1.16 [supabase, panel] Run Tests: `supabase db reset`, `pnpm --filter panel run test:integration`
  - [ ] 1.17 [supabase, panel] Quality gates: `pnpm --filter panel run validate` (lint, format:check, typecheck, test, audit)

- [ ] 2.0 Implement Story S-221: Ingestion contract version 1: validator, names, fixtures, contract document — [#489](https://github.com/llipe/dev-tasks-agent-fleet/issues/489)

  > Note: As the maintainer of the dev-tasks CLI, I want a versioned, documented definition of a push with example payloads, so that I can build a sender against it without reading the panel's code.

  - [ ] 2.1 [panel, repo root] Write the fixtures (valid and invalid) (D-16, D-18, D-20)
  - [ ] 2.2 [panel, repo root] Write the tests, then `names.ts` and `contract.ts`
  - [ ] 2.3 [panel, repo root] Write the contract document from the fixtures
  - [ ] 2.4 [panel, repo root] Migration: none — no data-model change
  - [ ] 2.5 [panel, repo root] Verify Acceptance Criterion: `names.ts` exports the eight issue step names and the eight wave stage names in order.
  - [ ] 2.6 [panel, repo root] Verify Acceptance Criterion: `validatePush(json)` accepts every valid fixture and returns a normalized push; it rejects each invalid fixture with a path and a message that contains no value from the input.
  - [ ] 2.7 [panel, repo root] Verify Acceptance Criterion: It rejects: an unsupported `contract_version` (naming `[1]`), a missing `push_id`, an unknown `kind`, an unknown `event.kind`, an unknown step, stage or result, `skipped` without a reason, an `observed_at` more than 5 minutes ahead of the supplied clock, and any string or array over its cap (spec §12).
  - [ ] 2.8 [panel, repo root] Verify Acceptance Criterion: It accepts and ignores unknown extra fields.
  - [ ] 2.9 [panel, repo root] Verify Acceptance Criterion: It accepts the seven event kinds, including `session_ended` with `usage` and a snapshot with a `lanes` block in both `ok` and `unreadable` states.
  - [ ] 2.10 [panel, repo root] Verify Acceptance Criterion: `docs/reference/tower-ingestion-contract.md` documents the envelope, both kinds, every event kind and every response code, and its examples are the fixture files.
  - [ ] 2.11 [panel, repo root] Verify Acceptance Criterion: At most 20 errors are returned.
  - [ ] 2.12 [panel, repo root] Unit Tests: one case per fixture; table-driven negative cases
  - [ ] 2.13 [panel, repo root] Manual/UI Testing: read the contract document end to end against the fixtures
  - [ ] 2.14 [panel, repo root] Edge-Case Matrix: empty snapshot (no PRDs, no issues); issue with null `prd_slug` and `wave_key`; cell with no evidence; 1,000-issue snapshot under 1 MiB; non-GitHub pull-request `url` is accepted here and neutralized at render (S-230)
  - [ ] 2.15 [panel, repo root] Map each acceptance criterion to its test evidence in the PR (AC-7 → version case; story ACs → fixture cases)
  - [ ] 2.16 [panel, repo root] Run Tests: `pnpm --filter panel run test:unit`
  - [ ] 2.17 [panel, repo root] Quality gates: `pnpm --filter panel run validate` (lint, format:check, typecheck, test, audit)

- [ ] 3.0 Implement Story S-220: Tower token and repository lifecycle (register, rotate, revoke, remove, threshold) — [#488](https://github.com/llipe/dev-tasks-agent-fleet/issues/488)

  > Note: As the owner, I want to register a repository and manage its token and stale threshold, so that its CLI can report and a leaked token can be stopped without touching other repositories.

  - [ ] 3.1 [panel] Unit tests for `token.ts`, then the module (D-11, D-23, D-29)
  - [ ] 3.2 [panel] Integration tests for the lifecycle, then `tower-repository-save.ts` and the queries
  - [ ] 3.3 [panel] Server Actions returning typed results
  - [ ] 3.4 [panel] Migration: none — uses S-219's tables unchanged
  - [ ] 3.5 [panel] Verify Acceptance Criterion: `generateTowerToken()` returns `twr_<12 base32>.<43 base64url>` and the SHA-256 hash of the secret; the plain token is returned to the caller once and is not stored.
  - [ ] 3.6 [panel] Verify Acceptance Criterion: `verifyTowerToken(header)` returns the repository id for a valid active token, and the same negative result for a missing header, a malformed header, an unknown id, a wrong secret and a revoked token.
  - [ ] 3.7 [panel] Verify Acceptance Criterion: The comparison uses `timingSafeEqual`, and an unknown id still performs one comparison against a dummy hash.
  - [ ] 3.8 [panel] Verify Acceptance Criterion: `registerTowerRepository` creates the repository, its token and its change marker, and returns the plain token; a duplicate name returns `already_registered`; an invalid name returns `invalid_name`.
  - [ ] 3.9 [panel] Verify Acceptance Criterion: `rotateTowerToken` revokes the old token and issues a new one atomically; the old one no longer verifies (AC-5).
  - [ ] 3.10 [panel] Verify Acceptance Criterion: `revokeTowerToken` leaves the repository with no active token; `removeTowerRepository` deletes the repository and everything under it.
  - [ ] 3.11 [panel] Verify Acceptance Criterion: `setTowerStaleThreshold` accepts 1–720 or null and rejects anything else.
  - [ ] 3.12 [panel] Verify Acceptance Criterion: No function logs the token or the header.
  - [ ] 3.13 [panel] Unit Tests: token format, parse, hash, every negative variant, the dummy-compare path (spy on `timingSafeEqual`)
  - [ ] 3.14 [panel] Integration Tests: register, duplicate, rotate, revoke, remove with cascade, threshold bounds, against real Postgres
  - [ ] 3.15 [panel] Edge-Case Matrix: header with extra whitespace, wrong prefix, two dots, 10 KB header; rotate twice; revoke with no active token
  - [ ] 3.16 [panel] Map each acceptance criterion to its test evidence in the PR (AC-5 → rotation integration case; each story AC → a named case)
  - [ ] 3.17 [panel] Run Tests: `pnpm --filter panel run test:unit`, `pnpm --filter panel run test:integration`
  - [ ] 3.18 [panel] Quality gates: `pnpm --filter panel run validate` (lint, format:check, typecheck, test, audit)

- [ ] 4.0 Implement Story S-222: `tower_apply_push`: merge, deduplicate, place events, summarize — [#490](https://github.com/llipe/dev-tasks-agent-fleet/issues/490)

  > Note: As the owner, I want every accepted push merged into one consistent picture, so that two lanes reporting from different branches never overwrite each other and nothing moves backward.

  - [ ] 4.1 [supabase, panel] Write the integration cases from the fixtures (D-20, D-21, D-25)
  - [ ] 4.2 [supabase, panel] Implement dedup and snapshot upsert with the merge rule
  - [ ] 4.3 [supabase, panel] Implement events, placement, summaries and the change marker
  - [ ] 4.4 [supabase, panel] Add the concurrency case
  - [ ] 4.5 [supabase, panel] Migration: record rollback and impact notes in the PR (additive; drop the function)
  - [ ] 4.6 [supabase, panel] Migration: apply locally with `supabase db reset` and verify (integration suite green). The live apply is task 10.0, after explicit owner confirmation
  - [ ] 4.7 [supabase, panel] Verify Acceptance Criterion: A push whose `push_id` was already recorded for the repository returns `duplicate` and changes no row (AC-6).
  - [ ] 4.8 [supabase, panel] Verify Acceptance Criterion: For each result cell, a newer `observed_at` replaces the stored cell; an equal or older one does not.
  - [ ] 4.9 [supabase, panel] Verify Acceptance Criterion: Two snapshots from different branches that disagree on a step leave the cell with the newer observation, whichever arrived last.
  - [ ] 4.10 [supabase, panel] Verify Acceptance Criterion: A non-default-branch snapshot never sets `removed_at`. A default-branch snapshot sets `removed_at` only on items previously seen on the default branch and absent from it; an item that reappears has `removed_at` cleared.
  - [ ] 4.11 [supabase, panel] Verify Acceptance Criterion: An event for an unknown issue is stored with `placed = false`, and is applied when a later snapshot contains that issue (AC-8).
  - [ ] 4.12 [supabase, panel] Verify Acceptance Criterion: Rework increments once per distinct key: a gate entering `failed`, an audit observation with `drift_findings > 0`, a `changes_requested` review. Re-sending the same failure does not increment it (AC-13).
  - [ ] 4.13 [supabase, panel] Verify Acceptance Criterion: `block_raised` on the owner then `block_cleared` adds the interval to `waiting_seconds` and sets `waiting_reported`; with no block ever reported, `waiting_reported` stays false.
  - [ ] 4.14 [supabase, panel] Verify Acceptance Criterion: `first_observed_at`, `shipped_at`, `event_count`, `workflow_agents`, `tokens_total` and `models` follow spec §8.3.
  - [ ] 4.15 [supabase, panel] Verify Acceptance Criterion: Each applied push sets the repository's `last_push_received_at` and `last_push_outcome` and increments its change marker by one.
  - [ ] 4.16 [supabase, panel] Verify Acceptance Criterion: The function is executable by `service_role` only, and receives the repository id as an argument, never from the payload.
  - [ ] 4.17 [supabase, panel] Verify Acceptance Criterion: Two pushes for one repository applied concurrently both succeed and leave the same result as applying them in sequence.
  - [ ] 4.18 [supabase, panel] Integration Tests: every AC above, against real Postgres, using the S-221 fixtures
  - [ ] 4.19 [supabase, panel] Edge-Case Matrix: tie on `observed_at`; event before snapshot; snapshot with zero items; issue moved from one wave to another; issue with no PRD; block raised twice; cleared with none open; `passed` then newer `failed`; concurrent pushes
  - [ ] 4.20 [supabase, panel] Map each acceptance criterion to its test evidence in the PR (AC-6, AC-8, AC-13 → named cases; story ACs → one case each in `tower-apply-push.test.ts`)
  - [ ] 4.21 [supabase, panel] Run Tests: `supabase db reset`, `pnpm --filter panel run test:integration`
  - [ ] 4.22 [supabase, panel] Quality gates: `pnpm --filter panel run validate` (lint, format:check, typecheck, test, audit)

- [ ] 5.0 Implement Story S-223: `POST /api/tower/ingest`: authenticate, cap, validate, apply — [#491](https://github.com/llipe/dev-tasks-agent-fleet/issues/491)

  > Note: As the dev-tasks CLI, I want one endpoint that accepts my pushes and tells me precisely why one was refused, so that I can retry what is retryable and report what is not.

  - [ ] 5.1 [panel] Tests for policy and pipeline order (D-23, D-25, D-28)
  - [ ] 5.2 [panel] `ingest.ts`, then the route handler
  - [ ] 5.3 [panel] Integration cases for every response
  - [ ] 5.4 [panel] Migration: none — no data-model change
  - [ ] 5.5 [panel] Verify Acceptance Criterion: A valid push returns 202 `accepted`; the same `push_id` again returns 200 `duplicate` (AC-2, AC-6).
  - [ ] 5.6 [panel] Verify Acceptance Criterion: A missing header, a malformed header, an unknown token and a revoked token each return 401 with the identical body, and nothing is stored (AC-3).
  - [ ] 5.7 [panel] Verify Acceptance Criterion: A valid token with another repository's name returns 403 and stores no tower data (AC-4).
  - [ ] 5.8 [panel] Verify Acceptance Criterion: A body over 1 MiB returns 413 without being buffered whole; invalid JSON or a contract failure returns 422 with `supported_versions` and `errors` (AC-7).
  - [ ] 5.9 [panel] Verify Acceptance Criterion: The body is not read before the token is verified.
  - [ ] 5.10 [panel] Verify Acceptance Criterion: Authenticated rejections (403, 413, 422) are recorded in `tower_pushes` with their outcome and set `last_push_outcome` to `rejected`.
  - [ ] 5.11 [panel] Verify Acceptance Criterion: `/api/tower/ingest` is class `internal` in `route-policy.ts` and passes the login gate; every other `/api/tower/**` path stays class `api`.
  - [ ] 5.12 [panel] Verify Acceptance Criterion: An unhandled error returns 500 and logs only the error name. The token, the header and the body are never logged.
  - [ ] 5.13 [panel] Unit Tests: route policy classes; the pipeline with injected dependencies for ordering (no body read before auth)
  - [ ] 5.14 [panel] Integration Tests: the HTTP pipeline end to end for 202, 200, each 401, 403, 413, 422
  - [ ] 5.15 [panel] Manual/UI Testing: `curl` a fixture at the local panel
  - [ ] 5.16 [panel] Edge-Case Matrix: wrong content type; empty body; exactly 1 MiB; 1 MiB + 1; GET on the route; token valid but repository removed mid-request
  - [ ] 5.17 [panel] Map each acceptance criterion to its test evidence in the PR (AC-2, AC-3, AC-4, AC-6, AC-7 → `tower-ingest.test.ts` cases)
  - [ ] 5.18 [panel] Run Tests: `pnpm --filter panel run test:unit`, `pnpm --filter panel run test:integration`
  - [ ] 5.19 [panel] Quality gates: `pnpm --filter panel run validate` (lint, format:check, typecheck, test, audit)

- [ ] 6.0 Implement Story S-224: Retention: `tower.prune()` and its daily job — [#492](https://github.com/llipe/dev-tasks-agent-fleet/issues/492)

  > Note: As the owner, I want raw tower events removed 90 days after an issue ships while its summary stays, so that the events table does not grow without limit and old waves remain comparable.

  - [ ] 6.1 [supabase, panel] Write the integration tests for `tower.prune()` with rows dated by fixture (D-15)
  - [ ] 6.2 [supabase, panel] Write `tower.prune()` in a new migration
  - [ ] 6.3 [supabase, panel] Schedule the daily `tower-prune` job with `cron.schedule`
  - [ ] 6.4 [supabase, panel] Migration: record rollback and impact notes in the PR (unschedule the job and drop the function; no data is restored by rollback)
  - [ ] 6.5 [supabase, panel] Migration: apply locally with `supabase db reset` and verify (the job is listed in `cron.job`). The live apply is task 10.0, after explicit owner confirmation
  - [ ] 6.6 [supabase, panel] Verify Acceptance Criterion: Events of an issue shipped more than `event_retention_days` ago are deleted and its `summary_final_at` is set; its summary columns are unchanged (AC-19).
  - [ ] 6.7 [supabase, panel] Verify Acceptance Criterion: Events of an open issue, and of an issue shipped inside the window, are kept whatever their age.
  - [ ] 6.8 [supabase, panel] Verify Acceptance Criterion: Wave-level events are pruned by their wave's `shipped_at`.
  - [ ] 6.9 [supabase, panel] Verify Acceptance Criterion: `tower_pushes` rows older than `push_retention_days` are deleted.
  - [ ] 6.10 [supabase, panel] Verify Acceptance Criterion: The job `tower-prune` is scheduled daily and running the function twice changes nothing the second time.
  - [ ] 6.11 [supabase, panel] Verify Acceptance Criterion: Changing a `tower.config` value changes the behavior without a migration.
  - [ ] 6.12 [supabase, panel] Integration Tests: the five behaviors above with rows dated by fixture
  - [ ] 6.13 [supabase, panel] Edge-Case Matrix: unplaced events of an issue that never appeared (kept); issue shipped exactly at the boundary; missing config key falls back to the default
  - [ ] 6.14 [supabase, panel] Map each acceptance criterion to its test evidence in the PR (AC-19 → `tower-prune.test.ts`)
  - [ ] 6.15 [supabase, panel] Run Tests: `pnpm --filter panel run test:integration`
  - [ ] 6.16 [supabase, panel] Quality gates: `pnpm --filter panel run validate` (lint, format:check, typecheck, test, audit)

- [ ] 7.0 Implement Story S-225: Read contract version 1: module, endpoints, document — [#493](https://github.com/llipe/dev-tasks-agent-fleet/issues/493)

  > Note: As the owner, I want all Control Tower data served through one documented shape, so that the page and any later plugin read the same thing.

  - [ ] 7.1 [panel, repo root] Write the read-contract fixture and the unit tests for `read.ts` (D-12, D-14, D-27)
  - [ ] 7.2 [panel, repo root] Implement `panel/lib/tower/read.ts`
  - [ ] 7.3 [panel, repo root] Implement the paged service-role queries
  - [ ] 7.4 [panel, repo root] Implement the two route handlers
  - [ ] 7.5 [panel, repo root] Write `docs/reference/tower-read-contract.md` from the fixture
  - [ ] 7.6 [panel, repo root] Migration: none — read-only
  - [ ] 7.7 [panel, repo root] Verify Acceptance Criterion: `buildRepositoryTree(rows, now, scope)` and `buildRepositorySummaries(rows, now)` are pure and return the shapes of spec §6.2.
  - [ ] 7.8 [panel, repo root] Verify Acceptance Criterion: Step gaps are the difference between consecutive `passed` or `skipped` cells and are `null` when either is missing or the difference is negative.
  - [ ] 7.9 [panel, repo root] Verify Acceptance Criterion: `in_wave` is false for an issue with no wave; issues with no PRD are returned under `no_prd_issues`.
  - [ ] 7.10 [panel, repo root] Verify Acceptance Criterion: A value that was not reported is `null`: a missing cell, `waiting_seconds` with `waiting_reported` false, `subtasks`, `coverage_gate`, `drift_findings` (AC-14).
  - [ ] 7.11 [panel, repo root] Verify Acceptance Criterion: `stale` is true only with open work and a last push older than the threshold; the threshold is the repository override, else the config default, and `threshold_source` says which (AC-16, AC-17).
  - [ ] 7.12 [panel, repo root] Verify Acceptance Criterion: `scope=recent` returns open items and items shipped inside `default_window_days`, keeping a wave or PRD when any child is kept; `scope=all` returns everything not removed (AC-18).
  - [ ] 7.13 [panel, repo root] Verify Acceptance Criterion: PRD and wave rollups match the counts of their non-removed children; a wave with no audit evidence and a Done ship stage returns exactly those two cells (AC-10).
  - [ ] 7.14 [panel, repo root] Verify Acceptance Criterion: `GET /api/tower/repositories` and `GET /api/tower/repositories/{owner}/{name}` return the module's output; an unregistered name is 404; an unauthenticated request is 401 (AC-23).
  - [ ] 7.15 [panel, repo root] Verify Acceptance Criterion: Reads page in 1,000-row pages; a repository with 2,500 issues returns all of them.
  - [ ] 7.16 [panel, repo root] Verify Acceptance Criterion: `docs/reference/tower-read-contract.md` documents the shapes; one test asserts the module's output and the endpoint's body equal the shared fixture.
  - [ ] 7.17 [panel, repo root] Unit Tests: gaps, seven-node rule, staleness matrix, rollups, window, nulls
  - [ ] 7.18 [panel, repo root] Integration Tests: endpoints over rows produced by real pushes; paging beyond 1,000 rows; 401 and 404
  - [ ] 7.19 [panel, repo root] Edge-Case Matrix: repository that never pushed; PRD with no waves; wave with no issues; all issues shipped; removed items; clock exactly at the threshold
  - [ ] 7.20 [panel, repo root] Map each acceptance criterion to its test evidence in the PR (AC-10, AC-12, AC-14, AC-16, AC-17, AC-18, AC-23 → named cases)
  - [ ] 7.21 [panel, repo root] Run Tests: `pnpm --filter panel run test:unit`, `pnpm --filter panel run test:integration`
  - [ ] 7.22 [panel, repo root] Quality gates: `pnpm --filter panel run validate` (lint, format:check, typecheck, test, audit)

- [ ] 8.0 Implement Story S-226: Minimal `/tower`: repositories, registration, show-once token, settings — [#494](https://github.com/llipe/dev-tasks-agent-fleet/issues/494)

  > Note: As the owner, I want a Control Tower page where I register a repository, copy its token once and manage it, so that I can connect a repository without a script.

  - [ ] 8.1 [panel] Write the E2E test for register and reveal-once (D-11, D-30)
  - [ ] 8.2 [panel] Build the `/tower` page and the repository list
  - [ ] 8.3 [panel] Build the register dialog, the reveal-once dialog and the repository settings
  - [ ] 8.4 [panel] Add the Control Tower entry to the sidebar
  - [ ] 8.5 [panel] Migration: none — UI only
  - [ ] 8.6 [panel] Verify Acceptance Criterion: The sidebar has a "Control Tower" entry leading to `/tower`.
  - [ ] 8.7 [panel] Verify Acceptance Criterion: The page lists tower repositories with last-reported time, last push outcome, and pushes accepted and rejected in the last day.
  - [ ] 8.8 [panel] Verify Acceptance Criterion: Registering `owner/name` reveals the token once with the CLI line to paste; closing the dialog and reloading never shows it again (AC-1).
  - [ ] 8.9 [panel] Verify Acceptance Criterion: A duplicate or invalid name shows the named error and creates nothing.
  - [ ] 8.10 [panel] Verify Acceptance Criterion: Rotate reveals a new token once after a confirmation; revoke and remove each ask for confirmation, and remove states what is deleted.
  - [ ] 8.11 [panel] Verify Acceptance Criterion: The stale threshold field shows the value in effect and whether it comes from the default or the repository; clearing it returns to the default.
  - [ ] 8.12 [panel] Verify Acceptance Criterion: With no repository, and for a repository with no push yet, the page shows the empty state with the next CLI step, and says the hierarchy arrives with the next wave.
  - [ ] 8.13 [panel] Verify Acceptance Criterion: A logged-out visit to `/tower` redirects to `/login` (AC-23).
  - [ ] 8.14 [panel] Unit Tests: name validation; threshold field logic
  - [ ] 8.15 [panel] Integration Tests: covered by S-220
  - [ ] 8.16 [panel] Manual/UI Testing: the full register → reveal → reload flow at `/tower`
  - [ ] 8.17 [panel] Edge-Case Matrix: name with uppercase or spaces; double submit; rotate while the reveal dialog is open; narrow viewport
  - [ ] 8.18 [panel] Map each acceptance criterion to its test evidence in the PR (AC-1, AC-23 → `tower-repositories.spec.ts`)
  - [ ] 8.19 [panel] Run Tests: `pnpm --filter panel run test:unit`, `pnpm --filter panel run test:e2e`
  - [ ] 8.20 [panel] Quality gates: `pnpm --filter panel run validate` (lint, format:check, typecheck, test, audit)

- [ ] 9.0 Implement Story S-227: Release-gate probes and the Control Tower runbook — [#495](https://github.com/llipe/dev-tasks-agent-fleet/issues/495)

  > Note: As the owner, I want every release to prove that an unauthenticated push and an unauthenticated read are refused, and a runbook for operating the tower, so that the new public surface cannot regress silently.

  - [ ] 9.1 [panel, repo root] Write the unit tests for the gate verdict with the two new probes (D-26)
  - [ ] 9.2 [panel, repo root] Extend `evaluateAuthGate` in `panel-auth-check.mjs`
  - [ ] 9.3 [panel, repo root] Add the two probes to `scripts/verify-panel-auth.sh`
  - [ ] 9.4 [panel, repo root] Write `docs/runbooks/control-tower.md` and link it from the runbooks index
  - [ ] 9.5 [panel, repo root] Migration: none — scripts and documentation only
  - [ ] 9.6 [panel, repo root] Verify Acceptance Criterion: `scripts/verify-panel-auth.sh` sends a `POST /api/tower/ingest` with no token and requires 401, and a `GET /api/tower/repositories` with no session and requires 401.
  - [ ] 9.7 [panel, repo root] Verify Acceptance Criterion: `evaluateAuthGate` in `panel/scripts/panel-auth-check.mjs` fails the gate when either probe returns anything else, including 404 and 302.
  - [ ] 9.8 [panel, repo root] Verify Acceptance Criterion: The parser's unit tests cover both probes passing, each failing, and both failing; CI runs them.
  - [ ] 9.9 [panel, repo root] Verify Acceptance Criterion: `docs/runbooks/control-tower.md` covers: register a repository, rotate and revoke a token, send a hand-made snapshot and event with `curl`, read the push counters, and what to check when a repository shows stale.
  - [ ] 9.10 [panel, repo root] Verify Acceptance Criterion: `docs/runbooks/` index links the new runbook.
  - [ ] 9.11 [panel, repo root] Unit Tests: the verdict function with the new inputs
  - [ ] 9.12 [panel, repo root] Manual/UI Testing: run the script against the local panel
  - [ ] 9.13 [panel, repo root] Edge-Case Matrix: probe timeout; a 5xx from either probe fails the gate
  - [ ] 9.14 [panel, repo root] Map each acceptance criterion to its test evidence in the PR (AC-3, AC-23 → gate unit tests and a local script run)
  - [ ] 9.15 [panel, repo root] Run Tests: `pnpm --filter panel run test:unit`, `scripts/verify-panel-auth.sh`
  - [ ] 9.16 [panel, repo root] Quality gates: `pnpm --filter panel run validate` (lint, format:check, typecheck, test, audit)

- [ ] 10.0 Implement Story S-228: Wave A live: migrations pushed, panel deployed, one real push accepted — [#496](https://github.com/llipe/dev-tasks-agent-fleet/issues/496)

  > Note: As the owner, I want Wave A running on the live panel with one repository registered and one push accepted, so that the dev-tasks CLI has a real endpoint to build against.

  - [ ] 10.1 [repo root] Run the pre-checks on the hosted project: `pg_cron`, Realtime, `service_role` execute grants (D-30)
  - [ ] 10.2 [repo root] Push the Wave A migrations to the live database, after owner confirmation
  - [ ] 10.3 [repo root] Deploy the panel and run the release gate
  - [ ] 10.4 [repo root] Register one repository on the live panel and send the hand-made snapshot and event
  - [ ] 10.5 [repo root] Update the technical guidelines, product context and roadmap; record the change under `infra/changes/`
  - [ ] 10.6 [repo root] Migration: request explicit owner confirmation before the live `db push`; record the revert plan first
  - [ ] 10.7 [repo root] Migration: verify the applied state on the live project
  - [ ] 10.8 [repo root] Verify Acceptance Criterion: Before the push, the hosted project is confirmed to have `pg_cron` and Realtime enabled, and `service_role` able to execute the new functions.
  - [ ] 10.9 [repo root] Verify Acceptance Criterion: The Wave A migrations are applied to the live database after explicit owner confirmation, and `tower-prune` is listed in `cron.job`.
  - [ ] 10.10 [repo root] Verify Acceptance Criterion: The panel is deployed and the release gate passes, including the two new probes.
  - [ ] 10.11 [repo root] Verify Acceptance Criterion: One repository is registered on the live panel; a hand-made snapshot returns 202 and a hand-made event returns 202; a repeat returns 200; a push with a wrong token returns 401.
  - [ ] 10.12 [repo root] Verify Acceptance Criterion: `/tower` shows the repository with its last-reported time and push counts.
  - [ ] 10.13 [repo root] Verify Acceptance Criterion: `docs/technical-guidelines.md` documents the ingest endpoint, the token model and the new tables; `docs/roadmap.md` Wave A row is updated; the change is recorded under `infra/changes/`.
  - [ ] 10.14 [repo root] Manual/UI Testing: the live `curl` sequence from the runbook; the `/tower` check
  - [ ] 10.15 [repo root] Edge-Case Matrix: migration push fails midway (revert plan recorded before the push)
  - [ ] 10.16 [repo root] Map each acceptance criterion to its test evidence in the PR (AC-2, AC-3, AC-6 → recorded live responses)
  - [ ] 10.17 [repo root] Run Tests: `scripts/verify-panel-auth.sh`, the runbook's `curl` lines
  - [ ] 10.18 [repo root] Quality gates: `pnpm --filter panel run validate` (lint, format:check, typecheck, test, audit)

## Decisions Consumed

| ID   | Decision (short form) |
| ---- | --------------------- |
| D-11 | One write-only tower token per repository, shown once, stored hashed, revocable |
| D-12 | Embedding is out of scope; one documented read contract is kept |
| D-14 | Live updates, last-reported time, stale flag after 24 hours with open work |
| D-15 | Summaries kept permanently; raw events pruned 90 days after ship; default view is open work plus 14 days |
| D-16 | Two PRDs; this one owns the contract and ships three waves; a companion PRD in `llipe/dev-tasks` owns the sending side |
| D-18 | Specification covers Waves A and B; contract version 1 reserves lanes and token usage |
| D-19 | Tower repositories get their own table, independent of `repositories` |
| D-20 | The CLI sends results with evidence; the panel computes times, rework and rollups |
| D-21 | Newest observed result per item wins; a snapshot never erases; each push names its branch |
| D-22 | One table per level, results in columns, raw events separate |
| D-23 | `POST /api/tower/ingest`, bearer token in a header, hash stored, one 401 for all authentication failures |
| D-25 | Sender-generated push identifier; a repeat answers 200 |
| D-26 | Two release-gate probes: unauthenticated push and unauthenticated read both 401 |
| D-27 | Read contract as HTTP endpoints computed by one server module the page also calls |
| D-28 | No rate limit in version 1; size cap, push counters, revocation |
| D-29 | Panel-wide stale threshold with an optional per-repository override |
| D-30 | Wave A ships visible with registration and tokens; additive migrations; infra pass and runbook |
| D-31 | Seven specification terms; "result", not "status"; `tower` prefix |
