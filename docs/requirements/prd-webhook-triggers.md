# PRD — Webhook Triggers

## Changelog

| Version | Date       | Summary                                                        | Author           |
| ------- | ---------- | -------------------------------------------------------------- | ---------------- |
| 0.1     | 2026-10-15 | Initial draft. Phase 1 (webhook mechanism + routing + UI) in full; Phases 2–3 (two new agents) as scoped forward-references. | product-engineer |

---

## 1. Overview

A third way to invoke fleet agents — **inbound webhooks** — alongside manual invocation
(Phase 2 panel) and schedules (Phase 4 Agent Scheduler). An external system POSTs a
**signed** event to a per-endpoint URL; a panel-configured **deterministic routing engine**
matches the event against ordered rules and resolves `(agent, repository, params)`; the
matched route invokes the agent through the **exact same internal invoke path, guardrails
(G1–G5), and notification machinery the scheduler already uses**. GitHub is the first-class
source; the mechanism is generic so any HMAC-signing caller can drive it.

This PRD covers **Phase 1 — the webhook mechanism** in full. It names, but does not fully
specify, two downstream phases that depend on it, each delivered as its own PRD:

- **Phase 2 — Code Review Agent** (`prd-code-review-agent.md`): a new AgentCore agent
  invoked when a reviewer tags it from the GitHub PR review pane; reviews the PR diff and
  posts review comments back.
- **Phase 3 — Repo Research Agent** (`prd-repo-research-agent.md`): a new AgentCore agent
  invoked by a comment on an issue or PR; clones the repo, researches, and answers in a
  GitHub comment.

Both new agents are substantial enough to warrant their own PRD/spec/stories; Phase 1 ships
with the **existing** agents as routing targets so the trigger chain is provable without
agent risk.

## 2. Problem Statement

Agents today run only on a human click or a clock tick. Real workflows are **event-driven**:
a PR is opened, a reviewer asks for a review, someone comments "security review" on a PR.
There is no way for an external event to invoke an agent. The data model anticipated this —
`runs.trigger_type` has carried `'webhook'` since v1 — but no front door exists.

The hard part is not "receive an HTTP POST." It is doing so **safely** (the endpoint is
public and the body is hostile input) and **usefully** (one GitHub webhook delivers every
event type to one URL, so the system must *route* — decide, deterministically and by
operator configuration, which event fires which agent against which repo with which params).

## 3. Goals

- **G1. A signed, public inbound webhook endpoint** that is safe against hostile input:
  unguessable URL, signature verification, replay/delivery-id dedup, size/timeout caps,
  event allowlisting — reject-before-work on every failure.
- **G2. GitHub as a first-class source** (the `X-Hub-Signature-256` HMAC scheme, GitHub
  event/delivery headers) with the mechanism generic enough for other HMAC-signing callers.
- **G3. A deterministic, panel-configured routing engine**: ordered rules match on event
  type + a safe, declarative condition language over the payload, and resolve
  `(agent, repository, params)` — with repo optionally taken from the payload (constrained
  to the registered allowlist) and an optional catch-all default.
- **G4. Full reuse of the scheduler's execution spine**: a matched route invokes via the
  existing internal invoke path and flows through the same guardrails (G1 overlap, G2
  no-catch-up n/a, G3 circuit breaker, G4 concurrency cap, G5 open-PR backoff) and the
  notify-sweep, so a webhook-triggered run is a first-class `runs` row indistinguishable in
  machinery from a scheduled one (only `trigger_type='webhook'`/`triggered_by` differ).
- **G5. Full delivery visibility**: every delivery is recorded (received → verified →
  matched/no-match → fired/skipped/rejected, with a reason) and surfaced in the panel, so a
  webhook that did not fire is debuggable — the "visible failed_to_start" philosophy.
- **G6. A `/webhooks` management UI**: CRUD for endpoints + their ordered rule sets, the
  signing secret lifecycle, and the delivery log, pinned to DESIGN.md.

## 4. Non-Goals (Phase 1)

- **The two new agents** (code-review, repo-research) — Phases 2–3, their own PRDs. Phase 1
  routes to **existing** agents.
- **A visual drag-and-drop rule builder.** Rules are a structured form (ordered rows); no
  graphical canvas.
- **Non-HMAC auth schemes** (OAuth-callback-style, mTLS, IP allowlisting as the *primary*
  gate). HMAC signature + unguessable URL is the v1 model; IP allowlisting MAY be a
  defense-in-depth add, not the boundary.
- **Auto-registering repositories** named by a payload. An inbound repo not already in the
  enabled `repositories` allowlist is rejected, never created.
- **A Turing-complete / scripting condition language.** The match language is a bounded,
  declarative spec (decision A below) — no arbitrary code, no unbounded regex.
- **Outbound posting back to GitHub** (comments, reviews). That capability is introduced by
  Phases 2–3 (the agents that need it), with the attendant GitHub App permission delta.
- **Fan-out** (one event firing multiple agents). First-match-wins, one route per delivery,
  in v1. Multi-match is a fast-follow.
- **Replaying/redelivering** a past delivery from the panel. Record + display only in v1.

## 5. Target Users

The single operator (same as the scheduler): configures webhook endpoints + routing rules,
holds the signing secrets, and debugs deliveries. External *senders* (GitHub, other systems)
are unauthenticated-until-signature-verified clients, never trusted callers.

## 6. User Stories (narrative)

- *As the operator*, I register a webhook endpoint for my GitHub org, get an unguessable URL
  and a signing secret, and paste them into GitHub's webhook settings.
- *As the operator*, I add ordered routing rules: "a `pull_request_review_comment` whose body
  is `security review` → run `security-analyst` on the PR's repo"; "a `push` to any enabled
  repo → run `dependency-update` on that repo"; and a default of "no match → record and drop."
- *As the operator*, when an expected run didn't happen, I open the delivery log and see the
  event arrived, verified, matched rule #2 (or matched nothing), and fired run `abc123` (or
  was skipped by a guardrail, with the reason).
- *As a GitHub event*, I arrive signed; if my signature is wrong, my delivery id is a
  replay, my body is too large, or my event type isn't allowlisted, I am rejected before any
  agent is touched.

## 7. Functional Requirements

### 7.1 Inbound endpoint & hostile-input hardening (FR1–FR8)

- **FR1 — Unguessable per-endpoint URL.** Each endpoint has a high-entropy path token
  (`/api/webhooks/<token>`), not a sequential id, so the URL itself is a weak secret;
  the signature is the real gate.
- **FR2 — Signature verification, fail-closed, constant-time.** The raw request body is
  verified against the endpoint's signing secret (GitHub: `X-Hub-Signature-256` =
  `sha256=HMAC(secret, rawBody)`; generic: the same HMAC-SHA256 over the raw body in a
  configurable header). Verification happens **before parsing or any work**, in constant
  time; a missing/invalid signature → **401**, nothing recorded as fired.
- **FR3 — Replay/delivery dedup.** GitHub's `X-GitHub-Delivery` (generic: a configurable
  idempotency header or a body hash) is recorded; a duplicate delivery id is a **200 no-op**
  (acknowledged, not re-fired) — at-most-once per delivery.
- **FR4 — Size + timeout caps.** Bodies over a hard limit are rejected (413) before buffering
  the whole payload where feasible; the handler has a strict time budget and never blocks on
  the agent invocation (fire-and-record, return fast).
- **FR5 — Event allowlist.** Only event types the endpoint is configured to accept are
  processed; others are a recorded **202 ignored** (acknowledged so GitHub doesn't retry,
  but no routing).
- **FR6 — Raw body integrity.** The signature is computed over the *exact* received bytes
  (no re-serialization), so verification is correct regardless of key ordering/whitespace.
- **FR7 — Fast acknowledgement.** The endpoint returns a 2xx to GitHub quickly after
  verify + record + enqueue-the-fire; the actual invoke is the existing async path. A slow
  agent never causes GitHub to see a timeout/retry storm.
- **FR8 — No secret ever logged.** Signing secrets, the raw signature, and payload contents
  that may carry tokens are never written to logs; delivery records store structured,
  non-sensitive fields (event type, delivery id, matched rule, outcome, reason).

### 7.2 Routing engine (FR9–FR15)

- **FR9 — Ordered rules per endpoint, first-match-wins.** An endpoint owns an ordered list
  of rules; the first whose conditions all match fires; evaluation stops. (Decisions C, D.)
- **FR10 — Safe declarative condition language.** Each rule is a set of conditions, ANDed,
  each `{ field, op, value }` where `field` is a bounded JSON-path-lite selector into the
  parsed payload, `op ∈ { equals, not_equals, contains, prefix, suffix, in, exists,
  matches_event }`, evaluated with depth/length limits and no backtracking regex. No code.
  (Decision A.)
- **FR11 — Event-type match.** Every rule implicitly scopes to one or more event types
  (GitHub `X-GitHub-Event`); the condition set refines within an event type.
- **FR12 — Route resolution.** A matched rule resolves: the **agent** (fixed, must be
  enabled); the **repository** (fixed, OR extracted from a payload field via the same path
  syntax); and **params** (static JSON, with payload-field interpolation allowed for
  declared keys only). (Decision B.)
- **FR13 — Repository allowlist enforcement.** A resolved repository — fixed or
  payload-derived — MUST already exist in `repositories`, be enabled, and non-archived, or
  the delivery is a recorded **route_rejected** (never auto-create). (Decision B.)
- **FR14 — Params validation.** Resolved params are validated against the target agent's
  `params_schema` (the same Ajv path as invoke/schedule) before any run row; an invalid
  resolution is a recorded **route_rejected**, no run.
- **FR15 — Optional default route + no-match.** An endpoint MAY define a catch-all default
  rule; with none, a delivery that matches nothing is a recorded **no_match** 202 (ack, drop).

### 7.3 Execution — reuse the scheduler spine (FR16–FR19)

- **FR16 — Trigger descriptor.** A webhook-fired run is inserted via the existing
  `buildRunInsert` with a new `webhook` `TriggerDescriptor`
  (`trigger_type='webhook'`, `triggered_by='webhook:<endpoint_id>:<rule_id>'`), through the
  same internal invoke path (SD-T9 analog). No second invoke code path.
- **FR17 — Guardrails apply.** A webhook-fired run is subject to the same G1 overlap, G4
  concurrency cap, and G5 open-PR backoff as a scheduled run (G2 catch-up is n/a — webhooks
  are edge-triggered, not cursor-driven; G3 circuit breaker applies **per routing rule**).
  A guardrail skip is a recorded delivery outcome with its reason.
- **FR18 — Notifications.** Webhook-fired runs flow through the notify-sweep exactly like
  scheduled runs: terminal failure → `run_failed`, a produced PR → `pr_opened`, opt-in
  success → `run_succeeded`, all in the same `notifications` table + feed + daily digest.
- **FR19 — Self-trigger / bot-author guard.** Routing MUST be able to exclude events
  authored by the fleet's own GitHub App / bot identity (and support an explicit
  `author is not <bot>` condition), so an agent that later posts a comment (Phases 2–3)
  cannot trigger itself into a loop. Phase 1 ships the guard even though its own targets
  don't post back yet.

### 7.4 Management UI & delivery log (FR20–FR24)

- **FR20 — `/webhooks` screen.** A new authenticated panel surface (sidebar nav item):
  list endpoints with their source type, enabled state, event allowlist, and rule count.
- **FR21 — Endpoint CRUD + secret lifecycle.** Create/edit/delete an endpoint; view the
  URL; generate/rotate the signing secret (shown once on creation/rotation, stored hashed/
  in Vault, never re-displayed) — mirrors the scheduler's shared-secret runbook posture.
- **FR22 — Rule editor.** Add/reorder/edit/delete the ordered rules: event-type selector,
  the structured condition rows (FR10), the agent select, the repository mode (fixed vs
  payload-field), the params form (schema-driven, reusing the invoke/schedule form), and the
  default-rule toggle. A rule whose resolution can't validate is flagged before save.
- **FR23 — Delivery log.** A per-endpoint feed of recent deliveries: timestamp, event type,
  delivery id, verification result, matched rule (or no-match), outcome
  (fired→run link / skipped+reason / rejected+reason / ignored), newest-first. Untrusted
  payload fields shown as text only. This is the primary debugging surface (G5).
- **FR24 — Boundary.** `/webhooks` is behind the panel auth gate (login). The inbound
  `/api/webhooks/**` endpoint is **public** (GitHub must reach it) but signature-gated; the
  auth release gate asserts an unsigned/invalid-signature POST → 401 (extending the S-160
  internal-endpoint assertion to the webhook class).

## 8. Acceptance Criteria

- **AC1.** A GitHub-signed delivery with a valid `X-Hub-Signature-256` is verified, recorded,
  routed, and (on match) produces a `runs` row with `trigger_type='webhook'` linked to the
  firing rule.
- **AC2.** An invalid/missing signature → 401, **no** delivery recorded as fired and **no**
  run; a replayed `X-GitHub-Delivery` → 200 no-op with no second run.
- **AC3.** An oversized body → 413; a non-allowlisted event → recorded 202 ignored; neither
  creates a run.
- **AC4.** Ordered rules evaluate first-match-wins; a payload matching rule #2's conditions
  (e.g. `pull_request_review_comment` body == "security review") fires rule #2's agent on the
  payload-derived repo; a no-match with no default is a recorded 202 no_match.
- **AC5.** A payload-derived repository not in the enabled allowlist → recorded
  route_rejected, no run; invalid resolved params → route_rejected, no run.
- **AC6.** A webhook-fired run is skipped by G1/G4/G5 exactly as a scheduled run would be,
  with the skip reason recorded on the delivery; a terminal failure records a `run_failed`
  notification via the same sweep.
- **AC7.** An event authored by the fleet's own bot identity is excluded by a self-trigger
  guard rule (no run), proving the loop-prevention path.
- **AC8.** The `/webhooks` UI creates an endpoint (secret shown once), adds ordered rules,
  and the delivery log shows each delivery's verify/route/outcome; untrusted fields render as
  text. Unauthenticated `/webhooks` → /login; unsigned `/api/webhooks/<token>` → 401
  (asserted by the release gate).
- **AC9.** No signing secret or raw signature appears in any log or delivery record.

## 9. Dependencies & Touchpoints

- **Reuses:** `runs`/`run_*` schema + the `webhook` `trigger_type` (already present); the
  internal invoke path (fire endpoint pattern, S-153); `buildRunInsert` + `TriggerDescriptor`
  (extend with a `webhook` variant); the guardrail functions G1/G4/G5 and
  `sweep_schedule_notifications` (generalize from "scheduled run" to "automated run"); the
  `repositories` allowlist + Ajv `validateParams`; the `notifications` table/feed/digest;
  Supabase Vault for the signing secret; the auth release gate (extend for the webhook class).
- **New schema:** `webhook_endpoints`, `webhook_rules`, `webhook_deliveries` (+ enums).
- **New routes:** public `POST /api/webhooks/[token]`; authenticated `/webhooks` panel +
  its Server Actions.
- **GitHub App:** Phase 1 is **read/receive only** (no new scopes). Phases 2–3 add the
  outbound comment/review scopes.
- **Downstream:** Phase 2 (code-review agent) and Phase 3 (repo-research agent) consume this
  routing to be invoked; the self-trigger guard (FR19) exists for them.

## 10. Risks & Mitigations

- **R1 — Public hostile endpoint.** Mitigation: signature-before-work, unguessable URL,
  dedup, size/timeout caps, event allowlist, text-only rendering of payload fields (FR1–FR8).
- **R2 — Routing on untrusted payload (injection/SSRF-ish).** Mitigation: bounded declarative
  condition language, no code/regex-DoS, repo constrained to the registered allowlist, params
  schema-validated (FR10, FR13, FR14).
- **R3 — Self-trigger loops** (an agent's comment re-triggering it, Phases 2–3). Mitigation:
  the bot-author exclusion guard shipped in Phase 1 (FR19); runaway also bounded by G3/G4.
- **R4 — GitHub retry storms** on a slow handler. Mitigation: fast ack after verify+record+
  enqueue (FR7); the invoke is async on the existing path.
- **R5 — Secret sprawl/rotation.** Mitigation: Vault-stored per-endpoint secret, show-once,
  rotation = re-generate + re-paste into GitHub (runbook), mirrors the scheduler secret.
- **R6 — Scope creep into the two agents.** Mitigation: Phase 1 explicitly routes to existing
  agents; the new agents are separate PRDs/phases.

## 11. Open Questions & Fast-Follows

- **OQ1.** Generic (non-GitHub) senders: confirm the default signature header name + scheme
  knobs we expose in v1 vs defer.
- **OQ2.** Delivery-log retention (rows grow with every GitHub event); a retention policy may
  be needed (ties to the backlog `run_events` retention item).
- **Fast-follows:** fan-out (one event → multiple rules), panel redelivery/replay of a past
  delivery, a visual rule builder, IP allowlisting as defense-in-depth, non-HMAC schemes.

## 12. Delivery Note

Phase 1 is delivered on an integration branch, wave by wave (schema → inbound endpoint +
verification → routing engine → execution reuse → UI + delivery log), test-first with L2.5
coverage of the verify/route/guardrail surface and E2E for the `/webhooks` UI + the
signed-delivery→run path, then a single consolidated PR to `main` (human-merged), then the
operator deploy (register the endpoint in GitHub, set the Vault secret, extend the release
gate). Phases 2–3 (the two agents) follow as their own PRDs once Phase 1 is live.
