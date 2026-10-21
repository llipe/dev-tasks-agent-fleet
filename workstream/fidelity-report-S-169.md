# Fidelity Report — S-169 (#314) inbound webhook route (verifier, Audit Mode)

**Verdict: High fidelity.** All 6 acceptance criteria met. Highest drift impact: **Minor**.

## AC → evidence

| AC | Evidence | Result |
| --- | --- | --- |
| Route is public: `/api/webhooks/**` classed like `/api/internal/**`; Node runtime, `force-dynamic`, no cache | `auth-route-policy.test.ts` (3 positive cases; `/api/webhooksx`, `/api/webhook` and `/webhooks` stay gated); route-segment config; `next build` lists `ƒ /api/webhooks/[token]` | Pass |
| Raw body read with a size cap → 413; unknown or disabled token → 404 with no row | `webhook-read-body.test.ts` (exact cap, cap+1, large `Content-Length`, missing or understated `Content-Length`); L2.5 413 / disabled / unknown-token cases leave 0 rows | Pass |
| Invalid or missing signature → `unauthorized` row, 401 | L2.5: unsigned and wrong-secret both 401, rows `unauthorized` with `dedup_key` null; missing Vault secret → 401 `secret_not_configured` (EC-21) | Pass |
| Duplicate key → `duplicate`, 200 no-op | L2.5 replay → 200, one claim; body-hash dedup when the header is absent (EC-18); 5 concurrent posts → exactly one claim (EC-14) | Pass |
| Valid delivery recorded `received`; non-allowlisted event → 202 `ignored` | L2.5 `received` row; `issues` event → `ignored` / `event_not_allowed` | Pass |
| Structured, secret-free log line (`at: "webhook_delivery"`) | L1: one line per delivery; responses and logs never contain the secret, signature or payload content | Pass |

Also covered: D-W16 end to end (a forged request reusing a real delivery id is recorded and the genuine one still goes through, EC-20); CT-3 (invalid JSON, empty body, top-level array or string → `ignored:invalid_json`); EC-8 token format; EC-23 (a DB failure propagates to 500 so GitHub retries).

## Drift

| # | Finding | Type | Impact |
| --- | --- | --- | --- |
| 1 | Body read as bytes through a byte-limited stream (`lib/webhooks/read-body.ts`), per the D-W3 correction from S-168. | Intended (already written back) | Minor |
| 2 | A `duplicate` delivery is recorded as its own unclaimed row. The spec says "record/return duplicate"; with a unique `dedup_key`, recording it means a second, unclaimed row. That's consistent with D-W16 (every attempt recorded). | Intended | Minor |
| 3 | The event-type header is fixed to `x-github-event` for both source types. The spec makes the signature and delivery-id header names configurable but doesn't name an event header for generic senders. Generic senders must send `x-github-event` in v1. Routed to product-engineer; a configurable `event_header` column would be a later addition. | Gap | Minor |
| 4 | GitHub's `ping` event, sent when a webhook is first registered, is not allowlisted, so it gets 202 `ignored`. That's still the 2xx GitHub expects. | Intended | — |

## Gates

- L1: `webhook-receive.test.ts` 26/26, `webhook-read-body.test.ts` 7/7, `auth-route-policy.test.ts` 27/27 (3 red before the policy change). The receive-core RED run raced with the file write and isn't valid evidence, so mutation checks stand in for it: skipping verification fails 5 tests, claiming a key on unauthorized fails 3, accepting a disabled endpoint fails 1, dropping the token check fails 4.
- L2.5: `webhook-route.test.ts` 11/11. A plain-insert claim mutant fails 3 of them.
- `make validate-js`: pass (1713 tests). `next build`: pass.
- `make validate-py`: audit fails on #355 (pre-existing).
