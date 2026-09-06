## Story S-113 (#126): Schema-driven invoke form

Closes #126

Wave 4, task 2.0. Renders the invoke dialog entirely from `agents.params_schema` — proving FR16/AC7: a new agent is one database row, not a deploy.

### What this delivers

- `lib/schema/form.ts` — `buildFieldDescriptors` maps `params_schema` to field descriptors (enum→select, boolean→toggle, bounded integer/number→number, string→text; everything else→a disabled "unsupported" note). SD8: no generic JSON-Schema form library.
- `components/invoke/{InvokeDialog,FieldRow,RepositorySelect,SchemaPreview,SuccessState}.tsx` — the §5.4 centered dialog built on the S-105 primitives.
- `app/agents/[slug]/invoke/page.tsx` — the dialog route (inline route-segment config).
- Client-side Ajv re-validation via the shared `lib/schema/ajv.ts` — same strictness as the S-112 route; the server stays authoritative.

### Guarantees

- **AC7 (the story-proving criterion):** a second synthetic agent row with a different schema renders a correct form with **zero code change**.
- **AC4:** an unsupported schema type renders a disabled field with a visible note — parameters never vanish silently.
- **AC13:** client Ajv blocks invalid submission; the server re-validates and a rejected submission leaves no `runs` row.
- Repository selector renders separately (outside `params`), only when `requires_repository = true`.
- Submission navigates to `/runs/[id]` on `202`; a `502` also navigates (run shows `failed_to_start`).
- Errors: inline per-field for `INVALID_PARAMS`, banner for the others.

### `ajv` bump

`ajv` bumped to `>=8.18.0` (this is where `ajv` first does real work); audit delta recorded below.

### Migration lifecycle

**Not applicable** — presentational + submit story, no schema or data-model change. Opt-out rationale recorded (plan task 2.32).

### Testing

Evidence and AC mapping added as the story completes; Layer 2.5 status (ran-live vs skipped) stated per #134.

### Deferred (recorded)

`/runs/[id]` (S-109) and SSE live tail (S-110) are their own wave — the form navigates to `/runs/[id]`, which may not fully render until S-109 lands.
