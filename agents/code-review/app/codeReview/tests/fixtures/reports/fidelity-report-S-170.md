# Fidelity Report — S-170 (#315) webhook routing engine (verifier, Audit Mode)

**Verdict: High fidelity.** All 4 acceptance criteria met. Highest drift impact: **Minor**.

## AC → evidence

| AC | Evidence | Result |
| --- | --- | --- |
| `selectField`: dotted keys + `[n]`, max depth, undefined on a miss, never throws | `webhook-routing.test.ts`: 8 resolve cases; misses (EC-5, out-of-range index); 9 malformed paths; forbidden keys, including own keys created by `JSON.parse`; depth boundary at exactly `MAX_PATH_DEPTH` (EC-30) | Pass |
| `evaluateCondition` with the fixed op set, length caps, no regex or code | 17 op cases incl. no coercion (EC-6); `matches_event` uses the header; over-cap string; unknown op / wrong-typed value → false | Pass |
| `routeDelivery`: bot guard first, then first match by `position`, then default or `no_match` | Ordering, disabled rule skipped (EC-9), event scoping, AND semantics, default fallthrough, a disabled default ignored; bot guard needs `login == bot_login` **and** `type == "Bot"` (EC-28), toggle off, explicit condition, no bot login set (AC7) | Pass |
| Pure, exhaustively unit-testable | No I/O; RT-2 (5000 hostile random trees, seed 315001: never throws, `Object.prototype` untouched); RT-3 (3000 iterations vs a brute-force reference, seed 315002); EC-33/34 time bound < 50 ms | Pass |

Task 6.5: `validateConditions`, an Ajv schema for the stored `conditions` list. It rejects unknown keys (B-2), wrong value types per op, over-cap values (EC-31), more than 50 conditions, and invalid or forbidden paths (CT-4).

## Drift

| # | Finding | Type | Impact |
| --- | --- | --- | --- |
| 1 | Mutation testing found a gap in the first draft: a payload parsed with `JSON.parse` has `__proto__` as an **own** key, so the own-property check alone doesn't block it. The forbidden-key list is what does. I added 5 tests built from `JSON.parse` input; that mutant now fails 5 of them. | Test gap closed | Minor |
| 2 | A default rule is chosen only after every non-default rule has been checked, whatever its `position`. The spec says "first-match-wins, optional catch-all default", and a catch-all placed first would otherwise shadow everything. | Intended (interpretation) | Minor |
| 3 | B-2 (reject unknown condition keys at save) is implemented as the test plan assumed. | Confirms a boundary assumption | — |

## Gates

- L1: 85/85. Red before the module existed. Mutants caught: inherited-property read (1 failing), forbidden-key list removed (5), bot type check removed (1), coercion (6), position sort removed (2), default treated as ordinary (1).
- The shared `tests/helpers/prng.ts` replaces the inline copy in `webhook-signature.test.ts` (test plan §6).
- `make validate-js`: pass (1800 tests).
