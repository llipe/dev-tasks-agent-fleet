# Fidelity Report — PRD rollup: Webhook Triggers Phase 1 (verifier, Audit Mode)

**Scope:** every story merged to `integration/webhook-triggers` (S-165–S-179, PRs #356–#395, plus fix #396), checked against `docs/requirements/prd-webhook-triggers.md` §8 and the spec (v1.4). **Verdict: High fidelity.** Every story-level report was rated High. **Highest drift impact: Minor.**

## PRD acceptance criteria → evidence

| AC | Evidence (test layer + live) | Result |
| --- | --- | --- |
| AC1 signed → verified, recorded, routed, a `webhook` run linked to the rule | L1/L2.5 S-168–S-172. E2E: `webhooks-delivery` AC1. **Live:** `/audit` comments on llipe/security-analyst-fixture #3 and #4 → `fired` → runs f68ee052 and 5195d039 (`triggered_by webhook:<ep>:<rule>`) | Pass |
| AC2 bad or missing signature → 401, no run; replay → 200 no-op | L1 S-168, L2.5 S-169, E2E AC2. **Live:** release-gate check 6, where the probe got 401 and was recorded `unauthorized/header_missing` | Pass |
| AC3 oversized → 413; non-allowlisted → 202 ignored | L2.5 S-169, E2E AC3. **Live:** GitHub `ping` → `ignored/event_not_allowed` | Pass |
| AC4 ordered first-match; no match → 202 no_match | L1 S-170 (routing, mutants), E2E AC4 (rule #2 fires) | Pass |
| AC5 repo outside the allowlist or invalid params → route_rejected | L1/L2.5 S-171, E2E AC5 | Pass |
| AC6 G1/G4/G5 skip with reason; terminal failure → run_failed via the sweep | L2.5 S-173 (`webhook-guardrails`, 3 SQL mutants), S-174 (`notify-sweep`), E2E AC6. **Live:** the second `/audit` → `skipped/overlap`; both failed runs got `run_failed` notifications titled with endpoint and rule | Pass |
| AC7 bot-authored → no run | L1 S-170, E2E AC7 (with the corrected `devtasks-agent-fleet[bot]`, #396) | Pass |
| AC8 UI: endpoint with show-once secret, ordered rules, delivery log text-only; `/webhooks` logged out → /login; unsigned → 401 in the release gate | S-176–S-178 (L1/L2/L2.5 + browser checks), E2E `webhooks-crud`. **Live:** operator created the endpoint and rule in the panel; `/webhooks` → 302 /login; gate 6/6 on release v20 | Pass |
| AC9 no secret or raw signature in any log or delivery record | Secret only in Vault, reachable only through service_role RPCs (`definer-grants`; live: anon gets 42501 on all 10 RPCs). E2E AC9 scans stored deliveries. The probe token never appeared in any log | Pass |

## Drift (rolled up)

| # | Finding | Type | Impact | Route |
| --- | --- | --- | --- | --- |
| 1 | Guardrails are a stateless SQL decision that reuses the scheduler predicates, instead of moving into the TS core. G4 is shared by both triggers. | Intended | Minor | Written back to spec §8.4 (v1.4) |
| 2 | Webhook G3 counts start failures only; scheduled G3 counts every terminal failure (D-W18). | Intended | Minor | Spec §8.4 (v1.4) |
| 3 | The seeded `bot_login` was wrong (`dev-tasks-…` vs the App slug `devtasks-…`). Live was corrected at rollout step 2; the repo is fixed in #396. | Unintended (fixed) | Minor | Done |
| 4 | Bugs that browser checks found, all fixed with regression tests: (a) a half-filled "fill from payload" row was silently dropped; (b) raw signature codes were shown; (c) two layout defects. | Unintended (fixed) | Minor | Done |
| 5 | The event header is fixed to `x-github-event`, including for generic senders (S-169). | Known gap | Minor | Follow-up |
| 6 | Array-typed params (e.g. `scanners`) can't be edited in the rule dialog; agent defaults apply, as in invoke/schedules. | Inherited | Minor | Follow-up |
| 7 | B-1/B-2/B-3 (202 skipped body, reject unknown condition keys, disabled endpoint → 404 with no row) were built as the test plan assumed but never explicitly confirmed by the user. | Open decision | Minor | User |
| 8 | Manual invoke still has its own copy of the invoke path, not the shared core. | Follow-up | Minor | Follow-up |

## Live state at handoff

Release v20 runs integration `125d6a6`. 9 migrations are pushed. `bot_login` is `devtasks-agent-fleet[bot]`. The probe endpoint (`87214c98…`) is set up and its token is in `~/.config/agent-fleet/webhook-probe-token`. One live endpoint with one `audit_only` rule is registered on llipe/security-analyst-fixture. Rollback: `fly releases rollback` to v19; per-migration rollback steps are in each migration header.
