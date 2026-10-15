## Execution status — #217 (refined plan v1.1, sub-tasks 1.1–1.19)

> ⚠️ This issue body predates the v1.1 refinement (it still reads 16.3.5 / Node 24).
> The authoritative executed plan is `workstream/tasks-issue-217-nextjs-16-node-upgrade.md`
> (16.4.1 / Node 26). Sub-tasks **1.1–1.19 are complete**; **1.20–1.21** are
> post-merge, human-only (release tag + live invoke, AC9).

**PR:** https://github.com/llipe/dev-tasks-agent-fleet/pull/304 (Draft → Ready)
**Branch:** `issue/217-nextjs-16-node-26`

### Quality gates (Node 26)

- `make validate` — **PASS**, both branches (Python 462 + 714; JS/TS 1535 tests incl. Layer 2.5 live, audit clean).
- `pnpm --filter panel run test:e2e` — **PASS**, 26/26 (local Supabase stack).
- `next build` (Turbopack) + `node:26-slim` image smoke with route assertions — **PASS** locally.

### verifier Audit Mode

**Fidelity: High · Highest drift impact: Minor · Drift findings: 2 (both out-of-scope / pre-existing, non-blocking).**

AC1–AC8 each covered by ≥1 positive and ≥1 negative/edge test and passing on
Node 26; the ADR-007/ADR-008 hard invariant (the auth gate behaves identically
after the Edge→Node `proxy.ts` rename) holds — the full security-negative set
(SEC-01…SEC-20, less the live-only SEC-13/17/18/19) passes, and D-15 adds the
bounded fail-closed `getClaims()` timeout that closes Design-time SEC-05. AC9 is
post-merge/human-only (uncovered-by-design).

Drift (non-blocking, routed to `product-engineer` / `technical-writer`):
- **AF-01** — the `agentcore/cdk` jest test fails identically on Node 24 **and** 26 (cwd-sensitivity in a third-party L3 construct, not in CI; install + `tsc` build pass on 26) → not a Node-26 regression, does not trigger the D-06 fallback.
- **AF-02** — `TESTING.md` still carries stale Node `>=22 <25` facts (no test *command* changed, so untouched per D-10).

Full report: `workstream/fidelity-report-issue-217.md`.

### Notable Next 16 / Node 26 breakages fixed

- `node:26-slim` dropped bundled `corepack` → install via npm in the Docker build stages.
- Next 16 forbids a route-segment `runtime` export in `proxy.ts` (proxy is implicitly Node).
- `tsconfig.json` took Next 16's mandatory `jsx: react-jsx` + `.next/dev/types` include.
- E2E webServer switched to a production build (`next build && next start`): Next 16's `next dev` + Turbopack attaches client React handlers after the DOM is interactive, so Playwright clicked `"use client"` controls before hydration. No assertion weakened; all 26 E2E green.

### Remaining (post-merge, human-only)

- 1.20 — `scripts/release-panel.sh` → approve prod deploy → `deploy-panel.sh` exit 0 (auth gate checks 1–5 + OIDC probe `status=200 token=present`).
- 1.21 — AC9: an invoke from the deployed panel reaches `running`; record the run id here and close.
