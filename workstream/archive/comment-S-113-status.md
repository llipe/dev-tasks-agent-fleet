### Wave 4 planner checkpoint — S-113 merged to integration

Story **S-113** (#126) is complete and merged into `integration/wave4-invoke` (squash, PR #142). Both Wave 4 stories are now on the integration branch.

| Sequence | Story | Issue | Status | PR |
| -------- | ----- | ----- | ------ | -- |
| 1 | S-112 Invoke route + payload translation | #125 | ✅ Merged to integration | #141 |
| 2 | S-113 Schema-driven invoke form | #126 | ✅ Merged to integration | #142 |

**S-113 evidence:**
- AC7 proven: a synthetic second agent row with a different schema renders correct controls with zero code change — asserted in a component test **and** a Layer 2.5 test that **RAN LIVE** against the local stack.
- Client Ajv shares strictness with the S-112 route; the server stays authoritative.
- `ajv` bumped 8.17.1 → 8.20.0; the previously-residual moderate advisory is now resolved (`pnpm audit` exit 1 → 0).
- Coverage: `form.ts` 100%, `FieldRow`/`SuccessState` 100%, `InvokeDialog` 92% stmts.
- `make validate` green on both branches.

**Recorded finding (non-blocking):** Postgres `jsonb` does not preserve `params_schema` key order, so form field order follows jsonb's internal order rather than authoring order. No AC mandates order; routed to `product-engineer` for a DESIGN §5.4 note.

Next: consolidated PR to `main` and Wave 4 exit-criteria evaluation.
