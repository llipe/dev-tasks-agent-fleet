# Product Context — Agent Fleet Control Plane

## Changelog

| Version | Date       | Summary                                                                 | Author           |
| ------- | ---------- | ----------------------------------------------------------------------- | ---------------- |
| 1.0     | 2026-08-26 | Initial version. Reformatted from consolidated PRD (tmp) into foundation doc format. No scope or decision changes. | product-engineer |
| 1.1     | 2026-08-26 | Translated to English. Introduced two-phase delivery model (Phase 1: backend + agent; Phase 2: panel UI). | product-engineer |

## 1. Executive Summary

Agent Fleet Control Plane is a personal panel for operating autonomous agents that run on AWS Bedrock AgentCore against the repositories of a GitHub organization. It replaces the AWS console and manual CloudWatch Logs Insights queries with a structured execution registry backed by Supabase as the system of record, with manual invocation from the panel and live log tailing.

## 2. Problem Statement

There is no way to see what the agents did without entering the AWS console and crafting CloudWatch Logs Insights queries. That does not scale to multiple agents across ~20 repos, and it does not allow triggering an execution with parameters without going through the console.

The v1 of this project was built on CloudWatch as the sole data source. Reconstructing the state of an execution by parsing log lines is fragile: an execution that dies leaves no trace of its death, and there is no way to distinguish "finished without finding vulnerabilities" from "failed." The project underwent a full reset (`chore/project-reset`, see `RESET-PLAN.md`) that tore down the previous AWS infrastructure (CDK, DynamoDB, Lambda orchestrator, EventBridge) to start from a simpler design.

## 3. Target Users/Market

**Primary user:** the project author, in their role as maintainer of the GitHub organization and operator of the agents. This is a personal, single-tenant system with no external user base in v1.

**Secondary user (future):** other members of a small team who need to trigger or audit agent executions on the same repos, once authentication exists (see Backlog in the specification).

There is no external market or intent to distribute to third parties in the current horizon. This is internal productivity infrastructure, not a commercial product.

## 4. Strategic Goals

1. **Visibility without the AWS console.** See what each agent execution did (status, duration, outcome, log) without entering CloudWatch Logs Insights.
2. **Low-friction invocation.** Trigger an agent with parameters from a form, not from `aws bedrock-agentcore invoke` by hand.
3. **Reliable execution records.** An execution that dies unreported gets registered as dead, not stuck as "running" forever.
4. **Extensible foundation without over-building.** The data model supports multiple agents, multiple repos, schedules, and webhooks in the medium term, even though v1 only covers manual invocation of one agent.
5. **Minimal cost and operational surface.** No static AWS keys, no extra infrastructure (queues, Lambdas) that does not pay for its complexity at this scale.

## 5. Current State

**Reset followed by scope restart.** The project had a prior v1 on CDK/DynamoDB/Lambda/EventBridge that was torn down entirely (`RESET-PLAN.md`, phases 1-3). This document and the associated PRD correspond to the **Draft 2 — consolidated** of v2: the data design ([`001_schema.sql`](reference/001_schema.sql), [`002_seed.sql`](reference/002_seed.sql)), the agent reporting contract ([`agent_reporter.py`](reference/agent_reporter.py)), and the AWS credential provider ([`credentials.ts`](reference/credentials.ts)) are already specified and, per the source PRD, "Done" at the design/artifact level. The Next.js front-end and the `dependency-update` agent runtime in AgentCore are **pending implementation**.

## 6. Vision & Roadmap

**Phase 1 — Backend + Agent (current):** Deploy the database schema to Supabase; build and deploy the `dependency-update` agent connected to GitHub via a GitHub App; expose a base API layer (PostgREST via Supabase) so the agent, when manually invoked, can write its lifecycle and events back to the database. If the API is unreachable, the run falls back to logging in CloudWatch (the SDK already dumps payloads to stderr on write failure).

**Phase 2 — Panel UI:** Build the Next.js application on Fly.io to visualize the run information already stored in the database — agent list, run list with status/duration/outcome, run detail with log tail in real time via Supabase Realtime, and the manual invocation form.

**Medium term (data model already supports, not built yet):**
- Multiple agents across multiple repos of the same GitHub organization.
- Executions triggered by schedule or webhook, not only manually.
- Enable/disable an agent per repository.

**Backlog declared, not implemented** (detail in the technical specification): Supabase Auth with allowlist, `schedules` table + EventBridge, `agent_repository_settings`, repo sync from the GitHub App, `findings` with stable fingerprint, run cancellation, `run_events` retention, heartbeat as a finer health signal, agent SDK as a pip package if the fleet grows beyond ~4 agents.

## 7. Success Metrics

These metrics are binary by design — they are the v1 acceptance criteria (see PRD §Acceptance Criteria), not indirect proxies:

1. A manual trigger of `dependency-update` on a real repo finishes with `status = succeeded` and the correct `outcome`.
2. The log of an execution is visible in the panel in real time, without page reload.
3. An agent that hangs shows up as `timed_out` within 60 seconds of exceeding its threshold, with an event explaining the reason.
4. An invocation that fails to launch shows up as `failed_to_start`, not as eternal `queued`.
5. Adding a new agent requires only inserting a row in `agents` with its `params_schema` — zero front-end deploys.
6. The front-end runs on Fly.io without any AWS keys in `fly secrets`, and runs locally with an SSO profile with no code changes.

## 8. Competitive Landscape

No competition in the commercial sense: this is internal tooling. Alternatives evaluated and discarded:

- **AWS Console + CloudWatch Logs Insights directly.** This is the status quo being replaced — it does not scale beyond 1-2 agents and does not allow invocation with parameters outside the console.
- **Reconstruct state from logs (v1 approach).** Discarded: fragile when executions die without reporting (see Problem Statement).
- **Generic AgentOps/third-party observability platforms.** Out of scope: the project is personal/small-team scale and the cost of integrating an external platform does not justify itself against a Postgres table.

Differentiator: the panel explicitly models the domain (agents, repos, runs, steps, artifacts) instead of treating an execution as a black box that only produces log text.

## 9. Key Constraints

- **Personal / small-team scale.** Minimal budget and operational footprint: Supabase (free/low tier), Fly.io, AWS pay-per-use. No dedicated infrastructure team.
- **No authentication in v1** (explicit decision, not an oversight — see Risks in the specification). Implies not exposing the panel publicly without minimal mitigation.
- **AgentCore controls the container lifecycle.** The panel cannot kill or pause an execution in v1; it can only detect it as stale.
- **No static AWS keys.** Explicit design constraint (D12): the front-end authenticates via Fly OIDC + `AssumeRoleWithWebIdentity`.
- **Retrofitting historical logs is not viable.** `run_steps` must be emitted from the first agent in production, even if the v1 front-end only displays raw log, because you cannot reconstruct step structure over already-written logs.

## 10. Key Stakeholders

A single decision-maker: the project author (Llipe), who is simultaneously product, engineering, and end user. There is no decision committee or external stakeholders in this phase.

## 11. Assumptions

- A single GitHub organization and a single `github_installation` are sufficient for v1 (not a multi-tenancy requirement, but a GitHub App token flow requirement).
- Execution and log event volume in v1 is low (few agents, non-continuous executions), so `run_events` growth and per-execution write volume (risks R3/R5 in the specification) are manageable without immediate mitigation.
- AgentCore, Fly.io, and the GitHub App are (or will be) configured outside the scope of this panel; the panel consumes those pieces, it does not provision them.
- The agent fleet stays small (on the order of 2-4) long enough that copying `agent_reporter.py` per repo (D13) does not cause problematic drift.

## 12. Open Questions

- At what point (number of agents, or actual drift signal) is `agent_reporter.py` packaged as a pip package instead of copied per repo (see D13 and backlog)?
- What is the retention threshold for `run_events` before table growth hurts (R3), and who reviews it?
- Is the minimal mitigation for R1 (no authentication) — shared-secret header, or keeping the app private — decided before or after the first Fly deployment?
- When does it become worthwhile to move from "a second Supabase project for development" (R7) to a more formal staging environment?
