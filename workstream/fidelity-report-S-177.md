# Fidelity Report — S-177 (#322) rule editor (verifier, Audit Mode)

**Verdict: High fidelity.** All 3 acceptance criteria met. Highest drift impact: **Minor**.

## AC → evidence

| AC | Evidence | Result |
| --- | --- | --- |
| Add, reorder, edit and delete rules; event-type select; structured condition rows; agent select; repo mode (fixed or payload field); schema-driven params form (reused); default-rule toggle | **L2 `rule-editor` (17 tests):** add, edit (prefilled), delete after confirm, enable/disable; condition rows (`in` value split into a list, `exists` sends no value, remove); switching agent rebinds the `FieldRow` grid; fixed repository; the default toggle hides the When group; Escape closes. **L2.5 `webhook-rules-admin` (8 tests):** every editable field persists; re-enabling resets the G3 counter; one default per endpoint is enforced in the DB | Pass |
| A rule whose resolution can't validate is flagged before save | **L1 `webhook-rule-save` (43 tests):** the S-170 condition validator (unknown op or key, missing value, bad or forbidden path); events non-empty and inside the endpoint allowlist; agent exists and is enabled; repository usable, or payload path parses; params checked against the agent schema; `from_payload` keys declared, scalar, with a parseable path and a chosen parameter; a required key may come from the payload; one default; threshold 1–100. The server action checks against live agents, repositories and rules; nothing is written on failure. **Browser:** an invalid rule is flagged inline and not stored | Pass |
| Reordering persists `position`; first-match order is visible | L2.5: append at max+1 under the endpoint row lock; reorder renumbers in one UPDATE (the deferrable unique is checked at end of statement); a partial, duplicate or foreign id list is rejected and nothing changes. **Browser:** "Move up" → DB shows `second:0, first:1`. L2: numbered list, the first-match note, the default rule in its own section, edge buttons disabled | Pass |

## Drift

| # | Finding | Type | Impact |
| --- | --- | --- | --- |
| 1 | **A bug the browser check caught:** the dialog silently dropped a "fill from payload" row with no parameter chosen, so a broken entry saved as if it were fine. The dialog now sends every row, and the validator flags it per row ("Payload value 1: choose a parameter"). L1 and L2 regression tests added. | Unintended (fixed) | Minor |
| 2 | Two new service-role-only RPCs: `webhook_create_rule` (append under lock) and `webhook_reorder_rules`. `definer-grants` stays green. | Intended (design) | Minor |
| 3 | Parameters the form can't render, such as array-typed `scanners`, stay unsupported in the rule dialog, the same as invoke and schedules; the agent default applies. | Inherited | Minor |
| 4 | `matches_event` is left out of the operator list because event checkboxes cover it; an existing rule that uses it still displays and edits. | Intended | Minor |
| 5 | `webhookUrl` moved from a component into `lib/webhooks/request-origin.ts`, so the server page doesn't import a client module. | Intended (refactor) | — |

## Gates

L1 43 · L2 30 (rule-editor + webhooks-list) · L2.5 8 + definer-grants. Mutants killed: reorder without the id-set guard, no allowlist check, no repository usability check, ignoring every `required` error. `make validate-js` (2061) · `make validate-py` · `next build` (`/webhooks/[id]`) pass. A throwaway Playwright check against the production build is not committed.
