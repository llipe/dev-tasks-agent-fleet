# Fidelity Report — S-176 (#321) /webhooks list + endpoint CRUD + show-once secret (verifier, Audit Mode)

**Verdict: High fidelity.** All 4 acceptance criteria are met. Highest drift impact: **Minor**.

## AC → evidence

| AC | Evidence | Result |
| --- | --- | --- |
| `/webhooks` list shows source, enabled pill, event allowlist, rule count, copyable URL | L2 `webhooks-list.test.tsx`: columns, the `+N` event overflow, `N rules`, a labelled Copy button writing the full URL with a "Copied" confirmation, and the empty state. The browser check showed the same on a production build | Pass |
| Create, edit and delete through Server Actions (service-role, server-only); event allowlist multi-select; `ignore_bot_author` toggle | L1 `webhook-endpoint-save` 29/29: validation, GitHub headers pinned, a generic sender's headers validated, at least 1 and at most 50 events, strict booleans, uuid ids. L2: create, edit with the source fixed, toggle, and delete only after a confirm that names the rule count and what is kept. L2.5 `webhook-endpoint-admin` 7/7: create persists, edit never touches token or secret, delete removes the Vault secret and cascades rules and deliveries | Pass |
| Generate and rotate the secret: shown once, stored in Vault, never re-displayed | Create writes the endpoint and its secret in **one transaction** (L2.5: a failed insert leaves no Vault entry). Rotate replaces the secret. The list query and every RPC result exclude it (L2.5). L2: after dismissal the secret is absent from the DOM; a failed rotate shows no secret. **Browser:** the shown secret equals the Vault value, and after dismiss and reload it is absent from the page HTML | Pass |
| New sidebar item after Schedules | L2 Sidebar: link to `/webhooks`, index = Schedules + 1, active on `/webhooks` and `/webhooks/<id>`, not on `/webhooksx` | Pass |

Logged out, `/webhooks` → `/login` (browser check; the route is `ui` in `route-policy`).

## Drift

| # | Finding | Type | Impact |
| --- | --- | --- | --- |
| 1 | **Three new service-role-only RPCs** (`webhook_create_endpoint`, `webhook_rotate_endpoint_secret`, `webhook_delete_endpoint`), needed because PostgREST can't reach the `webhook` schema. `definer-grants` and the L2.5 test both enforce the grants. | Intended (design) | Minor |
| 2 | The payload URL origin comes from the request host (display only; malformed hosts render a relative URL). L1 9/9 tests, 3 mutants caught. | Intended | Minor |
| 3 | First-pass layout without a `ux-engineer` prototype, like §5.6. Uses DESIGN.md tokens only, no new ones. Two layout issues found in the browser and fixed: undefined `--space-5` padding, and overlapping event labels. | Intended | Minor |
| 4 | Endpoint detail page (`/webhooks/<id>`) is deferred to S-177 (rules) and S-178 (delivery log); the sidebar already treats it as active. | Intended | Minor |

## Gates

- L1 38/38 · L2 32/32 (webhooks, Sidebar, AppShell) · L2.5 13/13 (admin + definer-grants) · token-discipline green.
- `make validate-js` (1,986 tests) · `make validate-py` · `next build` (`/webhooks` route present) pass.
- Production browser check via a throwaway Playwright spec (not committed; S-179 owns the E2E): create → show-once → dismiss → reload, and logged out → `/login`.
