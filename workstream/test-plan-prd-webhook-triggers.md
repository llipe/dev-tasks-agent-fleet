# Compliance Test Plan — Webhook Triggers Phase 1 (verifier, Design Mode)

> A test-first compliance plan written before implementation. It is derived from
> [`prd-webhook-triggers`](../docs/requirements/prd-webhook-triggers.md) (FR1–FR24, AC1–AC9),
> [`specification-prd-webhook-triggers`](specification-prd-webhook-triggers.md) v1.1 (D-W1…D-W15),
> the stories in [`user-stories-prd-webhook-triggers`](user-stories-prd-webhook-triggers.md) (S-165…S-179, GitHub #309–#311, #313–#324)
> and the task list [`tasks-prd-webhook-triggers-plan`](tasks-prd-webhook-triggers-plan.md).
> Companion: [`traceability-matrix-prd-webhook-triggers`](traceability-matrix-prd-webhook-triggers.md).
>
> **Status:** Design Mode, so no verdict yet. The plan adds to the existing gates and does not block
> anything; `make validate`, lint, typecheck and audit still apply. Every AC maps to at least one
> positive and one negative or edge test. The endpoint is public and takes hostile input, so most of
> the weight sits on signature verification, the size cap, routing over untrusted payloads, and
> rejection paths.

## Changelog

| Version | Date       | Summary                                                   | Author   |
| ------- | ---------- | --------------------------------------------------------- | -------- |
| 1.0     | 2026-10-19 | Initial plan from spec v1.1, stories v1.0, task list v1.0. | verifier |
| 1.1     | 2026-10-19 | B-4 decided (D-W16); EC-20, CT-8, I-3 updated; R-3 added. | verifier |

## 1. Source input summary

- **Mode:** Design (pre-implementation). **Input type:** spec (whole Phase 1, 15 stories).
- **Runners (`TESTING.md`):** Vitest L1 unit, L2 component, and L2.5 integration against the live local
  Supabase stack (`REQUIRE_LOCAL_DB=1`); Playwright for E2E. Table behavior, cron jobs and
  plpgsql functions are tested at L2.5 against the real stack and are never mocked.
- **AgentCore:** the existing HTTP-boundary stub (`AWS_ENDPOINT_URL_BEDROCK_AGENTCORE`) used by the E2E harness.
- **Signing in tests:** every signed request is built in the test with Node `crypto.createHmac('sha256', secret)`
  over the exact bytes sent. One fixed vector (secret, body and expected header) is checked in and
  verified against GitHub's documented example, so the verifier is checked against an independent
  reference and not only against itself.

## 2. Acceptance-criteria extraction

| AC | Observable behavior | Primary stories |
| --- | --- | --- |
| AC1 | A correctly signed GitHub delivery is verified, recorded and routed. On a match it creates a `runs` row with `trigger_type='webhook'`, linked to the endpoint and rule that fired it. | S-169, S-171, S-172 |
| AC2 | An invalid or missing signature returns 401, creates no run and records no `fired` outcome. A replayed delivery id returns 200 and creates no second run. | S-168, S-169 |
| AC3 | A body over the cap returns 413. An event not on the allowlist is recorded as `ignored` and returns 202. Neither creates a run. | S-169 |
| AC4 | Rules are evaluated in order and the first match wins. A payload matching rule #2 fires rule #2's agent on the repo taken from the payload. No match and no default rule gives a recorded `no_match` with 202. | S-170, S-171 |
| AC5 | A repo taken from the payload that is not on the enabled allowlist gives `route_rejected` and no run. Resolved params that fail the agent schema also give `route_rejected` and no run. | S-171 |
| AC6 | G1, G4 and G5 skip a webhook-fired run the same way they skip a scheduled run, and the skip reason is recorded on the delivery. A terminal failure creates a `run_failed` notification through the same sweep. | S-173, S-174 |
| AC7 | An event sent by the fleet's own bot is excluded and creates no run. | S-170 |
| AC8 | The UI creates an endpoint and shows its secret once, adds ordered rules, and lists each delivery's outcome with untrusted fields shown as plain text. `/webhooks` redirects to `/login` when logged out. An unsigned POST returns 401, and the release gate asserts it. | S-175–S-178 |
| AC9 | No signing secret or raw signature appears in any log line, delivery row or client-visible response. | S-166, S-168, S-169, S-176 |

**Invariants the tests rely on:**
- Signatures are verified before any parsing or routing (I-1).
- Every non-401/404/413 delivery leaves exactly one delivery row with a reason (I-2).
- A delivery creates at most one run per `(endpoint, dedup_key)`, and only verified deliveries claim a key (I-3).
- Repositories are never created from a payload (I-4).
- Params can only fill keys the agent schema declares (I-5).
- The schedule and webhook triggers share one invoke path, and the schedule fire route's behavior is unchanged (I-6).
- Untrusted payload text is rendered inert (I-7).
- Pruning old deliveries never deletes runs (I-8).

## 3. E2E scenarios (black-box)

The cron schedule itself is not tested E2E. Pruning, guardrails and the sweep are tested at L2.5 with a fixed clock.

| ID | Scenario | AC | Expected observable result | Severity | Layer |
| --- | --- | --- | --- | --- | --- |
| E2E-1 | Operator creates a GitHub endpoint and a rule (`pull_request_review_comment`, body equals `security review`, payload repo → `security-analyst`), then POSTs a correctly signed matching payload. | AC1, AC8 | 202 with a `run_id`. The delivery log shows `fired` with a link to the run. Run history shows the run with trigger `webhook`. | Critical | Playwright |
| E2E-2 | The same endpoint gets an unsigned POST, then a POST signed with the wrong secret. | AC2, AC8 | Both return 401. The log shows `unauthorized` and no run is created. | Critical | Playwright |
| E2E-3 | The E2E-1 POST is replayed with the same `X-GitHub-Delivery`. | AC2 | 200 with `duplicate`. Run count is unchanged. | Critical | Playwright |
| E2E-4 | A correctly signed payload whose `sender` is the bot account (`<app_slug>[bot]`, type `Bot`). | AC7 | 202 with no run. The log shows the guard reason. | High | Playwright |
| E2E-5 | A correctly signed `issues` event, which is not on the allowlist. | AC3 | 202, logged as `ignored`, no run. | Medium | Playwright |
| E2E-6 | Signed-out visits to `/webhooks` and `/webhooks/<id>`, and a POST to a Server Action. | AC8 | The pages redirect to `/login`. The action is rejected and nothing changes in the database. | Critical | Playwright |
| E2E-7 | Operator rotates the secret, then sends one POST signed with the old secret and one with the new secret. | AC8, AC2 | The new secret is shown once. The old-secret POST returns 401 and the new-secret POST returns 202. After a reload the secret is no longer visible. | High | Playwright |
| E2E-8 | Operator reorders two overlapping rules and sends the same payload again. | AC4 | The rule that is now first is the one recorded as matched. | High | Playwright |
| E2E-9 (abuse) | A correctly signed payload whose comment body contains `<img src=x onerror=…>` and `<script>`, matching no rule. | AC8, I-7 | The log row renders the text inertly. No script runs (checked with a dialog listener and the DOM). | High | Playwright |

## 4. Contract and schema-compatibility scenarios

Each contract gets a valid case, a missing-field case, a type-mismatch case and an extra-field case.

| ID | Contract | AC / D | Valid | Missing field | Type mismatch | Extra field |
| --- | --- | --- | --- | --- | --- | --- |
| CT-1 | Inbound request headers (`X-Hub-Signature-256`, `X-GitHub-Delivery`, `X-GitHub-Event`) | AC1–3 / D-W1, D-W15 | All present and valid → processed | No signature → 401. No delivery id → body-hash dedup key. No event header → `ignored` with reason `missing_event` | Signature `sha1=…`, bare hex, base64 or uppercase hex → 401 | An extra `X-Hub-Signature` (sha1) is ignored and the decision uses only the configured header |
| CT-2 | Inbound response shapes | AC1–5 | `202 {run_id,status:"queued"}`, `202 {skipped,reason}`, `200 {duplicate:true}` | — | — | Responses never contain the secret, signature, rule conditions or payload echo (AC9) |
| CT-3 | Inbound body | AC3 / D-W3 | Valid JSON within the cap | Empty body with a valid signature → `ignored:invalid_json` | Non-JSON or a top-level array with a valid signature → `ignored:invalid_json` and the route does not crash | Unknown payload keys are tolerated and only the selected paths are read |
| CT-4 | Stored `webhook_rules.conditions` | AC4 / D-W7 | `[{field,op,value}]` with a known op | Missing `field` or `op` → rejected at save | `value` not a string for `prefix` → rejected. `in` without an array → rejected | Unknown keys are rejected at save, because a stray key could hide a typo |
| CT-5 | Rule params (`static` + `from_payload`) checked against `agents.params_schema` | AC5 / D-W9 | Declared keys resolve and validate | A required schema key is absent at fire time → `route_rejected` | A payload value of the wrong type for the key → `route_rejected` | An undeclared `from_payload` key is rejected at save and dropped at fire, and is never sent to the agent |
| CT-6 | `runs` insert through `buildRunInsert` with the webhook descriptor | AC1 / D-W5 | `trigger_type='webhook'`, `triggered_by='webhook:<endpoint>:<rule>'`, all three timeout snapshots | Missing timeout → `RunSnapshotError` | A malformed `webhook:` identity fails to type-check | The manual and schedule descriptors produce byte-identical rows to before (I-6) |
| CT-7 | Fire-route contract after the refactor (S-172) | I-6 | Existing L1 and L2.5 fire suites pass, with the pass count equal to the baseline from task 8.1 | — | — | No new response fields or status codes |
| CT-8 | `webhook_deliveries` uniqueness and FK | AC2 / D-W4 | One claimed row per `(endpoint_id, dedup_key)`; any number of `unauthorized` rows may share a `delivery_id` | — | — | A duplicate verified insert adds no claimed row. Deleting a run nulls `run_id` and keeps the row |
| CT-9 | RLS deny-all on the three new tables | AC9 / D-W4 | service_role can read | — | — | anon reads 0 rows from each table. The guard seeds rows first so the check cannot pass on empty tables |
| CT-10 | Vault secret wrappers | AC9 / D-W4 | Set then read returns the same value | A missing secret reads as null, and the route fails closed with 401 | — | No table or view exposes the secret to anon or to the panel's row types |
| CT-11 | Release-gate parser (`checkWebhookRejected`) | AC8 / FR24 | 401 → pass | `WEBHOOK_PROBE_TOKEN` unset → the gate fails with a clear message | 2xx, 404 or 5xx → the gate fails | — |

**Boundaries without a clear contract (routed to `product-engineer`):**
- **B-1:** When a route resolves and then a guardrail skips the run, which response does the endpoint return? The spec table says `202 {skipped, reason}`. The plan assumes that and asserts it.
- **B-2:** CT-4 says unknown condition keys are rejected at save, but the spec does not say so. The plan asserts rejection. If the spec intends to tolerate them, CT-4 should be changed.

## 5. Edge-case catalog

Each case is tied to an AC and gives a concrete example. The layer is shown in brackets.

### 5.1 Input domain
- **EC-1** (AC2) [L1] The signature header has whitespace around it or has two values joined by a comma → reject. The header is not trimmed or split before comparison.
- **EC-2** (AC2) [L1] `sha256=` followed by 64 valid hex characters plus one more → reject (wrong length) without throwing.
- **EC-3** (AC2) [L1] The body differs only by a trailing `\n`, or by `\r\n` instead of `\n` → reject. This proves the HMAC covers the raw bytes and no re-serialized form.
- **EC-4** (AC1) [L2.5] The body contains multibyte UTF-8 (emoji in a comment) → verifies. The bytes are not normalized or decoded and re-encoded before hashing.
- **EC-5** (AC4) [L1] A condition path into an array index that is out of range (`commits[99].id`), a negative index, or a non-numeric index → undefined. The condition is false and nothing throws.
- **EC-6** (AC4) [L1] The selected field is a number, a boolean or null and the op is a string op (`prefix`) → false. Values are not coerced.
- **EC-7** (AC5) [L1] A `payload_field` repo value with different case (`LLipe/Repo`), a trailing `.git`, or a URL instead of `owner/name` → only the exact `full_name` match (case-insensitive) resolves. The others give `route_rejected`.
- **EC-8** (AC1) [L1] The URL token contains `../`, `%2F` or has an extra path segment → 404. The token is checked against a fixed character set and length before any lookup.

### 5.2 State transitions
- **EC-9** (AC4) [L2.5] A disabled rule that would match comes before an enabled rule that also matches → the enabled rule fires.
- **EC-10** (AC6) [L2.5] G3: after N−1 failures, one success, then N−1 more failures, the rule is still enabled because the success reset the counter. After N consecutive failures it is disabled, one notification is created, and the next matching delivery skips to the next rule or `no_match`.
- **EC-11** (AC8) [L2.5] A disabled endpoint receives a correctly signed delivery → 404 with no row. This matches the spec's "unknown or disabled token". It is listed for confirmation as B-3 in §8.
- **EC-12** (AC4) [L2.5] A rule is deleted while a delivery that matched it is recorded. The FK on `matched_rule_id` must allow this (set null), and the log still renders.
- **EC-13** (AC6) [L2.5] The agent is disabled after the rule was saved → `route_rejected:agent_unavailable` and no run.

### 5.3 Timing and concurrency
- **EC-14** (AC2, I-3) [L2.5] Two identical deliveries arrive concurrently (`Promise.all`) → exactly one delivery row, exactly one run, and one 200 `duplicate`.
- **EC-15** (AC1) [L2.5] AgentCore is slow (the stub delays 8 s) → the endpoint responds within the budget from task 8.8, the run is visible as queued, and the invoke still completes or is marked `failed_to_start`.
- **EC-16** (AC6) [L2.5] G4 cap at K−1 in-flight and two webhook deliveries arrive at the same moment → at most one is dispatched and the other is `skipped:concurrency_cap`. The cap is never exceeded.
- **EC-17** (I-8) [L2.5] Prune runs while a delivery is being inserted → no error, and the new row survives.

### 5.4 Idempotency
- **EC-18** (AC2) [L2.5] There is no delivery header and the same body is sent twice → body-hash dedup returns `duplicate`. The same body sent to two different endpoints is not a duplicate, because the key is per endpoint.
- **EC-19** (AC6) [L2.5] The notify sweep runs three times over the same terminal webhook run → one `run_failed` row.
- **EC-20** (AC2) [L2.5] A forged POST reusing a real delivery id arrives first → recorded `unauthorized`, no key claimed. The genuine signed POST with that id then fires. Both rows show up together when filtering the log by delivery id. A replay of a delivery that already verified stays `duplicate`, even after a secret rotation (D-W16).

### 5.5 Failure modes
- **EC-21** (AC9) [L2.5] The Vault read returns null for the endpoint secret → 401 (fail closed). The log says `secret_not_configured` and shows no value.
- **EC-22** (AC1) [L1] AgentCore invoke throws → the run becomes `failed_to_start`, the delivery is recorded `fired` with the run id, the G3 counter goes up by one, and the endpoint still returns 2xx so GitHub does not retry a routing decision.
- **EC-23** (I-2) [L1] The database is unreachable after the signature has been verified → 5xx so GitHub retries. A routing decision must not be acknowledged when it could not be recorded.
- **EC-24** (AC6) [L2.5] A run whose rule was deleted reaches a terminal state → the sweep follows the #302 decision (task 10.1).

### 5.6 Auth and permissions
- **EC-25** (AC8) [E2E] A signed-in operator session cookie sent to `/api/webhooks/<token>` without a signature → still 401. A session does not replace the signature.
- **EC-26** (AC8) [L1] Route policy: `/api/webhooks` and `/api/webhooks/x` are classed as session-bypass. `/api/webhooksx` and `/webhooks` (the UI page) stay session-gated.
- **EC-27** (AC9) [L2.5] A Server Action response, an RSC payload or a page HTML never contains the endpoint secret after the show-once moment. Grep the rendered output.
- **EC-28** (AC7) [L1] A human user whose login is literally `<app_slug>[bot]` with `type: "User"` is not excluded. A different app's bot is not excluded unless a condition excludes it.

### 5.7 Data boundaries
- **EC-29** (AC3) [L2.5] A body of exactly the cap → accepted. Cap + 1 byte → 413. No `Content-Length` with a chunked body over the cap → 413, so the stream limit enforces the cap.
- **EC-30** (AC4) [L1] A path at exactly the max depth resolves. Max depth + 1 → undefined.
- **EC-31** (AC4) [L1] A condition value or field string at the length cap is accepted. Cap + 1 is rejected at save.
- **EC-32** (AC8) [L2] The delivery log with 0 rows shows an empty state. One page plus one row → pagination appears. A newest-first tie on `created_at` is broken by `id`.

### 5.8 Resource exhaustion
- **EC-33** (AC4) [L1] A payload nested 10,000 levels deep, an array of 100k items, or a 4 MB string field, all within the body cap → routing returns within a time bound (assert < 50 ms), with no recursion stack overflow.
- **EC-34** (AC4) [L1] An endpoint with the maximum supported number of rules (pick 100) is evaluated within the same time bound.
- **EC-35** (I-8) [L2.5] One prune call over more than the batch-size aged rows deletes exactly the batch size and leaves the rest for the next run.

### 5.9 API versioning
- **EC-36** (AC1) [L1] A GitHub payload with extra new fields is handled the same way (forward compatible). The plan uses checked-in fixture payloads for the four allowlisted events.
- N/A otherwise. The panel has no versioned public API, and the inbound contract is GitHub's webhook format.

## 6. Randomized and property tactics

The randomized tests use the repo's existing approach instead of adding a new dependency. They use a `mulberry32(seed)` PRNG, take the seed from `TEST_SEED` with a fixed default, and include the seed in every assertion message. This is the same pattern as `panel/tests/component/live-log-viewer.test.tsx`. The helper should move into a shared `panel/tests/helpers/prng.ts` rather than being copied. If shrinking is needed, the minimized vector from the failure triage is added as a fixed regression case.

**Replay:** `TEST_SEED=<seed> pnpm --filter panel exec vitest run <file> -t "<RT-id>"`. Record the Node version (22.23.2 in this sandbox) and the OS with any failure.

| ID | AC | Type | Input surface | Property / oracle | Iterations | Default seed | Shrink |
| --- | --- | --- | --- | --- | --- | --- | --- |
| RT-1 | AC2 | fuzz | `verifyHmacSignature` with random bodies (0–64 KiB of random bytes) and random secrets | Only the exactly computed header verifies. Any single-bit flip in the body, secret or header rejects. Never throws. | 2,000 | 309001 | Halve the body length while it still fails |
| RT-2 | AC4 | fuzz | `selectField` / `routeDelivery` with random JSON trees (depth 0–40, mixed types, keys drawn from a pool that includes `__proto__`, `constructor` and `prototype`) and random paths | Never throws. The result is always `match`, `default` or `no_match`. `Object.prototype` is unchanged afterwards. | 5,000 | 315001 | Prune subtrees while it still fails |
| RT-3 | AC4 | property | Random rule lists (1–20 rules, random positions and enabled flags) and a payload | The returned rule is the enabled, matching rule with the lowest `position`. A brute-force reference implementation in the test is the oracle. | 3,000 | 315002 | Drop rules one at a time |
| RT-4 | AC5, I-5 | property | Random `from_payload` maps (declared and undeclared keys) against a fixed agent schema | Resolved param keys are always a subset of the schema's declared properties. An undeclared key never reaches the result. | 2,000 | 316001 | Remove keys |
| RT-5 | AC2, I-3 | stateful random walk | A random sequence of new, duplicate, unsigned and oversized POSTs (length 20–60) against the L2.5 route | Number of runs equals number of distinct valid matching delivery ids. Number of delivery rows equals number of distinct delivery ids plus 401 rows. Never more than one run per id. | 30 walks | 314001 | Cut the walk short at the first divergence |
| RT-6 | AC6 | stateful random walk | Random success/failure sequences for one rule | The rule is disabled if and only if the sequence contains N consecutive failures since the last success. Exactly one notification is created per disable. | 200 | 318001 | Trim the sequence prefix |

## 7. Execution checklist (test-first order)

Write each group before the matching story's `[I]` tasks:

1. **S-168 signature** (CT-1, EC-1–EC-3, RT-1, the fixed GitHub vector) at L1. This is the highest-risk area and has no dependencies.
2. **S-165/S-166 schema and Vault** (CT-8–CT-10, EC-21) at L2.5.
3. **S-169 route** (E2E-2/3/5 at L1 and L2.5 first, EC-8, EC-14, EC-18, EC-20, EC-23, EC-25–EC-26, EC-29, RT-5) at L1 and L2.5.
4. **S-170 routing** (CT-4, EC-5/6, EC-9, EC-28, EC-30/31, EC-33/34, RT-2/3) at L1.
5. **S-171 resolution** (CT-5, EC-7, EC-13, RT-4) at L1 and L2.5.
6. **S-172 refactor.** Record the baseline first (task 8.1), then CT-6, CT-7, EC-15, EC-22.
7. **S-173 guardrails** (EC-10, EC-16, RT-6), **S-174 sweep** (EC-19, EC-24) and **S-167 prune** (EC-17, EC-35) at L2.5.
8. **S-175 gate** (CT-11) at L1, plus shellcheck.
9. **S-176–S-178 UI** (EC-11/12, EC-27, EC-32, E2E-6/7/8/9) at L2 and L2.5, matched to DESIGN.md.
10. **S-179 E2E** (E2E-1–E2E-9), the last story. It reuses the fixtures from the earlier steps.

## 8. Boundary questions and residual risks (routed to `product-engineer`)

- **B-1 (skip response shape):** a guardrail skip after resolution returns `202 {skipped, reason}`, as assumed in CT-2. Confirm.
- **B-2 (unknown condition keys):** the plan rejects them at save (CT-4). Confirm, or relax CT-4.
- **B-3 (disabled endpoint):** returns 404 with no row (EC-11), so a disabled endpoint leaves no trace in the delivery log. If the operator wants to see deliveries sent to a disabled endpoint, the behavior should be 202 `ignored` with a row instead.
- **B-4 — decided 2026-10-19 (D-W16):** every delivery is recorded, including `unauthorized`, for tracking and troubleshooting. Only deliveries whose signature verified claim the dedup key. Covered by EC-14, EC-18, EC-20, RT-5.
- **R-3 (unauthorized-row volume):** because `unauthorized` rows claim no key, anyone holding the endpoint URL can add rows without limit. Mitigations already in place: the unguessable URL token, the 5 MiB body cap, structured rows with no body stored, and the 30-day prune. If the token leaks, rotate it. A per-endpoint rate cap on `unauthorized` recording is a candidate fast-follow, not in v1.
- **B-5 (DB failure after verify):** returns 5xx so GitHub retries (EC-23). GitHub will then redeliver with the same id. That is safe only if nothing was recorded, so the dedup insert and the outcome must not be split across a failure. This is covered by RT-5.
- **R-1 (latency):** GitHub's 10 s timeout and the synchronous invoke (task 8.8). EC-15 makes this observable. The fallback is to respond after insert.
- **R-2 (fire-route refactor):** I-6 is verified by the baseline pass count (CT-7), not only by "tests still pass". A test deleted by mistake during the refactor would otherwise go unnoticed.

## 9. Output contract

- **Mode / phase:** Design, Phase 3 complete (test design).
- **Artifacts:** this plan and `traceability-matrix-prd-webhook-triggers.md`.
- **AC coverage:** 9 of 9 ACs have at least one positive and one negative or edge test (see the matrix). Invariants I-1 to I-8 are each covered by at least one test.
- **Blocking gaps:** none. B-4 decided (D-W16). B-1, B-2 and B-3 are confirmations.
- **Handoff:** `developer` implements test-first in the §7 order. After implementation, `verifier` Audit Mode checks the delivered behavior against this plan and fills in the matrix.
