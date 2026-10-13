# Issue Refinement: #252 - fix(deps): unblock the pnpm and pip-audit CI gates

## Changelog

| Version | Date       | Summary            | Author           |
| ------- | ---------- | ------------------ | ---------------- |
| 1.0     | 2026-10-13 | Initial refinement | product-engineer |

## Summary

- Goal: make both CI dependency-audit gates green on `main`, so that PRs (including #244 and #245) get a real CI signal again (D-04, D-06).
- Primary user impact: none at the UI level. The two deployed agents run with a patched PyJWT once they are redeployed (D-10).
- Non-goals: upgrading `next` (handed over to #217, D-05/D-06); dev-only advisories outside the `--prod` gate; the local Node 26 vs `engines` mismatch.

## Diagnosis (D-01)

| Gate | Command | Blocking advisories | Fix |
| --- | --- | --- | --- |
| Panel | `pnpm --filter panel run audit` → `pnpm audit --prod --audit-level=high` | `sharp <0.35.5` (GHSA-wq5f-xc86-pv6w, via `next`), `source-map-js <1.2.2` (GHSA-68fv-2mgg-jv7q, via `next>postcss`) | Root `pnpm.overrides` |
| Panel (non-blocking) | same | `fast-uri <3.1.8` (moderate, via `ajv`); `next <15.5.27` ×2 (moderate) | Override `fast-uri`; `next` → #217 |
| Python (×2 agents) | `pip-audit . --strict` | `PyJWT==2.13.0`, 14 PYSEC advisories | Pin `PyJWT==2.15.1` (zero OSV advisories) |

## Acceptance Criteria

- [ ] AC1: Given Node 22, when `pnpm --filter panel run audit` runs, then it exits 0 and `pnpm audit --prod --json` lists no high/critical advisory; the only remaining prod advisories are the two moderate `next` ones handed over to #217. Validation: CI `panel-quality` "Dependency audit" step.
- [ ] AC2: Given each agent package, when `pip-audit . --strict` runs on Python 3.13 and 3.14, then it exits 0. Validation: CI `python-quality` matrix.
- [ ] AC3: Given PyJWT 2.15.1, when the agents' credential tests run, then GitHub App JWT signing (`jwt.encode`, RS256, `credentials.py:159`) passes unchanged. Validation: `make test` in both agent packages.
- [ ] AC4: `make validate` passes locally and both CI jobs are green on the PR.
- [ ] AC5: Given the `sharp` override, when `pnpm --filter panel build` runs, then the build succeeds and the existing E2E and auth-gate parser tests are unaffected.
- [ ] AC6: After merge, both agents are redeployed and verified: a real invocation of each completes GitHub App auth and reaches a terminal status, and the new deployed-state hash is recorded on the issue (D-10).

## Constraints

- Pin exact versions (repo convention). `jwt.encode` requires the `cryptography` backend, which is already present.
- Overrides use the `pkg@<range>` selector form that the root `package.json` already uses, and replace the stale `sharp@<0.34.4` entry rather than adding a second `sharp` key.
- The redeploy is an `infra-engineer` change: approval-gated, operator-run via the AgentCore CLI/CDK, and reversible by redeploying the previous image.

## Risks and Edge Cases

- PyJWT 2.14/2.15 may tighten key or algorithm validation on `encode`. AC3 catches this; if a change is needed, it stays minimal and is documented in the PR.
- `sharp` 0.35.5 is a native binary. The `Dockerfile.panel` (ARM64/x64) build must still resolve a prebuilt binary (AC5).
- A new advisory published between refinement and implementation can re-redden the gate. The implementer re-runs the audit and applies the same fix pattern for any new transitive high.
- The lockfile is regenerated: the diff must touch only the overridden packages and their direct dependents.

## Dependencies

- Blocks: #245 and #244 (they need green CI). Hands over the `next` advisories to #217.

## Testing Notes

- Unit/component: existing agent credential tests (AC3); no new test required unless `credentials.py` changes.
- Integration: CI gates themselves (AC1, AC2, AC4).
- Manual: `pnpm --filter panel build` (AC5); post-merge real invocation of both agents (AC6).
- AC-to-test mapping: AC1 → panel audit step; AC2 → pip-audit matrix; AC3 → `tests/` credential suites; AC4 → `make validate` + CI; AC5 → build + E2E job; AC6 → live invocation recorded on the issue.

## Decisions

| ID   | Decision (short form) |
| ---- | --------------------- |
| D-01 | Both gates fail; root causes are `sharp`/`source-map-js` via `next`, and PyJWT 2.13.0 |
| D-04 | One issue covers both gates |
| D-05 | The `next` advisories are fixed by the #217 Next 16.4.0 upgrade, not a 15.x patch |
| D-06 | #252 = PyJWT 2.15.1 + transitive overrides, `next` untouched; #217 clears the `next` moderates |
| D-10 | Post-merge redeploy of both agents is a task and gates closure |

## Open Questions

- None.
