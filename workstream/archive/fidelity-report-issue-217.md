# Fidelity Report — Issue #217 (Audit Mode)

> **Mode:** Audit (post-implementation). **Agent:** verifier.
> **PR head:** `issue/217-nextjs-16-node-26` @ `73300cc`. **Base:** `main`.
> **Sources:** `workstream/test-plan-issue-217.md` v1.1, `workstream/traceability-matrix-issue-217.md`,
> refinement v1.1 (AC1–AC9), decisions D-01..D-16.

## Verdict

**Fidelity: High. Highest drift impact: Minor. Drift findings: 2 (both out-of-scope / pre-existing, non-blocking).**

Every mechanically-testable AC (AC1–AC8) is covered by ≥1 positive and ≥1
negative/edge test and passes on Node 26. AC9 is post-merge/human-only
(uncovered-by-design, F-03). The ADR-007/ADR-008 hard invariant — the auth gate
behaves identically after the Edge→Node rename — holds: the full security-negative
set (SEC-01…SEC-20, less the live-only SEC-13/17/18/19) passes against `proxy.ts`.

## AC-by-AC

| AC | Result | Evidence |
| -- | ------ | -------- |
| **AC1** pins/Node 26/engines | **PASS** | `next`/`eslint-config-next` 16.4.1, companions exact (incl. `@types/node` 26.6.5, D-14); `.nvmrc` ×2 / `ci.yml` / `Dockerfile.panel` = 26; both `engines.node` `>=24 <27`; CI gains a `node -v`=v26 assertion step (F-02). |
| **AC2** `proxy.ts` gates identically | **PASS** | `middleware.ts` absent, `proxy.ts` present (named `proxy` + default export, no route-segment `runtime`). Gate suites retargeted and green: `proxy-gate` (26), `auth-route-policy` (20), `auth-no-getsession` (3, `AUTHZ_FILES`=`proxy.ts`), `internal-secret` (10). SEC-01..SEC-12, SEC-14..SEC-16, SEC-20 pass; new D-15 timeout tests (never-resolving→302/401, internal unaffected, timer cleared). E2E `auth.spec.ts` green. Image route probes: `/`→302, `/login`→200, SSE→401, internal POST→401. |
| **AC3** validate + E2E + make validate | **PASS** | `make validate` exit 0 both branches on Node 26 (Python: 462 + 714; JS: 1535 passed incl. Layer 2.5 live, audit clean). `pnpm --filter panel run test:e2e` 26/26 passed (local Supabase stack). |
| **AC4** native flat config, zero downgrades, SD2 | **PASS** | `eslint.config.mjs` spreads `eslint-config-next/core-web-vitals` + `/typescript`; `FlatCompat`/`@eslint/eslintrc` removed (dep dropped). Lint exit 0 with **zero** rules disabled/downgraded (fix ledger in PR). `eslint-server-import.test.ts` (SD2) green. |
| **AC5** image smoke on node:26-slim | **PASS (local)** | Image built on `node:26-slim` (corepack-via-npm fix); PID 1 uid/gid 1001, `:8080` serves, missing `/.fly/api` non-blocking, `setpriv` present, + route assertions (D-16). CI step updated; the job-level assertion runs on the GitHub runner. |
| **AC6** audit | **PASS** | `pnpm --filter panel run audit` clean — no `next` advisory, no new high/critical. |
| **AC7** CDK member on Node 26 | **PASS (install+build); test pre-existing-fail** | `pnpm --filter …/cdk install` + `tsc` build pass on Node 26. The single jest test fails identically on Node 24 **and** 26 (cwd-sensitivity in the `@aws/agentcore-cdk` L3 construct, not in CI) → **not** a Node-26 regression, does **not** trigger D-06 fallback. Finding AF-01. |
| **AC8** ADR-008 + doc refs | **PASS** | `docs/adr/ADR-008-*.md` present; `technical-guidelines.md` chokepoint section + 1.50 pin row; `panel/README.md`, runbook, root README, roadmap updated `middleware.ts`→`proxy.ts` / Node 26. |
| **AC9** post-merge release + live invoke | **UNCOVERED-BY-DESIGN** | Human-only release tag → `deploy-panel.sh` (auth gate 1–5 + OIDC probe) → live invoke. Sub-tasks 1.20–1.21. (F-03) |

## Security-negative set (Edge→Node, mandatory)

SEC-01..SEC-12, SEC-14, SEC-15, SEC-16, SEC-20 — **PASS** (component/unit against
`proxy.ts`). SEC-05 (never-resolving `getClaims`) now has a concrete, bounded
assertion thanks to D-15 (was a gap at Design time). SEC-13/17/18/19 are the
live release-gate negatives (AC9, post-merge). Contracts C-1/C-2/C-3 (CON-01..10)
hold — the `internal` branch passes through (never 200), the gate calls only
`getClaims`, the cookie-threading response is returned on success.

## Drift findings

| ID | Finding | Impact | Intent | Route |
| -- | ------- | ------ | ------ | ----- |
| **AF-01** | The `agents/dependency-update/agentcore/cdk` jest test fails on both Node 24 and 26 (cwd-sensitivity in a third-party L3 construct). Not Node-26-induced, not in CI; install + build pass. #217 must not modify agent code. | Minor | Unintended (pre-existing) | `product-engineer` (track a separate issue to fix the CDK test cwd setup) — out of #217 scope. |
| **AF-02** | `TESTING.md` still states Node `>=22 <25` / "Node 22 pinned" and cites the Node-26 engine-strict rejection as a "harness defect". No test **command** changed (D-10 said update TESTING.md only if commands change), so `developer` left it; but the Node-version facts are now stale. | Minor | Unintended | `technical-writer` (refresh the Node-version facts in `TESTING.md`). |

Neither finding blocks completion (both are out-of-#217-scope documentation/pre-existing-test items). Remediation routes to `product-engineer`/`technical-writer` per the drift-reconciliation flow.
