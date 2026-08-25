# Fidelity Report — S-002: `packages/shared` contract with Python code generation

## Header / Verdict

| Field             | Value                                                               |
| ----------------- | ------------------------------------------------------------------- |
| **Fidelity**      | **High**                                                            |
| **Highest Drift** | Minor                                                               |
| **Scope**         | Story S-002, Issue #2, PR #33, branch `story/S-002-shared-contract` |

---

## Human-Readable Summary

The shared contract library delivers all requested functionality: key builders, Zod schemas, params validation, LLIPE constants, SPAN_FIELDS mapping, status derivation, session-ID generation, subject-ID normalization, and Python code generation. All 59 unit tests pass. The codegen script produces JSON Schema and a Python dataclass module with zero drift from committed output. The package has no dependency on `apps/` or `agents/`, and the import-boundary check passes.

Two minor specification-level deviations were identified:

1. The spec defines `dep-updater` params (`allow_fixes`, `max_fix_attempts`) as **optional** fields. The implementation makes them **required**. This means a partial params object (e.g., `{ allow_fixes: true }` without `max_fix_attempts`) would be rejected, whereas the spec allows it.

2. The spec's `deriveStatus` uses strict greater-than (`elapsed > threshold`) to transition to `incomplete`. The implementation uses greater-than-or-equal (`elapsed >= threshold`), meaning a run is marked `incomplete` exactly at the boundary rather than 1ms after. The tests are consistent with the implementation's choice.

Neither drift item blocks functionality or downstream consumers, and both represent defensible implementation choices (stricter validation, conservative timeout).

---

## Per-AC Result Table

| AC-ID | Description                                                                                          | Codebase Evidence                                                                                             | Workstream Evidence  | Test Evidence                                                                                                                                                | Result                                              |
| ----- | ---------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------- | -------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------ | --------------------------------------------------- |
| 2.11  | Key builders round-trip tests pass                                                                   | `src/keys.ts`: `subjectPk`, `agentSk`, `META`, `CONFIG`, `PREFIXES` exported                                  | Task 2.1 marked [x]  | `keys.test.ts`: 10 tests including round-trip extraction — all pass                                                                                          | **Pass**                                            |
| 2.12  | deriveStatus boundary ±1ms, absent maxLifetime fallback, unparseable lastRunAt                       | `src/status.ts`: `deriveStatus` with `DEFAULT_MAX_LIFETIME_MS=28_800_000`, `TERMINATION_GRACE_MS=300_000`     | Task 2.6 marked [x]  | `status.test.ts`: 13 tests covering ±1ms boundary, undefined/null fallback, unparseable dates — all pass                                                     | **Pass** (minor boundary operator drift, see below) |
| 2.13  | buildSessionId length floor, determinism, charset                                                    | `src/session-id.ts`: MIN_LENGTH=33, sha256-based deterministic padding                                        | Task 2.7 marked [x]  | `session-id.test.ts`: 9 tests — shortest inputs ≥33 chars, determinism verified, charset `[A-Za-z0-9-]+` — all pass                                          | **Pass**                                            |
| 2.14  | normalizeSubjectId all forms including SSH remote edge case                                          | `src/normalize-subject-id.ts`: handles bare, HTTPS, SSH, .git, trailing slash                                 | Task 2.8 marked [x]  | `normalize-subject-id.test.ts`: 12 tests — bare, HTTPS variants, SSH with/without .git, case, whitespace — all pass                                          | **Pass**                                            |
| 2.15  | PARAMS_SCHEMAS rejects unknown keys and wrong types                                                  | `src/params-schemas.ts`: `.strict()` on dep-updater schema, empty strict for unknown                          | Task 2.3 marked [x]  | `params-schemas.test.ts`: 14 tests — unknown keys rejected, wrong types rejected, boundary values, unknown agent — all pass                                  | **Pass** (minor optionality drift, see below)       |
| 2.16  | packages/shared has no dependency on apps/ or agents/                                                | `package.json`: only dependency is `zod`; no imports to `apps/` or `agents/` anywhere in `src/` or `scripts/` | Task 2.16 marked [x] | `scripts/check-import-boundaries.ts` passes                                                                                                                  | **Pass**                                            |
| 2.17  | pnpm --filter shared run test:unit && pnpm --filter shared run codegen && pnpm run validate all pass | All source present; codegen produces no diff                                                                  | Task 2.17 marked [x] | `test:unit`: 59/59 pass; `codegen`: no drift; `validate` (filter-level): format:check fails on generated JSON schemas due to missing local `.prettierignore` | **Drift** (Minor — operational, see D-2 below)      |

---

## Drift Catalog

### D-1: `PARAMS_SCHEMAS` dep-updater fields are required; spec says optional

| Field              | Value                                                                                                                                                                                                               |
| ------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Impact**         | Minor                                                                                                                                                                                                               |
| **Intent**         | Undetermined                                                                                                                                                                                                        |
| **Evidence**       | Spec §6.2 code sample: `allow_fixes: z.boolean().optional()`, `max_fix_attempts: z.number().int().min(1).max(5).optional()`. Implementation (`src/params-schemas.ts`): both fields are required (no `.optional()`). |
| **Effect**         | A params payload with only one field (e.g., `{ allow_fixes: true }`) is rejected by validation. The spec intends partial params to be valid so an operator can set one without the other.                           |
| **Non-blocking**   | This drift does not block PR or issue completion.                                                                                                                                                                   |
| **Recommendation** | `developer` fix: add `.optional()` to both fields in the dep-updater params schema, or escalate to `product-engineer` if requiring both was intentional (then spec should be updated).                              |

### D-2: `pnpm --filter shared run validate` fails on `format:check` for generated JSON schemas

| Field              | Value                                                                                                                                                                                                                                                                                                                                     |
| ------------------ | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Impact**         | Minor                                                                                                                                                                                                                                                                                                                                     |
| **Intent**         | Unintended                                                                                                                                                                                                                                                                                                                                |
| **Evidence**       | Running `pnpm --filter @fleet/shared run validate` fails because `prettier --check .` (invoked from the package directory) does not see the root `.prettierignore` which excludes `packages/shared/generated`. The root-level `pnpm run format:check` (which runs prettier from the repo root) passes because it reads `.prettierignore`. |
| **Effect**         | AC 2.17's literal requirement "pnpm run validate" passes when invoked from the repo root. The package-level validate does not pass due to a missing local `.prettierignore` (or the package script not referencing the root ignore file).                                                                                                 |
| **Non-blocking**   | This drift does not block PR or issue completion.                                                                                                                                                                                                                                                                                         |
| **Recommendation** | `developer` fix: add a `generated/` entry to a `packages/shared/.prettierignore` file, or update the package's `format:check` script to pass `--ignore-path ../../.prettierignore`.                                                                                                                                                       |

### D-3: `deriveStatus` boundary operator differs from spec (`>=` vs `>`)

| Field              | Value                                                                                                                                                                                                                                                                            |
| ------------------ | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Impact**         | Minor                                                                                                                                                                                                                                                                            |
| **Intent**         | Intended                                                                                                                                                                                                                                                                         |
| **Evidence**       | Spec §8.1: `return elapsed > maxLifetimeMs + TERMINATION_GRACE_MS ? "incomplete" : "running"` (strict `>`). Implementation: `if (elapsed >= threshold) { return "incomplete"; }` (inclusive `>=`). Test plan AC-11: "elapsed > the agent's maxLifetime + 5 min grace" uses `>`.  |
| **Effect**         | At exactly `maxLifetime + grace` milliseconds, the spec says "running", the implementation says "incomplete". Off-by-one-millisecond edge case — in practice inconsequential since this is a derived status and the platform has already terminated the instance at this point.  |
| **Non-blocking**   | This drift does not block PR or issue completion.                                                                                                                                                                                                                                |
| **Recommendation** | No action needed — the implementation's conservative choice (fail-safe: mark as incomplete at the exact threshold) is arguably more correct given that AgentCore has definitively terminated the instance at `maxLifetime`. If strict spec compliance is desired, change to `>`. |

---

## Edge-Case and Randomized Test Outcomes

The test plan's edge-case matrix for S-002 is fully covered:

| Edge Case                                   | Test Coverage                                                                   | Result |
| ------------------------------------------- | ------------------------------------------------------------------------------- | ------ |
| `deriveStatus` with unparseable `lastRunAt` | `status.test.ts` — empty string, "not-a-date", undefined                        | Pass   |
| `buildSessionId` with short agent/repo      | `session-id.test.ts` — `ci`/`a/b` yields ≥33 chars                              | Pass   |
| Params with valid key but wrong type        | `params-schemas.test.ts` — string for boolean, string for number, float for int | Pass   |
| `normalizeSubjectId` with SSH remote        | `normalize-subject-id.test.ts` — `git@github.com:myorg/repo.git`                | Pass   |

---

## Recommendations Summary

| Drift                      | Action                                                                        | Owner                             |
| -------------------------- | ----------------------------------------------------------------------------- | --------------------------------- |
| D-1 (params optionality)   | Add `.optional()` to dep-updater params fields, or update spec if intentional | `developer` or `product-engineer` |
| D-2 (prettierignore scope) | Add local `.prettierignore` or update script to reference root ignore         | `developer`                       |
| D-3 (boundary operator)    | No action needed (implementation is more conservative)                        | —                                 |

---

## Output Contract

| Field                    | Value                                                                                                     |
| ------------------------ | --------------------------------------------------------------------------------------------------------- |
| **Mode**                 | Audit                                                                                                     |
| **Phase**                | 4 — Reporting & Publication                                                                               |
| **Source artifact**      | `workstream/specification-agent-control-plane-v1.md`, `workstream/user-stories-agent-control-plane-v1.md` |
| **Output file**          | `workstream/fidelity-report-S-002.md`                                                                     |
| **GitHub issue**         | #2                                                                                                        |
| **AC coverage**          | 7/7 covered (2.11–2.17)                                                                                   |
| **Fidelity verdict**     | High                                                                                                      |
| **Highest drift impact** | Minor                                                                                                     |
| **Blocking gaps**        | None                                                                                                      |
