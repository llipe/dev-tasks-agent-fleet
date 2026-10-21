# Fidelity Report — S-175 (#320) release-gate CHECK 6: unsigned webhook → 401 (verifier, Audit Mode)

**Verdict: High fidelity.** Both acceptance criteria are met. The highest drift impact is **Minor**.

## AC → evidence

| AC | Evidence | Result |
| --- | --- | --- |
| `verify-panel-auth.sh` has a CHECK that an unsigned `POST /api/webhooks/<probe-token>` returns 401, and the release fails non-zero otherwise | **End to end against a local production build**, with real enabled and disabled endpoints:<br>• enabled token → check 6 passes, and one `unauthorized` delivery is recorded<br>• unset token → fail, with a reason naming `WEBHOOK_PROBE_TOKEN`<br>• disabled token → fail with 404 ("signature check never ran")<br>• malformed token → fail<br>The token appears 0 times in the output in all four cases. `shellcheck` is clean | Pass |
| Parser and tests extended | `checkWebhookRejected`: passes only on 401; fails on 200/202/404/400/413/5xx, unset, error, missing or garbage input; never echoes a token. `evaluateAuthGate` now runs 6 checks. The CLI exits 1 on 202 and on unset. 62/62 L1 tests pass; 12 failed before the change | Pass |

## Drift

| # | Finding | Type | Impact |
| --- | --- | --- | --- |
| 1 | **Shared parser change:** `statusOf` now rejects malformed strings such as `"401x"`, which used to parse as 401 because `parseInt` is lenient. This tightens checks 2, 3 and 5 as well. The wrapper always passes a numeric status, so real runs are unaffected. | Intended (hardening) | Minor |
| 2 | **Deploy ordering:** once this reaches `main`, every panel deploy needs `WEBHOOK_PROBE_TOKEN`, and the probe endpoint must exist on live **before** the first such deploy (webhook runbook step 5). Task 16.0 has to follow that order. | Intended | Minor |
| 3 | **Gate leaves a DB row:** each gate run records one `unauthorized` delivery on the probe endpoint, which the 30-day prune removes. Documented in the runbook. | Intended | Minor |

## Gates

L1 62/62 · shellcheck clean · local end-to-end run with 4 cases · `make validate-js` passes (1915 tests) · `make validate-py` passes. No migration, so no reset or build-dependent change.
