# Fidelity Report — S-171 (#316) route resolution (verifier, Audit Mode)

**Verdict: High fidelity.** All 5 acceptance criteria met. Highest drift impact: **Minor**.

## AC → evidence

| AC | Evidence | Result |
| --- | --- | --- |
| Agent resolved and must be enabled | L1 missing/disabled → `agent_unavailable` (EC-13); mutant that allows a disabled agent fails 1 test | Pass |
| Repo: `fixed` → id; `payload_field` → path + `getRepositoryByFullName`; miss → `route_rejected` 202, never auto-create | L1 fixed / payload / no repo needed; unknown, disabled or archived repo rejected; malformed names (URL, `.git/x`, no slash, too long) rejected **without a lookup**. L2.5 against the real allowlist, case-insensitive (EC-7); `repositories` row count unchanged (I-4) | Pass |
| Params: static plus declared payload keys, then `validateParams`; invalid → `route_rejected` | L1 and L2.5: schema failure, missing required key, wrong payload type; payload overrides static; missing path leaves the key unset | Pass |
| Interpolation into an undeclared key is dropped, not injected | L1: dropped and reported in `droppedKeys`, absent from the result. L2.5: the delivery `reason` records it. Objects and arrays are never interpolated, tested against an untyped schema key | Pass |
| The handler runs allowlist + bot guard + rules + resolution end to end | `lib/webhooks/dispatch.ts`, wired into the route. L2.5: first match, default fallthrough, `no_match`, the bot account ignored through the real `webhook.bot_login()` | Pass |

## Drift

| # | Finding | Type | Impact |
| --- | --- | --- | --- |
| 1 | New migration `20261020130000_webhook_bot_login_rpc.sql`. S-166 only exposed `webhook.bot_login()` inside the `webhook` schema, which PostgREST can't reach. `public.webhook_bot_login()` is service-role only; `definer-grants.test.ts` enumerates it automatically and stays green. | Gap filled | Minor |
| 2 | A resolved route records `received` with reason `resolved` plus the matched rule, and the route answers `202 {received, resolved}`. Invocation is S-172, which replaces `onResolved`. | Intended (staged) | Minor |
| 3 | `getRepositoryByFullName` returns null when more than one enabled repository matches. `full_name` is unique per installation, not globally, so an ambiguous match is rejected rather than guessed. | Intended | Minor |
| 4 | Undeclared **static** keys follow the existing invoke path: with `additionalProperties: false` the whole params set is rejected; otherwise the keys are projected away. Only `from_payload` keys are reported as dropped. | Intended (consistent with manual invoke) | — |
| 5 | The S-169 L2.5 expectations changed: an endpoint with no rules now ends at `no_match` instead of `received`. | Expected behavior change | — |

## Gates

- L1: `webhook-resolve.test.ts` 32/32 (red before the module existed); 5/5 mutants caught after one test was strengthened (scalar-only guard). `webhook-dispatch.test.ts` 9/9; 3/3 mutants caught.
- L2.5: `webhook-resolve.test.ts` 9/9; `webhook-route.test.ts` 11/11; `definer-grants.test.ts` 6/6.
- `make validate-js`: pass (1850 tests). `next build`: pass.
