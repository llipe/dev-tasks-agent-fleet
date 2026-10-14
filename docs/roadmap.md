# Roadmap

Last updated: 2026-10-14

One row per PRD phase or wave, newest PRD first. Issue batches without a PRD are tracked in their own table below. This page indexes the PRDs, GitHub issues, and merged PRs. If it disagrees with them, they are correct and this page gets fixed.

| PRD | Phase/Wave | Scope (one line) | Status | Issues/PRs | What's missing |
| --- | --- | --- | --- | --- | --- |
| [prd-agent-fleet-panel-v3-ui-depth](requirements/prd-agent-fleet-panel-v3-ui-depth.md) | All | Run History filter/search/pagination and inline links, Run Detail steps panel and log-level filtering, queued-animation fix, All Runs feed, Repositories reference list | Done | #202–#208, PR #216; follow-up #241 / PR #243 | — (Settings, System health, and command palette are parked as non-goals, not missing scope) |
| [prd-security-analyst-agent](requirements/prd-security-analyst-agent.md) | All | `security-analyst` agent: five scanners, cross-tool dedup, classification, `audit_only` and `fix` modes with re-scan gate, verified live | Done | #185–#201, PR #247; hardening PRs #235–#240, #242, #246 | — |
| [prd-panel-password-auth](requirements/prd-panel-password-auth.md) | Phase A | Supabase password login, fail-closed middleware gate, logout, live-tail 401 handling, auth release gate (verified while private) | Done | #155–#161, PR #170, #173 | — |
| [prd-panel-password-auth](requirements/prd-panel-password-auth.md) | Phase B | Go public: public HTTPS service, boundary re-verified on the public hostname | Done | #162, PRs #174, #175; key cutover #172 / PRs #180, #181 | — |
| [prd-panel-auth-and-rls](requirements/prd-panel-auth-and-rls.md) | All | GitHub OAuth + allowlist, `viewer`/`operator` roles, identity-based RLS replacing deny-all, `runs.triggered_by`, SSE-relay removal | Not started | — | Entire scope. PRD is DEFERRED (v1.1), with password auth as the interim step |
| [prd-agent-fleet-panel-v2](requirements/prd-agent-fleet-panel-v2.md) | Phase 1 | Database schema, `dependency-update` agent, base API (PostgREST), CloudWatch fallback | Done | Delivered via prd-dependency-update-agent; reaper #94, #99, #101 / PRs #96, #104, #110 | — |
| [prd-agent-fleet-panel-v2](requirements/prd-agent-fleet-panel-v2.md) | Phase 2 | Next.js panel on Fly.io: agents dashboard, run history, run detail with live tail, schema-driven invoke form, E2E, deploy + OIDC | Done | #114–#128, #89, #134; PRs #129–#133, #135, #138–#140, #143, #144, #150, #152–#154 | — (the S-115 privacy gate was superseded by the auth release gate, ADR-007) |
| [prd-dependency-update-agent](requirements/prd-dependency-update-agent.md) | All | `dependency-update` agent on AgentCore: GitHub App auth, audit + version eligibility, validation, LLM fix escape hatch, PR builder | Done | #70–#78, PRs #79–#88; fixes #90, #97, #98, #100, #106, #108, #109, #145 | — |

## Issue batches (no PRD)

| Batch | Scope (one line) | Status | Issues/PRs | What's missing |
| --- | --- | --- | --- | --- |
| CI audit gates + run-detail follow-ups | Unblock the pnpm and pip-audit CI gates (PyJWT 2.15.1, transitive overrides, redeploy both agents); bound the audit-report findings table; refresh run detail when a run finishes | Done | #252 / PR #254, #245 / PR #255, #244 / PR #256 (all merged into `integration/run-detail-followups-and-audit`); consolidated PR #257; plan `workstream/tasks-issue-252-245-244-audit-gates-and-run-detail.md`; redeploy change record `infra/changes/20261013-redeploy-agents-pyjwt/` | — (follow-ups tracked separately: #280 panel Fly OIDC, R-01 CT-3 classification) |
| Panel Fly OIDC fix | Deployed panel cannot invoke agents (non-root `nextjs` gets EACCES on root-only `/.fly/api`): root entrypoint grants group write then drops to uid 1001; OIDC token probe in `deploy-panel.sh`. Runs before #217 | Done | #280; PRs #295, #297; panel-v1.1.0/v1.1.1; infra change `20261014-fly-oidc-issuer-trust` | — (retire IAM provider `oidc.fly.io/personal` in a later change) |
| Next.js 16 upgrade | Next 15.5.25 → 16.4.0 and Node LTS bump; clears the two moderate `next` advisories handed over by #252. Runs after #280 | Not started | #217 | Entire scope; needs refinement against 16.4.0 |

## Not yet on a PRD

- Product backlog with no PRD yet (see [`product-context.md`](product-context.md) §6): scheduled and webhook triggers, per-repository agent enablement, GitHub App repo sync, `findings` with stable fingerprints, run cancellation, `run_events` retention.
