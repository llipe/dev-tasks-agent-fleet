# Compliance Test Plan — Wave 2 (S-104, S-105, S-111)

**Mode:** Design (test-first, pre-implementation)
**Produced:** 2026-09-03
**Fallback notice:** produced by `product-engineer` applying the `verifier` Design Mode activity skills (`activity-contract-test-design`, `activity-edge-case-refinement`) directly, because no `verifier` delegation tool is available in this runtime. Treat it as a Design Mode artifact; it has **not** been independently reviewed by the `verifier` agent.

## Sources

| Artifact | Version | Consumed |
| --- | --- | --- |
| [`user-stories-prd-agent-fleet-panel-v2.md`](user-stories-prd-agent-fleet-panel-v2.md) | v1.0 | § S-104, S-105, S-111 |
| [`specification-prd-agent-fleet-panel-v2.md`](specification-prd-agent-fleet-panel-v2.md) | v1.3 | SD2, SD4, SD9, SD10, SD12, §13, §14, §16 |
| [`/DESIGN.md`](../DESIGN.md) | v1.0 | §2, §6, §7, §10, §11.2 |
| [`tasks-prd-agent-fleet-panel-v2-wave2-plan.md`](tasks-prd-agent-fleet-panel-v2-wave2-plan.md) | — | Tasks 1.0, 2.0, 3.0 |
| [`TESTING.md`](../TESTING.md) | — | Layer taxonomy, reachability rule |

## Acceptance Criteria Under Test

Renumbered for traceability; the story file is authoritative for wording.

**S-104 — server-side data layer and status parity (#117)**

| ID | Criterion |
| --- | --- |
| AC-104.1 | `lib/supabase/server.ts` creates a per-request client from a server-only env var; importing it from a client component fails lint |
| AC-104.2 | Typed query helpers exist for all eight read paths |
| AC-104.3 | `lib/domain/status.ts` exports `effectiveStatus(run, now)` implementing SD4 exactly |
| AC-104.4 | A Layer 2.5 parity test proves `effectiveStatus` agrees with `v_runs.effective_status`, including exact-boundary rows |
| AC-104.5 | A Layer 2.5 security-negative test proves an anon-key client reads zero rows from every table and from `v_runs` |
| AC-104.6 | A build-artifact test proves no client chunk contains the service role key |
| AC-104.7 | Run routes are `force-dynamic`; no Next.js data cache for run data |

**S-105 — tokens, primitives, formatters (#118)**

| ID | Criterion |
| --- | --- |
| AC-105.1 | `styles/tokens.css` defines every `/DESIGN.md` §2 token, incl. the four SD10 `--st-*` colors |
| AC-105.2 | No component contains a hardcoded hex, font family, or pixel spacing value |
| AC-105.3 | All twelve `/DESIGN.md` §11.2 components exist and are unit-tested with their documented variants |
| AC-105.4 | `StatusPill`/`StatusDot` cover all six statuses incl. `failed_to_start` hollow dot and `running`/`queued` pulse |
| AC-105.5 | Status meaning is conveyed by text, never color alone; `:focus-visible` is a 2px accent outline at 2px offset, default rings suppressed |
| AC-105.6 | `lib/format.ts` implements every `/DESIGN.md` §7 convention |
| AC-105.7 | Icons come from `@phosphor-icons/react` on `currentColor`; no Unicode stand-ins |

**S-111 — AWS credential provider (#124)**

| ID | Criterion |
| --- | --- |
| AC-111.1 | Branch detection by `FLY_APP_NAME` + socket existence; callers receive a provider and cannot tell which branch ran |
| AC-111.2 | Fly branch requests `/.fly/api` with `aud=sts.amazonaws.com` and exchanges via `AssumeRoleWithWebIdentity` |
| AC-111.3 | Token extraction accepts `value` or `token` only; other shapes throw `FlyOidcShapeError` naming received keys; `aud` and `data.trim()` fallbacks removed |
| AC-111.4 | Local branch uses `fromNodeProviderChain()` with no code change between environments |
| AC-111.5 | In-memory cache with 60s refresh margin + single-flight promise — concurrent invokes trigger one STS call |
| AC-111.6 | `credentialSource()` reports the active branch and is logged on every invoke |
| AC-111.7 | All comments English; the embedded `curl` probe command retained |
| AC-111.8 | `CREDENTIALS_UNAVAILABLE` (500) is distinct from `INVOCATION_FAILED` (502) |

---

## Part 1 — Contract Scenarios

Eight boundaries identified. Two of them carry no verified provider and are flagged in Part 3.

| # | Boundary | Type | Provider | Consumer |
| --- | --- | --- | --- | --- |
| B1 | `v_runs.effective_status` ↔ `effectiveStatus()` | schema-compat | SQL view (canonical) | TypeScript |
| B2 | PostgREST row shapes ↔ `lib/supabase/types.ts` | provider-driven | Postgres schema | query helpers |
| B3 | RLS deny-all ↔ anon client | provider-driven (security) | Postgres RLS | any anon caller |
| B4 | Built client bundle ↔ secret-free invariant | provider-driven (security) | Next.js build | browser |
| B5 | Fly OIDC socket response ↔ token extraction | provider-driven | Fly Machine (**UNVERIFIED**) | `credentials.ts` |
| B6 | STS `AssumeRoleWithWebIdentity` ↔ provider | provider-driven | AWS STS | `credentials.ts` |
| B7 | `/DESIGN.md` §2 token set ↔ `tokens.css` | schema-compat | DESIGN.md (normative) | panel CSS |
| B8 | `/DESIGN.md` §7 formatting ↔ `lib/format.ts` | schema-compat | DESIGN.md (normative) | formatters |

### CT-1: `effectiveStatus` agrees with the view on every status value

| Field | Value |
| --- | --- |
| **AC(s)** | AC-104.3, AC-104.4 |
| **Contract type** | schema-compat |
| **Boundary** | B1 |
| **Direction** | response (derived value) |
| **Input** | A fixture matrix of `runs` rows covering the cross-product of `{queued, running, succeeded, failed, canceled, timed_out, failed_to_start}` × `{fresh, stale}` clocks, inserted into the local database, then read back through `v_runs` and passed through `effectiveStatus` with the same injected `now` |
| **Expected Result** | For every row, `v_runs.effective_status === effectiveStatus(row, now)` |
| **Pass Criteria** | Zero disagreements across the matrix. The test asserts row-by-row with the failing row's `id`, `status`, and both derived values in the failure message |

### CT-2: Exact-boundary equality resolves identically on both sides

| Field | Value |
| --- | --- |
| **AC(s)** | AC-104.4 |
| **Contract type** | schema-compat |
| **Boundary** | B1 |
| **Direction** | response |
| **Input** | Rows where `now` equals `started_at + max_runtime_seconds + grace_seconds` **exactly**, and where `now` equals `queued_at + start_timeout_seconds` exactly. Plus one row one microsecond either side of each boundary |
| **Expected Result** | The SQL uses `now() > …` (strict). At exact equality both sides must return the **pass-through** status, not the reaped one. One microsecond past, both must flip |
| **Pass Criteria** | Both implementations agree at equality, at −1µs, and at +1µs. This is the single scenario most likely to expose an inclusive/exclusive mismatch, which is why it is separated from CT-1 |

### CT-3: Null `started_at` on a `running` row does not derive `timed_out`

| Field | Value |
| --- | --- |
| **AC(s)** | AC-104.3, AC-104.4 |
| **Contract type** | schema-compat |
| **Boundary** | B1 |
| **Direction** | response |
| **Input** | `status = 'running'`, `started_at = null`, `queued_at` far in the past |
| **Expected Result** | Both sides return `running`. In SQL the `and started_at is not null` guard handles it; in TypeScript the `run.started_at &&` guard must match |
| **Pass Criteria** | Neither side returns `timed_out`. A row that cannot be evaluated must not be silently reaped |

### CT-4: Null `max_runtime_seconds` does not produce a nonsense comparison

| Field | Value |
| --- | --- |
| **AC(s)** | AC-104.3 |
| **Contract type** | schema-compat |
| **Boundary** | B1 |
| **Direction** | response |
| **Input** | `status = 'running'`, `started_at` far past, `max_runtime_seconds = null` (reachable only by direct insert — the column is `not null`, so this is a defensive contract, not a live shape) |
| **Expected Result** | SQL yields `null` from the interval arithmetic, so the `case` falls through to `running`. TypeScript must do the same, not coerce `null` to `0` and derive `timed_out` |
| **Pass Criteria** | Both return `running`. **Flagged:** because the column is `not null`, this scenario tests TypeScript's defensiveness against a shape the database forbids. Keep it as a unit test even if the integration side is unreachable |

### CT-5: Query helper row shapes match the declared types

| Field | Value |
| --- | --- |
| **AC(s)** | AC-104.2 |
| **Contract type** | provider-driven |
| **Boundary** | B2 |
| **Direction** | response |
| **Input** | Each of the eight helpers executed against the seeded local stack |
| **Expected Result** | Every returned object carries exactly the declared keys with the declared types. `v_runs` supplies `effective_status`, `agent_slug`, `repository_full_name` |
| **Pass Criteria** | Runtime shape assertion per helper (not just a TypeScript cast — a cast proves nothing at runtime). Absent or extra columns fail |

### CT-6: Anon-key client reads zero rows from every table and the view

| Field | Value |
| --- | --- |
| **AC(s)** | AC-104.5 |
| **Contract type** | provider-driven (security) |
| **Boundary** | B3 |
| **Direction** | response |
| **Input** | An anon-key client issues a `select` against each of `github_installations`, `repositories`, `agents`, `runs`, `run_steps`, `run_events`, `run_artifacts`, **and** `v_runs`, against a database containing seeded rows |
| **Expected Result** | Zero rows or an explicit permission error from every one of the eight objects |
| **Pass Criteria** | No object returns ≥1 row. The table list is enumerated from the schema, not hardcoded, so a future table is not silently exempt. This is the test that would have caught F2 before it became an architecture decision |

### CT-7: No built client chunk contains the service role key

| Field | Value |
| --- | --- |
| **AC(s)** | AC-104.6 |
| **Contract type** | provider-driven (security) |
| **Boundary** | B4 |
| **Direction** | build artifact |
| **Input** | A production build performed with a **sentinel** service role key value, then every emitted client chunk scanned for that sentinel and for the `SUPABASE_SERVICE_ROLE_KEY` identifier |
| **Expected Result** | Zero occurrences in any client-side asset |
| **Pass Criteria** | Grep over the real build output returns nothing. **Design note:** the test must use a sentinel rather than the live key, or the assertion is untestable in CI where no real key exists — and a test that cannot fail is worse than no test |

### CT-8: Fly OIDC token extraction accepts only `value` or `token`

| Field | Value |
| --- | --- |
| **AC(s)** | AC-111.3 |
| **Contract type** | provider-driven |
| **Boundary** | B5 |
| **Direction** | response |
| **Input** | Six mocked socket bodies: `{"value":"<jwt>"}`, `{"token":"<jwt>"}`, `{"aud":"sts.amazonaws.com"}`, `{}`, `not-json-at-all`, `{"value":12345}` |
| **Expected Result** | First two resolve to the JWT. The last four throw `FlyOidcShapeError` whose message names the keys actually received |
| **Pass Criteria** | No input path sends a non-token string to STS. `{"aud":…}` in particular must throw, not return `"sts.amazonaws.com"` — that is the exact F5 defect |

### CT-9: STS failure surfaces `CREDENTIALS_UNAVAILABLE`, not a generic error

| Field | Value |
| --- | --- |
| **AC(s)** | AC-111.5, AC-111.8 |
| **Contract type** | provider-driven |
| **Boundary** | B6 |
| **Direction** | response |
| **Input** | Mocked STS returning `AccessDenied`, then `InvalidIdentityToken`, then a network error |
| **Expected Result** | All three surface as `CREDENTIALS_UNAVAILABLE` (500), never as `INVOCATION_FAILED` (502) |
| **Pass Criteria** | Error code asserted per case. R6 diagnosis depends on this split: 500 means "the panel could not get credentials", 502 means "AgentCore rejected the call". Conflating them sends the operator to the wrong runbook |

### CT-10: Every `/DESIGN.md` §2 token exists in `tokens.css`

| Field | Value |
| --- | --- |
| **AC(s)** | AC-105.1 |
| **Contract type** | schema-compat |
| **Boundary** | B7 |
| **Direction** | token declaration |
| **Input** | The token name list from `/DESIGN.md` §2.1–§2.8, held as test data |
| **Expected Result** | Every listed custom property is declared in `tokens.css` |
| **Pass Criteria** | Zero missing. **Must include the four SD10 `--st-*` colors**, which are absent from the Nocturne stylesheet and are the documented trap. A missing `--st-timeout` renders a `timed_out` pill transparent — visually plausible and silently wrong |

### CT-11: Formatter output matches the §7 conventions exactly

| Field | Value |
| --- | --- |
| **AC(s)** | AC-105.6 |
| **Contract type** | schema-compat |
| **Boundary** | B8 |
| **Direction** | formatted string |
| **Input** | Table-driven cases per §7.1–§7.3: `184000ms → "3m 04s"` (zero-padded seconds), `4000ms → "4s"`, `72000ms → "1m 12s"`, a running run → `"running · 2m"`, `"01J8XQ2F"` short-ID casing, `"2/4"` step progress, `"12 ev"`, `"65 ok · 11 fail · 6 timeout"` |
| **Expected Result** | Byte-exact match, including the `·` separator and the zero-padded seconds in `Xm XXs` |
| **Pass Criteria** | Every case exact. Note `3m 04s` pads seconds but `4s` does not — a naive single formatter gets one of these wrong |

### CT-12: Unknown status renders a fallback, not a crash

| Field | Value |
| --- | --- |
| **AC(s)** | AC-105.4 |
| **Contract type** | schema-compat (forward compatibility) |
| **Boundary** | B7 |
| **Direction** | render |
| **Input** | `StatusPill` and `StatusDot` given a status string not in the six-value enum (simulating a future enum value added by a migration before the panel is redeployed) |
| **Expected Result** | A neutral pill with the raw status as text. No throw, no blank render |
| **Pass Criteria** | Component renders and the unknown value is legible. This is the only versioning scenario in Wave 2 and it is real: `run_status` is a Postgres enum that a future migration can extend |

---

## Part 2 — Edge-Case Catalog

All nine categories evaluated.

### 1. Input Domain

### EC-1: 8 KB log message renders wrapped, never truncated

| Field | Value |
| --- | --- |
| **AC(s)** | AC-105.3 |
| **Category** | Input Domain |
| **Input / Setup** | `LogLine` given a message at the `run_events.message` 8 KB truncation ceiling, containing no whitespace for 2,000 consecutive characters |
| **Expected Result** | Full content present in the DOM, wrapped via `pre-wrap` + `word-break`. No ellipsis, no clipping |
| **Risk if Missed** | The operator loses the tail of a stack trace — exactly the content the panel exists to surface. `/DESIGN.md` §7.5 forbids truncating log content |

### EC-2: Log message containing HTML and script tags renders inert

| Field | Value |
| --- | --- |
| **AC(s)** | AC-105.3 |
| **Category** | Input Domain (security) |
| **Input / Setup** | `LogLine` given `<script>alert(1)</script>` and `<img src=x onerror=alert(1)>` as message content |
| **Expected Result** | Rendered as visible literal text; no script execution, no element injection |
| **Risk if Missed** | Stored XSS with an agent-authored payload. The agent runs LLM-generated code (ADR-001), so `message` is untrusted input by design, not by accident |

### EC-3: Extremely long agent name truncates per variant

| Field | Value |
| --- | --- |
| **AC(s)** | AC-105.3 |
| **Category** | Input Domain |
| **Input / Setup** | A 400-character agent name and a 1,200-character description rendered in the table variant and the card variant |
| **Expected Result** | Table: single-line ellipsis. Card: 2-line clamp. Neither breaks the grid or pushes sibling columns |
| **Risk if Missed** | One bad seed row destroys the dashboard layout |

### 2. State Transitions

### EC-4: A terminal status is never re-derived

| Field | Value |
| --- | --- |
| **AC(s)** | AC-104.3 |
| **Category** | State Transitions |
| **Input / Setup** | `effectiveStatus` given `succeeded`, `failed`, `canceled`, `timed_out`, and `failed_to_start` rows whose clocks are all far past every threshold |
| **Expected Result** | Each passes through unchanged. A `succeeded` run with a stale clock stays `succeeded` |
| **Risk if Missed** | The panel would relabel a successful run as `timed_out` — directly contradicting D3's separation of lifecycle from outcome, and destroying trust in the one screen that is supposed to be authoritative |

### EC-5: `failed_to_start` written by the panel and by the reaper are indistinguishable downstream

| Field | Value |
| --- | --- |
| **AC(s)** | AC-104.2, AC-104.3 |
| **Category** | State Transitions |
| **Input / Setup** | Two `failed_to_start` rows — one with `error_code = INVOCATION_FAILED`-style panel attribution, one with the reaper's `START_TIMEOUT` and its explanatory `run_events` row |
| **Expected Result** | Both read back and derive identically; the read path does not assume a single writer (spec §8.1) |
| **Risk if Missed** | A read path that assumes only the reaper writes `failed_to_start` mishandles the panel's own synchronous write, which is the more common case |

### 3. Timing & Concurrency

### EC-6: Two concurrent credential requests trigger exactly one STS call

| Field | Value |
| --- | --- |
| **AC(s)** | AC-111.5 |
| **Category** | Timing & Concurrency |
| **Input / Setup** | Cold cache. Two `getCredentials()` calls issued in the same tick with a mocked STS that records call count and resolves after a delay |
| **Expected Result** | One STS call; both callers receive the same credentials |
| **Risk if Missed** | Every concurrent invoke burns an STS call. Not fatal at single-operator scale, but the single-flight promise is explicitly in the AC, so an untested one is an unverified one |

### EC-7: Clock skew inside the refresh margin does not serve an expired credential

| Field | Value |
| --- | --- |
| **AC(s)** | AC-111.5 |
| **Category** | Timing & Concurrency |
| **Input / Setup** | Cached credentials whose expiry is 59 seconds away (inside the 60-second margin), and a second case at 61 seconds |
| **Expected Result** | 59s → cache miss, refresh. 61s → cache hit, no STS call |
| **Risk if Missed** | An invoke fails with an expired-token auth error that looks like an IAM misconfiguration, sending the operator down the wrong diagnostic path (R6) |

### 4. Idempotency

### EC-8: Repeated `effectiveStatus` calls with the same `now` are stable

| Field | Value |
| --- | --- |
| **AC(s)** | AC-104.3 |
| **Category** | Idempotency |
| **Input / Setup** | The same row evaluated 100 times with an identical injected `now` |
| **Expected Result** | Identical result every time; no hidden clock read, no mutation of the input row |
| **Risk if Missed** | A function that reads the ambient clock internally cannot be tested at boundaries at all, which would silently void CT-2 — the most important scenario in this plan |

### 5. Failure Modes

### EC-9: PostgREST failure surfaces `DATABASE_ERROR` without leaking the Postgres code

| Field | Value |
| --- | --- |
| **AC(s)** | AC-104.2 |
| **Category** | Failure Modes |
| **Input / Setup** | Mocked PostgREST returning a connection error, then a `42501` insufficient-privilege error, then a malformed JSON body |
| **Expected Result** | All become `DATABASE_ERROR` (500). The Postgres code appears in the server log and **not** in the response body |
| **Risk if Missed** | Schema and privilege details leak to a client on an app with no authentication in front of it (D16) |

### EC-10: Fly socket present but connection refused

| Field | Value |
| --- | --- |
| **AC(s)** | AC-111.1, AC-111.8 |
| **Category** | Failure Modes |
| **Input / Setup** | `FLY_APP_NAME` set and the socket path exists, but connecting yields `ECONNREFUSED`; separately, the socket returns HTTP 500 |
| **Expected Result** | `CREDENTIALS_UNAVAILABLE`, with a message distinguishing "socket unreachable" from "socket returned an error shape". Never a silent fall back to the local provider chain |
| **Risk if Missed** | A silent fallback on Fly would try the ambient chain, find nothing, and produce an unrelated error — or worse, find something unintended. The branch must fail loudly (SR1) |

### EC-11: Missing role ARN fails at startup, not at first invoke

| Field | Value |
| --- | --- |
| **AC(s)** | AC-111.1 |
| **Category** | Failure Modes |
| **Input / Setup** | Fly branch active, `AGENT_RUNTIME_ROLE_ARN` unset |
| **Expected Result** | A named configuration error identifying the missing variable |
| **Risk if Missed** | The failure appears as an invoke-time auth error, which reads as an IAM trust-policy problem. Same class of misdirection as the F5 `aud` defect |

### EC-12: Absent or malformed Supabase env var fails fast

| Field | Value |
| --- | --- |
| **AC(s)** | AC-104.1 |
| **Category** | Failure Modes |
| **Input / Setup** | `SUPABASE_URL` unset; then set to `not-a-url`; then `SUPABASE_SERVICE_ROLE_KEY` empty |
| **Expected Result** | A named startup error per case. Never an `undefined` client that fails later with a null-dereference |
| **Risk if Missed** | Every query fails with an unrelated error; the real cause (one unset variable) is invisible |

### 6. Auth & Permissions

### EC-13: Server-only client cannot be imported into a client component

| Field | Value |
| --- | --- |
| **AC(s)** | AC-104.1 |
| **Category** | Auth & Permissions |
| **Input / Setup** | A fixture client component (carrying `"use client"`) that imports `@/lib/supabase/server`, run through ESLint |
| **Expected Result** | Lint error citing the SD2 rule |
| **Risk if Missed** | The rule was added in S-101 before the module existed and **has never been observed firing**. An unproven guard on the boundary that protects the service role key is the highest-leverage untested assertion in this wave |

### EC-14: `v_runs` is not granted to `anon`

| Field | Value |
| --- | --- |
| **AC(s)** | AC-104.5 |
| **Category** | Auth & Permissions |
| **Input / Setup** | Anon client selects from `v_runs` specifically |
| **Expected Result** | Zero rows or permission denied |
| **Risk if Missed** | Views do not inherit RLS from base tables the way people assume — a view owned by a privileged role can bypass base-table RLS entirely. `v_runs` is the object that exposes the most run data in one query, so it needs its own assertion rather than relying on the table-level ones |

### 7. Data Boundaries

### EC-15: Zero, negative, and sub-second durations format sanely

| Field | Value |
| --- | --- |
| **AC(s)** | AC-105.6 |
| **Category** | Data Boundaries |
| **Input / Setup** | Durations of `0`, `-1000`, `1`, `999`, `1000`, `59999`, `60000`, `3599999`, `3600000` ms |
| **Expected Result** | Defined output for each. Negative (clock skew between agent and database) must not render `-1m -0s`; exactly `60000` must be `1m 00s`, not `60s` |
| **Risk if Missed** | The 60-second boundary is the classic off-by-one here, and negative durations are reachable because `started_at` and `finished_at` are written by different clocks |

### EC-16: Zero and negative `grace_seconds`

| Field | Value |
| --- | --- |
| **AC(s)** | AC-104.3 |
| **Category** | Data Boundaries |
| **Input / Setup** | `grace_seconds = 0` and `grace_seconds = -60` on a `running` row at the threshold |
| **Expected Result** | Both sides agree. Zero grace means the threshold is `started_at + max_runtime` exactly; negative grace tightens it |
| **Risk if Missed** | A divergence here is invisible until a real run is reaped early or late, and by then the run data is gone |

### EC-17: Empty collections render empty states, not crashes

| Field | Value |
| --- | --- |
| **AC(s)** | AC-104.2, AC-105.3 |
| **Category** | Data Boundaries |
| **Input / Setup** | Zero agents; zero runs for an agent; zero `run_events`; zero artifacts; `StatusBar` with all-zero segments; `RunStrip` with 0 and with 23 runs |
| **Expected Result** | Every helper returns `[]` (never `null`). `StatusBar` with all-zero segments renders the empty rule rather than dividing by zero. `RunStrip` pads to 24 with 33%-height placeholders |
| **Risk if Missed** | A division by zero in the stacked status bar, or a `null.map()` on a fresh agent. Both crash the dashboard for the first-run case — the state a new operator sees first |

### EC-18: A run whose agent has `requires_repository = false`

| Field | Value |
| --- | --- |
| **AC(s)** | AC-104.2 |
| **Category** | Data Boundaries |
| **Input / Setup** | A `runs` row with `repository_id = null`, read through `v_runs` |
| **Expected Result** | `repository_full_name` is null and every helper handles it. No `"null/null"` string, no throw on a split |
| **Risk if Missed** | The seeded agent requires a repository, so this shape does not exist locally today and will first appear when a second agent is added — long after this code is written and forgotten |

### 8. Resource Exhaustion

### EC-19: Bounded `run_events` read is actually bounded

| Field | Value |
| --- | --- |
| **AC(s)** | AC-104.2 |
| **Category** | Resource Exhaustion |
| **Input / Setup** | A run seeded with 5,000 `run_events` rows; the bounded helper invoked |
| **Expected Result** | At most 2,000 rows returned (SD11), `seq`-ordered, taken from the most recent end |
| **Risk if Missed** | R3 says `run_events` outgrows every other table by two orders of magnitude. An unbounded read is fine on a seeded stack and pathological on a real 60-minute `llm_fix` run — the sizing note in SD11 warns the seeded `max_runtime_seconds` is 3600, four times what the schema default implies |

### 9. API Versioning

### EC-20: A future `run_status` enum value degrades gracefully

| Field | Value |
| --- | --- |
| **AC(s)** | AC-104.3, AC-105.4 |
| **Category** | API Versioning |
| **Input / Setup** | A status value outside the six known ones, passed through `effectiveStatus` and rendered by `StatusPill` |
| **Expected Result** | `effectiveStatus` passes it through unchanged; `StatusPill` renders a neutral fallback with the raw text |
| **Risk if Missed** | A migration that adds an enum value (e.g. the deferred `canceled` work) would break the panel until redeploy. Pass-through plus neutral render makes the two independently deployable |

---

## Part 3 — Flagged Gaps and Harness Risks

These require a decision before or during implementation. They are not test scenarios.

### G1 — B5 has no verified provider, so CT-8 tests a guess (High)

The Fly OIDC socket's response shape is unverified against a real Machine (SR1, OQ1). CT-8 asserts the panel accepts `value` or `token` and rejects everything else — but if the real socket returns, say, `{"jwt": "..."}`, then a fully green CT-8 ships a provider that fails on first deploy.

This is acceptable **only** because SD9's failure mode was designed for it: `FlyOidcShapeError` naming the received keys converts that failure from a misleading STS auth error into a one-line diagnosis. The test's real purpose is proving the error message is useful, not proving the shape is right.

**Recommendation:** keep CT-8 as specified and treat AC-111.2 as *contract-defined, provider-unverified* in the S-111 fidelity report. Do not let a green suite imply the Fly branch works.

### G2 — The SR3 parity test is Docker-gated and can skip to green (High)

Wave 1 established a good pattern: Layer 2.5 suites probe for the local Postgres and skip with a recorded reason when Docker is absent, so `make validate` does not fail on a developer laptop. Applied to CT-1 through CT-6, that pattern has a sharp edge — **the one test pinning SD4's duplicated SQL/TypeScript logic, and the one test proving RLS is deny-all, both become no-ops when Docker is down.** A green `make validate` would then assert nothing about either.

**Recommendation:** the skip is fine locally and **must not** be available in CI. The CI Node job should start the local stack and treat a skipped integration project as a failure for the `status-parity` and `rls-deny-all` suites specifically. Without that, SR3's stated mitigation and security-negative test 2 are both theoretically present and practically absent. This is worth a sub-task added to task 1.11/1.12.

### G3 — CT-7 is untestable without a sentinel key (Medium)

A build-artifact grep for the service role key cannot run in CI unless a key value exists there. Using the real key would be a secret-in-CI problem; using nothing makes the test vacuous.

**Recommendation:** build with a recognizable sentinel (e.g. `SUPABASE_SERVICE_ROLE_KEY=SENTINEL_MUST_NOT_APPEAR_IN_BUNDLE`) and grep for the sentinel. The test then fails loudly if the value ever reaches a client chunk, and needs no real secret.

### G4 — AC-105.2 has no mechanical check by default (Medium)

The AC says "enforced by review plus a lint/stylelint check where practical". "Where practical" is where this quietly becomes review-only, and review does not scale across twelve components plus every Wave 3 screen.

**Recommendation:** make the check mechanical now, while the surface is twelve files. A stylelint rule (or a grep-based unit test over `components/**`) rejecting `#[0-9a-f]{3,8}`, `font-family:` literals, and bare `px` in spacing properties is cheap at this size and expensive to retrofit at Wave 3 scale. Task 2.10 should produce a rule, not a judgment.

### G5 — AC-111.6's "logged on every invoke" is only assertable once the invoke path exists (Low)

`credentialSource()` logging on every invoke is verifiable in S-111 only for `lib/aws/invoke.ts` in isolation; the route-level guarantee lands with S-112.

**Recommendation:** assert it at the `invoke.ts` boundary in S-111 and carry the route-level assertion into S-112's plan, so it is not assumed complete here.

### G6 — No Layer 2 coverage of `StatusPill` against real derived data (Low)

CT-1 proves `effectiveStatus` is correct; AC-105.4 proves `StatusPill` renders six statuses. Nothing in Wave 2 proves the derived value is what reaches the pill, because the composition happens in Wave 3.

**Recommendation:** accept for Wave 2, and record it as a required scenario in the S-107/S-108 plans rather than discovering it during Wave 3.

---

## Part 4 — Coverage Matrix

| AC | Layer | Scenarios | Command |
| --- | --- | --- | --- |
| AC-104.1 | 1, 2 | EC-12, EC-13 | `test:unit` + `lint` |
| AC-104.2 | 2.5 | CT-5, EC-9, EC-17, EC-18, EC-19, EC-5 | `test:integration` |
| AC-104.3 | 1 | CT-1, CT-3, CT-4, EC-4, EC-8, EC-16, EC-20 | `test:unit` |
| AC-104.4 | 2.5 | CT-1, CT-2, CT-3 | `test:integration` |
| AC-104.5 | 2.5 | CT-6, EC-14 | `test:integration` |
| AC-104.6 | 1 (build) | CT-7 | `test:unit` post-build |
| AC-104.7 | 2 | route config assertion | `test` |
| AC-105.1 | 1 | CT-10 | `test:unit` |
| AC-105.2 | lint | G4 rule | `lint` |
| AC-105.3 | 2 | EC-1, EC-2, EC-3, EC-17 | `test` |
| AC-105.4 | 2 | CT-12, EC-20 | `test` |
| AC-105.5 | 2 | accessible-text + focus assertions | `test` |
| AC-105.6 | 1 | CT-11, EC-15 | `test:unit` |
| AC-105.7 | 1 | import audit | `test:unit` |
| AC-111.1 | 1 | EC-10, EC-11 | `test:unit` |
| AC-111.2 | 1 | CT-8 (**provider unverified — G1**) | `test:unit` |
| AC-111.3 | 1 | CT-8 | `test:unit` |
| AC-111.4 | 1 | branch-detection cases | `test:unit` |
| AC-111.5 | 1 | CT-9, EC-6, EC-7 | `test:unit` |
| AC-111.6 | 1 | log-capture assertion (**partial — G5**) | `test:unit` |
| AC-111.7 | review | file review | — |
| AC-111.8 | 1 | CT-9 (route-level in S-112) | `test:unit` |

**Totals:** 12 contract scenarios, 20 edge cases, 22 acceptance criteria. Every AC has at least one mapped scenario. Three ACs are partially deferred by design and flagged: AC-111.2 (G1), AC-111.6 (G5), AC-111.8 (route level, S-112).

**Highest-value scenarios if effort must be cut:** CT-2 (exact-boundary parity), CT-6 (anon deny-all), EC-13 (the SD2 lint guard firing), and EC-2 (log XSS). The first three are the stated mitigations for SR3, F2, and SD2; the fourth is the only untrusted-input path in the wave.
