# Fidelity Report — S-179 (#324) webhooks E2E (verifier, Audit Mode)

**Verdict: High fidelity.** All 5 acceptance criteria are met. Highest drift impact: **Minor**.

## AC → evidence

| AC | Evidence | Result |
| --- | --- | --- |
| The operator creates an endpoint and a rule; a signed POST produces a run, visible and linked in the delivery log and in run history with `trigger_type=webhook` | `webhooks-crud.spec.ts` creates the endpoint and rules through the UI, capturing the secret once and checking it against Vault. `webhooks-delivery.spec.ts` AC1: signed → 202 `queued`, one run with `trigger_type=webhook`, `webhook:<ep>:<rule>`, and the payload repository. The log shows `fired` and the delivery id; **Open run ▸** opens `/runs/<id>`, and the row appears in Run history | Pass |
| Unsigned POST → 401, recorded `unauthorized`, no run | AC2: both unsigned and wrong-signature requests → 401, recorded `unauthorized`, 0 runs. AC9: no secret or `sha256=<hex>` in any stored delivery column | Pass |
| Replayed delivery id → no second run | AC2: replay → `200 {duplicate: true}`, still 1 run | Pass |
| Unauthenticated `/webhooks` → `/login` | Both `/webhooks` and `/webhooks/<id>` redirect to `/login` with no session | Pass |
| Scenario → spec traceability (AC1–AC9) recorded | A traceability table is in each spec header | Pass |

Beyond the story: AC3 (non-allowlisted event → ignored; >5 MiB → 413), AC4 (rule #2 fires on `pull_request_review_comment` "security review" with the payload's repo; a miss → `no_match`), AC5 (an unregistered repo → `route_rejected:repository_not_allowed`), AC6 (G1: the second delivery is `skipped:overlap`), AC7 (a bot-authored event → `ignored:bot_author`, no run), and the UI rejecting a broken rule before it is stored.

**Not vacuous:** with the guardrail check removed from `fire.ts`, the AC6 scenario fails. The full Playwright suite (51 tests) is green with the new specs.

## Drift

| # | Finding | Type | Impact |
| --- | --- | --- | --- |
| 1 | AC6's `run_failed` notification half and AC8's release-gate half are not repeated in E2E. They are covered by L2.5 `notify-sweep` (S-174) and by S-175's end-to-end gate run. Noted in the spec header. | Intended | Minor |
| 2 | AC4 uses `equals` on the comment body. The routing language has no case-insensitive operator (D-W7), so "Security Review" would not match. | Inherited (D-W7) | Minor |

## Gates

- Playwright: webhook specs 11/11; full suite 51/51.
- `make validate-js` (2110 tests) and `make validate-py` pass.
- No app code changed in this story.
