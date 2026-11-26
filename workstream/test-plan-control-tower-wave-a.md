# Compliance Test Plan — Control Tower, Wave A (verifier, Design Mode)

## Changelog

| Version | Date       | Summary                                                                                              | Author   |
| ------- | ---------- | ---------------------------------------------------------------------------------------------------- | -------- |
| 1.0     | 2026-11-26 | Initial plan for Wave A (S-219–S-228, issues #487–#496) from stories v1.2, spec v1.1, PRD v1.4, task list v1.1. | verifier |

> A test-first plan written before implementation. Companion:
> [`traceability-matrix-control-tower-wave-a`](traceability-matrix-control-tower-wave-a.md).
>
> **Status:** Design Mode, so there is no verdict. The plan adds to the existing gates
> (`test`, `lint`, `format:check`, `typecheck`, `audit`) and blocks nothing. 76 acceptance criteria are
> numbered; every one has at least one positive and one negative or edge case. 284 cases are
> specified: 93 L1, 11 L2, 156 L2.5, 8 E2E and 16 Manual. 26 findings (A-01 to
> A-26) are open against the stories and the spec. Cases whose expected result depends on a finding
> say so in their Expected column and must not be written as passing assertions until the finding is
> decided.

## 1. Source input summary

- **Mode:** Design. **Input type:** stories (ten, Wave A only) with the spec and PRD as authority.
- **Sources read:** `workstream/user-stories-control-tower.md` v1.2 ("Wave A — Ingest", lines 56–676);
  `workstream/specification-control-tower.md` v1.1; `docs/requirements/prd-control-tower.md` v1.4;
  `workstream/tasks-control-tower-plan.md` v1.1; `workstream/decisions-control-tower.md` D-01–D-31;
  `/TESTING.md`. `workstream/research-control-tower.md` was not read in full; its claims are used
  only as the spec quotes them.
- **Out of scope:** Wave B stories S-229–S-234, PRD FR-33–FR-39 and AC-20–AC-22, and the rendering
  half of PRD AC-9–AC-12 and AC-15–AC-18. Their data half is in scope where S-225 owns it.
- **Layers and runners (`/TESTING.md`):**

| Layer  | Runner                                                         | Used here for                                                                                   |
| ------ | -------------------------------------------------------------- | ----------------------------------------------------------------------------------------------- |
| L1     | Vitest `unit` project, `panel/tests/unit/`                     | Validator, token module, ingest pipeline with injected dependencies, read module, route policy, gate verdict |
| L2     | Vitest `component` project, `panel/tests/component/` (jsdom)   | `/tower` components, the proxy gate                                                             |
| L2.5   | Vitest `integration` project against the local Supabase stack  | Schema, `tower_apply_push`, `tower.prune()`, lifecycle, the HTTP handlers invoked directly. No data-layer mock |
| E2E    | Playwright, `panel/tests/e2e/`                                 | Register, reveal once, settings, logged-out access                                              |
| Manual | A person, with recorded evidence                               | Document read-through, the local gate run, all of S-228                                          |

- **Conventions taken from the existing webhook tests:** an integration file probes the database with
  `probeLocalDb()` and uses `describe.skipIf(!probe.available)`; CI sets `REQUIRE_LOCAL_DB=1` so a
  skip is a failure. Route handlers are imported and called with a `Request`, with no server. SQL
  set-up and assertions go through `withDb()`. Randomized cases use `mulberry32` and `testSeed` from
  `panel/tests/helpers/prng.ts`.
- **Clock control.** `validatePush` and the read module take the clock as a parameter. The SQL
  function uses the database clock for received time, so integration cases assert received times
  with a window (`before <= value <= after`, both read from the database), never with equality.
- **Shared fixtures.** `panel/tests/fixtures/tower/*.json` (S-221) are the only push examples. Later
  stories derive pushes from them with a small builder (new `push_id`, shifted `observed_at`); a
  second copy of a payload in a test file is a defect under `/TESTING.md`.

### Planned test files

| Key     | File                                                                 | State                    |
| ------- | -------------------------------------------------------------------- | ------------------------ |
| SCH     | `panel/tests/integration/tower-schema.test.ts`                       | new (S-219)              |
| RLS     | `panel/tests/integration/rls-deny-all.test.ts`                       | existing, must not change |
| DEF     | `panel/tests/integration/definer-grants.test.ts`                     | existing, must not change |
| TOK     | `panel/tests/unit/tower-token.test.ts`                               | new (S-220)              |
| REP     | `panel/tests/integration/tower-repository.test.ts`                   | new (S-220)              |
| CON     | `panel/tests/unit/tower-contract.test.ts`                            | new (S-221)              |
| APP     | `panel/tests/integration/tower-apply-push.test.ts`                   | new (S-222)              |
| APR     | `panel/tests/integration/tower-apply-push-random.test.ts`            | new, proposed by this plan (S-222) |
| ING-U   | `panel/tests/unit/tower-ingest.test.ts`                              | new (S-223)              |
| POL     | `panel/tests/unit/auth-route-policy.test.ts`                         | existing, extended (see A-24) |
| GATE-C  | `panel/tests/component/proxy-gate.test.ts`                           | existing, extended       |
| ING-I   | `panel/tests/integration/tower-ingest.test.ts`                       | new (S-223)              |
| PRU     | `panel/tests/integration/tower-prune.test.ts`                        | new (S-224)              |
| RD-U    | `panel/tests/unit/tower-read.test.ts`                                | new (S-225)              |
| RD-I    | `panel/tests/integration/tower-read.test.ts`                         | new (S-225)              |
| UI-U    | `panel/tests/unit/tower-repository-input.test.ts`                    | new, proposed by this plan (S-226) |
| UI-C    | `panel/tests/component/tower-repositories.test.tsx`                  | new, proposed by this plan (S-226) |
| SB-C    | `panel/tests/component/Sidebar.test.tsx`                             | existing, extended       |
| E2E     | `panel/tests/e2e/tower-repositories.spec.ts`                         | new (S-226)              |
| PAC     | `panel/tests/unit/panel-auth-check.test.ts`                          | existing, extended (S-227) |
| PAC-CLI | `panel/tests/unit/panel-auth-check-cli.test.ts`                      | existing, extended (S-227) |
| REVIEW  | No test file. A recorded review or script run in the story PR        | —                        |
| LIVE    | `infra/changes/<date>-control-tower-wave-a/` (recorded live evidence) | new (S-228)             |

## 2. Acceptance-criteria extraction

Criteria are numbered in the order of each story's "Acceptance Criteria" checklist. The text is
shortened here; the story is the authority.

| AC ID        | Criterion (short)                                                                                       |
| ------------ | ------------------------------------------------------------------------------------------------------- |
| S-219-AC-1   | The eight `tower_*` tables exist with the columns, keys and indexes of spec §5.1                         |
| S-219-AC-2   | `full_name` is unique and rejects anything that is not lowercase `owner/name`                            |
| S-219-AC-3   | A second active token is rejected; a revoked one plus an active one is allowed                           |
| S-219-AC-4   | `steps` and `stages` reject an unknown key and an unknown result; a missing key is allowed               |
| S-219-AC-5   | `tower.config` exists with the four default values                                                       |
| S-219-AC-6   | Every new public table is RLS deny-all and is covered by `rls-deny-all` without editing it               |
| S-219-AC-7   | No existing table is altered                                                                             |
| S-220-AC-1   | `generateTowerToken()` format and hash; the plain token is returned once and not stored                  |
| S-220-AC-2   | `verifyTowerToken` returns the repository id, or one identical negative for five failure kinds           |
| S-220-AC-3   | `timingSafeEqual` is used; an unknown id still performs one comparison against a dummy hash              |
| S-220-AC-4   | `registerTowerRepository` creates repository, token, marker; `already_registered`; `invalid_name`        |
| S-220-AC-5   | `rotateTowerToken` revokes and issues atomically; the old token no longer verifies                       |
| S-220-AC-6   | `revokeTowerToken` leaves no active token; `removeTowerRepository` deletes everything under it           |
| S-220-AC-7   | `setTowerStaleThreshold` accepts 1–720 or null and rejects anything else                                 |
| S-220-AC-8   | No function logs the token or the header                                                                 |
| S-221-AC-1   | `names.ts` exports the eight step names and the eight stage names in order                               |
| S-221-AC-2   | `validatePush` accepts every valid fixture (normalized) and rejects every invalid one with path and a value-free message |
| S-221-AC-3   | The listed rejections: version, `push_id`, kinds, names, result, skipped reason, future time, caps       |
| S-221-AC-4   | Unknown extra fields are accepted and ignored                                                            |
| S-221-AC-5   | The seven event kinds, `session_ended` with `usage`, and `lanes` in both states are accepted             |
| S-221-AC-6   | The contract document covers envelope, kinds, event kinds, response codes; its examples are the fixtures |
| S-221-AC-7   | At most 20 errors are returned                                                                           |
| S-222-AC-1   | A repeated `push_id` returns `duplicate` and changes no row                                              |
| S-222-AC-2   | A newer `observed_at` replaces a cell; an equal or older one does not                                    |
| S-222-AC-3   | Two branches that disagree leave the newer observation, whichever arrived last                           |
| S-222-AC-4   | `removed_at`: never from a non-default snapshot; only on items seen on default; cleared on reappearance  |
| S-222-AC-5   | An event for an unknown issue is stored unplaced and applied when a snapshot supplies the issue          |
| S-222-AC-6   | Rework increments once per distinct key and not on a re-sent failure                                     |
| S-222-AC-7   | `block_raised` then `block_cleared` adds to `waiting_seconds`; `waiting_reported` stays false with no block |
| S-222-AC-8   | `first_observed_at`, `shipped_at`, `event_count`, `workflow_agents`, `tokens_total`, `models` follow §8.3 |
| S-222-AC-9   | Each applied push sets `last_push_received_at`, `last_push_outcome` and increments the marker by one     |
| S-222-AC-10  | Executable by `service_role` only; the repository id is an argument, never read from the payload         |
| S-222-AC-11  | Two concurrent pushes for one repository both succeed with the result of a sequential application        |
| S-223-AC-1   | A valid push returns 202; the same `push_id` again returns 200                                           |
| S-223-AC-2   | Missing, malformed, unknown and revoked each return 401 with the identical body; nothing is stored       |
| S-223-AC-3   | A valid token with another repository's name returns 403 and stores no tower data                        |
| S-223-AC-4   | Over 1 MiB returns 413 without whole-body buffering; invalid JSON or contract failure returns 422        |
| S-223-AC-5   | The body is not read before the token is verified                                                        |
| S-223-AC-6   | 403, 413 and 422 are recorded in `tower_pushes` and set `last_push_outcome` to `rejected`                |
| S-223-AC-7   | `/api/tower/ingest` is class `internal`; every other `/api/tower/**` path stays `api`                    |
| S-223-AC-8   | An unhandled error returns 500 and logs only the error name; token, header, body never logged            |
| S-224-AC-1   | Events of an issue shipped longer ago than the retention are deleted; `summary_final_at` set; summary unchanged |
| S-224-AC-2   | Events of an open issue, and of one shipped inside the window, are kept whatever their age               |
| S-224-AC-3   | Wave-level events are pruned by their wave's `shipped_at`                                                |
| S-224-AC-4   | `tower_pushes` rows older than `push_retention_days` are deleted                                         |
| S-224-AC-5   | `tower-prune` is scheduled daily; a second run changes nothing                                           |
| S-224-AC-6   | Changing a `tower.config` value changes the behavior without a migration                                 |
| S-225-AC-1   | `buildRepositoryTree` and `buildRepositorySummaries` are pure and return the §6.2 shapes                 |
| S-225-AC-2   | Step gaps: difference between consecutive `passed` or `skipped` cells; `null` when missing or negative   |
| S-225-AC-3   | `in_wave` false with no wave; issues with no PRD under `no_prd_issues`                                   |
| S-225-AC-4   | An unreported value is `null`                                                                            |
| S-225-AC-5   | `stale` only with open work and a last push older than the threshold; override, default, `threshold_source` |
| S-225-AC-6   | `scope=recent` and `scope=all`                                                                           |
| S-225-AC-7   | Rollups match non-removed children; the wave with no audit evidence and a Done ship stage                |
| S-225-AC-8   | The two GET endpoints return the module's output; 404 unregistered; 401 unauthenticated                  |
| S-225-AC-9   | Reads page in 1,000-row pages; 2,500 issues are all returned                                             |
| S-225-AC-10  | The read-contract document; one test asserts module output, endpoint body and fixture are equal          |
| S-226-AC-1   | The sidebar has a "Control Tower" entry leading to `/tower`                                              |
| S-226-AC-2   | The list shows last-reported time, last push outcome, accepted and rejected counts for the last day      |
| S-226-AC-3   | Registering reveals the token once with the CLI line; never again after close and reload                 |
| S-226-AC-4   | A duplicate or invalid name shows the named error and creates nothing                                    |
| S-226-AC-5   | Rotate, revoke and remove each ask for confirmation; remove states what is deleted                       |
| S-226-AC-6   | The threshold field shows the value in effect and its source; clearing returns to the default            |
| S-226-AC-7   | Empty states with the next CLI step; the page says the hierarchy arrives with the next wave              |
| S-226-AC-8   | A logged-out visit to `/tower` redirects to `/login`                                                     |
| S-227-AC-1   | `verify-panel-auth.sh` probes ingest (no token) and read (no session) and requires 401 for both          |
| S-227-AC-2   | `evaluateAuthGate` fails when either probe returns anything else, including 404 and 302                  |
| S-227-AC-3   | The parser's unit tests cover pass/pass, each failing, both failing; CI runs them                        |
| S-227-AC-4   | The runbook covers its five procedures                                                                   |
| S-227-AC-5   | The runbooks index links the new runbook                                                                 |
| S-228-AC-1   | Pre-checks on the hosted project: `pg_cron`, Realtime, `service_role` execute                            |
| S-228-AC-2   | Migrations applied live after owner confirmation; `tower-prune` listed in `cron.job`                     |
| S-228-AC-3   | Panel deployed; the release gate passes with the two new probes                                          |
| S-228-AC-4   | One live repository; snapshot 202, event 202, repeat 200, wrong token 401                                |
| S-228-AC-5   | `/tower` shows the repository with its last-reported time and push counts                                |
| S-228-AC-6   | Technical guidelines, roadmap row and `infra/changes/` record updated                                    |

**Invariants the cases rely on** (each is stated by the spec; a case that breaks one is a defect):

- **I-1.** Nothing is read from the body, and nothing is written, before the token is verified (§7, §12).
- **I-2.** Every authentication failure produces the same status and the same body (§6.1, D-23).
- **I-3.** A push can write only under the repository its token resolves to (§7, FR-4).
- **I-4.** A cell's `observed_at` never decreases (§8.2, FR-9).
- **I-5.** Ingest never physically deletes a PRD, wave or issue row; removal is `removed_at` (§8.1, FR-8).
- **I-6.** A duplicate push changes no row (§8.1, FR-9).
- **I-7.** Received time is the database clock, never a value from the payload (§8.1).
- **I-8.** An unreported value is `null` in the read contract, never `0`, `""` or `passed` (§6.2, FR-27).
- **I-9.** `tower.prune()` never changes a summary column (§5.3, FR-13).
- **I-10.** The plain token, the header and the request body appear in no log line and no stored column (§12).

## 3. Test cases by story

Columns: **Type** is `pos` (positive), `neg` (negative), `edge`, `sec` (security-negative) or `prop`
(property or randomized). **File** is a key from the table in §1. Step and stage keys are written as
`plan`, `test_design`, `build`, `quality_gates`, `coverage_gate`, `fidelity_audit`, `merged`,
`shipped` and `refine`, `spec`, `stories`, `publish`, `plan`, `build`, `audit`, `ship`; the spec
never lists them literally (A-17), so they are an assumption until `names.ts` exists.

### 3.1 S-219 — Tower schema (#487)

| ID | ACs | Layer | Type | File | Preconditions | Steps / input | Expected result |
| --- | --- | --- | --- | --- | --- | --- | --- |
| TC-219-01 | S-219-AC-1 | L2.5 | pos | SCH | Fresh `supabase db reset` | Query `information_schema` and `pg_indexes` for the eight tables | All eight exist. Every column named in §5.1 exists. Unique keys: `full_name`; `public_id`; `(repository_id, push_id)`; `(repository_id, slug)`; `(prd_id, key)`; `(repository_id, number)`. The five indexes of §5.1 exist, including the partial one on `tower_events where placed = false` |
| TC-219-02 | S-219-AC-1 | L2.5 | neg | SCH | One repository with a PRD, a wave, an issue and a push row | Insert a second row with the same natural key in each of the four tables; insert the same issue number under a second repository | Each same-key insert fails with a unique violation. The insert under the second repository succeeds |
| TC-219-03 | S-219-AC-1 | L2.5 | edge | SCH | One repository with a row in each of the seven child tables; a second repository likewise | Delete the first repository | Zero rows remain for it in all seven tables. The second repository's rows are untouched |
| TC-219-04 | S-219-AC-1 | L2.5 | neg | SCH | Fresh schema | Insert rows with `last_push_outcome='ok'`, push `kind='sync'`, push `outcome='failed'`, `roadmap_status='Done'`, `coverage_gate='pass'`, `stale_threshold_hours` 0 and 721 | Each is rejected by a check constraint. `stale_threshold_hours` 1, 720 and null are accepted |
| TC-219-05 | S-219-AC-1 | L2.5 | neg | SCH | Fresh schema | List foreign keys of all `tower_*` tables | None references `repositories` or any non-tower table (D-19) |
| TC-219-06 | S-219-AC-2 | L2.5 | pos | SCH | Fresh schema | Insert `llipe/riel`, `a_b.c-d/e.f`, `0/0` | All accepted |
| TC-219-07 | S-219-AC-2 | L2.5 | neg | SCH | `llipe/riel` exists | Insert `llipe/riel` again; insert `Llipe/riel`, `llipe`, `llipe/riel/x`, `/riel`, `llipe/`, `llipe/ri el`, ` llipe/riel`, the empty string | The repeat fails with a unique violation. Each malformed value fails the pattern check |
| TC-219-08 | S-219-AC-3 | L2.5 | neg | SCH | A repository with one active token | Insert a second token with `revoked_at` null | Rejected by the partial unique index |
| TC-219-09 | S-219-AC-3 | L2.5 | pos | SCH | A repository with two revoked tokens | Insert one active token; insert an active token for a second repository; insert a token reusing an existing `public_id` | The first two succeed. The reused `public_id` is rejected |
| TC-219-10 | S-219-AC-4 | L2.5 | pos | SCH | A wave and an issue | Set `steps` and `stages` to: the empty object; one key; all eight keys with each of the five results | All accepted. A missing key is stored as missing, not as `pending` |
| TC-219-11 | S-219-AC-4 | L2.5 | neg | SCH | A wave and an issue | Set `steps` with key `deploy`; `steps` with stage-only key `refine`; `stages` with step-only key `merged`; a cell with `result` `done`; a cell with `result` `PASSED` | Each rejected by a check constraint |
| TC-219-12 | S-219-AC-4 | L2.5 | edge | SCH | An issue | Set a cell `{ "result": "skipped" }` with no `reason` | Accepted by the schema (the contract enforces the reason, S-221) |
| TC-219-13 | S-219-AC-5 | L2.5 | pos | SCH | Fresh `supabase db reset` | Select all rows of `tower.config` | Exactly `stale_threshold_hours=24`, `event_retention_days=90`, `push_retention_days=30`, `default_window_days=14` |
| TC-219-14 | S-219-AC-5 | L2.5 | neg | SCH | Fresh schema; the anon key | Request `tower.config` through PostgREST as anon and as authenticated | No row is returned to either role |
| TC-219-15 | S-219-AC-6 | L2.5 | pos | SCH | Fresh schema | Query `pg_class` and `pg_policies` for the eight tables | `relrowsecurity` is true and the policy count is zero for each |
| TC-219-16 | S-219-AC-6 | L2.5 | neg | RLS | Fresh schema; one row in each tower table | Run the unchanged `rls-deny-all` suite; confirm its enumerated list contains the eight names; `git diff` on the file is empty | anon select returns no row and anon insert is refused on all eight. The test file has no diff |
| TC-219-17 | S-219-AC-7 | L1 | neg | REVIEW | The story's migration files | Scan the new SQL files for `alter table`, `drop`, `create policy`, `alter publication` naming a non-tower object | No match. Every created object is `tower_*` in `public` or lives in the `tower` schema |
| TC-219-18 | S-219-AC-7 | L2.5 | pos | REVIEW | Branch with the migrations applied locally | Run the full existing integration suite; review the diff of `panel/lib/supabase/types.ts` | Every pre-existing suite is green. The types diff only adds tower entries |

### 3.2 S-220 — Token and repository lifecycle (#488)

| ID | ACs | Layer | Type | File | Preconditions | Steps / input | Expected result |
| --- | --- | --- | --- | --- | --- | --- | --- |
| TC-220-01 | S-220-AC-1 | L1 | pos | TOK | None | Call `generateTowerToken()` | The token matches `^twr_[a-z2-7]{12}\.[A-Za-z0-9_-]{43}$`. The returned hash is 32 bytes and equals SHA-256 of the 43-character secret |
| TC-220-02 | S-220-AC-1 | L1 | edge | TOK | None | Generate 1,000 tokens | 1,000 distinct public ids and 1,000 distinct secrets. No returned value other than the token contains the secret |
| TC-220-03 | S-220-AC-1, S-220-AC-8 | L2.5 | sec | REP | A repository registered through `registerTowerRepository` | Read every column of every `tower_*` row as text | No column contains the plain token or the secret. `secret_hash` equals SHA-256 of the secret |
| TC-220-04 | S-220-AC-2 | L2.5 | pos | REP | A registered repository and its plain token | `verifyTowerToken("Bearer <token>")` | Returns that repository's id |
| TC-220-05 | S-220-AC-2 | L1 | sec | TOK | Injected lookup with one active row and one revoked row | Verify with: no header; empty header; malformed header; unknown public id; right id and wrong secret; revoked token with the right secret | All six return a deep-equal negative value. None throws. None returns a repository id |
| TC-220-06 | S-220-AC-2 | L1 | edge | TOK | Injected lookup that records calls | Headers: leading and trailing whitespace; `Basic …`; prefix `twx_`; two dots; uppercase public id; 42- and 44-character secret; trailing newline; a 10 KB header | Each returns the negative value. The lookup is not called for any of them (§7 step 1) |
| TC-220-07 | S-220-AC-3 | L1 | pos | TOK | Spy on `timingSafeEqual`; lookup returns an active row | Verify once with the right secret and once with a wrong secret | The spy is called exactly once per verification, with two 32-byte buffers |
| TC-220-08 | S-220-AC-3 | L1 | sec | TOK | Spy on `timingSafeEqual`; lookup returns no row | Verify with a well-formed token whose public id is unknown | The lookup is called once. The spy is called exactly once against a fixed 32-byte dummy hash. The result is the negative value |
| TC-220-09 | S-220-AC-4 | L2.5 | pos | REP | Empty tower tables | `registerTowerRepository("llipe/riel")` | One repository row, one active token row, one change-marker row. The returned token verifies to the new repository id |
| TC-220-10 | S-220-AC-4 | L2.5 | neg | REP | `llipe/riel` registered | Register `llipe/riel` again | Returns `already_registered`. Row counts are unchanged. The first token still verifies |
| TC-220-11 | S-220-AC-4 | L2.5 | neg | REP | Empty tower tables | Register `llipe`, `llipe/riel/x`, `llipe/ri el`, the empty string, a 500-character name | Each returns `invalid_name`. No row is created. Uppercase input is covered by A-18 and is not asserted here |
| TC-220-12 | S-220-AC-4 | L2.5 | edge | REP | Empty tower tables | Two `registerTowerRepository("llipe/riel")` calls started together | Exactly one returns a token and the other returns `already_registered`. One repository, one active token |
| TC-220-13 | S-220-AC-5 | L2.5 | pos | REP | A registered repository with token T1 | `rotateTowerToken(id)` returns T2 | T1 no longer verifies. T2 verifies. Exactly one active token. T1's row has `revoked_at` set |
| TC-220-14 | S-220-AC-5 | L2.5 | edge | REP | A registered repository | Rotate twice in sequence; then start two rotations together | After the sequence only the last token verifies. After the concurrent pair exactly one token is active and neither call leaves zero or two active tokens |
| TC-220-15 | S-220-AC-5 | L2.5 | neg | REP | Two registered repositories A and B | Rotate A | B's token still verifies and its token row is unchanged |
| TC-220-16 | S-220-AC-6 | L2.5 | pos | REP | A registered repository with data from one applied snapshot | `revokeTowerToken(id)` | Zero active tokens. The old token does not verify. The repository row and its PRDs, waves and issues remain |
| TC-220-17 | S-220-AC-6 | L2.5 | pos | REP | Two repositories, each with a row in every child table | `removeTowerRepository(A)` | A and every row under it are gone. B and its rows are untouched |
| TC-220-18 | S-220-AC-6 | L2.5 | neg | REP | Repository A removed in TC-220-17 | Verify A's old token; call `removeTowerRepository` and `revokeTowerToken` with an unknown id | The token does not verify. Each call returns a typed result and does not throw. The result of revoking with no active token is open (A-19) |
| TC-220-19 | S-220-AC-7 | L2.5 | pos | REP | A registered repository | Set the threshold to 1, 24, 720, then null | Each is stored. Null clears the column |
| TC-220-20 | S-220-AC-7 | L2.5 | neg | REP | Threshold stored as 48 | Set 0, 721, -1, 1.5, `"24"`, `NaN` | Each is rejected with a typed error. The stored value stays 48 |
| TC-220-21 | S-220-AC-8 | L1 | sec | TOK | Spies on every `console` method and on `process.stdout.write` and `process.stderr.write` | Run generate and every verify variant of TC-220-05 and TC-220-06 with a token carrying a unique marker string | No captured output contains the marker, the secret, the header or the hash in hex |
| TC-220-22 | S-220-AC-8 | L2.5 | sec | REP | The same spies; a lookup forced to fail | Run register, rotate, revoke, remove and a verification whose database call throws | No captured output and no thrown error message contains the token, the secret or the header |
| TC-220-23 | S-220-AC-8 | L2.5 | pos | REP | The same spies | Register a repository and verify its token successfully | Both succeed and the caller receives the token. Whatever is logged holds at most the repository id and the public id |

### 3.3 S-221 — Ingestion contract version 1 (#489)

| ID | ACs | Layer | Type | File | Preconditions | Steps / input | Expected result |
| --- | --- | --- | --- | --- | --- | --- | --- |
| TC-221-01 | S-221-AC-1 | L1 | pos | CON | None | Import the two name lists | Each has eight entries in the order of FR-19 and FR-17 |
| TC-221-02 | S-221-AC-1 | L1 | neg | CON | A valid snapshot fixture | Put the stage-only name `refine` under `steps`; put the step-only name `merged` under `stages` | Both are rejected with a path. `plan` and `build`, which exist in both lists, are accepted in both places |
| TC-221-03 | S-221-AC-2 | L1 | pos | CON | Every `valid-*.json` fixture; a fixed clock | `validatePush(fixture, clock)` | Each returns a normalized push. Validating the normalized push again succeeds and returns an equal value |
| TC-221-04 | S-221-AC-2 | L1 | neg | CON | Every `invalid-*.json` fixture | `validatePush(fixture, clock)` | Each returns at least one error with a non-empty `path` and a non-empty `message`, and no normalized push |
| TC-221-05 | S-221-AC-2 | L1 | sec | CON | Invalid fixtures in which every string value carries a unique marker and every number is a unique large value | Validate and collect all messages | No message contains a marker or one of the numbers. Whether a `path` may contain an input key is open (A-16) |
| TC-221-06 | S-221-AC-3 | L1 | neg | CON | A valid fixture | Set `contract_version` to 2, 0, `"1"`, null; remove it | Each is rejected. The result names the supported versions as `[1]` |
| TC-221-07 | S-221-AC-3 | L1 | neg | CON | A valid fixture | Remove `push_id`; set it to the empty string and to a non-UUID string | Missing is rejected with path `push_id`. The empty and non-UUID values are rejected too (assumption: the column is `uuid`) |
| TC-221-08 | S-221-AC-3 | L1 | neg | CON | Valid snapshot and event fixtures | `kind` set to `sync`; `event.kind` set to `issue_closed`; `event` missing on an event push | Each rejected with the path of the field |
| TC-221-09 | S-221-AC-3 | L1 | neg | CON | Valid fixtures | Step `deploy`; stage `release`; `result` `done`, in a snapshot cell and in `step_result` and `stage_result` events | Each rejected with a path to the cell or field |
| TC-221-10 | S-221-AC-3 | L1 | neg | CON | Valid fixtures | `result: skipped` with no `reason`, with null and with the empty string, in a snapshot cell and in a `step_result` event | Each rejected. The same cell with a reason is accepted |
| TC-221-11 | S-221-AC-3 | L1 | sec | CON | Clock fixed at T | `observed_at` = T + 5 min 1 s, in a snapshot cell, a wave stage and each event kind that carries it | Each rejected with a path |
| TC-221-12 | S-221-AC-3 | L1 | sec | CON | Valid fixtures | Title of 301 characters; reason of 1,001; block note of 1,001; evidence `ref` of 501 | Each rejected with a path. No message contains the string |
| TC-221-13 | S-221-AC-3 | L1 | pos | CON | Clock fixed at T | Title of 300, reason of 1,000, `ref` of 500; `observed_at` = T + 5 min exactly; `observed_at` ten years in the past | All accepted |
| TC-221-14 | S-221-AC-4 | L1 | pos | CON | Valid snapshot and event fixtures | Add unknown fields at the top level and inside `event` | Accepted. The unknown fields are absent from the normalized push |
| TC-221-15 | S-221-AC-4 | L1 | neg | CON | An invalid fixture; a valid fixture | Add unknown fields to the invalid fixture; add keys `__proto__` and `constructor` to the valid one | The invalid fixture is still rejected. The prototype of the normalized push and of `Object` is unchanged |
| TC-221-16 | S-221-AC-5 | L1 | pos | CON | One fixture per event kind | Validate `step_result`, `stage_result`, `block_raised`, `block_cleared`, `pull_request_linked`, `changes_requested`, `session_ended` with `usage` | All seven accepted. `workflow_agent` and `evidence` are accepted on each |
| TC-221-17 | S-221-AC-5 | L1 | pos | CON | Snapshot fixtures | Snapshot with `lanes.status` `ok`; with `unreadable`; with no `lanes` | All three accepted. The `lanes` block is kept in the normalized push |
| TC-221-18 | S-221-AC-5 | L1 | neg | CON | The seven event fixtures | Remove each required field of the §6.1 table in turn; `session_ended` with neither `issue_number` nor `prd_slug` plus `wave_key`; with `prd_slug` only; `lanes.status` `broken` | Each rejected with a path to the missing or wrong field |
| TC-221-19 | S-221-AC-6 | L1 | pos | CON | The contract document and the fixtures directory | Parse the document | Every JSON example equals a fixture file, and every fixture is referenced. The text names both push kinds, the seven event kinds and the codes 202, 200, 401, 403, 413, 422, 429, 500 |
| TC-221-20 | S-221-AC-6 | L1 | neg | CON | The same | Run each example of the document through `validatePush` | An example presented as valid is accepted and one presented as invalid is rejected. An example that matches no fixture fails the test |
| TC-221-21 | S-221-AC-6 | Manual | pos | REVIEW | The contract document | A person who has not read the panel code reads it against the fixtures | They can state the request, both kinds, every event kind and every response without opening the code. The read-through is recorded in the PR |
| TC-221-22 | S-221-AC-7 | L1 | neg | CON | A snapshot with 50 independent violations | Validate | Exactly 20 errors |
| TC-221-23 | S-221-AC-7 | L1 | pos | CON | Snapshots with 1, 20 and 21 violations; a valid one | Validate each | 1, 20 and 20 errors; no error for the valid one |
| TC-221-24 | S-221-AC-2 | L1 | edge | CON | Built inputs | An empty snapshot (no PRDs, no issues); an issue with null `prd_slug` and `wave_key`; a cell with no `evidence`; a pull request whose `url` is not on GitHub | All accepted |
| TC-221-25 | S-221-AC-3 | L1 | edge | CON | A generated 1,000-issue snapshot | Serialize and validate | The serialized size is under 1,048,576 bytes and it is accepted. The duration is reported, not asserted |

### 3.4 S-222 — `tower_apply_push` (#490)

All cases call the function with the service-role client or through `withDb`, on a repository created
for the case. "Digest" means every column of every `tower_*` row of the repository, read in a stable
order.

| ID | ACs | Layer | Type | File | Preconditions | Steps / input | Expected result |
| --- | --- | --- | --- | --- | --- | --- | --- |
| TC-222-01 | S-222-AC-1 | L2.5 | pos | APP | A snapshot P applied once | Apply P again | Returns `duplicate`. The digest, including the marker `seq` and `last_push_received_at`, is identical |
| TC-222-02 | S-222-AC-1 | L2.5 | neg | APP | An event push E applied once on a known issue | Apply E again, three times | `duplicate` each time. One `tower_events` row. `event_count` and `rework_count` unchanged |
| TC-222-03 | S-222-AC-1 | L2.5 | edge | APP | Repositories A and B; push P applied to A | Apply a push with the same `push_id` to B; apply to A a push with the same `push_id` and different content | B returns `accepted`. A returns `duplicate` and keeps the first content |
| TC-222-04 | S-222-AC-2 | L2.5 | pos | APP | Cell `build` stored as `in_progress` at t1 | Apply a snapshot with `build` `passed` at t2 > t1, with a different evidence and branch | The cell holds result, `observed_at`, reason, evidence and branch of the incoming value. Its `received_at` lies between two database clock reads taken around the call |
| TC-222-05 | S-222-AC-2 | L2.5 | neg | APP | Cell `build` stored as `passed` at t2 | Apply `build` `in_progress` at t1 < t2, by snapshot and by `step_result` event | The cell is unchanged in every field. Both pushes return `accepted` |
| TC-222-06 | S-222-AC-2 | L2.5 | edge | APP | Cell stored as `passed` at t1 | Apply `failed` at exactly t1, by snapshot and by event | The stored cell is kept (a tie keeps the stored value) |
| TC-222-07 | S-222-AC-2 | L2.5 | edge | APP | Cell stored as `passed` at t1; a wave stage stored at t1 | Apply `failed` at t1 + 1 ms; apply a `stage_result` newer by 1 ms; apply a snapshot that omits the stored cell's key | The 1 ms newer values replace. The omitted key is not erased |
| TC-222-08 | S-222-AC-3 | L2.5 | pos | APP | Empty repository | Apply snapshot from branch X with `quality_gates` `failed` at t1, then from branch Y with `passed` at t2 > t1 | The cell is `passed` at t2 with branch Y |
| TC-222-09 | S-222-AC-3 | L2.5 | neg | APP | Empty repository | Apply the same two snapshots in the opposite order | The cell is `passed` at t2 with branch Y, identical to TC-222-08 |
| TC-222-10 | S-222-AC-3 | L2.5 | edge | APP | Snapshot from branch X with issues 1 and 2 | Apply a snapshot from branch Y that contains only issue 2 | Issue 1 keeps every cell and has `removed_at` null |
| TC-222-11 | S-222-AC-4 | L2.5 | neg | APP | A default-branch snapshot with PRD P, wave W, issues 1 and 2 | Apply a non-default snapshot that contains none of them | `removed_at` is null on P, W and both issues |
| TC-222-12 | S-222-AC-4 | L2.5 | pos | APP | A default-branch snapshot with PRD P, wave W, issues 1 and 2 | Apply a default-branch snapshot with P, W and issue 1 only; then one with no PRD and no issue | After the first, issue 2 has `removed_at` set and the rest do not. After the second, P, W and issue 1 are removed too. No row is deleted |
| TC-222-13 | S-222-AC-4 | L2.5 | neg | APP | Issue 7 and wave W2 seen only in a non-default snapshot | Apply a default-branch snapshot that contains neither | Both keep `removed_at` null and `seen_on_default` false |
| TC-222-14 | S-222-AC-4 | L2.5 | pos | APP | Issue 2 removed as in TC-222-12 | Apply a default-branch snapshot that contains issue 2 | `removed_at` is cleared. Its cells and summary are as before removal, merged with the new content |
| TC-222-15 | S-222-AC-4 | L2.5 | edge | APP | Default snapshot D1 (observed t1) contains issue 2; default snapshot D2 (observed t2 > t1) does not | Apply D2 then D1; separately apply D1 then D2 | Open (A-01). Until decided, assert only I-5 in both orders: issue 2's row exists with its cells. The `removed_at` values of the two orders are recorded in the PR |
| TC-222-16 | S-222-AC-5 | L2.5 | pos | APP | A repository that has never seen issue 912 | Apply a `step_result` event for 912; then a snapshot containing 912 without that step | After the event: one `tower_events` row with `placed` false, no issue row, `placed_events` 0. After the snapshot: `placed` true, the step cell holds the event's result, `event_count` 1, and the response reports `placed_events` 1 |
| TC-222-17 | S-222-AC-5 | L2.5 | neg | APP | The unplaced event of TC-222-16 | Apply a snapshot without 912; apply a snapshot containing 912 to a different repository | The event stays `placed` false both times |
| TC-222-18 | S-222-AC-5 | L2.5 | edge | APP | Two unplaced `step_result` events for the same step of 912, observed t1 and t2, delivered newest first | Apply a snapshot whose own cell for that step is observed t3 > t2; repeat with a snapshot cell observed t0 < t1 | With t3 the snapshot's cell is kept. With t0 the t2 event wins. Both events end `placed` true and `event_count` is 2 |
| TC-222-19 | S-222-AC-5 | L2.5 | edge | APP | An unplaced `stage_result` for an unknown wave; an unplaced `session_ended` for it | Apply a snapshot containing the PRD and the wave | Both events are placed. The stage cell holds the event's result |
| TC-222-20 | S-222-AC-6 | L2.5 | pos | APP | An issue with `quality_gates` `in_progress` | Apply `quality_gates` `failed` at t1; then a snapshot with `fidelity_audit` observed t2 and `drift_findings` 2 | `rework_count` is 2. `rework_keys` holds one `gate:` key and one `audit:` key (PRD AC-13) |
| TC-222-21 | S-222-AC-6 | L2.5 | pos | APP | The issue of TC-222-20 | Apply a `changes_requested` event with pull request 915 and `review_id` r1; apply `coverage_gate` `failed` | `rework_count` is 4. Keys include `review:915:r1` and a second `gate:` key |
| TC-222-22 | S-222-AC-6 | L2.5 | neg | APP | The issue of TC-222-21 | Re-send each of the four observations with a new `push_id` and unchanged content, by snapshot and by event | `rework_count` stays 4 and `rework_keys` is unchanged |
| TC-222-23 | S-222-AC-6 | L2.5 | edge | APP | A fresh issue | `quality_gates`: `failed` t1, `in_progress` t2, `failed` t3; then `failed` t4 with no result in between | Count is 2 after t3 and still 2 after t4 (no entry into `failed`) |
| TC-222-24 | S-222-AC-6 | L2.5 | neg | APP | A fresh issue | `build` `failed`; `fidelity_audit` with `drift_findings` 0; `quality_gates` `passed` twice at different times | `rework_count` is 0 |
| TC-222-25 | S-222-AC-7 | L2.5 | pos | APP | A known issue | `block_raised` with `on_owner` true at t1; `block_cleared` at t1 + 600 s | `waiting_seconds` 600, `waiting_reported` true, `blocked_on_owner_since` null |
| TC-222-26 | S-222-AC-7 | L2.5 | neg | APP | A known issue with events but no block | Read the issue; then apply `block_raised` with `on_owner` false | `waiting_reported` is false before and after. No interval is opened |
| TC-222-27 | S-222-AC-7 | L2.5 | edge | APP | A known issue | Raise at t1, raise again at t2, clear at t3; then clear again; then raise at t4 and clear at t5 | `blocked_on_owner_since` stays t1 after the second raise. The second clear changes nothing. The final `waiting_seconds` is (t3 − t1) + (t5 − t4) |
| TC-222-28 | S-222-AC-7 | L2.5 | edge | APP | A known issue | Apply a snapshot with `blocked_on_owner.since` t1; apply `block_cleared` at t2; then deliver a `block_cleared` observed before its `block_raised` | The snapshot opens the interval and sets `waiting_reported`. The event closes it with t2 − t1. The out-of-order pair's expected value is open (A-03); assert only that `waiting_seconds` is never negative |
| TC-222-29 | S-222-AC-8 | L2.5 | pos | APP | A fresh issue | Apply cells observed t3 and t5, then an event observed t1 | `first_observed_at` is t1 |
| TC-222-30 | S-222-AC-8 | L2.5 | pos | APP | A fresh issue | Apply `shipped` `in_progress` at t1, then `shipped` `passed` at t2 | `shipped_at` is null after the first and t2 after the second |
| TC-222-31 | S-222-AC-8 | L2.5 | neg | APP | A known issue 5 and an unknown issue 6 | Apply three events for 5 from workflow agents `developer`, `verifier`, `developer`, and two events for 6 | Issue 5 has `event_count` 3 and `workflow_agents` equal to the set `developer`, `verifier`. The unplaced events are counted nowhere |
| TC-222-32 | S-222-AC-8 | L2.5 | edge | APP | A known issue with no `session_ended` | Read; apply two `session_ended` events with different models; apply a wave-level `session_ended` | `tokens_total` and `models` are null first, not 0 and not empty. Then `tokens_total` is the sum of both usages and `models` holds both. The wave-level event changes no issue. Whether the total is input plus output is an assumption (A-14) |
| TC-222-33 | S-222-AC-9 | L2.5 | pos | APP | A repository with marker `seq` n | Apply one snapshot, then one event | `seq` is n + 2. `last_push_outcome` is `accepted`. `last_push_received_at` lies between database clock reads around each call, even when `sent_at` is a year old |
| TC-222-34 | S-222-AC-9 | L2.5 | neg | APP | Repositories A and B | Apply a push to A; apply a duplicate to A | B's marker and `last_push_*` never change. The duplicate leaves A's `seq` and `last_push_received_at` unchanged |
| TC-222-35 | S-222-AC-10 | L2.5 | sec | DEF | Fresh schema; anon and authenticated keys | `has_function_privilege` for the three roles; call the RPC through PostgREST as anon and as authenticated; run the unchanged `definer-grants` suite | Execute is true for `service_role` only. Both PostgREST calls are refused and write nothing. The suite lists the function and passes |
| TC-222-36 | S-222-AC-10 | L2.5 | sec | APP | Repositories A and B, both registered | Call the function with A's id and a payload whose `repository` is B's name | Every row written belongs to A. B has no new row and its marker is unchanged |
| TC-222-37 | S-222-AC-10 | L2.5 | pos | APP | Repository A | Call with A's id and a payload naming A; call with a random unknown id | The first is `accepted`. The second raises an error and writes no row |
| TC-222-38 | S-222-AC-11 | L2.5 | pos | APP | Repository A; two snapshots with different `push_id` and distinct observed times, on two connections | Start both calls together | Both return `accepted`. `seq` rose by 2. Cells equal those of applying the two in sequence on a fresh repository |
| TC-222-39 | S-222-AC-11 | L2.5 | edge | APP | Repository A; one push on two connections | Start both calls together, 20 repetitions | Each repetition: one `accepted`, one `duplicate`, `seq` + 1, one `tower_pushes` row |
| TC-222-40 | S-222-AC-11 | L2.5 | edge | APP | Repositories A and B; a third connection holds `select … for update` on A's row | Apply a push to B, then to A, then release the lock | B completes while the lock is held. A's call waits and completes after the release |
| TC-222-41 | S-222-AC-11 | L2.5 | neg | APP | Repository A | Call the function directly with a payload that fails inside the merge (a cell with `result` `done`) | The call errors. No row of any tower table changed, including `tower_pushes`. The same `push_id` with a valid payload is then `accepted` (§13) |

### 3.5 S-223 — `POST /api/tower/ingest` (#491)

L2.5 cases import the route handler and call it with a `Request`, as `webhook-route.test.ts` does.
L1 cases call `ingest.ts` with injected verify, read-body, validate and apply functions.

| ID | ACs | Layer | Type | File | Preconditions | Steps / input | Expected result |
| --- | --- | --- | --- | --- | --- | --- | --- |
| TC-223-01 | S-223-AC-1 | L2.5 | pos | ING-I | A registered repository and its token | POST the valid snapshot fixture, then a valid event fixture | 202 each, body `status` `accepted` with a numeric `placed_events`. `last_push_received_at` is set and `last_push_outcome` is `accepted` |
| TC-223-02 | S-223-AC-1 | L2.5 | neg | ING-I | TC-223-01 done | POST the same snapshot again | 200, body exactly `{ "status": "duplicate" }`. The digest is unchanged |
| TC-223-03 | S-223-AC-1 | L1 | edge | ING-U | Injected apply that throws once, then succeeds | Send the same push twice | 500 then 202. The first attempt left nothing recorded |
| TC-223-04 | S-223-AC-2 | L2.5 | sec | ING-I | One repository with an active token, one with a revoked token; a valid body | POST with: no `Authorization`; `Bearer x`; a well-formed token with an unknown id; the revoked token; the active id with a wrong secret | Five 401 responses with byte-identical bodies `{ "status": "unauthorized" }` and the same header names. No row changed in any tower table, including `last_push_*` and the marker |
| TC-223-05 | S-223-AC-2 | L2.5 | pos | ING-I | The active token of TC-223-04 | POST the same body with the valid token | 202 (control: the body was acceptable, so the 401s came from the token) |
| TC-223-06 | S-223-AC-3 | L2.5 | sec | ING-I | Repositories A and B registered; A's token | POST a valid snapshot whose `repository` is B | 403, body `{ "status": "forbidden" }`. B has no new row of any kind. A has no PRD, wave, issue or event row |
| TC-223-07 | S-223-AC-3 | L2.5 | edge | ING-I | A's token | POST with `repository` set to an unregistered name | 403. No repository row is created for that name |
| TC-223-23 | S-223-AC-3 | L2.5 | pos | ING-I | Repositories A and B registered; A's token | POST the snapshot of TC-223-06 with `repository` set to A's own name | 202. Rows exist under A only (control: the 403 came from the name, not from the body) |
| TC-223-08 | S-223-AC-4 | L2.5 | neg | ING-I | A valid token | POST a body of 1,048,577 bytes; POST a valid snapshot padded with whitespace to exactly 1,048,576 bytes | 413 with `{ "status": "too_large", "limit_bytes": 1048576 }` for the first. 202 for the second |
| TC-223-09 | S-223-AC-4 | L1 | sec | ING-U | A stream of 64 KiB chunks totalling 5 MiB that counts the chunks pulled; no `Content-Length` | Run the pipeline with a valid token; repeat with a `Content-Length` of 100 on the same stream | 413 both times. At most 17 chunks are pulled and the stream is cancelled. The whole body is never held (A-20 defines "not buffered whole" this way) |
| TC-223-10 | S-223-AC-4 | L2.5 | neg | ING-I | A valid token | POST: the text `{`; an empty body; `[]`; `null`; a fixture with an unknown `event.kind`; a fixture with `contract_version` 2 | 422 each. Every body has `status` `invalid`, `supported_versions` `[1]` and an `errors` array of 1 to 20 entries with `path` and `message` |
| TC-223-11 | S-223-AC-4 | L2.5 | pos | ING-I | A valid token | POST a 900 KiB valid snapshot | 202 |
| TC-223-12 | S-223-AC-5 | L1 | sec | ING-U | A request whose body stream records any read; verify returns the negative value | Run the pipeline for each 401 variant | 401. The body stream was never read and `bodyUsed` is false |
| TC-223-13 | S-223-AC-5 | L1 | pos | ING-U | Injected functions that record their call order | Run a valid push | The order is verify, read body, validate, apply. Each is called once |
| TC-223-14 | S-223-AC-5 | L1 | neg | ING-U | Verify returns the negative value | Send an oversized body; send invalid JSON | 401 both times, never 413 or 422. Read-body, validate and apply were not called |
| TC-223-15 | S-223-AC-6 | L2.5 | pos | ING-I | A valid token; `last_push_outcome` is `accepted` | Send one 403, one 422 with a readable `push_id`, one 413 | One `tower_pushes` row each, with outcome `rejected_repository`, `rejected_payload`, `rejected_size`. `last_push_outcome` is `rejected` after each. The `push_id` stored for the 413 and for unparseable bodies is open (A-02) |
| TC-223-16 | S-223-AC-6 | L2.5 | neg | ING-I | TC-223-15 done | Send a 401; then a valid push | The 401 adds no row and leaves `last_push_outcome` `rejected`. The valid push sets it to `accepted`. None of the rejections created a PRD, wave, issue or event row |
| TC-223-17 | S-223-AC-7 | L1 | pos | POL | None | `classifyRoute("/api/tower/ingest")` | `internal` |
| TC-223-18 | S-223-AC-7 | L1 | sec | POL | None | Classify `/api/tower`, `/api/tower/ingest/x`, `/api/tower/ingestx`, `/api/tower/repositories`, `/api/tower/repositories/o/n`, `/api/tower/stream`, `/API/tower/ingest`, `/tower` | `api` for every `/api/tower` path listed. `ui` for the last two |
| TC-223-19 | S-223-AC-7 | L2 | pos | GATE-C | The proxy with no session cookie | POST `/api/tower/ingest`; GET `/api/tower/repositories` | The proxy lets the POST through to the handler. The GET gets 401 with `{ "error": "UNAUTHORIZED" }` |
| TC-223-20 | S-223-AC-8 | L1 | neg | ING-U | Apply throws `new TypeError("boom MARKER")`; spies on `console` | Send a valid push | 500 with body exactly `{ "status": "error" }`. The log contains `TypeError` and does not contain `boom`, `MARKER` or a stack |
| TC-223-21 | S-223-AC-8 | L1 | sec | ING-U | Spies on `console` and both process streams; a token and body strings carrying unique markers | Drive every response path: 202, 200, 401 (five variants), 403, 413, 422, 500 | No captured output and no response body contains a marker, the token, the secret or the header |
| TC-223-22 | S-223-AC-8 | L1 | pos | ING-U | The same spies | Send a 403 and a 422 | The log line holds the outcome, the repository id and the `push_id`, and nothing else from the request (§12) |

### 3.6 S-224 — Retention (#492)

Rows are dated by writing `shipped_at`, `observed_at` and `received_at` relative to the database's
`now()` in set-up. No case waits for time to pass.

| ID | ACs | Layer | Type | File | Preconditions | Steps / input | Expected result |
| --- | --- | --- | --- | --- | --- | --- | --- |
| TC-224-01 | S-224-AC-1 | L2.5 | pos | PRU | Issue 1 shipped 91 days ago with 5 placed events and a full summary | Record its row and its entry in `buildRepositoryTree(…, "all")`; run `tower.prune()` | Its events are gone. `summary_final_at` is set. Every summary column and `steps` are equal to the record. The tree entry is deep-equal (PRD AC-19) |
| TC-224-02 | S-224-AC-1 | L2.5 | neg | PRU | TC-224-01 plus a second repository with a recently shipped issue and an open issue | Run `tower.prune()` | Only issue 1's events are deleted. No PRD, wave or issue row is deleted anywhere |
| TC-224-03 | S-224-AC-2 | L2.5 | pos | PRU | An open issue with events 400 days old; an issue shipped 89 days ago with events 400 days old | Run `tower.prune()` | All events are kept. `summary_final_at` stays null on both |
| TC-224-04 | S-224-AC-2 | L2.5 | edge | PRU | Issues shipped 90 days minus 1 minute ago and 90 days plus 1 minute ago | Run `tower.prune()` | The first keeps its events and the second loses them. The exact 90-day instant is open (A-11) |
| TC-224-05 | S-224-AC-3 | L2.5 | pos | PRU | Wave W1 shipped 91 days ago and wave W2 open, each with wave-level `session_ended` events (no `issue_number`) | Run `tower.prune()` | W1's wave-level events are deleted. W2's are kept |
| TC-224-06 | S-224-AC-3 | L2.5 | neg | PRU | Unplaced events for an issue and a wave that never appeared, 400 days old | Run `tower.prune()` | They are kept |
| TC-224-07 | S-224-AC-4 | L2.5 | pos | PRU | `tower_pushes` rows received 31 days ago and 29 days ago, one of each outcome | Run `tower.prune()` | Every 31-day row is deleted and every 29-day row is kept, whatever the outcome |
| TC-224-08 | S-224-AC-4 | L2.5 | neg | PRU | TC-224-07 set-up with issues and summaries present | Run `tower.prune()` | No issue, wave, PRD or repository row changes because a push row was deleted |
| TC-224-09 | S-224-AC-5 | L2.5 | pos | PRU | Fresh `supabase db reset` | Select from `cron.job` where `jobname = 'tower-prune'` | Exactly one row, schedule `37 3 * * *`, command calling `tower.prune()` |
| TC-224-10 | S-224-AC-5 | L2.5 | neg | PRU | The set-up of TC-224-01 | Run `tower.prune()` twice and take the digest after each | The two digests are equal, including `summary_final_at` |
| TC-224-11 | S-224-AC-5 | L2.5 | sec | DEF | Fresh schema | Check execute privilege on `tower.prune()` for anon, authenticated and `service_role` | anon and authenticated cannot execute it (§12) |
| TC-224-12 | S-224-AC-6 | L2.5 | pos | PRU | An issue shipped 11 days ago; a push row 2 days old | Set `event_retention_days` to 10 and `push_retention_days` to 1; run `tower.prune()` | The issue's events and the push row are deleted. No migration ran |
| TC-224-13 | S-224-AC-6 | L2.5 | neg | PRU | An issue shipped 50 days ago | Delete the `event_retention_days` key; run; then set the key to `abc` and run | With the key missing the default 90 applies and the events are kept. With a non-numeric value the function must not delete them either (assumption: fail safe) |

### 3.7 S-225 — Read contract version 1 (#493)

| ID | ACs | Layer | Type | File | Preconditions | Steps / input | Expected result |
| --- | --- | --- | --- | --- | --- | --- | --- |
| TC-225-01 | S-225-AC-1 | L1 | pos | RD-U | The row fixture and the `read-*.json` fixtures; a fixed `now` | Call both functions | The outputs deep-equal the fixtures. Every field of the §6.2 types is present on every object |
| TC-225-02 | S-225-AC-1 | L1 | neg | RD-U | Deep-frozen input rows; fake timers | Call each function twice with the same arguments while the system clock is moved between calls | Both results are deep-equal. No input was mutated. Nothing was thrown by the frozen input |
| TC-225-03 | S-225-AC-1 | L1 | edge | RD-U | No rows; one repository row that never pushed | Call both functions | An empty list for no rows. For the second: `last_push_received_at` null, `last_push_outcome` null, `stale` false, counts 0, `prds` and `no_prd_issues` empty |
| TC-225-04 | S-225-AC-2 | L1 | pos | RD-U | An issue with eight `passed` cells at known times, one of them `skipped` | Build the tree | `step_gaps_seconds` has seven entries, each the difference in seconds between neighbours, with the `skipped` cell used like a `passed` one |
| TC-225-05 | S-225-AC-2 | L1 | neg | RD-U | Issues where one neighbour is missing, `failed`, `in_progress` or `pending`; one where the later cell is older; one where both have the same time | Build the tree | `null` for the missing, non-terminal and negative pairs. `0` for the equal-time pair, not `null` |
| TC-225-06 | S-225-AC-3 | L1 | pos | RD-U | An issue with no wave and no PRD; an issue in a wave | Build the tree | The first has `in_wave` false and appears only under `no_prd_issues`. The second has `in_wave` true and appears only under its wave |
| TC-225-07 | S-225-AC-3 | L1 | edge | RD-U | An issue with a PRD and no wave | Build the tree | `in_wave` is false. Where the issue appears is open (A-12): the shape has no place for it. Assert only that it appears exactly once |
| TC-225-08 | S-225-AC-4 | L1 | pos | RD-U | An issue with two cells, `waiting_reported` false, and null `subtasks_*`, `coverage_gate`, `drift_findings` | Build the tree and serialize it | The six missing step keys are present with value `null`. `waiting_seconds`, `subtasks`, `coverage_gate` and `drift_findings` are `null` in the JSON text (PRD AC-14) |
| TC-225-09 | S-225-AC-4 | L1 | neg | RD-U | An issue with `drift_findings` 0, `waiting_reported` true with `waiting_seconds` 0, subtasks 0 of 0 | Build the tree | `drift_findings` is 0, `waiting_seconds` is 0 and `subtasks` is `{ done: 0, total: 0 }`. A reported zero is not turned into `null` |
| TC-225-10 | S-225-AC-5 | L1 | pos | RD-U | Config default 24; `now` fixed | Open work with last push 25 hours ago and no override; the same with override 48; the same with override 12 and last push 13 hours ago | `stale` true with `threshold_source` `default` and `stale_threshold_hours` 24; false with `repository` and 48; true with `repository` and 12 (PRD AC-16) |
| TC-225-11 | S-225-AC-5 | L1 | neg | RD-U | The same config | All issues shipped and last push 30 days ago; open work and last push exactly 24 hours ago; open work and never pushed; the only open issue is removed | `stale` false in all four (PRD AC-17). One second past 24 hours is `stale` true |
| TC-225-12 | S-225-AC-6 | L1 | pos | RD-U | Window 14 days; issues open, shipped 13 days ago and shipped 15 days ago, in one wave | Build with `scope` `recent` | The open and the 13-day issues are returned. The 15-day issue is not. The wave and the PRD are kept |
| TC-225-13 | S-225-AC-6 | L1 | pos | RD-U | The same rows plus a removed issue | Build with `scope` `all` | All three issues are returned with their times and counts. The removed one is absent (PRD AC-18) |
| TC-225-14 | S-225-AC-6 | L1 | edge | RD-U | A wave and a PRD whose every issue shipped 20 days ago; a PRD with no wave; a wave with no issue and no `shipped_at`; a removed wave | Build with `recent` and with `all` | Under `recent` the fully old wave and PRD are absent and the two empty open containers are kept. Under `all` everything but the removed wave is present |
| TC-225-15 | S-225-AC-7 | L1 | pos | RD-U | A PRD with two waves, one shipped; issues with known rework, pull requests and blocks | Build the tree | `waves_shipped`, `waves_total`, `issues_shipped`, `issues_total`, `blocked_count`, `rework_total`, `pull_request_total` equal a hand count over the children. `oldest_open_issue_since` is the minimum `first_observed_at` of open issues |
| TC-225-16 | S-225-AC-7 | L1 | pos | RD-U | A wave with a `ship` cell `passed` and no `audit` key | Build the tree | `stages.ship` is the `passed` cell with its evidence. `stages.audit` is `null`. No other stage is filled in from the `ship` cell (PRD AC-10, BR-3) |
| TC-225-17 | S-225-AC-7 | L1 | neg | RD-U | The PRD of TC-225-15 with one removed issue and one removed wave; a wave with no issue | Build the tree | Removed children are in no count and no sum. The empty wave has totals 0 and `oldest_open_issue_since` null |
| TC-225-18 | S-225-AC-8 | L2.5 | pos | RD-I | A repository filled by real pushes through the ingest handler | Call both GET handlers | 200. Each body equals the module's output for the same rows and the same `now` |
| TC-225-19 | S-225-AC-8 | L2.5 | neg | RD-I | One registered repository that never pushed | GET the tree for an unregistered name; GET it for the registered one | 404 with a JSON `error` for the first. 200 with empty `prds` and `no_prd_issues` for the second |
| TC-225-20 | S-225-AC-8 | L2 | sec | GATE-C | The proxy | GET both read paths with no cookie; with only `Authorization: Bearer <valid tower token>` | 401 with `{ "error": "UNAUTHORIZED" }` in both cases, and the handler is not reached (PRD AC-23, FR-4) |
| TC-225-21 | S-225-AC-9 | L2.5 | pos | RD-I | 2,500 open issues inserted by SQL under one repository | GET the tree with `scope=all` | 2,500 issues, 2,500 distinct numbers, none missing |
| TC-225-22 | S-225-AC-9 | L2.5 | edge | RD-I | Repositories with 0, 999, 1,000, 1,001 and 2,000 issues | GET each tree | Each returns exactly its count with no duplicate |
| TC-225-23 | S-225-AC-9 | L1 | neg | RD-U | An injected page fetcher that returns pages of 1,000, 1,000 and 0 rows and counts calls | Run the paged read | It stops after the empty page, asks for consecutive ranges with a stable order, and returns 2,000 rows |
| TC-225-24 | S-225-AC-10 | L2.5 | pos | RD-I | The shared fixture's rows loaded into the database; `now` injected | Compare the module output, the endpoint body and the fixture file | The three are deep-equal after `generated_at` is set to the injected `now` |
| TC-225-25 | S-225-AC-10 | L1 | neg | RD-U | The read-contract document and the fixture | Parse the document | Every field name of the §6.2 types occurs in it. Its example equals the fixture. The fixture holds at least one `null` of each nullable kind, so the comparison of TC-225-24 cannot pass on a shape that drops nulls |

### 3.8 S-226 — Minimal `/tower` (#494)

| ID | ACs | Layer | Type | File | Preconditions | Steps / input | Expected result |
| --- | --- | --- | --- | --- | --- | --- | --- |
| TC-226-01 | S-226-AC-1 | L2 | pos | SB-C | The sidebar rendered | Find the entry named "Control Tower" | It is a link to `/tower`. It is marked current when the path is `/tower` |
| TC-226-02 | S-226-AC-1 | L2 | edge | SB-C | The sidebar rendered collapsed | Find the entry by its accessible name | It is still reachable by name and by keyboard |
| TC-226-03 | S-226-AC-2 | L2 | pos | UI-C | `RepositoryList` with two summaries from the read fixture | Render | Each row shows the name, the last-reported time, the last push outcome, and the accepted and rejected counts |
| TC-226-04 | S-226-AC-2 | L2 | neg | UI-C | A summary with `last_push_received_at` null; a summary whose name contains markup | Render | No time and no outcome is shown for the first, not an epoch date. The name is shown as text |
| SC-01 | S-226-AC-3 | E2E | pos | E2E | Logged in; no tower repository | Open `/tower`, register `e2e/riel` | A dialog shows a token matching the `twr_` format once, with the `dev-tasks tower login` line containing it. The list shows the repository |
| SC-02 | S-226-AC-3 | E2E | sec | E2E | SC-01 with the token captured | Close the dialog; reload; go back and forward; inspect the document, the responses of the reload, the URL and web storage | The token and its secret appear in none of them (PRD AC-1) |
| SC-03 | S-226-AC-3 | E2E | pos | E2E | The token captured in SC-01 | POST a valid snapshot to `/api/tower/ingest` with it; reload `/tower` | 202. The row shows a last-reported time and 1 accepted push |
| TC-226-05 | S-226-AC-4 | L1 | neg | UI-U | The client-side name check | Check `llipe/riel`, `llipe`, `a/b/c`, `a b/c`, the empty string | Only the first is valid. The verdict equals the server's for every input |
| SC-04 | S-226-AC-4 | E2E | neg | E2E | `e2e/riel` registered | Register `e2e/riel` again; register `not a name`; submit a new valid name twice quickly | "Already registered" and "invalid name" errors are shown and the list is unchanged. The double submit creates one repository |
| TC-226-06 | S-226-AC-4 | L2 | pos | UI-C | `RegisterRepositoryDialog` with an action that returns each typed result | Submit | `ok` opens the reveal. `already_registered` and `invalid_name` each show their own message and no reveal |
| TC-226-07 | S-226-AC-5 | L2 | pos | UI-C | `RepositorySettings` with spied actions | Click rotate, revoke and remove, and confirm each | Each action is called once, only after confirmation. The remove dialog lists what is deleted: the repository, its token and its reported data |
| TC-226-08 | S-226-AC-5 | L2 | neg | UI-C | The same | Click each and cancel | No action is called |
| SC-05 | S-226-AC-5 | E2E | pos | E2E | A registered repository with a captured token T1 | Rotate and confirm; push with T1, then with the new token; revoke and confirm; push again; remove and confirm | The new token is shown once. T1 gets 401 and the new token 202. After revoke the new token gets 401. After remove the row is gone |
| TC-226-09 | S-226-AC-6 | L1 | pos | UI-U | The threshold field logic | Summaries with source `default` and 24, and `repository` and 48; clear the field | "24 hours, default" and "48 hours, this repository". Clearing submits null |
| TC-226-10 | S-226-AC-6 | L1 | neg | UI-U | The same | Enter 0, 721, 1.5, `abc` | Each shows an error and submits nothing |
| SC-06 | S-226-AC-6 | E2E | edge | E2E | A registered repository | Set 48 and reload; clear it and reload | 48 with the repository source after the first reload. 24 with the default source after the second |
| TC-226-11 | S-226-AC-7 | L2 | pos | UI-C | The page body with no repository; with one repository that never pushed | Render | Both show an empty state naming the next CLI step. The page says the hierarchy arrives with the next wave |
| TC-226-12 | S-226-AC-7 | L2 | neg | UI-C | A repository with one accepted push | Render | No empty state for that repository. It is not shown as stale |
| SC-07 | S-226-AC-8 | E2E | sec | E2E | No session | Open `/tower` | The browser ends on `/login`. The response to `/tower` contains no repository name (PRD AC-23) |
| TC-226-13 | S-226-AC-8 | L1 | pos | POL | None | `classifyRoute("/tower")` and `classifyRoute("/tower/anything")` | `ui` for both |
| SC-08 | S-226-AC-2, S-226-AC-5 | E2E | edge | E2E | A registered repository; a 390-pixel-wide viewport | Open `/tower`; open the register dialog and rotate while the reveal dialog is open | The list and dialogs are usable without horizontal page scroll. The result of rotating with the reveal open is open (A-19) |

### 3.9 S-227 — Release-gate probes and runbook (#495)

| ID | ACs | Layer | Type | File | Preconditions | Steps / input | Expected result |
| --- | --- | --- | --- | --- | --- | --- | --- |
| TC-227-01 | S-227-AC-1 | Manual | pos | REVIEW | The panel running locally with the tower routes | Run `scripts/verify-panel-auth.sh` against it | Both new probes report 401 and the gate passes. The output is recorded in the PR |
| TC-227-02 | S-227-AC-1 | L1 | neg | PAC-CLI | A gate-input file in which the ingest probe is 200; another in which the read probe is 302 | Run the CLI on each | Exit code 1 each time, with a reason naming the probe |
| TC-227-03 | S-227-AC-1 | L1 | edge | REVIEW | The script source | Read the two new probe commands; run `shellcheck` | The ingest probe is a POST with no `Authorization` header. The read probe is a GET with no cookie. Neither needs a secret. `shellcheck` is clean |
| TC-227-04 | S-227-AC-2 | L1 | pos | PAC | A complete passing gate input with both tower probes at 401 | `evaluateAuthGate(input)` | `pass` true, no reason |
| TC-227-05 | S-227-AC-2 | L1 | sec | PAC | The passing input | For each tower probe in turn set status 200, 202, 302, 403, 404, 500, 503, null; set `{ error: "timeout" }`; remove the field | `pass` false every time, with one reason naming that probe. A missing field fails closed |
| TC-227-06 | S-227-AC-3 | L1 | pos | PAC | The passing input | Evaluate four inputs: both pass; ingest fails; read fails; both fail | One pass. Three failures, with one, one and two reasons |
| TC-227-07 | S-227-AC-3 | L1 | neg | REVIEW | `.github/workflows/ci.yml` | Find the step that runs the parser suite by name | The step still matches the test file names, so CI runs the new cases |
| TC-227-08 | S-227-AC-4 | Manual | pos | REVIEW | The runbook and a local panel | Follow each of the five procedures as written | Register, rotate and revoke work. The `curl` lines return 202, 202, 200 and, with a wrong token, 401. The counters match. The stale checklist names received time, threshold and open work |
| TC-227-09 | S-227-AC-4 | L1 | sec | REVIEW | The runbook text | Search it for a string in the `twr_` token format and for a bearer value | Only placeholders are present. No real token is in the file |
| TC-227-10 | S-227-AC-5 | L1 | pos | REVIEW | `docs/runbooks/README.md` | Find the link to `control-tower.md` | The link exists and its target file exists |
| TC-227-11 | S-227-AC-5 | L1 | neg | REVIEW | The runbook and the index | Resolve every relative link in both; compare the runbook with `runbook-template.md` | No dead link. The runbook has the template's required sections |

### 3.10 S-228 — Wave A live (#496): manual verification checklist

S-228 is an approval-gated `infra-engineer` pass. Nothing here is automated. Each item is a check
the operator performs and records under `infra/changes/<date>-control-tower-wave-a/`. A step that
changes the live system needs the owner's recorded approval first. Values recorded must never
include the plain token.

| ID | ACs | Layer | Type | File | Preconditions | Steps / input | Expected result |
| --- | --- | --- | --- | --- | --- | --- | --- |
| MV-228-01 | S-228-AC-1 | Manual | pos | LIVE | Read access to the hosted project | List extensions; confirm Realtime is enabled for the project | `pg_cron` is installed. Realtime is on. Both outputs are recorded |
| MV-228-02 | S-228-AC-1 | Manual | neg | LIVE | A written revert plan | Before any change, confirm the revert plan covers a migration push that fails midway, and that the owner has seen it | The plan is recorded before the push. If a pre-check fails the pass stops and reports; nothing is pushed |
| MV-228-03 | S-228-AC-1 | Manual | edge | LIVE | Migrations applied (after MV-228-04) | Check execute privilege on `tower_apply_push` and `tower.prune()` for `service_role`, anon and authenticated | `service_role` can execute both. anon and authenticated cannot. This check can only run after the push (A-21) |
| MV-228-04 | S-228-AC-2 | Manual | pos | LIVE | The owner's explicit approval, recorded with time | Push the Wave A migrations; list applied migrations; select `tower-prune` from `cron.job` | Every Wave A migration is listed as applied. `tower-prune` is listed once with schedule `37 3 * * *` |
| MV-228-05 | S-228-AC-2 | Manual | neg | LIVE | MV-228-04 done | Compare row counts or a schema dump of the pre-existing tables with the pre-push record; query a tower table with the anon key | Pre-existing tables are unchanged. The anon query returns nothing |
| MV-228-06 | S-228-AC-3 | Manual | pos | LIVE | The owner's approval for the deploy | Deploy the panel; run `scripts/verify-panel-auth.sh` against the live URL | The gate passes. The two tower probes show 401. The output is recorded |
| MV-228-07 | S-228-AC-3 | Manual | neg | LIVE | MV-228-06 done | Read the gate output for the ingest probe's response body, or repeat it with `curl` | The body is `{ "status": "unauthorized" }`, which shows the handler answered and not the session gate (A-13) |
| MV-228-08 | S-228-AC-4 | Manual | pos | LIVE | Logged in on the live panel | Register one repository; with its token send the runbook's snapshot, then its event, then the snapshot again | 202, 202 and 200, each recorded with status and body. The token is not recorded |
| MV-228-09 | S-228-AC-4 | Manual | sec | LIVE | MV-228-08 done | Send the snapshot with no header, with a wrong secret, and with the right token and another repository's name | 401, 401 with the same body, and 403. Fly logs for the period contain no token and no body |
| MV-228-10 | S-228-AC-5 | Manual | pos | LIVE | MV-228-08 and MV-228-09 done | Open `/tower` | The repository is listed with a last-reported time close to the pushes and counts of 2 accepted. The rejected count matches the outcome of A-02 and A-04 and is recorded as seen |
| MV-228-11 | S-228-AC-5 | Manual | neg | LIVE | A private browser window with no session | Open the live `/tower` and GET the live `/api/tower/repositories` | A redirect to `/login`, and 401 JSON |
| MV-228-12 | S-228-AC-6 | Manual | pos | LIVE | The wave's consolidated PR | Read the technical guidelines, `docs/roadmap.md` and the change record | The guidelines describe the ingest endpoint, the token model and the new tables. The Wave A roadmap row has the new status, issues and what is missing. The change record lists every live step with its approval and its revert. Which guidelines file name is written is open (A-25) |
| MV-228-13 | S-228-AC-6 | Manual | neg | LIVE | The same PR | Search the PR's changed files and the change record for the token format | No plain token is committed. The PR is a draft or ready PR for the owner; no agent merged to `main` |

## 4. Contract tests

Contract cases check the boundary only. Ingestion cases run over the HTTP handler against the real
database (ING-I) unless marked L1. Read cases compare against the shared fixture.

### 4.1 Ingestion contract version 1

| ID | ACs | Layer | Type | File | Preconditions | Steps / input | Expected result |
| --- | --- | --- | --- | --- | --- | --- | --- |
| CT-I-01 | S-223-AC-1, S-221-AC-2 | L2.5 | pos | ING-I | A valid token | POST every `valid-*.json` fixture with the repository name and a fresh `push_id` substituted | 202 for each, with exactly the keys `status` and `placed_events` |
| CT-I-02 | S-223-AC-4, S-221-AC-2 | L2.5 | neg | ING-I | A valid token | POST every `invalid-*.json` fixture | 422 for each, with exactly the keys `status`, `supported_versions`, `errors` |
| CT-I-03 | S-221-AC-5, S-223-AC-1 | L2.5 | pos | ING-I | A snapshot applied so the items exist | POST one event of each of the seven kinds | 202 each. One `tower_events` row per kind with that `kind` |
| CT-I-04 | S-223-AC-1 | L2.5 | pos | ING-I | One accepted push | Repeat it | 200 with exactly `{ "status": "duplicate" }` |
| CT-I-05 | S-223-AC-2 | L2.5 | sec | ING-I | None | POST with no header | 401 with exactly `{ "status": "unauthorized" }` and `content-type: application/json` |
| CT-I-06 | S-223-AC-3 | L2.5 | sec | ING-I | Two repositories | POST with A's token and B's name | 403 with exactly `{ "status": "forbidden" }` |
| CT-I-07 | S-223-AC-4 | L2.5 | neg | ING-I | A valid token | POST 1 MiB + 1 byte | 413 with exactly `{ "status": "too_large", "limit_bytes": 1048576 }` |
| CT-I-08 | S-223-AC-4, S-221-AC-3 | L2.5 | neg | ING-I | A valid token | POST `contract_version` 2, `"1"`, 0 and a push with none | 422 each, `supported_versions` `[1]`, an error whose path is `contract_version` (PRD AC-7) |
| CT-I-09 | S-221-AC-4, S-223-AC-1 | L2.5 | pos | ING-I | A valid token | POST a snapshot and an event with unknown top-level and event fields | 202. Stored rows are the same as without the unknown fields |
| CT-I-10 | S-223-AC-8 | L1 | neg | ING-U | Apply throws | POST a valid push | 500 with exactly `{ "status": "error" }` |
| CT-I-11 | S-223-AC-1 | L2.5 | edge | ING-I | A valid token | POST 50 valid pushes with distinct ids as fast as the test can | No response is 429 (reserved, D-28). All are 202 |
| CT-I-12 | S-221-AC-3, S-223-AC-4 | L2.5 | neg | ING-I | A valid token | Remove each envelope field in turn (`contract_version`, `push_id`, `repository`, `kind`, `branch`, `is_default_branch`, `sent_at`) | 422 with an error whose path names the field. `repository` and `sender` are treated as the validator decides; the precedence of 403 over 422 is open (A-07) |
| CT-I-13 | S-221-AC-7, S-223-AC-4 | L2.5 | edge | ING-I | A valid token | POST a snapshot with 50 violations | 422 with 20 errors. No error contains a value from the body |
| CT-I-14 | S-221-AC-6 | L1 | pos | CON | The contract document | Compare its response table with the bodies asserted in CT-I-01 to CT-I-10 | Every documented status and body matches the asserted one. No asserted status is undocumented |

### 4.2 Read contract version 1

| ID | ACs | Layer | Type | File | Preconditions | Steps / input | Expected result |
| --- | --- | --- | --- | --- | --- | --- | --- |
| CT-R-01 | S-225-AC-1, S-225-AC-10 | L1 | pos | RD-U | The row fixture | `buildRepositorySummaries` and `buildRepositoryTree` | Deep-equal to `read-*.json` |
| CT-R-02 | S-225-AC-8, S-225-AC-10 | L2.5 | pos | RD-I | The fixture rows in the database | GET both endpoints | The list body has exactly `read_contract_version` 1, `generated_at`, `repositories`. The tree body has exactly `read_contract_version` 1, `generated_at`, `repository`. Both equal the fixture |
| CT-R-03 | S-225-AC-4 | L1 | neg | RD-U | Any tree | Compare the key set of every object with the §6.2 type | Every declared key is present on every object, with `null` where unreported. No key is `undefined` and none is dropped by serialization |
| CT-R-04 | S-225-AC-6 | L2.5 | pos | RD-I | A repository with an issue shipped 15 days ago | GET with no `scope`, with `scope=recent`, with `scope=all` | No parameter equals `recent`. `all` includes the old issue. An unknown value such as `scope=x` is open (A-10) |
| CT-R-05 | S-225-AC-8 | L2.5 | neg | RD-I | None | GET an unregistered repository | 404 with a JSON body holding `error`, in the shape of the panel's other API routes |
| CT-R-06 | S-225-AC-1 | L1 | sec | RD-U | Rows with `tokens_total`, `models`, `lanes`, cell `branch` and cell `received_at` set | Build the tree | None of those values appears in the output (they are not part of version 1) |
| CT-R-07 | S-225-AC-10 | L1 | neg | RD-U | The fixture and the document | Check field parity both ways | No field in the fixture is missing from the document and none in the document is missing from the fixture |

## 5. Security-negative cases

`/TESTING.md` requires these on every authentication path. The first table indexes cases defined
above; the second adds cases that exist only here.

| Requirement | Cases |
| --- | --- |
| Each 401 variant, identical body | TC-223-04, TC-220-05, CT-I-05, RT-06 |
| Cross-repository 403 | TC-223-06, TC-223-07, TC-222-36, CT-I-06 |
| Oversized body | TC-223-08, TC-223-09, CT-I-07 |
| Future `observed_at` | TC-221-11, SN-01 |
| Over-long strings | TC-221-12, SN-02 |
| Token never logged or stored | TC-220-03, TC-220-21, TC-220-22, TC-223-21, TC-227-09, MV-228-09 |
| No body read before authentication | TC-223-12, TC-223-14 |
| Token lifecycle | TC-220-13, TC-220-16, TC-220-18, SN-07, SN-08, SC-05 |
| Read side refuses a tower token | TC-225-20 |

| ID | ACs | Layer | Type | File | Preconditions | Steps / input | Expected result |
| --- | --- | --- | --- | --- | --- | --- | --- |
| SN-01 | S-221-AC-3, S-223-AC-4 | L2.5 | sec | ING-I | A valid token; an issue with a stored cell | POST a snapshot and a `step_result` event whose `observed_at` is one hour ahead of the database clock | 422. The stored cell is unchanged. `tower_events` has no new row |
| SN-02 | S-221-AC-3, S-223-AC-4 | L2.5 | sec | ING-I | A valid token | POST a snapshot with a 301-character title and a 501-character evidence `ref`, each carrying a marker | 422. No PRD, wave or issue row is created. The response does not contain the marker |
| SN-03 | S-223-AC-1, S-222-AC-10 | L2.5 | sec | ING-I | A valid token | POST a snapshot whose title, slug, wave key and branch are SQL fragments such as `'); drop table tower_issues; --` | 202. The strings are stored verbatim. Every tower table still exists with its rows |
| SN-04 | S-223-AC-2 | L2.5 | sec | ING-I | A valid panel session cookie | POST a valid push with the cookie and no `Authorization` header | 401. The session grants nothing on this route (§12 CSRF) |
| SN-05 | S-223-AC-2 | L2.5 | sec | ING-I | A valid token | POST with the token in the query string, and in the body as `token`, with no header | 401 both times |
| SN-06 | S-223-AC-3, S-222-AC-10 | L2.5 | sec | ING-I | Repositories A and B that both have issue 912 and PRD `ops` | With A's token and A's name, POST events and a default-branch snapshot that omit and change those items | Only A's rows change. B's issue 912, PRD `ops`, `removed_at` values and marker are untouched |
| SN-07 | S-220-AC-5, S-223-AC-2 | L2.5 | sec | ING-I | A registered repository with token T1 | Rotate; POST with T1; POST with the new token | 401 with the fixed body, then 202 (PRD AC-5) |
| SN-08 | S-220-AC-6, S-223-AC-2 | L2.5 | sec | ING-I | A repository that was removed; its old token | POST a valid push naming it | 401 with the fixed body. No repository row is recreated |
| SN-09 | S-220-AC-4, S-220-AC-5, S-220-AC-6, S-220-AC-7 | L1 | sec | REVIEW | The five Server Actions; no session | Call each action | Each is refused before any database call (§6.3). No token is returned |
| SN-10 | S-223-AC-4 | L2.5 | sec | ING-I | A valid token | POST a body under 1 MiB made of 100,000 nested arrays; POST JSON with the `repository` key twice, the first naming another repository | 422 for the first, not 500. For the second the value the parser keeps is the one compared and the one applied, so the 403 check cannot be bypassed |
| SN-11 | S-221-AC-2, S-225-AC-1 | L2.5 | sec | RD-I | A valid token | POST a snapshot whose pull-request `url` is `javascript:alert(1)` and whose title holds `<script>`; GET the tree | 202. The tree returns both as plain strings, unchanged. Link neutralization is Wave B (S-230) |
| SN-12 | S-223-AC-8, S-223-AC-4 | L2.5 | sec | ING-I | A valid token | Collect every non-2xx response body from TC-223-04 to TC-223-10 | None contains a stack trace, an SQL fragment, a table name or a repository id |

## 6. Edge-case catalog

By category, for staleness, the default window, paging and retention, as the caller asked. Cases that
repeat a §3 case are not listed again.

| ID | ACs | Layer | Type | File | Preconditions | Steps / input | Expected result |
| --- | --- | --- | --- | --- | --- | --- | --- |
| EC-01 | S-225-AC-5 | L1 | edge | RD-U | Staleness, data boundary. Override 1 and override 720 | Last push 1 hour and 1 second ago with override 1; last push 719 hours ago with override 720 | `stale` true for the first and false for the second |
| EC-02 | S-225-AC-5 | L1 | edge | RD-U | Staleness, timing. `now` earlier than `last_push_received_at` by 2 minutes | Build the summary | `stale` false. No negative age is reported |
| EC-03 | S-225-AC-5 | L1 | edge | RD-U | Staleness, state. A repository whose only open issue has no PRD and no wave | Build the summary with an old last push | `has_open_work` true and `stale` true |
| EC-04 | S-225-AC-5 | L1 | edge | RD-U | Staleness, state. A repository with an `in_progress` PRD, an open wave and no issue | Build the summary with an old last push | `has_open_work` false and `stale` false (§8.3 defines open work by issues only) |
| EC-05 | S-225-AC-5, S-224-AC-6 | L2.5 | edge | RD-I | Staleness, configuration. Open work, last push 30 hours ago, no override | GET the list; set `tower.config` `stale_threshold_hours` to 48; GET again; delete the key; GET again | `stale` true with 24, then false with 48. With the key missing the default 24 is used and the request does not fail (assumption) |
| EC-06 | S-225-AC-5, S-223-AC-6 | L2.5 | edge | RD-I | Staleness, failure mode. Open work; last accepted push 30 hours ago | Send one rejected push (422) now; send one duplicate now; GET the list | Open (A-04): whether a rejected or duplicate push refreshes `last_push_received_at` decides `stale`. Record the observed value |
| EC-07 | S-225-AC-5, S-220-AC-7 | L2.5 | edge | RD-I | Staleness, state transition. Override 48, last push 30 hours ago | GET; clear the override; GET | `stale` false with source `repository`, then true with source `default` |
| EC-08 | S-225-AC-6 | L1 | edge | RD-U | Window, data boundary | Issues shipped 14 days minus 1 second ago and 14 days plus 1 second ago | The first is kept under `recent` and the second is not. The exact 14-day instant is open (A-11) |
| EC-09 | S-225-AC-6 | L1 | edge | RD-U | Window, timing. An issue whose `shipped_at` is 3 minutes after `now` | Build with `recent` | It is kept and counted as shipped |
| EC-10 | S-225-AC-6 | L1 | edge | RD-U | Window, state. A wave with `shipped_at` 20 days ago that still has one open issue | Build with `recent` | The wave is kept with that issue. Its old shipped issues are not listed |
| EC-11 | S-225-AC-6 | L1 | edge | RD-U | Window. `no_prd_issues` with one open, one shipped 5 days ago, one shipped 40 days ago | Build with `recent` | The first two are returned |
| EC-12 | S-225-AC-6, S-225-AC-7 | L1 | edge | RD-U | Window and rollups. A wave with 2 open and 8 old shipped issues | Build with `recent` | `issues` has 2 entries. Whether `issues_total` is 10 or 2 is open (A-10) |
| EC-13 | S-225-AC-6, S-224-AC-6 | L2.5 | edge | RD-I | Window, configuration. An issue shipped 5 days ago | Set `default_window_days` to 3 and GET with `recent`; set it to 0 and GET | The issue is absent in both. Open work is still returned |
| EC-14 | S-225-AC-9 | L2.5 | edge | RD-I | Paging. 1,200 waves under one PRD and 1,200 PRDs under one repository, inserted by SQL | GET the tree with `scope=all` | 1,200 of each, none missing or repeated |
| EC-15 | S-225-AC-9, S-226-AC-2 | L2.5 | edge | RD-I | Paging. 1,500 accepted and 1,100 rejected `tower_pushes` rows in the last day, and 300 older | GET the list | `pushes_last_day` is 1,500 accepted and 1,100 rejected. The count is not capped at 1,000 |
| EC-16 | S-225-AC-9 | L2.5 | edge | RD-I | Paging, concurrency. 2,500 issues | Start a tree read; apply a push that adds issue 2,501 while it runs | The response has no repeated issue and does not fail. It holds 2,500 or 2,501 issues |
| EC-17 | S-225-AC-9 | L2.5 | edge | RD-I | Paging, resource. 2,500 issues with eight cells each | GET the tree | 200. Duration is reported against the 500 ms target for 500 issues, not asserted (§11) |
| EC-18 | S-224-AC-1, S-224-AC-2 | L2.5 | edge | PRU | Retention, state. An issue shipped 91 days ago and marked `removed_at` | Run `tower.prune()` | Its events are pruned and `summary_final_at` is set like any other shipped issue. Its row remains |
| EC-19 | S-224-AC-1 | L2.5 | edge | PRU | Retention, late data. An issue with `summary_final_at` set | Apply a new `step_result` event and a `session_ended` event for it | Open (A-06). Record whether the summary changed. Assert only that the call does not fail |
| EC-20 | S-224-AC-4, S-222-AC-1 | L2.5 | edge | PRU | Retention, idempotency. An event push applied 31 days ago, then pruned from `tower_pushes` | Apply the same push again | Open (A-05). Record whether it returns `accepted` and whether `event_count` and `tokens_total` rise |
| EC-21 | S-224-AC-4 | L2.5 | edge | PRU | Retention, data boundary. Push rows received 30 days minus 1 minute and 30 days plus 1 minute ago | Run `tower.prune()` | The first is kept and the second deleted. The exact instant is open (A-11) |
| EC-22 | S-224-AC-5, S-222-AC-11 | L2.5 | edge | PRU | Retention, concurrency. A repository with a prunable issue | Run `tower.prune()` and `tower_apply_push` for that repository together, 20 repetitions | Both complete every time. No deadlock error. The final state equals one of the two sequential orders |
| EC-23 | S-224-AC-1, S-220-AC-6 | L2.5 | edge | PRU | Retention, cascade. A repository with prunable events | Remove the repository; run `tower.prune()` | The function completes with no error |
| EC-24 | S-224-AC-3 | L2.5 | edge | PRU | Retention. A wave shipped 91 days ago that holds one open issue with events | Run `tower.prune()` | The wave-level events are pruned. The open issue's events are kept |
| EC-25 | S-222-AC-2, S-222-AC-8 | L2.5 | edge | APP | State transition. An issue with `shipped` `passed` at t1 | Apply `shipped` `failed` at t2 > t1 | The cell becomes `failed`. Whether `shipped_at` is cleared is open (A-17) |
| EC-26 | S-222-AC-4, S-222-AC-2 | L2.5 | edge | APP | State. Issue 5 in wave A | Apply a newer snapshot placing issue 5 in wave B; then an older snapshot placing it back in A | Open (A-08): the scalar list of §8.2 does not include the wave. Assert only that the issue exists once |
| EC-27 | S-223-AC-2, S-223-AC-1 | L2.5 | edge | ING-I | Failure mode. A valid token | Start a POST; remove the repository after the token check and before the apply (injected pause) | Open (A-19). Assert only that the response is not 202 and that no repository row is recreated |
| EC-28 | S-223-AC-4 | L2.5 | edge | ING-I | Input domain. A valid token | POST a valid body with `Content-Type: text/plain` and with no content type; send GET, PUT and DELETE to the route | Open for the content type (A-19). GET, PUT and DELETE are not handled as a push: no row is written and the status is 405 |
| EC-29 | S-220-AC-2 | L2.5 | edge | REP | Timing. A valid token | Verify it 5 times within one second, then once after moving `last_used_at` back 2 minutes by SQL | `last_used_at` is written once in the first burst and again after the 2 minutes (S-220 technical note) |
| EC-30 | S-222-AC-4, S-222-AC-9 | L2.5 | edge | APP | Input domain. A repository with no data | Apply a snapshot with no PRD and no issue, default branch | `accepted`. `seq` + 1. No row is created or removed |

## 7. Randomized tactics and seed policy

### 7.1 Seed policy

- Every tactic has a fixed default seed in the test file, so CI is deterministic. `TEST_SEED`
  overrides it: `testSeed(defaultSeed)` from `panel/tests/helpers/prng.ts`.
- The generator is `mulberry32(seed)`. No tactic calls `Math.random`, `randomUUID` or reads the wall
  clock for generated data: push ids and observed times are derived from the generator and a fixed
  base instant.
- Every assertion message includes the seed, the iteration index and the tactic id, so a failure can
  be replayed from the log alone.
- Replay: `TEST_SEED=<seed> pnpm --filter panel exec vitest run --project <unit|integration> <file> -t "<RT-id>"`.
- A weekly or pre-release run may set `TEST_SEED` from the date to explore new sequences; a failure
  found that way is added as a named regression case with its seed.
- A failure that does not reproduce with its seed is retried at most three times, then recorded as
  `inconclusive` with the environment (Node version, Postgres version, Supabase CLI version).
- Triage follows the verifier's workflow: capture, isolate, minimize, classify (spec gap to
  `product-engineer`, defect to `developer`, environmental as `inconclusive`), report.

### 7.2 Tactics

| ID | ACs | Layer | Type | File | Preconditions | Steps / input | Expected result |
| --- | --- | --- | --- | --- | --- | --- | --- |
| RT-01 | S-222-AC-2, S-222-AC-3 | L2.5 | prop | APR | A generated universe of 2 PRDs, 3 waves, 6 issues; 30 pushes (snapshots from 3 non-default branches, `step_result` and `stage_result` events) with pairwise distinct observed times | Apply the 30 pushes to 12 fresh repositories, each in a different shuffled order | **Order independence of cells.** Every cell (result, `observed_at`, reason, evidence, branch) is identical across the 12 repositories and equals the oracle "the incoming value with the greatest `observed_at` for that cell". Received times, summaries and `removed_at` are excluded (A-01, A-03) |
| RT-02 | S-222-AC-1, S-222-AC-9 | L2.5 | prop | APR | A generated sequence of 25 pushes of every kind | Apply it once to repository R1. Apply it to R2 with each push re-delivered 1 to 3 more times at random later positions | **Idempotence under replay.** Every re-delivery returns `duplicate` and leaves the digest unchanged. R2 equals R1 in every column except ids and received times. R2's marker `seq` equals the number of distinct push ids |
| RT-03 | S-222-AC-2, S-222-AC-6, S-222-AC-8 | L2.5 | prop | APR | A generated sequence of 60 pushes including ties, older and newer observations | Apply in order; after each push read every cell, `rework_count`, `event_count`, `first_observed_at` and the marker | **Monotonicity.** No cell's `observed_at` decreases. `rework_count` and `event_count` never decrease. `first_observed_at` never increases. `seq` rises by exactly 1 per `accepted` and 0 per `duplicate` |
| RT-04 | S-222-AC-4, S-222-AC-5 | L2.5 | prop | APR | A generated sequence of 40 pushes with default and non-default snapshots and events for items not yet seen | Apply in order beside a small reference model of §8.1 steps 3 to 5 (sets of seen-on-default, removed and placed keys) | **Stateful walk.** After each push `seen_on_default`, `removed_at` set or null, and `placed` match the model. No row count ever decreases (I-5). An item never seen on the default branch is never removed |
| RT-05 | S-222-AC-11 | L2.5 | prop | APR | 15 generated pairs of pushes with distinct observed times | Apply each pair concurrently on two connections to one repository, and in sequence to a second | **Concurrency.** Both calls return `accepted`. The cells of the two repositories are equal. `seq` rose by 2. No deadlock or serialization error surfaces |
| RT-06 | S-220-AC-2, S-223-AC-2 | L1 | prop | TOK | 2,000 generated header strings: random bytes, near-miss tokens, long runs of dots and underscores up to 64 KiB | `verifyTowerToken` with an injected lookup that knows one token | It never throws. Every result is the one negative value, except for the exact valid header. The lookup is called only for strings that match the anchored format. Each call returns in under 50 ms (guards against a slow regular expression; reported as `inconclusive` on a loaded runner, not as a defect) |
| RT-07 | S-221-AC-2, S-221-AC-4, S-221-AC-7 | L1 | prop | CON | The valid fixtures; 3,000 mutations per run: delete a key, swap a type, lengthen a string past its cap, inject an unknown key, replace a value with a marker string | `validatePush(mutant, clock)` | It never throws. The result is either a normalized push or 1 to 20 errors. No message contains a marker. Injecting an unknown top-level or event key into a valid fixture keeps it valid. Normalizing twice gives an equal value |
| RT-08 | S-225-AC-1, S-225-AC-4, S-225-AC-5, S-225-AC-6, S-225-AC-7 | L1 | prop | RD-U | 500 generated row sets (0 to 4 PRDs, 0 to 5 waves each, 0 to 30 issues, random cells, removals, ship times and thresholds) and a generated `now` | Build summaries and trees with both scopes | Same input gives an equal output. Inputs are not mutated. `stale` implies `has_open_work`. Every `step_gaps_seconds` has 7 entries, each `null` or at least 0. `issues_total` under `all` equals the number of non-removed child rows. Every issue under `recent` is also under `all`. No removed item appears. No unreported field is 0 |

Shrinking, for every tactic: on failure, drop pushes (or mutations, or rows) one at a time from the
end, then from the start, re-running with the same seed-derived values, until no single removal
keeps the failure. Report the remaining list with the seed.

| Tactic | Iterations per run | Default seed | Runs against |
| --- | --- | --- | --- |
| RT-01 | 12 orders of 30 pushes | 222001 | local Postgres |
| RT-02 | 1 sequence of 25 pushes, about 75 deliveries | 222002 | local Postgres |
| RT-03 | 60 pushes | 222003 | local Postgres |
| RT-04 | 40 pushes | 222004 | local Postgres |
| RT-05 | 15 pairs | 222005 | local Postgres |
| RT-06 | 2,000 headers | 220006 | no I/O |
| RT-07 | 3,000 mutations | 221007 | no I/O |
| RT-08 | 500 row sets | 225008 | no I/O |

## 8. Findings (ambiguities, contradictions, untestable criteria)

None of these is resolved here, and no story, spec or PRD text was edited. "Stories" is
`workstream/user-stories-control-tower.md`, "spec" is `workstream/specification-control-tower.md`,
"PRD" is `docs/requirements/prd-control-tower.md`. They are ordered by how much a wrong guess would
cost. Route: `product-engineer` for all of them.

| ID | Concerns | Finding | Proposed resolution |
| --- | --- | --- | --- |
| A-01 | Spec §8.1 step 3 (line 346); stories line 264 (S-222-AC-4); PRD FR-9 | Removal depends on delivery order, not on observed time. A default-branch snapshot that arrives late and is older than the stored state still sets `removed_at` on items a newer default snapshot contained, and the opposite order resurrects an item a newer snapshot dropped. The cell rule protects results from reordering; nothing protects removal. | Store the observed time of the last default-branch snapshot per repository and ignore removal and un-removal from a default snapshot older than it. State the rule in §8.1 and add it to S-222-AC-4 |
| A-02 | Spec §5.1 `tower_pushes` (line 143), §8.1 (lines 327–329, 345); stories line 335 (S-223-AC-6) | Rejected pushes are recorded in the table whose unique key is `(repository_id, push_id)`. A 413 and a non-JSON 422 have no readable `push_id` (and no `kind`). A 422 recorded under a real `push_id` makes the corrected resend with the same id answer `duplicate` and never apply. | Say what `push_id` and `kind` a rejected row holds (nullable, outside the unique key), and that only `accepted` rows take part in deduplication |
| A-03 | Spec §8.3 (lines 383–388); stories lines 266–267, 271 (S-222-AC-6, AC-7, AC-11); PRD FR-9 | Rework and waiting depend on delivery order. A `gate:` key is added on "entering `failed`", so `failed@t1, passed@t2, failed@t3` counts 2 in order and 1 when t3 arrives first. A `block_cleared` delivered before its `block_raised` leaves the block open for ever; an interval could be negative. "The same result as applying them in sequence" (AC-11) does not say which sequence, and with a tie the two orders differ. | State that summary columns are order-dependent and exclude them from FR-9, or derive rework and waiting from the stored events ordered by observed time. For AC-11 say "equal to one of the two sequential orders" |
| A-04 | Spec line 143 vs line 345; stories lines 261, 269, 335; PRD FR-11 | `tower_pushes.outcome` lists `duplicate`, but a duplicate "changes no row", so no such row can exist. It is not stated whether a duplicate or a rejected push updates `last_push_received_at`. That value drives the stale flag: a sender whose every push is rejected or repeated is either stale or healthy depending on the answer. The meaning of the "rejected" counter (S-226-AC-2) depends on it too. | Decide: duplicates are not recorded and do not refresh the time; rejections refresh `last_push_received_at` or do not. Remove `duplicate` from the outcome list or define its row |
| A-05 | Spec lines 143, 170; stories line 395 (S-224-AC-4); PRD FR-9 | Push rows are pruned after 30 days, so a push replayed after that is applied again. Cells are safe, but its event is inserted a second time: `event_count` and `tokens_total` are counted twice. Idempotence holds for 30 days only. | State the idempotence horizon in the contract, or deduplicate events on `(repository_id, push_id)` in `tower_events` as well |
| A-06 | Spec line 170; stories lines 401, 412 (S-224) | "A summary whose events were pruned is final", but nothing says what an event does when it arrives for an issue with `summary_final_at` set. Unplaced events are never pruned, so a sender naming unknown issues grows the table without bound. | Say whether a late event changes a final summary. Give unplaced events an age limit |
| A-07 | Spec lines 327–329; D-23; stories lines 332–333; PRD AC-4 (line 216) | The order between 403 and 422 is not given: 403 needs the parsed `repository`, so a body that is both for another repository and invalid can be either. PRD AC-4 says "nothing is stored" while S-223-AC-6 records the 403 and S-223-AC-3 says "no tower data". | Fix the order: token, size, JSON parse, repository match, then contract validation. Reword AC-4 as "no tower data is stored; the rejection is counted" |
| A-08 | Spec line 362; stories line 286 (S-222 edge matrix) | `content_observed_at` is "the push's newest cell time or `sent_at`": per push or per row, and which one when both exist, is not said. The column is missing from §5.1. A newer snapshot that omits `subtasks` or `drift_findings` either erases or keeps it. `prd_slug` and `wave_key` are not in the scalar list, so "issue moved from one wave to another" has no expected result. `sent_at` has no future bound although it can pin scalars. | Define it as the greatest of the row's cell times and `sent_at`, add the column to §5.1, say that an omitted scalar keeps the stored value, add the parent keys to the list, and apply the 5-minute rule to `sent_at` |
| A-09 | Spec line 388 | "A newer snapshot without `blocked_on_owner`" closes the waiting interval: newer by which time, closed at which time, and whether a snapshot from another branch (a lane that does not know about the block) may clear it, are not said. `waiting_seconds` cannot be asserted for that path. | Close a block from a snapshot only when it is newer by `content_observed_at`, at that time, or only by `block_cleared` |
| A-10 | Spec lines 259, 397–398, 458; stories lines 457–458 (S-225-AC-6, AC-7) | §11 filters `scope=recent` in SQL, but rollups count all non-removed children and the module is a pure function of the rows it is given: both cannot hold. It is not said whether `issues_total` under `recent` counts hidden issues. An unknown `scope` value has no defined answer. `scope=all` excludes removed items, so the history FR-8 keeps is not readable in version 1. | Rollups always count all non-removed children; the module filters; an unknown `scope` is 400. State that removed items are stored and not served in version 1 |
| A-11 | Spec lines 170, 398; stories lines 412, 476 | The exact boundary is undefined for the 14-day window, the 90-day event retention and the 30-day push retention. Staleness is defined (`>`), the others are not. | Use the strict comparison everywhere: exactly at the boundary is still inside |
| A-12 | Spec lines 223, 272–274; PRD FR-21, FR-22 | An issue may have a PRD and no wave, but `Prd` holds only `waves` and `no_prd_issues` is for issues with no PRD. Such an issue has no place in `RepositoryTree`. | Add `Prd.no_wave_issues`, or state that an issue with no wave is always listed under `no_prd_issues` |
| A-13 | Stories lines 576–577 (S-227-AC-1, AC-2); spec line 473 | The ingest probe passes on any 401. If the route were classed `api` by mistake, the session gate would answer 401 (`{ "error": "UNAUTHORIZED" }`), the gate would pass, and every real push would be refused. | Have the probe also require the handler's body, `{ "status": "unauthorized" }` |
| A-14 | Spec lines 229–235, 385, 390; §5.1 | The event table leaves gaps: `pull_request_linked` has no `observed_at` although events are replayed oldest first and stored with one; the `audit:` rework key needs `drift_findings`, which a `step_result` event does not carry, and uses `evidence.ref`, which may be absent; `block_raised` with `on_owner` false has no stated effect and `blocked_count` is not defined; "adds to token totals" does not say input plus output; a wave-level `session_ended` has no summary column, so its usage is lost when the wave's events are pruned (FR-12 keeps totals permanently). | Add `observed_at` to `pull_request_linked`; define the audit key from the snapshot only; define `blocked_count`; define the total; add token columns to `tower_waves` |
| A-15 | Spec line 468; stories lines 201–202 (S-221-AC-3, AC-4) | "Any string or array over its cap" cannot be tested as written: arrays are "bounded" with no number, and `repository`, `branch`, `slug`, wave `key`, `name`, `scope`, `workflow_agent`, `url`, `model`, `review_id` and `sender` fields have no cap. It is not said which timestamps the 5-minute rule covers (`blocked_on_owner.since`, `lanes.observed_at`, `sent_at`). Unknown-field tolerance is stated for top-level and event fields only; nested objects are not covered. | Publish one table of caps per field and per array, list the timestamps under the rule, and state the tolerance for nested objects |
| A-16 | Stories line 200 (S-221-AC-2); spec line 252 | A message must contain "no value from the input", but a `path` for an unknown step key such as `issues[0].steps.deploy` repeats an input key. | State that paths may contain keys and indexes, truncated to a fixed length, and that only values are never echoed |
| A-17 | Spec lines 157, 389, 395; stories lines 199, 394 | The sixteen step and stage keys are never written literally. It is not said which key an issue with no wave uses for the merged-and-shipped step, how a wave's `shipped_at` is derived (S-224-AC-3 depends on it), or whether `shipped_at` is cleared when a newer non-`passed` `shipped` cell arrives. | List the keys in §5.2; define wave `shipped_at` as the `ship` stage's `passed` time; say whether `shipped_at` can be unset |
| A-18 | Spec line 137; stories lines 73, 139, 537 | "Stored lowercase" suggests input is lowercased, while the table rejects uppercase and S-220-AC-4 returns `invalid_name`. Whether the payload's `repository` and the read URL are compared case-insensitively is not said. | Choose one: lowercase on registration, on the 403 comparison and in the read path, or reject uppercase everywhere |
| A-19 | Stories lines 158, 352, 537 | Edge-matrix entries with no expected result: revoke with no active token and rotate after revoke (S-220); wrong content type, GET on the route, repository removed mid-request (S-223); double submit and rotate while the reveal dialog is open (S-226). | Give each an expected result, for example: revoke is a no-op `ok`; rotate after revoke issues a token; content type is not checked; GET is 405; removal mid-request is 401 |
| A-20 | Stories line 333 (S-223-AC-4) | "Without being buffered whole" is not observable from outside. | Define it as in TC-223-09: the reader stops within one chunk of the cap and cancels the stream, with or without `Content-Length` |
| A-21 | Stories line 633 (S-228-AC-1); spec line 500 | "Before the push … `service_role` able to execute the new functions" cannot be checked before the functions exist. Realtime is confirmed in Wave A although its publication migration is Wave B (stories line 872). | Split the criterion: extensions before the push, execute privileges after it. Keep the Realtime check as an early warning and say so |
| A-22 | Spec lines 306, 466; stories line 138 (S-220-AC-3) | §12 says "one code path for every authentication failure" while §7 answers a malformed header with no database call, so timing differs between malformed and unknown. The comparison count for a revoked token and for a malformed header is not stated. | Say that enumeration protection covers well-formed tokens only, and that a revoked token is compared before it is refused |
| A-23 | Stories line 136 (S-220-AC-1); spec line 304 | "12 base32 characters" does not name the alphabet, and the scheme word `Bearer` is not said to be case-sensitive. TC-220-01 and TC-220-06 assume RFC 4648 lowercase and an exact `Bearer`. | Name the alphabet and the scheme matching in §7 |
| A-24 | Stories line 370 (S-223 files) | The story names `panel/tests/unit/route-policy.test.ts`. The route-policy tests are in `panel/tests/unit/auth-route-policy.test.ts`; a second file would split one subject across two files. | Extend the existing file |
| A-25 | Stories lines 638, 671 (S-228-AC-6) | The story writes `docs/technical-guidelines.md` and `docs/product-context.md`. `CLAUDE.md` says a foundation document is always written under the new name (`docs/tech.md`, `docs/product.md`) and that `dev-tasks migrate docs` is proposed when an old name is met. This repository still carries only the old names. | The owner decides whether to migrate first; then name the files accordingly in the story |
| A-26 | PRD line 225 (AC-13); stories lines 287, 458; spec line 349; task list line 10 | Minor wording. PRD AC-13 is validated by "Unit" but rework is computed in SQL and only an integration test can show it. "Returns exactly those two cells" (S-225-AC-7) reads oddly against a record that always has eight keys. `last_activity_at` has no defined value. The task list cites stories v1.1; the stories are v1.2. | Change AC-13's validation to "Integration, Unit"; say "`ship` is `passed` and `audit` is `null`"; define `last_activity_at` as the received time of the last applied push touching the PRD; update the citation |

## 9. Execution checklist

1. **Before each story:** the developer writes the story's cases from §3 first and sees them fail.
   Cases marked "open (A-nn)" are written as recorded observations, not as assertions, until the
   finding is decided.
2. **S-221 first for fixtures:** S-222, S-223 and S-225 load the S-221 fixtures; none carries its own
   copy of a payload.
3. **Per story:** `pnpm --filter panel run validate`, plus `supabase db reset` and
   `REQUIRE_LOCAL_DB=1 pnpm --filter panel run test:integration` wherever a table, function or route
   is touched. `pnpm --filter panel run test:e2e` for S-226.
4. **Randomized cases:** run with the default seeds in CI. Record the seeds in the PR. On failure
   follow §7.1.
5. **Security-negative cases (§5):** all of them green before S-223 and S-220 are called done.
   `/TESTING.md` treats a missing one as incomplete.
6. **Coverage map:** each story PR maps its acceptance criteria to case ids using the traceability
   matrix.
7. **S-228:** the operator fills in MV-228-01 to MV-228-13 in the change record, with the owner's
   approval noted before MV-228-04 and MV-228-06.
8. **Audit Mode** (after implementation) reads this plan, the matrix and the findings' decisions,
   and reports each case as pass, fail or drift.

**Not covered by this plan:** performance targets of spec §11 are reported, not asserted. Wave B
rendering, live updates and the Realtime publication are out of scope. No test was written or run in
this pass, and no fixture exists yet, so every file path above is planned, not verified.
