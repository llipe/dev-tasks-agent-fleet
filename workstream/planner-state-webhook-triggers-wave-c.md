# Planner State: webhook-triggers-wave-c

## Run Info

- Task source: `workstream/tasks-prd-webhook-triggers-plan.md` (v1.1), Wave C only (tasks 6.0–9.0)
- Integration branch: `integration/webhook-triggers` (main merged in @ e4fe720: #355 audit exception)
- Repository: llipe/dev-tasks-agent-fleet
- Started: 2026-10-20T13:20-03:00
- Last updated: 2026-10-20T16:10-03:00 (corrected; an earlier commit wrote a placeholder 17:30)

## Story Status

| Sequence | Story ID | Issue # | Status | PR | Branch |
| --- | --- | --- | --- | --- | --- |
| 1 | S-170 | #315 | ✅ Merged | #385 | story/S-170-webhook-routing |
| 2 | S-171 | #316 | ✅ Merged | #386 | story/S-171-webhook-resolve |
| 3 | S-172 | #317 | ✅ Merged | #388 | story/S-172-invoke-core |
| 4 | S-173 | #318 | ✅ Merged | #389 | story/S-173-webhook-guardrails |

## Current Position

- Next story: none. Wave C complete. Next: Wave D (S-174 #319 needs the #302 decision; S-175 #320)
- Last merged PR: #389
- Integration branch HEAD: 4396b50 (post-merge: fresh db reset + validate-js green, 1891 tests; one #387 flake on the first run)

## Decisions Log

- 2026-10-20: User approved "start wave C".
- 2026-10-20: #355 closed on main (time-boxed audit exception); merged into integration. The Python gate is now green, so it no longer blocks the consolidated PR.
- Carried over: Node 26; CI only on PRs to main; planner review as a PR comment; migrations local-only until task 16.4.
- S-172 touches the live schedule fire route: record the pre-refactor test baseline first (task 8.1).
- 2026-10-20: S-171 added migration 20261020130000 (public.webhook_bot_login, service_role only).
- 2026-10-20: S-172 baseline (task 8.1) before refactor: 55 tests / 9 files (unit fire-route, run-insert, invoke-route; L2.5 fire-insert, fire-due-schedules, invoke-insert, guardrail-overlap, guardrail-open-pr, guardrail-autopause). Must be >= 55 and all green after.
- 2026-10-20: S-172 baseline held (55 -> 57/57). Webhook invoke capped at 8 s (prod p95 run start 3.2 s). SSE flake filed #387.
- 2026-10-20: S-173 design: stateless public.webhook_guardrail reusing scheduler predicates (not moved into the TS core). Shared G4 cap: in_flight_scheduled_runs now counts webhook runs (scheduler behavior change, intended per FR17). Spec §8.4 write-back pending.
- 2026-10-20: Formatting: always `prettier --write .` then `--check` (file-list writes silently missed integration files 3 times).
