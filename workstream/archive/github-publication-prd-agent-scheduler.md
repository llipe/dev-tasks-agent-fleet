# GitHub Publication Report — Agent Scheduler

Published 2026-10-13 to [`llipe/dev-tasks-agent-fleet`](https://github.com/llipe/dev-tasks-agent-fleet)
from [`user-stories-prd-agent-scheduler.md`](user-stories-prd-agent-scheduler.md) v1.0.

## Milestone & label

- **Milestone:** `v3.0 — Phase 4 Agent Scheduler` (#4) — all 16 issues assigned.
- **New label:** `prd:agent-scheduler` (`#0E8A16`) — created following the existing
  `prd:panel-v3-ui-depth` convention.
- **Reused labels:** `story`, `phase:orchestration` (Phase 4), `scope:panel`, `scope:infra`,
  `security`, `size:XS|S|M|L`.
- Every issue body was published via `--body-file` (never inline `--body`), per the
  git-guard invariant.

## Story → Issue map

| Story | Issue | Title | Wave | Labels (beyond story/prd/phase) | Size |
| --- | --- | --- | --- | --- | --- |
| S-149 | [#261](https://github.com/llipe/dev-tasks-agent-fleet/issues/261) | schedules + notifications schema, enums, RLS | A | scope:infra | M |
| S-150 | [#262](https://github.com/llipe/dev-tasks-agent-fleet/issues/262) | buildRunInsert trigger descriptor | A | scope:panel | XS |
| S-151 | [#263](https://github.com/llipe/dev-tasks-agent-fleet/issues/263) | pg_net + Vault + DB settings (+ runbook) | A | scope:infra, security | S |
| S-152 | [#264](https://github.com/llipe/dev-tasks-agent-fleet/issues/264) | compute_next_run_at (DST + cron) + RPC | B | scope:infra | L |
| S-153 | [#265](https://github.com/llipe/dev-tasks-agent-fleet/issues/265) | fire endpoint + shared-secret internal class | B | scope:panel, security | M |
| S-154 | [#266](https://github.com/llipe/dev-tasks-agent-fleet/issues/266) | fire_due_schedules tick + G4 cap + G2 | B | scope:infra | M |
| S-155 | [#267](https://github.com/llipe/dev-tasks-agent-fleet/issues/267) | G1 overlap suppression | C | scope:infra | S |
| S-156 | [#268](https://github.com/llipe/dev-tasks-agent-fleet/issues/268) | G5 open-PR backoff (a+c) + manual clear | C | scope:infra | M |
| S-157 | [#269](https://github.com/llipe/dev-tasks-agent-fleet/issues/269) | G3 circuit breaker (auto-pause) | C | scope:infra | S |
| S-158 | [#270](https://github.com/llipe/dev-tasks-agent-fleet/issues/270) | notify-sweep tick (reaper failures) | D | scope:infra | M |
| S-159 | [#271](https://github.com/llipe/dev-tasks-agent-fleet/issues/271) | SES sender + IAM + daily digest | D | scope:panel, scope:infra, security | L |
| S-160 | [#272](https://github.com/llipe/dev-tasks-agent-fleet/issues/272) | release-gate: /api/internal/** rejects unauth | D | scope:panel, security | S |
| S-161 | [#273](https://github.com/llipe/dev-tasks-agent-fleet/issues/273) | /schedules list + CRUD | E | scope:panel | L |
| S-162 | [#274](https://github.com/llipe/dev-tasks-agent-fleet/issues/274) | new/edit schedule dialog | E | scope:panel | L |
| S-163 | [#275](https://github.com/llipe/dev-tasks-agent-fleet/issues/275) | notifications feed + bell | E | scope:panel | M |
| S-164 | [#276](https://github.com/llipe/dev-tasks-agent-fleet/issues/276) | agent-page scheduled indicator | E | scope:panel | XS |

## Dependency order (for `plan`)

```
#261 ─┬─ #262 ─┐
      │        ├─ #265 ─┬─ #266 ─┬─ #267
#263 ─┘  #264 ─┘        │        ├─ #268
                        │        └─ #269 ─┐
                        │                 ├─ #270 ─ #271 ─ #272
                        └─────────────────┘
UI: #273 → #274 → #275 → #276 (after Wave C/D land)
```

## Notes

- 16 of 16 stories published; coverage validated in the stories doc (every FR1–FR26 and
  AC1–AC15 mapped).
- Open decision flagged in #264 (S-152): **OQ-S2** — `advanced` cron interpreted in the
  schedule timezone (recommended) vs. UTC. Resolve at that story's refinement/implementation.
