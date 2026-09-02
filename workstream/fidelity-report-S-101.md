# Fidelity Report — Story S-101 (issue #114)

## Verdict

- **Fidelity: High**
- **Highest drift impact present: Minor**
- **Scope:** Story S-101 "pnpm workspace, Next.js panel scaffold, and gate reachability" · issue [#114](https://github.com/llipe/dev-tasks-agent-fleet/issues/114) · PR [#129](https://github.com/llipe/dev-tasks-agent-fleet/pull/129) (draft) · branch `story/S-101-workspace-panel-scaffold`
- **Mode:** Audit (grey-box) · **Note:** drift below is **non-blocking** to completion — this is a mandatory reporting gate, not a quality gate.

---

## What changed and why (plain language)

This story builds the *container* for the whole Phase 2 web panel and wires it into the project's automated quality check on day one — so no future panel work is ever briefly "outside the gate." It does not build any actual screens or features yet.

Concretely, the delivered work:

- Turns the repo into a pnpm workspace and adds a new `panel/` package holding a minimal Next.js 15 app that builds and shows a placeholder page.
- Wires up the test runner (Vitest) with code-coverage from the very first commit, proven by one trivial passing test.
- Extends the root `make validate` command and the CI pipeline so both the existing Python agent **and** the new JavaScript/TypeScript panel are checked together; if either fails, the whole thing fails.
- Puts a security guardrail (an ESLint rule) in place *ahead* of the code it protects: the server-only Supabase client (which will hold the secret database key) cannot be accidentally imported into browser code. There is deliberately no browser-exposed Supabase variable anywhere.

Everything requested was delivered and independently verified by running the actual commands. Three version choices differ from the spec's originally-written pins; all three are deliberate, defensible, and correctly written down. The most notable is that `next` was pinned to `15.5.25` instead of `15.5.4` **specifically to avoid a critical security advisory** in `15.5.4` — a case where deviating from the spec is the safer choice, and the story explicitly instructed re-confirming versions before pinning. None of the deviations affect what the story set out to achieve.

---

## Per-AC results

| AC | Description | Codebase evidence | Workstream evidence | Test / runtime evidence | Result |
|----|-------------|-------------------|---------------------|-------------------------|--------|
| AC1 | `pnpm-workspace.yaml` + root `package.json` exist; clean `pnpm install` succeeds | `pnpm-workspace.yaml` (members `panel`, `agents/.../cdk`); root `package.json` with delegating scripts + `pnpm.overrides` | Task 0.2, 0.17 `[x]` | `pnpm install --frozen-lockfile` → "Lockfile is up to date / Already up to date", exit 0 (no drift) | **Pass** |
| AC2 | `panel/` is a Next.js 15 App Router + TS package that builds and serves a placeholder route | `panel/` (`next.config.ts` with `outputFileTracingRoot`, `tsconfig.json` `strict:true`, `app/layout.tsx`, `app/page.tsx`) | Task 0.4, 0.13, 0.18 `[x]` | `pnpm --filter panel build` → "Compiled successfully", route `/` prerendered (4/4), exit 0 | **Pass** |
| AC3 | Canonical scripts exist at root and delegate to `panel/` | Root `package.json` scripts all `pnpm --filter panel run <s>`; `panel/package.json` defines every canonical script incl. `lint:fix`, `test:unit/integration/e2e` | Task 0.2, 0.19 `[x]` | `pnpm run validate` at root delegates and passes | **Pass** |
| AC4 | `make validate` runs BOTH branches and fails if either fails | `Makefile`: `validate: validate-py validate-js`; `validate-js → pnpm --filter panel run validate` | Task 0.10, 0.15, 0.20 `[x]` | Negative-path probe (failing test) → `make validate-js` exit **2**; `make -n validate` shows Python branch then `pnpm --filter panel run validate` | **Pass** |
| AC5 | CI gains a Node job on every push/PR to `main` | `.github/workflows/ci.yml` `panel-quality` job (pnpm 10.11.0, Node 22, lint/format/typecheck/`test:coverage`/audit) | Task 0.11, 0.21 `[x]` | No `paths:`/`paths-ignore:` filter present (grep → no matches); triggers `push`/`pull_request` on `main` | **Pass** |
| AC6 | Vitest + `@vitest/coverage-v8` wired from first commit; one passing test | `panel/vitest.config.ts` (v8 coverage + unit/component/integration projects); `tests/smoke.test.ts` | Task 0.7, 0.14, 0.22 `[x]` | `vitest run` → 1 passed; `test:coverage` script + provider `v8` present | **Pass** |
| AC7 | `TESTING.md` gains a `panel` row with layers + reachability | `TESTING.md` Packages table `panel` row (Vitest 3.2.4, reachable from `make validate`, jsdom+node projects); E2E row flipped to "config stub only" | Task 0.12, 0.23 `[x]` | Read directly; content matches delivery | **Pass** |
| AC8 | No `NEXT_PUBLIC_SUPABASE_*` anywhere; `.env.example` server-only | No such var in any code/config; `.env.example` documents `SUPABASE_URL` / `SUPABASE_SERVICE_ROLE_KEY` / AWS vars as server-only, with explicit "do NOT prefix with NEXT_PUBLIC_" notes | Task 0.5, 0.24 `[x]` | Repo-wide grep for `NEXT_PUBLIC`: only prose in docs/spec/README (`NEXT_PUBLIC_SUPABASE_*` referenced as *forbidden*); zero variable definitions | **Pass** |

**AC coverage: 8/8 covered and satisfied.** No AC is asserted-but-unmet.

### Business-rule / technical-note checks (beyond the 8 ACs)

| Item | Requirement | Evidence | Result |
|------|-------------|----------|--------|
| SD1 | Panel at `panel/`, not root; `pnpm --filter` scoping | Workspace members correct; panel package name `panel`; root stays neutral | **Pass** |
| SD2 (guard) | ESLint forbids importing `lib/supabase/server` (+ `@/` alias) from components | Temp probe importing both `@/lib/supabase/server` and `../lib/supabase/server` → ESLint exit **2**, both flagged | **Pass** |
| SD12 | Vitest + RTL (Layers 1–2.5), Playwright E2E; not the CDK jest precedent | `vitest`, `@vitest/coverage-v8`, `@testing-library/react`, `@playwright/test` present; no jest in panel | **Pass** |
| §16 pins | Exact pins; all `@aws-sdk/*` same minor | `react`/`react-dom@19.1.1`, `ajv@8.17.1`, `ajv-formats@3.0.1`, `@phosphor-icons/react@2.1.10` exact; AWS SDKs correctly absent (land S-104/S-105/S-111) | **Pass (w/ recorded deviations — see drift)** |
| DESIGN §1.2 | Inter preconnect + stylesheet `<link>` markup | `app/layout.tsx` uses the exact §1.2 markup with a scoped, justified `eslint-disable-next-line @next/next/no-page-custom-font` | **Pass** |
| `force-dynamic` convention | Establish + document | Documented in `panel/README.md` Conventions; no data routes yet to apply it to (correct for S-101) | **Pass** |

---

## Drift catalog

All drift items are **non-blocking to completion.** Each was disclosed by the implementer and is correctly recorded in the code/docs.

### D1 — `next`/`eslint-config-next` pinned to `15.5.25`, not spec's `15.5.4` — **Minor**, **Intended**
- **Evidence:** `panel/package.json` (`next: 15.5.25`, `eslint-config-next: 15.5.25`); build runs on Next 15.5.25; spec §16 line reads `15.5.4`; task 0.6 instructs "re-confirm each is current before pinning."
- **Assessment:** Correct and safer than literal compliance. `15.5.4` carries a critical RCE advisory plus multiple highs; `15.5.25` is the security-patched tip of the same `15.5` minor, so App Router behavior and the spec's minor-line intent are preserved. This is a spec-baseline staleness issue, not an implementation defect.
- **Recommendation:** `product-engineer` — write back the `15.5.x` pin into spec §16 so the doc stops citing a vulnerable version. No code change.

### D2 — Vitest/`coverage-v8` at `3.2.4`, not a `2.x` line — **Minor**, **Intended**
- **Evidence:** `panel/package.json` devDeps; `vitest.config.ts` uses the config-level `projects` API (unit/component/integration).
- **Assessment:** Acceptable. The `projects` API that cleanly maps to the TESTING.md layer taxonomy is a 3.x feature; SD12/§16 named Vitest without pinning a major (`vitest … dev`). Verified working: `vitest run` green, coverage provider `v8` active.
- **Recommendation:** No action needed. Optionally note the `3.x` choice in §16.

### D3 — One residual **moderate** advisory (`ajv` ReDoS, `<8.18.0`) — **Minor**, **Intended**
- **Evidence:** `pnpm audit --prod --audit-level=high` → exit 0, "1 moderate"; JSON shows `ajv` "ReDoS when using `$data`", vulnerable `>=7.0.0 <8.18.0`. Pinned `ajv@8.17.1` (spec §16 exact pin) sits below the `8.18.0` fix.
- **Assessment:** Below the `high` gate the story's `audit` script enforces, so it does not fail the gate. `ajv` is a spec-pinned dependency not yet consumed by any code in this story (used from S-113). The disclosure ("one residual moderate remains") is accurate. `pnpm.overrides` correctly clear the postcss/sharp advisories (verified: `postcss@8.5.26`, `sharp@0.35.4` in lockfile).
- **Recommendation:** `developer` — consider bumping `ajv` to `>=8.18.0` when the S-113 form-validation code lands (still same minor). Non-urgent; `$data` ReDoS path is unused today.

### D4 — DESIGN §1.2 raw `<link>` instead of `next/font` — **Minor**, **Intended**
- **Evidence:** `app/layout.tsx` uses the literal §1.2 preconnect + stylesheet markup with a scoped `eslint-disable-next-line @next/next/no-page-custom-font` and an inline justification comment.
- **Assessment:** Faithful to the canonical visual contract (DESIGN §1.2 prescribes this exact markup). The disable is line-scoped and documented, not blanket. Trade-off (foregoing `next/font` optimization) is a deliberate fidelity-to-DESIGN choice, appropriate to defer any change to the design-token story (S-105).
- **Recommendation:** No action needed. S-105 may revisit if DESIGN adopts `next/font`.

### Non-drift observations (no action)
- **SD2 rule breadth:** the `no-restricted-imports` rule applies to all `.ts/.tsx`, not only `"use client"` files — a *stricter* backstop than the literal SD2 wording, self-documented in the config. Safe over-enforcement; server modules import the Supabase client via other paths so this will not create false positives for legitimate server-side use (the server client is consumed in Server Components/route handlers, which per SD2 read Supabase directly — worth a glance in S-104, but not a defect here).
- **Audit environment:** verification ran on Node **26.7.0** locally (CI pins Node 22). Build/validate/tests all pass on 26; the pinned CI runtime is the source of truth. No divergence observed.

---

## Edge-case & randomized outcomes

No Design-Mode test plan exists for this scope (none required for a scaffold story). The story's own edge-case matrix was exercised directly:
- **JS-branch failure fails the gate:** injected failing test → `make validate-js` exit 2 (then removed). ✅
- **Clean-checkout install, no lockfile drift:** `pnpm install --frozen-lockfile` → up to date, exit 0. ✅
- **SD2 guard fires:** probe import → ESLint exit 2 on both alias and relative forms (then removed). ✅

No randomized/property tests in scope.

---

## Scope-creep check

**None found.** The `panel/` source tree contains only `app/layout.tsx`, `app/page.tsx`, `tests/setup.ts`, `tests/smoke.test.ts`. No `lib/`, `components/`, `styles/tokens.css`, or any `domain`/`aws`/`supabase` logic that belongs to S-104/S-105/S-111 has leaked in. `@supabase/supabase-js` and `@aws-sdk/*` are correctly **absent** (their consuming modules land in later stories); only the SD2 lint guard is present ahead of its module, exactly as the story directs.

---

## Recommendations summary

| Item | Impact | Next step | Owner |
|------|--------|-----------|-------|
| D1 `next` pin `15.5.4` → `15.5.x` in spec §16 | Minor | Spec write-back (doc only) | product-engineer |
| D2 Vitest 3.x note in §16 | Minor | Optional doc note | product-engineer |
| D3 `ajv` → `>=8.18.0` when S-113 lands | Minor | Dependency bump later | developer |
| D4 raw font `<link>` | Minor | None (revisit in S-105 if DESIGN changes) | — |
| SD2 rule breadth vs client-only | — | Sanity-check in S-104 when server client lands | verifier (next audit) |

**All 8 acceptance criteria are genuinely met, verified by executing the actual gates rather than trusting assertions. The four deviations are intended, defensible, and correctly recorded. Fidelity is High; the highest drift impact is Minor; nothing blocks completion.**
