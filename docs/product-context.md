# Product Context — Agent Control Plane

## Changelog

| Version | Date       | Summary                                                    | Author           |
| ------- | ---------- | ---------------------------------------------------------- | ---------------- |
| 1.0     | 2026-08-19 | Initial version, derived from PRD v1.0 (scope closed)      | product-engineer |

---

## 1. Executive Summary

Agent Control Plane is a single-operator web application for observing and operating a fleet of AI agents running on AWS Bedrock AgentCore. It presents agent activity along two axes — **by agent** and **by repository** — with result, logs, span timeline, and estimated cost, and exposes exactly one write action: enabling or disabling a repository within an agent's scope.

It is deliberately not an agent management console. It cannot create, deploy, modify, delete, or invoke agent runtimes. That constraint is enforced by the IAM policy, not by convention.

---

## 2. Problem Statement

Operating agents on AgentCore today means using the AWS console, which is organized by service: runtimes in one place, logs in CloudWatch, configuration nowhere. Two concrete consequences follow.

**Changing an agent's scope requires a deploy.** Adding a repository to the dependency-update agent's list is a code change, a commit, and a deploy — for what is fundamentally a configuration decision.

**There is no per-repository view.** AWS has no concept of "the repository an agent acted on." The question *"what did all agents do to `fintrack-home` this month"* is not expressible against any AWS API. The repository axis has to be manufactured, which is what the emission contract exists to do.

A third, quieter problem: there is no cheap signal for an agent that died mid-run. A run that never closed out looks identical to a run still in progress.

---

## 3. Target Users / Market

**Primary user:** one person — the fleet's owner and operator. This is a personal tool, not a product with a market.

The implications are load-bearing rather than incidental:

- No roles, permissions, or multi-tenancy (explicitly out of scope).
- No onboarding, no empty-state tutorials, no settings UI beyond what the single write action needs.
- Single AWS account, single region.
- Trust boundary is the perimeter (Cloudflare Access), not in-app authorization.

**Secondary consumers** are machine, not human: the orchestrator Lambda and the agents themselves both write to the same DynamoDB table the front end reads and writes. They are participants in the data model, and the write-separation rules in the PRD exist to keep the three writers from clobbering each other.

---

## 4. Strategic Goals

1. **Make scope a configuration decision, not a deploy.** Adding or removing a repository from an agent's scope should be a toggle, resolved in seconds, with no code change and no release.
2. **Establish the repository as a first-class query axis.** Every run must be attributable to a subject repository, so the fleet can be viewed by what was acted upon rather than only by what did the acting.
3. **Shorten the path from failure to cause.** A failed run should reach its logs in a small, fixed number of clicks, without leaving the tool.
4. **Remove the AWS console from steady-state operation.** Routine checking-in on the fleet should require zero console visits. Console access remains for the things v1 deliberately cannot do.
5. **Keep spend visible enough to notice anomalies.** A token-derived estimate, honestly labeled, is sufficient to catch a runaway agent. Accurate billing is not the goal.

---

## 5. Current State

**Greenfield.** The repository contains the PRD and these foundation documents on a single commit. No application code, no infrastructure, no CI.

State of the surrounding world:

| Item                                        | Status                                                     |
| ------------------------------------------- | ---------------------------------------------------------- |
| `dev-tasks-agent-fleet` repo scaffolding    | Not started — layout defined in PRD §16                    |
| CloudWatch Transaction Search               | Not enabled (prerequisite)                                 |
| Unified span destination                    | Not decided (per-runtime log group vs shared `aws/spans`)   |
| Discovery tags on existing agents           | Not applied                                                |
| Emission contract in agents                 | Not implemented                                            |
| DynamoDB table + GSI1                       | Not created                                                |
| Orchestrator Lambda                         | Not written                                                |
| Control plane front end                     | Not started                                                |
| `dep-updater` agent                         | Exists outside this repo; will be **rebuilt** here, not migrated |

The `dep-updater` rebuild is a deliberate choice. The existing implementation is available for reference and its behavioural details will be supplied when that work is scheduled; no migration path is assumed or documented.

---

## 6. Vision & Roadmap

**v1 scope in one line:** a read-mostly run browser over two axes, plus a scope toggle.

The build order matters and is not negotiable: the data has to exist before the surface that reads it. Building the front end first yields empty tables and no way to tell an integration bug from an absence of data.

**Phase 1 — Foundations.** Repo scaffolding with path-gated CI. Enable Transaction Search, pick and unify the span destination, apply discovery tags.

**Phase 2 — Contract and data.** `packages/shared` as the single source of truth for the DynamoDB schema and the `llipe.*` span attributes. Create the table and GSI1, load the current repository list.

**Phase 3 — Emission.** Rebuild `dep-updater` in-repo against the shared contract, emitting the required root-span attributes and JSON logs carrying `session_id` on every line. This is the phase that makes the repository axis real.

**Phase 4 — Orchestration.** EventBridge Scheduler plus the orchestrator Lambda: GSI1 query, `session_id` generation, bounded-concurrency fan-out, fire-and-forget invocation.

**Phase 5 — Control plane.** The four views: Agents, Agent (Runs + Repos), Repos, and the Run side panel.

**Beyond v1** — recorded in PRD §19 so it does not get re-litigated: actual billed cost via Cost Explorer, missing-run detection against declared schedules, a deterministic tool-usage panel, an outcome loop fed by GitHub webhooks, AgentCore Evaluations, and Configuration Bundles for prompt versioning.

---

## 7. Success Metrics

| Metric                                                       | Target                  |
| ------------------------------------------------------------ | ----------------------- |
| Time to add a repository to an agent's scope                 | Under 30 seconds, zero deploys |
| Clicks from the run list to the logs of a failed run         | Under 3                 |
| AWS console visits to check on agents, in steady state       | Zero                    |
| Monthly infrastructure cost of the control plane             | Under USD 10            |

These are operator-experience metrics, measured by the operator. There is no analytics instrumentation in v1 and none is planned — adding telemetry to a single-user tool to measure the single user would cost more than asking him.

---

## 8. Competitive Landscape

**The AWS console** is the incumbent and the thing being replaced. It is organized by service, which is the right decomposition for AWS and the wrong one for operating a fleet. It has no repository axis and no configuration surface for agent scope.

**LLM observability platforms** (LangSmith, Langfuse, Braintrust and similar) overlap on the run-timeline and token-accounting features and would do them better. They do not overlap where it matters: they have no view of AgentCore runtime inventory, no notion of the subject repository, and no path to writing agent scope configuration. Adopting one would mean a second SDK, a second destination for telemetry, and an external dependency with its own cost — while still leaving the two original problems unsolved.

**Doing nothing** remains a real option and the honest baseline. Its cost is the AWS console tax on every check-in and a deploy on every scope change.

**Differentiation** comes down to the `llipe.subject.id` attribute. The repository axis is a private convention this fleet imposes on itself, which is precisely why no off-the-shelf tool can provide it. The tool is small because the contract does the heavy lifting.

---

## 9. Key Constraints

**Budget.** Under USD 10/month total infrastructure. This rules out a managed database, a persistent run ledger, and always-on compute beyond a single small container.

**No persistence.** State lives in AgentCore, CloudWatch, and DynamoDB. The control plane holds an in-process memory cache and nothing else. A container restart clears the cache and loses nothing — that property is a design goal, not a limitation to work around.

**Read ceiling is CloudWatch.** Run history is bounded by log retention, and query latency is bounded by Logs Insights, which is a start-query/poll-results API measured in seconds. No amount of front-end work makes it instant.

**Hard dependency on the emission contract.** Without `llipe.subject.id` on the root span there is no repository axis and view C does not exist. The contract is a requirement on the agents, and agents that do not honour it are invisible to half the product.

**Opt-in by tag.** An agent without `agent:managed=true` does not appear. Discovery is deliberately not automatic.

**Fire-and-forget invocation.** `InvokeAgentRuntime` returns no identifier, so correlation depends entirely on the orchestrator generating `session_id` before invoking. There is no completion callback; the only completion signal is the agent's own write.

**Single account, single region.** Multi-account and multi-region are out of scope.

---

## 10. Key Stakeholders

| Stakeholder | Role                                                          |
| ----------- | ------------------------------------------------------------- |
| @llipe      | Owner, sole operator, sole decision-maker, PRD author         |

No approval chain, no external stakeholders. Scope decisions are made by one person and recorded in the PRD.

---

## 11. Assumptions

1. **1% Transaction Search indexing is sufficient.** 100% of spans are ingested as logs; the indexing percentage affects only X-Ray trace summaries, which the product does not consume.
2. **A single span destination is achievable across the fleet.** Two destinations means two queries and a materially more complex read path.
3. **A 5-minute cache TTL is acceptable freshness** for inventory, runtime detail, and run lists. Logs and configuration reads are uncached because they are the ones read when something is wrong.
4. **6 hours is the right threshold for `stale`.** Long enough that legitimate long runs are not flagged, short enough to catch a death the same working day. It is a heuristic, derived at read time, never written.
5. **Token-derived cost is close enough to be useful.** Excluding runtime compute cost is acceptable because the estimate exists to spot anomalies, not to reconcile a bill.
6. **A hand-maintained pricing table stays current enough.** Model prices change rarely; a versioned JSON file in the repo is cheaper than a pricing API integration.
7. **AgentCore's automatic instrumentation supplies tokens, latency, and model** without agent-side code.
8. **Cloudflare Access plus origin lockdown is adequate authentication** for a single-user tool holding no customer data.

---

## 12. Open Questions

| # | Question                                                                                                              | Owner   | Blocks                        |
| - | --------------------------------------------------------------------------------------------------------------------- | ------- | ----------------------------- |
| 1 | Span destination: per-runtime log group or shared `aws/spans`? Picking one is a prerequisite, and the choice shapes the query layer. | @llipe  | Phase 1, and the run read path |
| 2 | Does Fly Machines OIDC → AWS `AssumeRoleWithWebIdentity` work without friction, or is the static-key fallback needed?   | @llipe  | Phase 1 IAM                   |
| 3 | Origin lockdown mechanism: Cloudflare Tunnel or Cloudflare IP allowlist?                                              | @llipe  | Phase 5 deployment            |
| 4 | `dep-updater` rebuild: behavioural scope, current parameter shape, and prompt content — to be supplied from the existing repo when scheduled. | @llipe  | Phase 3                       |
| 5 | Pricing-table update cadence and who notices when a model's price changes.                                            | @llipe  | Cost accuracy, not delivery   |
| 6 | Log retention period on the span destination — this sets the real limit on how far back any view can look.            | @llipe  | Phase 1, and metric framing   |

---

## Reference

- PRD: [`docs/PRD-agent-control-plane-v1-en.md`](./PRD-agent-control-plane-v1-en.md) — v1.0, scope closed
- Technical guidelines: [`docs/technical-guidelines.md`](./technical-guidelines.md)
- Design contract: [`../DESIGN.md`](../DESIGN.md)
