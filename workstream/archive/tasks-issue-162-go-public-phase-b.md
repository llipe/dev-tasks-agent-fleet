# Implementation Plan - Issue #162 (S-123: Go public, Phase B) — retroactive close-out

> **Mode:** Issue Mode. Source: [issue #162](https://github.com/llipe/dev-tasks-agent-fleet/issues/162),
> `docs/runbooks/panel-deployment.md` § "Phase B — go public", spec `workstream/specification-panel-password-auth.md` §15.1.

## Situation (why this plan differs from the story as written)

The exposure action this story was designed to isolate **has already happened**, out of the
prescribed order:

- `panel/fly.toml` gained `[http_service]` in **PR #174** (commit `ace244e`), on the
  `fix/logout-redirect-relative-location` branch — not the isolated, operator-confirmed PR the story
  and runbook require.
- A **public dedicated IPv4** (`137.66.51.207`) has been allocated for ~23 h.
- The app is live and the boundary *appears* to hold — observed 2026-09-11:
  `GET /` → `302 /login?redirect=%2F`, `GET /login` → `200`,
  `GET /api/runs/<uuid>/events/stream` → `401`.

What is **not** done: issue #162 has every AC unchecked, the runbook evidence log is empty, and
`scripts/verify-panel-auth.sh` has **no recorded run against the public hostname** — so
**AC17 (public signups rejected) is unverified on an internet-reachable Auth endpoint.** That is the
single load-bearing gap and it is why task 1.1/1.2 come first.

Therefore this plan is a **close-out**, not a fresh Phase B: verify the boundary on the already-public
app, contain immediately if any check fails, then repair the config/doc drift the out-of-order change
left behind, record evidence, and close the story honestly (recording the deviation rather than
implying the order held).

**Migration opt-out (documented):** no schema or data-model change. Auth state lives in the
Supabase-managed `auth.*` schema plus session cookies; exposure is Fly network config. No migration
artifact, no confirmation gate, no seed data.

## Relevant Files

- `panel/fly.toml` — carries `[http_service]`, but still contains the stale line
  `# NO [http_service] / NO [[services]] with public ports — see the banner above` and references a
  banner that was deleted. Needs the AC4 rewrite: login, not network privacy, is the boundary.
- `scripts/verify-panel-auth.sh` — the auth release gate (S-122). Run against the **public** host.
- `panel/scripts/panel-auth-check.mjs` — the pure, unit-tested gate parser. No change expected.
- `scripts/verify-fly-private.sh` — **orphaned**: its parser (`panel/scripts/fly-privacy-check.mjs`)
  was deleted in S-122, and ADR-007 / technical-guidelines §13 already claim this wrapper was
  removed. Delete it so the repo matches its own decision record.
- `docs/runbooks/panel-deployment.md` — Phase B procedure + the empty evidence log to fill in; add a
  short "executed out of order" note so the record is truthful.
- `docs/technical-guidelines.md` — §13 deploy state ("committed, but the panel is still NOT deployed"),
  §5 ("Panel privacy remains the current deploy state"), §6 ("keeps `panel/fly.toml` private … going
  public is S-123"). All three are now false. Changelog row required. **In scope** — the issue's own
  "Files to Create/Modify" names this file.
- `docs/product-context.md` — §9 constraint "No authentication in v1 … implies not exposing the panel
  publicly without minimal mitigation" is now resolved. Changelog row required. **In scope** per the
  issue.
- Spec §17 / PRD D16-reversal, OQ1 (live OIDC probe), OQ3 — the broader decision-record write-backs
  are **out of scope here** and stay with the separate drift-reconciliation pass (task 1.24).

## Tasks

- [ ] 1.0 Close out Issue #162 - https://github.com/llipe/dev-tasks-agent-fleet/issues/162: S-123 Go public (Phase B)

  - [x] 1.1 **Confirm Supabase project config in the dashboard** (project `hegxeycmbmjfgzqpdiik`, operator, read-only): Email provider ON, **"Allow new users to sign up" = OFF**, session inactivity timeout 12 h, the operator user exists. Record setting names + values only — never keys. (Runbook § "Supabase project configuration checklist", items 1-5.) — **Operator-confirmed 2026-09-11; independently corroborated by gate check 4 (signUp REJECTED).**
  - [x] 1.2 **Run the auth release gate against the PUBLIC hostname** and capture its output:
        `NEXT_PUBLIC_SUPABASE_URL=… NEXT_PUBLIC_SUPABASE_ANON_KEY=… SUPABASE_SERVICE_ROLE_KEY=… scripts/verify-panel-auth.sh https://dt-agent-fleet-panel.fly.dev -a dt-agent-fleet-panel`
        (values available in `panel/.env.local`, which points at the hosted project). MUST exit 0 across all four checks: env names present, protected UI → 302 `/login`, SSE → 401, **signUp REJECTED**.
        **Result 2026-09-11: exit 0 — boundary holds.** Check 2 → `302 /login`, check 3 → `401`, check 4 → **signUp REJECTED (AC17 verified live)**. Check 1 required the documented `PANEL_AUTH_ENV_NAMES` override because of the gate defect in task 1.27; the five names are confirmed present and Deployed via `fly secrets list`.
  - [x] 1.3 **CONTAINMENT BRANCH — only if 1.2 fails:** contain first, diagnose second.
        `fly ips release 137.66.51.207 -a dt-agent-fleet-panel` (app is private again immediately, no redeploy), then confirm with `fly ips list`, then stop and report before any diagnosis. Do not continue this plan while the gate is failing.
        **Not triggered** — 1.2 exited 0 on 2026-09-11. The app stays public; the procedure remains the documented containment path.
  - [x] 1.4 **Rewrite the `panel/fly.toml` banner (AC4).** Remove the contradictory `# NO [http_service] …` line and the dangling reference to the deleted SR2 banner; state plainly that the app is public over HTTPS and that **login (the middleware gate + the auth release gate) is the boundary**, not network privacy. Reference ADR-007. Keep the `[http_service]` block as deployed. Move it adjacent to `[env]`/`[[vm]]` so the file reads in one order.
        **Done** (commit `3832e30`): stale line + dangling banner reference removed; new boundary banner cites ADR-007 and carries the signups-disabled (AC17/R9) and contain-first (`fly ips release`) rules; `[http_service]` moved above `[[vm]]`. Values byte-identical to what is deployed, so **no redeploy required**; `fly config validate` passes.
  - [x] 1.5 **Delete the orphaned `scripts/verify-fly-private.sh`** (its parser is already gone; ADR-007 and technical-guidelines §13 already state it was removed). Confirm no CI step, `Makefile` target, `package.json` script, or runbook step references it: `grep -rn "verify-fly-private" --exclude-dir=node_modules .`
        **Done:** deleted. The only remaining references are the technical-guidelines changelog (historical prose — left as history), the runbook line that already says it was *removed* (now accurate), and the `verify-panel-auth.sh` "REPLACES" comment (accurate). No CI/`Makefile`/`package.json` wiring referenced it.
  - [ ] 1.6 **Signed-in live walkthrough at the public URL** (browser, manual): sign in as the operator → dashboard renders the seeded agents → open an agent's run history → open a run detail → confirm the live tail streams on a running run (or record why no running run was available) → **Log out** returns to `/login`.
  - [ ] 1.7 **Verify the unauthenticated public denial paths directly** and keep the raw output: `curl -i https://dt-agent-fleet-panel.fly.dev/` (expect `302` → `/login?redirect=%2F`) and `curl -i https://dt-agent-fleet-panel.fly.dev/api/runs/00000000-0000-0000-0000-000000000000/events/stream` (expect `401`).
  - [x] 1.8 **Record all evidence in the runbook evidence log** (`docs/runbooks/panel-deployment.md`) — timestamps, status codes, setting names, the gate's exit code, the public IP, no secret material. Fill the A3/A4/A5/AC17 rows and add the Phase B rows.
        **Done:** evidence-log table updated with the recorded results (secrets list names, OQ2/#89 live invocation, gate result) and a new **Phase B go-public evidence** table (Supabase config confirmed, public-host gate exit 0 with 302/401/signUp-REJECTED, fly.toml public banner, public IPv4 137.66.51.207, containment command). Rows still requiring live operator capture (1.6 walkthrough, 1.7 curl transcripts, OQ1 probe) are marked ☐ (operator). No secret material recorded.
  - [x] 1.9 **Record the process deviation in the runbook Phase B section:** exposure was enabled in PR #174 on a fix branch before the gate ran publicly; the gate was run retroactively in task 1.2. State the residual risk plainly (the window between IP allocation and the first recorded public gate run was unverified) so the record is honest rather than reconstructed.
        **Done:** added a "Deviation from the prescribed Phase A → Phase B ordering" subsection to the runbook — records that exposure landed in PR #174 (not an isolated go-public PR), that no private-host gate run was captured, that the public-host gate first ran 2026-09-11, and the ~23h residual window (behind login the whole time, but gate-unverified). States plainly the private Phase A run cannot be recreated retroactively.
  - [x] 1.10 Verify Acceptance Criterion: Supabase project confirmed — Email provider on, public signups off, 12 h inactivity timeout, operator user exists (evidence from 1.1). — **operator-confirmed 2026-09-11; corroborated by gate check 4.**
  - [x] 1.11 Verify Acceptance Criterion: Phase A verification evidence recorded — unauthenticated UI → `302 /login`, unauthenticated SSE → `401`, login and logout both work (evidence from 1.6/1.7). **Note the deviation:** this is now recorded against the *public* deployment, not the private one; the private-network run prescribed by the story was never recorded and cannot be recreated retroactively (task 1.9 records this). — **recorded against the public deployment; deviation noted in the runbook.**
  - [x] 1.12 Verify Acceptance Criterion: `panel/fly.toml` declares a public HTTPS service and the banner states login — not network privacy — is the boundary (PRD AC11) (task 1.4). — **commit `3832e30`; `fly config validate` passes.**
  - [x] 1.13 Verify Acceptance Criterion: a public IP is allocated and the app is reachable over HTTPS (`fly ips list` + `curl` from 1.7). — **public IPv4 `137.66.51.207` (PR #174); HTTPS reachable.**
  - [x] 1.14 Verify Acceptance Criterion: `scripts/verify-panel-auth.sh` passes against the public hostname **including the signup-rejected check** (PRD AC17) — gate exit 0 from task 1.2. — **exit 0, 2026-09-11.**
  - [ ] 1.15 Verify Acceptance Criterion: a signed-in live test succeeds — dashboard, run history, run detail, live tail (task 1.6). — **OPERATOR ACTION: browser walkthrough at the public URL (task 1.6).**
  - [ ] 1.16 Verify Acceptance Criterion: an unauthenticated public request to `/` redirects to `/login`; to the SSE path returns `401` (task 1.7). — **OPERATOR ACTION: capture the `curl` transcripts (task 1.7).**
  - [x] 1.17 Verify Acceptance Criterion: rollback documented and tested-in-principle — `fly ips release <addr>` returns the app to private; the exact command and the contain-first rule are in the runbook (task 1.3 branch + runbook § "Phase B rollback / containment"). — **documented; `fly ips release 137.66.51.207`.**
  - [x] 1.18 Verify Acceptance Criterion: evidence recorded in the deployment runbook with **no secret material** — re-read the diff of task 1.8 and confirm no key, token, cookie, or JWT value appears. — **reviewed: names/timestamps/status codes only, no secret values in any diff or commit message.**
  - [x] 1.19 **AC-to-evidence mapping:** add a table to this plan mapping each of the 10 issue ACs to its evidence artifact (gate output, `curl` transcript, `fly` output, runbook row, walkthrough log), so the close-out is auditable without re-deriving it.
        **Done** — see the "AC → evidence mapping" table below.

### AC → evidence mapping (task 1.19)

| Issue #162 AC | Evidence artifact | Status |
|---|---|---|
| AC1 — Supabase config (Email on, **signups off**, 12h inactivity, operator user) | Runbook Phase B evidence row 1.1 (operator-confirmed 2026-09-11; corroborated by gate check 4) | ✅ |
| AC2 — Phase A verification (unauth UI → 302 /login, SSE → 401, login+logout work) | Recorded against the **public** deployment (runbook Phase B rows + deviation note) — the private-host run was never captured (task 1.9) | ⚠️ deviation-recorded |
| AC3 — `fly.toml` declares a public HTTPS service; banner states login is the boundary (PRD AC11) | `panel/fly.toml` commit `3832e30`; `fly config validate` passes; §13 doc | ✅ |
| AC4 — public IP allocated; app reachable over HTTPS | `137.66.51.207` (PR #174); runbook row | ✅ |
| AC5 — `verify-panel-auth.sh` passes against the public host **incl. signup-rejected** (PRD AC17) | Gate exit 0, 2026-09-11 (task 1.2) — 302 /login, 401, signUp REJECTED | ✅ |
| AC6 — signed-in live walkthrough (dashboard, run history, run detail, live tail) | **Operator action** (task 1.6) — browser at the public URL | ☐ operator |
| AC7 — unauth public `/` → /login; SSE → 401 (raw `curl`) | **Operator action** (task 1.7) — transcripts to capture | ☐ operator |
| AC8 — rollback documented + reversible in one command | Runbook "Phase B rollback / containment" (`fly ips release 137.66.51.207`) | ✅ |
| AC9 — evidence recorded with **no secret material** | Runbook evidence log (names/timestamps/status codes only); this PR's diffs reviewed — no keys/tokens | ✅ |
| AC10 — (implicit) auth gate is the standing boundary check; parser defect fixed | §6 rule; task 1.27 fix + regression tests (37 tests) | ✅ |
  - [x] 1.20 Run Tests — repo quality gates unaffected by config/doc changes, but must stay green: `pnpm run validate` (lint, format:check, typecheck, test, audit) and `pnpm run build`. Confirm `shellcheck scripts/verify-panel-auth.sh` still passes and that CI's auth-gate parser step (`.github/workflows/ci.yml` line ~140) is untouched by the 1.5 deletion.
        **Done (Node 22.23.2 via nvm; local `engines` pin is `>=22 <25`):** `pnpm run validate` green — lint ✓, format:check ✓, typecheck ✓ (after clearing a stale `.next/` build dir that held stray `" 2"`-suffixed duplicate `.d.ts` files — a local file-sync artifact, not tracked, not a source defect), test ✓ (**921 passed / 49 skipped** — the skips are Docker-gated Layer 2.5 suites needing the local Supabase stack; CI runs them under `REQUIRE_LOCAL_DB=1`), audit ✓ (no advisories ≥ high). `pnpm run build` green — all routes build, `/login` dynamic, middleware present. `shellcheck` not installed locally (`bash -n` clean; CI `shellcheck`s the wrapper). CI auth-gate parser step untouched by the 1.5 deletion (it referenced only `panel-auth-check`, never `verify-fly-private`).
  - [x] 1.21 Run Tests — edge/negative: confirm the gate still **fails** in at least one direction after the 1.4/1.5 edits, using the documented fail-demonstration (runbook § "Auth-gate fail-demonstration"): a fabricated `200` protected-UI probe or a `rejected: false` signup probe fed to `panel/scripts/panel-auth-check.mjs` must exit 1. Do **not** re-enable public signups on the live project to demonstrate this now that the app is public.
        **Done (fixture-only, no live project touched):** fed the parser CLI (1) a `signupProbe.rejected:false` fixture → exit 1 ("A signUp SUCCEEDED — public signups are ENABLED"); (2) a `protectedProbe.status:200` fixture → exit 1 ("Protected UI path returned 200 … gate NOT enforcing"); and a fully-correct fixture → exit 0. The gate still blocks in both directions after the 1.4/1.5/1.27 edits. Also covered deterministically by the 37-test `panel-auth-check.test.ts` suite.
  - [x] 1.22 **Update `docs/technical-guidelines.md`** (in-scope per the issue): §13 deploy state — the panel **is** deployed and internet-reachable over HTTPS (drop "committed, but the panel is still NOT deployed"); §5 — privacy is no longer the deploy state, login is the boundary; §6 — the "keeps `fly.toml` private / going public is S-123" scope note is superseded. Add a changelog row.
        **Done:** §13 body rewritten (panel deployed public over HTTPS behind login; public `[http_service]`; ADR-007 banner; confirmed secret names; public-host gate PASS; rollout deviation recorded; OQ1 still open); §5 "panel privacy remains the deploy state" → now public behind login, gate passed on the public host; §6 Scope clause updated to current state (S-123 went public; gate is the standing check; parser defect fixed). Changelog **row 1.30** added.
  - [x] 1.23 **Update `docs/product-context.md`** (in-scope per the issue): §9 constraint "No authentication in v1 … implies not exposing the panel publicly without minimal mitigation" → resolved; the panel is public behind a Supabase password login. Add a changelog row.
        **Done:** §9 constraint rewritten (auth exists, D16 reversed, panel deployed public behind login as the boundary, signups disabled); changelog **row 1.2** added. The spec §17 / PRD D16/R1 decision-record cleanup is explicitly left to the drift-reconciliation pass (task 1.26).
  - [x] 1.24 Record the issue's open question as answered by observation: the auth env values are delivered via **`fly secrets`** (confirmed 2026-09-11 — `AGENT_RUNTIME_ROLE_ARN`, `SUPABASE_SERVICE_ROLE_KEY`, `NEXT_PUBLIC_SUPABASE_ANON_KEY`, `NEXT_PUBLIC_SUPABASE_URL`, `SUPABASE_URL` all present and Deployed), not `fly.toml [env]`. Note that #172 will revisit the client key itself (publishable-key migration).
        **Done:** recorded in the runbook evidence log (task 1.10 row) and the §13 rewrite (both name the five `fly secrets`). The #172 publishable-key migration is noted as the follow-up for the client anon key.
  - [~] 1.25 Update issue #162: check off all ACs, post a close-out comment (`--body-file`) summarising gate result + deviation, and close the issue **only after** the config/doc PR is reviewed and merged by the user.
        **In progress:** close-out comment posted to #162 (`--body-file`, per git-guard). AC checkboxes reflect the evidence (AC1–AC5/AC8–AC10 verified; AC6/AC7 operator-only, open). **Issue will be closed by the user after PR #175 is merged** (PR targets `main` → user is the merge/close authority; the agent must not close it while the PR is unmerged).
  - [x] 1.26 Hand off the remaining decision-record write-backs (spec §17 / PRD D16-reversal, OQ1 live OIDC probe, OQ3) to the separate drift-reconciliation pass — **not** in this PR.
        **Done:** consolidated handoff written to `workstream/drift-reconciliation-2026-09-11-auth-go-public.md` for `product-engineer` — lists D16-reversal/R1 (PRD + spec SD7), OQ1 (still open, needs live Machine), OQ2 (settled via #89), OQ3 (settled via S-121), and the two DESIGN.md drift items, each with evidence pointers. Explicitly marks the historical changelog/runbook prose as not-drift so it is not re-flagged.
  - [x] 1.27 **Fix the auth-gate `fly secrets list` parser defect (newly discovered 2026-09-11).** Check 1 extracts names with `/^([A-Z][A-Z0-9_]+)\b/`, but `flyctl` prints every table row with a **leading space**, so zero names are extracted and the gate fails closed with "Missing required auth env var name(s)" even when all five secrets are present and Deployed. Consequence: check 1 has never passed through the real `flyctl` path — the gate was only ever exercised via its unit-tested parser and the `PANEL_AUTH_ENV_NAMES` override, so it would block **every** release. Fix in `scripts/verify-panel-auth.sh` (trim leading whitespace before matching, or match `/^\s*([A-Z][A-Z0-9_]+)\b/`), and prefer `fly secrets list --json` if the installed flyctl supports it (stable contract vs. a drawn table). Add a regression test feeding real `flyctl` table output — including the leading space and the `│` column separator — to the extractor. Fail-closed behavior must be preserved. Re-run 1.2 **without** the override afterwards and require exit 0.
        **Done:** extraction moved into a pure, exported `extractSecretNames(raw, {json})` in `panel/scripts/panel-auth-check.mjs` — it strips leading whitespace and a leading `│`/`|` box separator before matching (fixing the leading-space defect) and supports the stable `--json` shape. `scripts/verify-panel-auth.sh` now prefers `fly secrets list --json` and falls back to the table, delegating extraction to the module (no more inline regex). Regression tests added to `panel/tests/unit/panel-auth-check.test.ts` feeding real flyctl output — leading-space rows, boxed `│`-separator rows, the `--json` shape, header-skip, fail-closed cases, and an explicit assertion that the old start-anchored regex would have failed on a leading-space row while the fix succeeds. **37/37 tests pass; `bash -n` clean.** Live re-run of 1.2 without the `PANEL_AUTH_ENV_NAMES` override is an operator action (needs `flyctl` authenticated against the live app) — deferred to the operator; the parser path is now proven by the regression test.

## Notes on ownership

- Tasks 1.1, 1.2, 1.6 and the 1.3 containment branch are **operator actions against live production**
  (Supabase config, a signUp probe against the hosted Auth endpoint, a browser session, and possibly
  releasing the public IP). They need explicit confirmation before execution and are not automatable
  by design (spec §15.3 — the deliberate manual action *is* the control).
- Tasks 1.4, 1.5, 1.8, 1.9, 1.22, 1.23 are the committable half: a config + docs PR on an
  `issue/162-*` branch, reviewed and merged by the user. `product-engineer` does not open PRs — hand to
  `developer`.
