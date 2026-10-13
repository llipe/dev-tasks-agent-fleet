# Roadmap

Last updated: 2026-10-13

One row per PRD phase or wave, newest PRD first. This page indexes the PRDs, GitHub issues, and merged PRs. If it disagrees with them, they are correct and this page gets fixed.

| PRD | Phase/Wave | Scope (one line) | Status | Issues/PRs | What's missing |
| --- | --- | --- | --- | --- | --- |
| [prd-agent-scheduler](requirements/prd-agent-scheduler.md) | Wave A — Foundation | `schedules` + `notifications` schema/enums/RLS, `buildRunInsert` trigger descriptor, `pg_net` + Vault + settings + runbook | Done (on integration) | #261–#263 (S-149…S-151), PRs #277/#278/#279 | Delivered on `integration/agent-scheduler`; test-first, verified against the live local stack |
| [prd-agent-scheduler](requirements/prd-agent-scheduler.md) | Wave B — Trigger (A1) | `compute_next_run_at` (DST + cron) + RPC, fire endpoint + shared-secret internal class, `fire_due_schedules` tick + G4 cap + G2 no-catch-up | Done (on integration) | #264–#266 (S-152…S-154), PRs #281/#282/#283 | Delivered on `integration/agent-scheduler`; 41 scheduler L2.5 tests pass. Depends on Wave A |
| [prd-agent-scheduler](requirements/prd-agent-scheduler.md) | Wave C — Guardrails | G1 overlap suppression, G5 open-PR backoff (phased a+c) + manual clear, G3 circuit breaker (auto-pause) | Done (PRs open) | #267–#269 (S-155…S-157), PRs #284/#285/#286 | On story branches, stacked; 48 scheduler L2.5 tests pass. Pending merge to `integration/agent-scheduler` |
| [prd-agent-scheduler](requirements/prd-agent-scheduler.md) | Wave D — Notifications | notify-sweep tick (reaper-failure recording, exactly-once), SES sender + IAM + daily digest, auth-release-gate assertion | Not started | #270–#272 (S-158…S-160) | Pending |
| [prd-agent-scheduler](requirements/prd-agent-scheduler.md) | Wave E — UI | `/schedules` list + CRUD, new/edit dialog + cadence picker, notifications feed + bell, agent-page indicator | Not started | #273–#276 (S-161…S-164) | Pending. Pinned to DESIGN.md §5.7/§5.8. Fast-follows: G5-b auto GitHub PR-state polling, Slack channel, webhook triggers |
| [prd-agent-fleet-panel-v3-ui-depth](requirements/prd-agent-fleet-panel-v3-ui-depth.md) | All | Run History filter/search/pagination and inline links, Run Detail steps panel and log-level filtering, queued-animation fix, All Runs feed, Repositories reference list | Done | #202–#208, PR #216; follow-up #241 / PR #243 | — (Settings, System health, and command palette are parked as non-goals, not missing scope) |
| [prd-security-analyst-agent](requirements/prd-security-analyst-agent.md) | All | `security-analyst` agent: five scanners, cross-tool dedup, classification, `audit_only` and `fix` modes with re-scan gate, verified live | Done | #185–#201, PR #247; hardening PRs #235–#240, #242, #246 | — |
| [prd-panel-password-auth](requirements/prd-panel-password-auth.md) | Phase A | Supabase password login, fail-closed middleware gate, logout, live-tail 401 handling, auth release gate (verified while private) | Done | #155–#161, PR #170, #173 | — |
| [prd-panel-password-auth](requirements/prd-panel-password-auth.md) | Phase B | Go public: public HTTPS service, boundary re-verified on the public hostname | Done | #162, PRs #174, #175; key cutover #172 / PRs #180, #181 | — |
| [prd-panel-auth-and-rls](requirements/prd-panel-auth-and-rls.md) | All | GitHub OAuth + allowlist, `viewer`/`operator` roles, identity-based RLS replacing deny-all, `runs.triggered_by`, SSE-relay removal | Not started | — | Entire scope. PRD is DEFERRED (v1.1), with password auth as the interim step |
| [prd-agent-fleet-panel-v2](requirements/prd-agent-fleet-panel-v2.md) | Phase 1 | Database schema, `dependency-update` agent, base API (PostgREST), CloudWatch fallback | Done | Delivered via prd-dependency-update-agent; reaper #94, #99, #101 / PRs #96, #104, #110 | — |
| [prd-agent-fleet-panel-v2](requirements/prd-agent-fleet-panel-v2.md) | Phase 2 | Next.js panel on Fly.io: agents dashboard, run history, run detail with live tail, schema-driven invoke form, E2E, deploy + OIDC | Done | #114–#128, #89, #134; PRs #129–#133, #135, #138–#140, #143, #144, #150, #152–#154 | — (the S-115 privacy gate was superseded by the auth release gate, ADR-007) |
| [prd-dependency-update-agent](requirements/prd-dependency-update-agent.md) | All | `dependency-update` agent on AgentCore: GitHub App auth, audit + version eligibility, validation, LLM fix escape hatch, PR builder | Done | #70–#78, PRs #79–#88; fixes #90, #97, #98, #100, #106, #108, #109, #145 | — |

## Not yet on a PRD

- Open issues without a PRD: #244 (refresh run detail when a run reaches a terminal state), #245 (run detail can't scroll when the summary is tall), #217 (Next.js 16 + Node LTS upgrade).
- Product backlog with no PRD yet (see [`product-context.md`](product-context.md) §6): webhook triggers, per-repository agent enablement, GitHub App repo sync, `findings` with stable fingerprints, run cancellation, `run_events` retention. (Scheduled triggers now have a PRD — see [prd-agent-scheduler](requirements/prd-agent-scheduler.md) above.)
