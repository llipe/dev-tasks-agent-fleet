## Story S-113 (#126): Schema-driven invoke form

Closes #126

Wave 4, task 2.0. Renders the invoke dialog entirely from `agents.params_schema` — proving FR16/AC7: a new agent is one database row, not a deploy. Builds on the S-112 route (already merged to the integration branch).

### What this delivers

- `lib/schema/form.ts` — `buildFieldDescriptors` maps `params_schema` to field descriptors (enum→select, boolean→toggle, bounded integer/number→number, string→text; everything else→a disabled "unsupported" note). SD8: no generic JSON-Schema form library.
- `components/invoke/{InvokeDialog,FieldRow,RepositorySelect,SchemaPreview,SuccessState}.tsx` — the DESIGN §5.4 centered dialog (max-width 760, `--shadow-lg`, two-column `minmax(0,1fr) 292px` grid) built on the S-105 primitives (`Toggle`/`Input`/`Button`/`KLabel`), token-only CSS Modules.
- `app/agents/[slug]/invoke/page.tsx` — thin async server component; 404s on unknown/disabled agent; inline route-segment config.
- Client Ajv re-validation via the shared `lib/schema/ajv.ts` — same strictness as the S-112 route; the server stays authoritative.

### AC → test evidence

| AC | Evidence |
| -- | -------- |
| AC19 (§5.4 dialog) | `invoke-form.test.tsx` — slug/name, Cancel/Run |
| AC20/AC11 (four controls from schema) | `invoke-form.test.tsx` — select/toggle/number(min,max)/text |
| AC21 (repo selector separate) | hidden-when-`requires_repository=false` test |
| AC22/AC4 (unsupported → disabled + note) | `invoke-form-synthetic.test.tsx` — array + nested object |
| AC23 (client Ajv blocks; server authoritative) | client-Ajv out-of-range test + S-112 server test |
| AC24 (202 & 502 both navigate) | navigation tests |
| AC25 (labels/help/defaults from schema) | `form.test.ts` + dialog initial values |
| AC26/AC7 (synthetic agent, zero code change) | `invoke-form-synthetic.test.tsx` + Layer 2.5 `synthetic-agent-form.test.ts` **RAN LIVE** |
| AC27 (inline vs banner errors) | INVALID_PARAMS inline + CREDENTIALS_UNAVAILABLE banner tests |
| AC28 (schema preview) | preview toggle test |

### Layer 2.5 (#134 discipline)

`tests/integration/synthetic-agent-form.test.ts` **RAN LIVE** against the local Supabase stack — inserts a synthetic agent row with a *different* schema, reads it back through `getAgentBySlug`, and asserts `buildFieldDescriptors` maps its four properties to the right controls. This proves AC7 end-to-end through the database.

### `ajv` bump

`ajv` bumped **8.17.1 → 8.20.0** (satisfies the #126 `>=8.18.0` note — this is where `ajv` first does real work). **Audit delta:** the previously-residual moderate `ajv` advisory is now resolved — `pnpm audit` exit code went 1 → 0. The `--audit-level=high` gate remains green.

### DESIGN §5.4 conformance notes

- Reproduced: centered dialog, max-width 760, `--shadow-lg`, header (KLabel + name + slug + close), two-column field grid, toggle/select/number/text controls, schema preview toggle, footer with API hint + Cancel + Run, `rise` success state.
- **Minor drift D1 (jsonb key order):** Postgres `jsonb` does not preserve object key order, so the form field order follows Postgres's internal jsonb ordering, not the schema's authoring order. The §5.4 prototype implies authoring order. No AC mandates order, so this is non-blocking — recorded for a DESIGN note / a future explicit field-order key (routed to `product-engineer`). The integration test asserts the field→control **set**, not the sequence, for this reason.
- **Deferred D2:** the 1024px/1440px pixel-geometry comparison (task 2.18) needs a running dev server; deferred to the S-114 Playwright suite, consistent with the wave's geometry-deferral pattern.

### Coverage

`form.ts` 100% stmts; `FieldRow.tsx` 100%; `SuccessState.tsx` 100%; `InvokeDialog.tsx` 92% stmts. `coverage_gate: PASS`.

### Migration lifecycle

**Not applicable** — presentational + submit story, no schema or data-model change. Opt-out rationale recorded (plan task 2.32).

### Gates

`make validate` green on **both** branches (panel 621 passed / 9 Docker-gated skips; Python all gates passed).

### Deferred (recorded)

`/runs/[id]` (S-109) and SSE live tail (S-110) are their own wave — the form navigates to `/runs/[id]`, which may not fully render until S-109 lands. Sequence the merges accordingly.
