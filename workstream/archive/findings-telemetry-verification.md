# Telemetry Verification Findings — S-012

## Date

2025-01-27 (initial documentation, pending live verification)

## Status

**Partially Verified** — field paths are populated based on OTEL/ADOT documentation and AgentCore behavior. Live verification requires a deployed run (sub-tasks 12.1, 12.7 deferred).

---

## Assumptions from Spec §8.2

| # | Assumption | Status | Evidence/Notes |
|---|---|---|---|
| 1 | Span records use `resource.attributes.*` for resource-level data | **Expected (pending live)** | OTEL spec mandates this structure; ADOT preserves it in CloudWatch |
| 2 | Span records use `attributes.*` for span-level data | **Expected (pending live)** | OTEL spec standard; gen_ai semantic conventions follow this |
| 3 | `session.id` is injected by AgentCore as a resource attribute | **Assumed present, fallback implemented** | AgentCore documentation suggests session tracking; we emit both `session.id` AND `llipe.session.id` for safety |
| 4 | `gen_ai.usage.*` tokens are on child spans, not root | **Expected (pending live)** | OTEL gen_ai semantic conventions place usage on the LLM call span |
| 5 | Root spans identifiable by empty `parentSpanId` + presence of `llipe.run.status` | **Implemented defensively** | Our agent emits `llipe.*` on root only; `parentSpanId=""` is standard OTEL root indicator |
| 6 | `duration` field exists at top level (nanoseconds) | **Expected (pending live)** | ADOT may compute this or we derive from `endTimeUnixNano - startTimeUnixNano` |
| 7 | `startTimeUnixNano` at top level for timestamp | **Expected (pending live)** | OTEL Span data model standard |
| 8 | `service.name` under `resource.attributes` | **Confirmed by OTEL spec** | Mandatory resource attribute per OTEL Resource Semantic Conventions |

---

## Session ID Strategy

### Decision

Emit **both** `session.id` AND `llipe.session.id` from the agent (in `emission.py`):

- `session.id`: May be auto-injected by AgentCore. If present, it's the canonical lookup key.
- `llipe.session.id`: Explicitly emitted with our deterministic value. Acts as guaranteed fallback.

### Resolution Priority

1. `resource.attributes.session.id` (primary — AgentCore may inject)
2. `resource.attributes.llipe.session.id` (fallback — explicitly emitted)

### Rationale

- If AgentCore injects its own `session.id` that matches ours: no issue, primary resolves.
- If AgentCore injects a DIFFERENT `session.id`: primary would resolve to AgentCore's value; fallback gives us ours. Query builder uses OR filter.
- If AgentCore does NOT inject `session.id`: fallback resolves cleanly.

The Logs Insights query uses `OR` to match either path, making this resilient to all scenarios.

---

## Root Span vs Child Span Identification

### Root Spans

- **Condition:** `parentSpanId` is empty string (`""`) or absent
- **AND:** `resource.attributes.llipe.run.status` is present and non-empty
- **Contains:** All `llipe.*` attributes (subject, status, outcome type, outcome URL)
- **Does NOT contain:** `gen_ai.*` attributes (no model invocation data)

### Child Spans (gen_ai)

- **Condition:** `parentSpanId` is populated (non-empty string)
- **AND:** `attributes.gen_ai.request.model` is present
- **Contains:** `gen_ai.usage.input_tokens`, `gen_ai.usage.output_tokens`, `gen_ai.request.model`
- **Also has:** Resource attributes inherited (service.name, session.id, etc.)

### Query Strategy

- **Run list:** Filter `ispresent(resource.attributes.\`llipe.run.status\`)` → only root spans
- **Session detail:** Filter by session ID (OR on both paths) → all spans for timeline

---

## SPAN_FIELDS Mapping (Complete)

| Logical Field | Path | Location | Notes |
|---|---|---|---|
| SESSION_ID | `resource.attributes.session.id` | Root + Child | Primary session ID |
| SESSION_ID_FALLBACK | `resource.attributes.llipe.session.id` | Root + Child | Agent-emitted fallback |
| SUBJECT_ID | `resource.attributes.llipe.subject.id` | Root (+ inherited) | Normalized owner/repo |
| RUN_STATUS | `resource.attributes.llipe.run.status` | Root only (emitted) | "success" or "failed" |
| OUTCOME_TYPE | `resource.attributes.llipe.outcome.type` | Root only (emitted) | "pr" or "none" |
| OUTCOME_URL | `resource.attributes.llipe.outcome.url` | Root only (emitted) | PR URL or empty string |
| MODEL_ID | `attributes.gen_ai.request.model` | Child only | Model identifier |
| TOKENS_IN | `attributes.gen_ai.usage.input_tokens` | Child only | Input token count |
| TOKENS_OUT | `attributes.gen_ai.usage.output_tokens` | Child only | Output token count |
| DURATION_NS | `duration` | Root + Child | Nanoseconds |
| SERVICE_NAME | `resource.attributes.service.name` | Root + Child | Agent name |
| TIMESTAMP | `startTimeUnixNano` | Root + Child | Unix nanoseconds |
| PARENT_SPAN_ID | `parentSpanId` | Root + Child | Empty = root |
| SPAN_NAME | `name` | Root + Child | Span operation name |

---

## Logs Insights Query Templates

### Run List (Root Spans Only)

```
fields resource.attributes.`session.id` as session_id,
       resource.attributes.`llipe.session.id` as session_id_fallback,
       resource.attributes.`llipe.subject.id` as subject_id,
       resource.attributes.`llipe.run.status` as run_status,
       resource.attributes.`llipe.outcome.type` as outcome_type,
       resource.attributes.`llipe.outcome.url` as outcome_url,
       resource.attributes.`service.name` as service_name,
       duration as duration_ns,
       startTimeUnixNano as start_time
| filter ispresent(resource.attributes.`llipe.run.status`)
| sort @timestamp desc
| limit 100
```

### Session Spans (All Spans for a Run)

```
fields resource.attributes.`session.id` as session_id,
       resource.attributes.`llipe.session.id` as session_id_fallback,
       resource.attributes.`llipe.subject.id` as subject_id,
       resource.attributes.`llipe.run.status` as run_status,
       resource.attributes.`llipe.outcome.type` as outcome_type,
       resource.attributes.`llipe.outcome.url` as outcome_url,
       attributes.`gen_ai.request.model` as model_id,
       attributes.`gen_ai.usage.input_tokens` as tokens_in,
       attributes.`gen_ai.usage.output_tokens` as tokens_out,
       resource.attributes.`service.name` as service_name,
       duration as duration_ns,
       startTimeUnixNano as start_time,
       parentSpanId as parent_span_id,
       name as span_name
| filter (resource.attributes.`session.id` = '<session_id>' or resource.attributes.`llipe.session.id` = '<session_id>')
| sort @timestamp asc
| limit 500
```

---

## Newly Surfaced Questions

1. **Duration field format:** ADOT may store `duration` as a computed field or require derivation from `endTimeUnixNano - startTimeUnixNano`. Need live verification.
2. **Attribute flattening:** CloudWatch Logs Insights may flatten nested JSON. If so, paths might be `resource.attributes.session.id` (dot notation in flat JSON) vs nested object traversal. Need live verification.
3. **`@timestamp` vs `startTimeUnixNano`:** Logs Insights injects `@timestamp` automatically. Need to verify whether it aligns with `startTimeUnixNano` or represents ingestion time.
4. **Multiple gen_ai spans per session:** A single run may produce multiple model calls. Cost aggregation must SUM across all gen_ai child spans per session.

---

## Deferred Verifications (Require Deployed Run)

- [ ] 12.1: Trigger token-consuming run
- [ ] 12.7: Confirm HealthyBusy and survival past 5 minutes
- [ ] 12.9: Update spec §8.2 with verified paths
- [ ] Live confirmation of `session.id` injection by AgentCore
- [ ] Live confirmation of `duration` field presence and format
- [ ] Live confirmation of attribute nesting vs flattening in Logs Insights output

---

## Implementation Summary

| Artifact | Path | Purpose |
|---|---|---|
| Span fields | `packages/shared/src/span-fields.ts` | All field paths in one place |
| Session resolver | `packages/shared/src/span-session-resolver.ts` | Greedy path resolution + session ID fallback |
| Span mapper | `packages/shared/src/span-mapper.ts` | Extract structured data from raw spans |
| Query builder | `packages/shared/src/span-query.ts` | Logs Insights query construction |
| Root span fixture | `packages/shared/__fixtures__/root-span.json` | Expected root span shape |
| Gen AI fixture | `packages/shared/__fixtures__/gen-ai-child-span.json` | Expected child span shape |
| Mapper tests | `packages/shared/src/span-mapper.test.ts` | 14 tests covering all paths |
| Resolver tests | `packages/shared/src/span-session-resolver.test.ts` | 12 tests for path resolution |
| Query tests | `packages/shared/src/span-query.test.ts` | 13 tests for query building |
