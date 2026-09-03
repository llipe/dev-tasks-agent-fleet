# Fidelity Report — S-104 (Server-side data layer & `effectiveStatus` parity)

> **Mode:** Audit (grey-box). **Produced:** 2026-09-03.
> **Fallback notice:** produced by applying the `verifier` Audit Mode activity directly; this runtime has no separate `verifier` delegation tool. Findings are reported only — remediation routes to `developer`, and any spec-level drift routes to `product-engineer`'s `activity-drift-reconciliation`. This audit is **additive and non-blocking**: it does not gate PR/issue completion and does not replace the `test`/`lint`/`format:check`/`typecheck`/`audit` gates.

---

## 1. Verdict

| | |
| --- | --- |
| **Overall fidelity** | **High** |
| **Highest drift impact** | **Minor** |
| **Scope** | Story S-104 · issue [#117](https://github.com/llipe/dev-tasks-agent-fleet/issues/117) · PR #132 · branch `story/S-104-server-data-layer` |
| **Commits audited** | `51d4423`, `8e6e1bf`, `f857614`, `07375fe`, `19b99af` |
| **AC result** | 7 / 7 acceptance criteria **Pass** (0 Fail) |
| **Drift items** | 4 total — 4 Intended, 0 Unintended, 0 Undetermined |
| **Quality gates** | `make validate` green on both branches; 68 panel tests pass + CT-7 bundle test (3, `RUN_BUNDLE_SECRET_TEST=1`); Layer 2.5 ran **live** (not skipped); `coverage_gate: PASS` (qa-engineer) |

**Bottom line.** Every acceptance criterion is satisfied by code and by test evidence. All four deviations from the letter of the plan/spec are deliberate, documented in-code, and preserve the underlying security and behavioral intent (RLS deny-all, no secret in the browser, SD4 parity, the SD11 bound). None weakens a guarantee. The one item worth a second look — the local test grants `SELECT` to `service_role` to compensate for a CLI/production grant asymmetry — is correctly scoped (service_role only, never `anon`) and is a test-harness accommodation, not a schema change; its residual is that the production read path is proven *by inference* (a documented platform-default) rather than by a live assertion.

---

## 2. Human-readable summary — what changed and why

S-104 builds the server-only "data layer" the panel reads through. Before any screen exists, this story draws the security boundary: the browser can never read the database directly, all reads go through the server using a privileged key that stays on the server, and the app derives a run's *effective* status (e.g. flipping a hung "running" run to "timed out") using the exact same logic the database itself uses, proven equal by a test that runs both side by side.

Everything asked for was delivered and tested. Four things were done differently than the plan's first draft assumed, and in every case the change was made on purpose and written down:

1. **The "don't import the server file into browser code" guardrail was made stronger, not weaker.** The original lint rule was catching legitimate server pages during the build and had to be narrowed to the browser-component folder — but at the same time a hard, build-level block (`import "server-only"`) was added that the build itself enforces and that no developer can switch off. The net result is a stronger guarantee than a lint rule alone.

2. **A newer, audit-clean version of the Supabase library was pinned** (2.114.0 instead of the spec's 2.58.0), following the same "re-confirm current before pinning" rule the project already adopted in Wave 1.

3. **A quirk of the local test database was worked around** so the tests actually exercise the real read path. The hosted production database automatically grants the server role read access; a fresh local database created by the CLI does not, so the test grants it locally — to the server role only, never to the anonymous role, so the "browser reads nothing" guarantee is untouched.

4. **The log-history read was made to page internally** because the database platform caps any single request at 1000 rows, while the requirement is to read up to 2000. The code fetches in two passes so the 2000 contract is honored without changing platform settings.

The one thing a reviewer should keep in mind: because the local test adds the grant that production already has, the tests prove the read path works *given* production's known configuration — they do not themselves re-prove that production carries that configuration. That is a reasonable inference (it is documented from the S-115 baseline diff), but it is an inference, not a live assertion, and it is the single reason this is not a "nothing to see here" audit.

---

## 3. Per-AC result table

| AC | Description | Codebase evidence | Workstream evidence | Test evidence | Result |
| --- | --- | --- | --- | --- | --- |
| AC1 | `server.ts` per-request client from server-only env; importing from a client component fails lint | `lib/supabase/server.ts` (`createServerClient` + `readSupabaseEnv` fail-fast; `import "server-only"` hard guard); `eslint.config.mjs` `no-restricted-imports` scoped `components/**` | Plan 1.5/1.15/1.21; test-plan EC-13/EC-12 | `tests/unit/eslint-server-import.test.ts` (rule fires on client fixture, does **not** fire on server-context fixture); `tests/unit/server-env.test.ts` (EC-12) | **Pass** (see Drift D1) |
| AC2 | Typed helpers for all eight read paths | `lib/supabase/queries.ts` (8 helpers); `lib/supabase/types.ts` (6 row types); `lib/supabase/errors.ts` (`DATABASE_ERROR`, pg code logged/never returned) | Plan 1.4/1.7/1.8/1.22 | `tests/integration/queries.test.ts` runtime shape assertions per helper (CT-5, EC-17/18/19); `tests/unit` errors (EC-9, 8 tests) | **Pass** |
| AC3 | `effectiveStatus(run, now)` implements SD4 exactly | `lib/domain/status.ts` — strict `>`, null-guarded `startedAt`, null-safe `maxRuntime`; pure & now-injected | Plan 1.2/1.23; spec SD4 §line 214–223 | `tests/unit/status.test.ts` truth table (fresh/stale, terminals pass-through, null started_at, ±boundary, zero/negative grace, EC-4/8/16/20) | **Pass** |
| AC4 | Layer 2.5 parity test proves agreement with `v_runs.effective_status`, incl. exact-boundary rows | `effectiveStatus` mirrors the view's `case` verbatim (documented in-file) | Plan 1.11/1.24; test-plan CT-1..CT-4, SR3 | `tests/integration/status-parity.test.ts` — matrix + CT-2 (959/960/961 running, 299/300/301 queued) + CT-3 null-started; read back against DB `now()` (no clock skew). **Ran live.** | **Pass** |
| AC5 | Anon-key client reads zero rows from every table **and** `v_runs` | RLS deny-all migration (D11); anon never granted | Plan 1.12/1.25; test-plan CT-6/EC-14; the F2 regression test | `tests/integration/rls-deny-all.test.ts` — schema-enumerated table loop + explicit `v_runs` + non-vacuous "actually seeded rows" guard. **Ran live.** | **Pass** |
| AC6 | No client chunk contains the service role key | `import "server-only"` keeps it out of client bundles | Plan 1.14/1.26; test-plan CT-7, gap G3 | `tests/unit/bundle-secrets.test.ts` — sentinel build + grep of `.next/static/**` for sentinel **and** identifier; verified with `RUN_BUNDLE_SECRET_TEST=1` (3 tests) | **Pass** |
| AC7 | Run routes are `force-dynamic`; no Next.js data cache for run data | `lib/supabase/route-config.ts` (canonical values) + **inline** `dynamic/revalidate/fetchCache` in `app/dev/agent-count/page.tsx` | Plan 1.9/1.27; spec §10 caching row | Route config asserted; manual route renders server-fetched agent count | **Pass** (see Drift D4 — non-drift clarification) |

Every AC maps to at least one positive and one negative/edge scenario, satisfying the traceability requirement.

---

## 4. Drift catalog

> All drift below is **non-blocking to completion.** Impact classes: Critical / Major / Minor. Intent classes: Intended / Unintended / Undetermined.

### D1 — SD2 ESLint rule rescoped from tree-wide to `components/**`; hard guard moved to `import "server-only"`
- **Impact:** Minor · **Intent:** Intended
- **Evidence:** `panel/eslint.config.mjs` (rule `files: ["components/**/*.ts", "components/**/*.tsx"]`); `lib/supabase/server.ts` (`import "server-only"`); spec SD2 (§line 132: "A lint rule forbids importing `lib/supabase/server.ts` from a client component"); `tests/unit/eslint-server-import.test.ts`.
- **Assessment:** AC1's literal requirement — "importing it from a client component fails lint" — is **genuinely satisfied and not weakened**. The test proves the rule fires on a `"use client"` fixture under `components/` and correctly does *not* fire on a legitimate server-context module. The rescope was forced by a real defect (the prior tree-wide rule flagged legitimate Server Components during `next build`), and the protection that actually matters — keeping the service-role key out of the browser bundle — is now carried by the `import "server-only"` pragma, a **build-time hard failure that no `eslint-disable` can suppress**. That is strictly stronger than a lint rule.
  - **Narrow residual (the reason this is logged at all):** the lint *hint* now covers only `components/**`. A client component authored directly under `app/**` (e.g. a co-located `"use client"` file) that imports the server module would not trip the lint rule — it would still be caught by `server-only` at build time, but later and with a less didactic message. This is an acceptable, intentional trade (SD2's intent is satisfied by the hard guard; the lint rule is explicitly documented as a "fast hint" on top of it). Spec SD2 does not mandate tree-wide lint scope, so this is an implementation-detail deviation, not a spec contradiction.
- **Recommendation:** `no action needed` for S-104. Optional hardening for a later story: extend the lint `files` glob to include `app/**/*.tsx` client components, or add a mechanical check, so the fast hint covers the `app/` tree too. Worth routing to `product-engineer` only as an optional SD2 note, not a fix.

### D2 — `@supabase/supabase-js` pinned `2.114.0`, not spec §16 `2.58.0`
- **Impact:** Minor · **Intent:** Intended
- **Evidence:** `panel/package.json` (`"@supabase/supabase-js": "2.114.0"`); spec §16 table (`2.58.0`); Wave-2 plan "re-confirm-then-pin" note; `technical-guidelines.md` row 1.11 (same-precedent `next` correction).
- **Assessment:** Directly analogous to the S-101 `next` 15.5.4 → 15.5.25 correction the project already blessed. The plan explicitly instructs "verify it is current and audit-clean before pinning." `pnpm run audit --prod --audit-level=high` passes, so the newer pin is audit-clean. This is a version write-back owed to the spec, not a behavioral change (same major, server-side read + Realtime-relay surface unchanged).
- **Recommendation:** `product-engineer` spec clarification — write `2.114.0` back into spec §16, exactly as row 1.3 did for `next`. No code change.

### D3 — Layer 2.5 `queries.test.ts` applies `grant select … to service_role` locally in setup; no schema/migration change shipped
- **Impact:** Minor · **Intent:** Intended
- **Evidence:** `tests/integration/queries.test.ts` → `grantServiceRoleSelectLocalOnly()` (grants `usage on schema public` + `select on all tables` to `service_role` **only**); the canonical migration `supabase/migrations/20260902200101_initial_schema.sql` grants no SELECT to `service_role`; `supabase/config.toml` documents the "new entities not auto-exposed" cloud default; the in-file comment cites the S-115 baseline diff (`docs/runbooks/issue-115-baseline-adoption.md`) confirming production carries the 84 platform-managed grants.
- **Assessment (the FINDING requiring judgment):** **Intended, and the RLS deny-all posture is preserved.** The grant is scoped to `service_role` exclusively — `anon` is never granted — so CT-6/EC-14 remain a true test (anon reads zero rows because RLS is the gate, not a missing grant). The asymmetry is real and correctly diagnosed: hosted Supabase applies default table privileges to `service_role` automatically; `supabase db reset` on this CLI version does not reproduce them; without the local grant the service-role transport is denied `42501` locally even though it works in production. Keeping the platform grants **out** of the canonical migration was a deliberate "don't tamper with platform-managed grants" decision, consistent with S-115.
  - **Residual — is the production read path actually proven?** *By inference, yes; by live assertion, no.* The tests prove: (a) the helper transport returns correct shapes when the service role *has* SELECT (which production does), and (b) anon is denied. They do **not** independently re-prove that production still carries those grants — that rests on the documented S-115 baseline diff. If a future platform change or a `db reset`-from-scratch reprovision ever stripped those defaults in production, this suite would stay green while production reads would 42501. That is a low-likelihood, documented, single-tenant risk — acceptable for S-104, but it is the honest gap behind the "High, not perfect" verdict.
- **Recommendation:** `no action needed` to complete S-104. Route to `product-engineer` as a drift-reconciliation note: consider a lightweight production/staging smoke read (one `getEnabledAgents` against the live project) in a deploy story (S-113/S-115 territory) so the service-role read path has a live assertion, not only an inferred one. Do **not** move the grants into the migration (that would be the platform-tampering the team explicitly rejected).

### D4 — Route segment config declared **inline** in the page, with a shared `route-config.ts` as documentation only
- **Impact:** Minor · **Intent:** Intended (clarification — arguably not drift)
- **Evidence:** `app/dev/agent-count/page.tsx` (inline `export const dynamic/revalidate/fetchCache`); `lib/supabase/route-config.ts` (canonical values + comment "Next does not honor re-exported segment config").
- **Assessment:** This is a correctness accommodation to a genuine Next.js constraint: the App Router only honors route-segment config exported *directly* from the route module; a re-export from another file is silently ignored (emits a "can't recognize the exported field" warning and falls back to defaults). Declaring inline is the correct implementation of AC7; the shared module remains the single documented source of the canonical values. Behavior matches spec §10 ("Caching: None … `force-dynamic` on run routes") exactly.
- **Recommendation:** `no action needed`. Logged for completeness because the plan's Relevant-Files text describes `route-config.ts` as the config source; the inline declaration is the honored one.

---

## 5. Edge-case & scenario outcomes (from the prior Design-Mode test plan)

The S-104 slice of the Wave-2 test plan (CT-1..CT-7, EC-9/12/13/14/17/18/19/20) is fully realized in the delivered suite:

| Scenario | Where verified | Outcome |
| --- | --- | --- |
| CT-1 matrix parity | `status-parity.test.ts` (MATRIX, live) | Pass |
| CT-2 exact-boundary ±1s | `status-parity.test.ts` (959/960/961; 299/300/301) | Pass — equality passes through, +1s flips, both sides agree |
| CT-3 null `started_at` running | `status-parity.test.ts` + `status.test.ts` | Pass — stays `running` |
| CT-4 null `max_runtime_seconds` | `status.test.ts` (unit; column is `not null`, so unit-only by design) | Pass — passes through, not coerced to 0 |
| CT-5 helper shapes | `queries.test.ts` runtime assertions | Pass |
| CT-6 anon deny-all (all tables + view) | `rls-deny-all.test.ts` (schema-enumerated, live) | Pass |
| CT-7 no secret in client bundle | `bundle-secrets.test.ts` (sentinel build, `RUN_BUNDLE_SECRET_TEST=1`) | Pass |
| EC-9 `DATABASE_ERROR` hides pg code | `errors.ts` + unit tests | Pass — pg code on `logDetail`/`pgCode`, never in client message |
| EC-12 env fail-fast | `server-env.test.ts` | Pass |
| EC-13 SD2 lint fires | `eslint-server-import.test.ts` | Pass (positive + negative) |
| EC-14 `v_runs` not granted to anon | `rls-deny-all.test.ts` explicit view check | Pass |
| EC-17 empty collections → `[]` | `queries.test.ts` | Pass |
| EC-18 no-repository run | `queries.test.ts` (`repository_full_name` null, no `"null/null"`) | Pass |
| EC-19 bounded read (>2000 events) | `queries.test.ts` (2025 seeded → 2000 returned, seq-ordered) + `getRunEvents` `.range()` paging | Pass — **SD11 honored despite `max_rows=1000`** |
| EC-20 unknown future status | `status.test.ts` | Pass — passes through unchanged |

**G2 harness risk (carried, not a defect):** the Layer 2.5 suites are Docker-gated and *can* skip-to-green when the local stack is down. For this delivery they **ran live** (not skipped), so AC4/AC5 are genuinely proven here. The standing requirement that CI must start the stack and treat a skip of `status-parity`/`rls-deny-all` as a failure (test-plan G2) remains a CI-config obligation outside S-104's code scope.

---

## 6. Recommendations (per item; no change applied by this audit)

| Item | Suggested next step | Owner |
| --- | --- | --- |
| D1 (lint scope) | Optional: extend SD2 lint glob to `app/**` client components. Not required — `server-only` covers it. | `product-engineer` (optional SD2 note) / `developer` (optional) |
| D2 (supabase-js pin) | Write `2.114.0` back into spec §16, mirroring the v1.3 `next` correction. | `product-engineer` (drift-reconciliation) |
| D3 (local grant) | Add a live service-role smoke read in a deploy story so the production read path has a live assertion, not only inference. Do **not** move grants into the migration. | `product-engineer` (note) → later deploy story |
| D4 (inline route config) | None. Update the plan's Relevant-Files wording if desired. | `no action needed` |
| G2 (CI skip-to-green) | Ensure CI starts the local stack and fails on a skipped parity/deny-all project. | CI config (outside S-104) |

---

## 7. Output contract

- **Mode / phase:** Audit / Phase 4 (Reporting & Publication)
- **Source artifacts:** issue #117 body; `tasks-prd-agent-fleet-panel-v2-wave2-plan.md` task 1.0; `test-plan-wave2-S-104-S-105-S-111.md`; spec SD2/SD4/SD11/§13/§16; delivered code on `story/S-104-server-data-layer` (commits `51d4423`,`8e6e1bf`,`f857614`,`07375fe`,`19b99af`)
- **Output file:** `workstream/fidelity-report-S-104.md`
- **AC coverage status:** 7/7 covered, 7/7 Pass
- **Overall fidelity verdict:** High · **Highest drift impact:** Minor
- **Blocking gaps:** none (audit is non-blocking; drift routes to `product-engineer`'s `activity-drift-reconciliation`)
