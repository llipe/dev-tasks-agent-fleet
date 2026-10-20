# Fidelity Report — S-178 (#323) delivery log (verifier, Audit Mode)

**Verdict: High fidelity.** All 3 acceptance criteria are met. Highest drift impact: **Minor**.

## AC → evidence

| AC | Evidence | Result |
| --- | --- | --- |
| Per-endpoint, newest-first feed showing timestamp, event type, delivery id, verification result, matched rule or no-match, and outcome (fired links to the run; skipped, rejected and ignored show their reason) | **L1 `delivery-view` (35 tests):** every outcome has a label and colour token; `fired` links to `/runs/<id>` and nothing else does; 17 reason codes are translated, including the S-168 signature verdicts; deleted or unnamed rules are labelled. **L2 `delivery-log` (6 tests):** all 8 outcomes render; exactly one link. **Browser, real POSTs:** signed → no match, replay → duplicate, unsigned → unauthorized ("signature failed"), event outside the allowlist → ignored | Pass |
| Untrusted payload-derived fields render as text only | **L2 security-negative:** `<img onerror>`, `<script>` and a `javascript:` link in event, delivery id and reason all render as text, with no `img`/`script`/`a` element and no links. **Browser:** a real `<img src=x onerror=…>` event header renders as text, with 0 `img` elements and 0 dialogs | Pass |
| Pagination or a bounded recent window (ties to retention) | **L2.5 `webhook-delivery-feed` (4 tests):** one endpoint only, newest first, keyset on `(created_at, id)` with no overlap or gap across a 3-way timestamp tie, log columns only. The `?before=` cursor is strictly validated (L1: garbage and filter-injection attempts → null → first page). The configured retention is shown, read through a new service-role-only RPC. **Browser:** 59 rows split over 2 pages with none lost; a garbage cursor → first page | Pass |

## Drift

| # | Finding | Type | Impact |
| --- | --- | --- | --- |
| 1 | **Found by the browser check:** `unauthorized` rows showed the raw verifier code (`header_missing`). The S-168 signature reasons now map to plain language, with L1 tests that failed before the fix. | Unintended (fixed) | Minor |
| 2 | New RPC `public.webhook_delivery_retention_days()`, service-role only, so the note shows the real (tunable) retention rather than a hard-coded 30. | Intended | Minor |
| 3 | A replayed delivery is its own `duplicate` row (D-W16), so the page count includes replays. The throwaway check's expectation was corrected to match. | Intended (as designed) | — |

## Gates

- L1 35 · L2 6 · L2.5 4 + definer-grants.
- `make validate-js`: 2110 passing on rerun. The first run hit only the #387 SSE flake after a reset.
- `make validate-py` and `next build` pass.
- A throwaway Playwright check against a production build was run and not committed.
