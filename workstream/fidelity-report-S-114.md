# Fidelity Report — Story S-114 (Playwright E2E + CI Layer-2.5 gating)

## Header / Verdict

- **Overall fidelity: HIGH**
- **Highest drift impact present: Minor**
- **Scope:** Story S-114 · issues #127 (Playwright E2E) + #134 (make Layer 2.5 gating in CI) · branch `story/S-114-e2e-and-ci-gating` · PR #153
- **Mode:** Audit (grey-box). Cross-checked against the codebase, `/workstream` artifacts, the test suite, and PRD/spec intent.
- **Result:** 9/9 story acceptance criteria Pass. All drift is Minor and Intended. This audit is additive and non-blocking; it does not gate PR/issue completion and does not replace the `test`/`lint`/`format:check`/`typecheck`/`audit` gates.

---

## Human-readable summary — what was delivered and why it holds up

S-114 was a tests-and-CI story: it wrote the end-to-end test suite that proves the panel's four screens and two route handlers actually work together, and it made the database-backed tests count for something in CI. No product feature changed, and there was no database change (a documented, legitimate opt-out).

Two things needed to be true, and both are:

1. **The end-to-end tests are real, not theatrical.** Each of the seven scenarios drives a real browser against the real local database and checks the result two ways: what a person sees on screen *and* what actually landed in the database. Nothing is faked at the data layer. The one external system that must not be called for real — AWS AgentCore — is intercepted at the network wire, not mocked away, so the panel still runs its genuine credential-selection and request-signing code; it just never reaches Amazon. That is exactly the boundary the story asked for. Every scenario traces back to a specific product requirement, and that mapping is written down in `TESTING.md`.

2. **A green CI now genuinely means the database tests ran.** Before this story, the database-backed tests would quietly *skip themselves* whenever Docker was missing — so CI could go green while proving nothing about the database boundary. The fix is a single environment switch (`REQUIRE_LOCAL_DB=1`) that CI sets: with it on, a test that would have skipped instead *fails loudly*. The team proved this works the only way that counts — they deliberately broke two safety checks (the run-status derivation and the "outsiders can't read the database" rule), watched CI turn red for the right reason each time, and reverted. That closes the long-standing "G2" gap that earlier stories kept deferring.

The one wrinkle worth knowing about: the tests run the app in development mode rather than a production build, because a production build currently trips over an unrelated, pre-existing defect in a different file (an SSE route from an earlier story exports a helper function that production builds reject). That defect is not part of this story and has been handed to product-engineering. Running in dev mode exercises the same behavior the scenarios check, so the tests remain valid — but it does mean this suite would not have caught that build defect, which is why flagging it matters.

---

## Per-AC result table

| AC | Description | Codebase evidence | Workstream evidence | Test evidence | Result |
| --- | --- | --- | --- | --- | --- |
| AC1 | Playwright runs against local stack, seeded agent, AgentCore stubbed at network boundary (no AWS call) | `agentcore-stub.ts` (HTTP server, not a mock of `lib/aws/*`); config points `AWS_ENDPOINT_URL_BEDROCK_AGENTCORE` at fixed-port stub; `global-setup.ts` seeds + asserts catalog | tasks 1.4–1.8, 1.17 checked; stub-at-boundary Context Note | invoke path reaches stub with real `fromNodeProviderChain` branch; catalog asserted in setup | **Pass** |
| AC2 / Scenario 1 | invoke → `/runs/[id]`; `runs` row `queued` + all 3 timeout snapshots non-null | `invoke.spec.ts` asserts via `readRun` on real DB: `status==='queued'`, `max_runtime_seconds`/`grace_seconds`/`start_timeout_seconds` not null | task 1.9; TESTING table → AC12 (D1/OQ3) | UI navigation + DB row assertion, both present | **Pass** |
| AC3 / Scenario 2 | live tail: inserted `run_events` appear with no reload (AC6) | `live-tail.spec.ts` inserts events after page open, asserts DOM text visible, never reloads | task 1.10; TESTING → AC6 (FR12) | non-vacuous: waits for a unique marker inserted post-open | **Pass** |
| AC4 / Scenario 3 | reconnect after mid-stream drop → no dup/no gap (SD6) | `live-tail.spec.ts` uses `context.setOffline` to drop, inserts during gap, asserts each marker `toHaveCount(1)` and DOM order `[1,2,3]` | task 1.11; TESTING → SD6 | strong exactly-once + ordering assertion, not an open-count proxy | **Pass** |
| AC5 / Scenario 4 | stale `running` reads `timed_out` with reaper off (AC10) | `stale-and-artifact.spec.ts` seeds started 3800s ago vs 3720 threshold; asserts "Run timed out" banner + "timed out" pill; raw column stays `running` (proven by smoke test) | task 1.12; TESTING → AC10 (SD4) | asserts read-time derivation via `v_runs`, reaper never invoked | **Pass** |
| AC6 / Scenario 5 | invalid param blocked; no `runs` row (AC13) | `invoke.spec.ts` — client: Run disabled with no repo; server: direct POST invalid enum → 4xx, `countRuns()===0`, `latestRunId()===null` | task 1.13; TESTING → AC13 | dual-path (client guard + server authority) + DB no-insert assertion | **Pass** |
| AC7 / Scenario 6 | density variant survives reload (AC9) | `density.spec.ts` clicks Cards, asserts `localStorage` key `panel.dashboard.density==='cards'`, reloads, asserts `aria-pressed` persists | task 1.14; TESTING → AC9 | UI + storage assertion across reload | **Pass** |
| AC8 / Scenario 7 | failed run shows `pull_request` artifact link (AC14) | `stale-and-artifact.spec.ts` seeds failed run + `pull_request` artifact; asserts link `href` == seeded URL + `rel=noopener` | task 1.15; TESTING → AC14 | asserts artifact renders on a red run, https-only guard honored | **Pass** |
| AC9 | `test:e2e` explicitly gated with recorded reason; scenario-to-AC table in `TESTING.md` | `test:e2e` excluded from `make validate` (browser needed), run in dedicated CI step; `TESTING.md` E2E row + full traceability table present | tasks 1.19, 2.8 | table complete (7 scenarios + edge cases), gating reason recorded | **Pass** |

**#134 (folded-in, parent task 2.0) — gate closure:**

| Check | Evidence | Result |
| --- | --- | --- |
| `REQUIRE_LOCAL_DB=1` turns a Docker-gated skip into a hard failure | `db.ts` `probeLocalDb()` **throws** when `requireLocalDb()` and the stack is unreachable | **Pass** |
| Uniform across all Layer 2.5 suites (no per-suite change) | all 13 integration suites call `await probeLocalDb()` at module top-level → a throw fails the file; verified by grep across `panel/tests/integration/*.test.ts` | **Pass** |
| Local ergonomics preserved (unset → skip with reason) | `probeLocalDb` returns `{available:false, reason}` when unset; `TESTING.md` skip policy documents it | **Pass** |
| CI wires stack + env + gate | `ci.yml` panel job: `supabase start` → `db reset` → export env → `REQUIRE_LOCAL_DB: "1"` → gated `test:coverage` + E2E | **Pass** |
| Negative demos observed (a gate never seen failing is unproven) | `workstream/s114-negative-demos.md` records both RED captures (status-parity on inverted comparison; rls-deny-all on permissive anon policy) then revert | **Pass** |

---

## Drift catalog

All drift below is **non-blocking to completion** (per verifier operating rule 8).

### D1 — Production build fails on a pre-existing non-route export; E2E uses `next dev`
- **Impact: Minor. Intent: Intended (pre-existing defect, correctly routed).**
- **Evidence:** `panel/app/api/runs/[id]/events/stream/route.ts` exports `parseAfterSeq` (line 37) — a non-standard export the Next.js App Router route type-validator rejects during `next build`. Confirmed present. `playwright.config.ts` `webServer.command` uses `pnpm exec next dev` and documents why in a block comment.
- **Assessment:** This is a real latent defect from S-110, not introduced by S-114, and it is correctly flagged to product-engineer. Using `next dev` is a legitimate choice for a test story. **Consequence to record honestly:** because the suite never runs a production build, this E2E layer cannot catch build-time route-contract regressions — the very class of defect it just tripped over. That is an inherent coverage limitation of the chosen server mode, worth carrying forward to S-115 (which *will* need a production build/Docker image to deploy).
- **Recommendation:** `product-engineer` — fix the route export (move `parseAfterSeq` to a `lib/` module) before or during S-115, since deployment requires a green `next build`.

### D2 — Local `service_role` SELECT grant reproduced in E2E global-setup
- **Impact: Minor. Intent: Intended (documented §7 asymmetry).**
- **Evidence:** `global-setup.ts` `grantServiceRoleSelectLocalOnly` grants `all privileges` on public tables/sequences to `service_role` only, mirroring the platform-default grant that `supabase db reset` does not reproduce (technical-guidelines §7). Scoped to `service_role`, never `anon`.
- **Assessment:** Consistent with the established S-104 pattern (the `queries` integration test applies the identical grant). RLS deny-all is preserved — the `rls-deny-all` suite still asserts `anon` reads zero rows, and its negative demo (D-B) confirms it is a live gate. No fidelity concern. **Honest limitation, unchanged from prior stories:** the production read path is proven by inference from the documented platform default, not by a live assertion against the hosted project.
- **Recommendation:** No action needed for S-114. (Pre-existing routed item: a live service-role smoke read against the hosted project, owned by a later deploy story.)

### D3 — Grant uses `all privileges`, slightly broader than the "SELECT grant" description
- **Impact: Minor. Intent: Intended.**
- **Evidence:** The setup function is named `grantServiceRoleSelectLocalOnly` and the §7 note frames it as a SELECT grant, but the implementation grants `all privileges`. This is correct for E2E (the invoke route *inserts* the `queued` run, so the E2E `service_role` needs write, unlike the read-only S-104 `queries` test), and the code comment says so. The name/description is narrower than the behavior.
- **Assessment:** Behaviorally correct and intentional; only the label under-describes it. Not a functional defect.
- **Recommendation:** `developer` (optional, cosmetic) — rename to reflect the write grant, or note in the comment that E2E needs write where the read-only S-104 test needed only SELECT. Non-blocking.

### D4 — Scenario 3 induces the SSE drop via `context.setOffline`, not the task's described `route interception`
- **Impact: Minor. Intent: Intended (stronger method than planned).**
- **Evidence:** `live-tail.spec.ts` Scenario 3 comment describes route interception, but the implementation uses `context.setOffline(true/false)`. The task list (1.11) actually specifies `context.setOffline`, so the spec/task and code agree; only an inline comment in the spec file mentions the alternative.
- **Assessment:** The offline approach is a faithful, arguably more realistic drop, and the assertion (exactly-once + seq order after reconnect) is stronger than counting reconnects. Documentation-only mismatch inside a comment.
- **Recommendation:** No action needed.

---

## Non-vacuity assessment (per scenario)

Every scenario asserts through **UI + DB only**, never internal function calls — confirmed by reading each spec:

- **S1/S5 (invoke):** assert on real `runs` rows via `pg` (`countRuns`, `readRun`, `latestRunId`) after a browser submit. S5 additionally exercises server authority with a direct API POST proving zero rows on rejection. **Non-vacuous.**
- **S2 (live tail):** inserts a unique timestamped marker *after* the page is open and asserts it appears without reload. A no-op relay would fail. **Non-vacuous.**
- **S3 (reconnect):** `toHaveCount(1)` per marker + DOM-order equality `[1,2,3]` across an induced offline gap. This is the strongest scenario — it would fail on duplication, gap, or reorder. **Non-vacuous.**
- **S4 (stale):** clocks set past the 3720s threshold; asserts the terminal banner + pill from read-time derivation with the reaper never called. The smoke test independently confirms the raw column stays `running`. **Non-vacuous.**
- **S6 (density):** asserts the concrete `localStorage` value *and* the post-reload `aria-pressed` state. **Non-vacuous.**
- **S7 (artifact):** asserts the exact seeded `href` + `rel=noopener` on a failed run. **Non-vacuous.**
- **Edge cases:** empty-fleet empty state, zero-event detail with a `pageerror` trap asserting no uncaught errors, and two-context concurrent tail. **Non-vacuous.**

The `e2e-fixture.smoke.test.ts` (Layer 2.5) independently pins the seeding fixture's contract, so a fixture regression surfaces there rather than as a confusing E2E flake — a sound design that protects the non-vacuity of everything built on it.

---

## Does #134 genuinely close G2?

**Yes.** G2 was the standing obligation that a green CI must mean the DB-boundary assertions actually ran, not that they skipped vacuously when Docker was absent. The closure is verified structurally and by observation:

1. **Mechanism is centralized, not per-suite.** The throw lives in the shared `probeLocalDb`, and all 13 integration suites call it at module load. A top-level throw fails the Vitest file and cannot be swallowed by `describe.skipIf`. This means future Layer 2.5 suites inherit the gate automatically — no per-suite assertion to forget.
2. **Both directions verified.** Gate on + stack down → 13 files FAIL; gate off + stack down → 13 files skip with a recorded reason (`s114-negative-demos.md`, `TESTING.md`).
3. **The gates themselves are proven live.** The two negative demos (broken `effectiveStatus` → `status-parity` RED; permissive `anon` policy → `rls-deny-all` RED) confirm the gated assertions are non-vacuous and reverted clean. A gate that fails on skip but never on a real defect would be hollow; these are not.

One honest caveat: the enforcement depends on every suite continuing to call `probeLocalDb()` at module top-level. That is the current uniform pattern and is documented, but it is a convention rather than a compiler-enforced invariant — a future suite that queries the DB without routing through `probeLocalDb` would silently escape the gate. Worth a lint/review note, not a blocker.

---

## Edge-case and randomized outcomes

No prior Design-Mode test plan artifact exists for S-114 (Design Mode was not run for this scope), so there is no separate edge-case/randomized catalog to reconcile. The story's own edge-case matrix (empty DB, zero-event run, two concurrent contexts, CI cold-start) is implemented in `edge-cases.spec.ts` + the `global-setup.ts` readiness poll and is covered in the per-AC and non-vacuity sections above. No randomized/fuzz tactics are in scope for this story.

---

## Recommendations (per drift item)

| Drift | Severity | Owner | Suggested next step |
| --- | --- | --- | --- |
| D1 — `next build` fails on `parseAfterSeq` route export | Minor | product-engineer | Move the helper out of the route module before S-115 (deploy needs a green build); already routed. E2E layer cannot catch build-contract regressions — carry to S-115. |
| D2 — local `service_role` grant asymmetry | Minor | (none for S-114) | No action; pre-existing routed item for a live hosted read assertion in a deploy story. |
| D3 — grant is `all privileges`, name says SELECT | Minor | developer (optional) | Cosmetic rename/comment to reflect the write grant E2E needs. Non-blocking. |
| D4 — Scenario 3 drop-method comment vs `setOffline` | Minor | (none) | No action; comment-only, task and code agree. |

---

## Output contract

- **Mode / phase:** Audit / Phase 4 (Reporting & Publication)
- **Source artifacts:** `workstream/tasks-prd-agent-fleet-panel-v2-s114-plan.md`, `workstream/user-stories-prd-agent-fleet-panel-v2.md` (Story S-114), `workstream/specification-prd-agent-fleet-panel-v2.md`, `docs/technical-guidelines.md` §7/§11
- **Codebase read:** `panel/playwright.config.ts`, `panel/tests/e2e/**` (5 specs + global setup/teardown + 4 fixtures), `panel/tests/integration/db.ts` + all 13 integration suites, `panel/app/api/runs/[id]/events/stream/route.ts`, `.github/workflows/ci.yml`, `TESTING.md`, `workstream/s114-negative-demos.md`
- **Output file:** `workstream/fidelity-report-S-114.md`
- **AC coverage status:** 9/9 covered, all Pass; #134 gate closure verified
- **Overall verdict:** Fidelity HIGH; highest drift impact Minor (all Intended)
- **Blocking gaps:** none
- **GitHub publication:** header/verdict + human-readable summary to be posted to PR #153 / issues #127 + #134 (see note below)
