# GitHub Publication Report: Control Tower

## Changelog

| Version | Date       | Summary                                        | Author           |
| ------- | ---------- | ---------------------------------------------- | ---------------- |
| 1.0     | 2026-11-26 | 16 stories published (#487–#502), Waves A and B. | product-engineer |
| 1.1     | 2026-11-26 | Task checklists posted as one comment on each Wave A issue (#487–#496), from `tasks-control-tower-plan.md` v1.0. | product-engineer |
| 1.2     | 2026-11-26 | Story IDs renumbered to S-219–S-234 after a collision with `main`; the 16 issue titles and bodies and the 10 checklist comments were updated to match. | product-engineer |

## Target Repository

- Repo: `llipe/dev-tasks-agent-fleet`
- Date: 2026-11-26
- Milestone: none (see Notes)
- Source: [`user-stories-control-tower.md`](user-stories-control-tower.md) v1.1

## Created Issues

| Story ID | Wave | Story Title | Issue | Labels | Milestone | Assignee |
| -------- | ---- | ----------- | ----- | ------ | --------- | -------- |
| S-219 | A | Tower schema, settings and deny-all RLS | [#487](https://github.com/llipe/dev-tasks-agent-fleet/issues/487) | prd:control-tower, priority: critical, scope: backend, size:M, story, type: enhancement | — | — |
| S-220 | A | Tower token and repository lifecycle | [#488](https://github.com/llipe/dev-tasks-agent-fleet/issues/488) | prd:control-tower, priority: critical, scope: backend, size:M, story, type: enhancement | — | — |
| S-221 | A | Ingestion contract v1: validator and fixtures | [#489](https://github.com/llipe/dev-tasks-agent-fleet/issues/489) | prd:control-tower, priority: critical, scope: api, size:M, story, type: enhancement | — | — |
| S-222 | A | tower_apply_push: merge, dedup, summarize | [#490](https://github.com/llipe/dev-tasks-agent-fleet/issues/490) | prd:control-tower, priority: critical, scope: backend, size:L, story, type: enhancement | — | — |
| S-223 | A | POST /api/tower/ingest endpoint | [#491](https://github.com/llipe/dev-tasks-agent-fleet/issues/491) | prd:control-tower, priority: critical, scope: api, size:M, story, type: enhancement | — | — |
| S-224 | A | Retention: tower.prune and its daily job | [#492](https://github.com/llipe/dev-tasks-agent-fleet/issues/492) | prd:control-tower, priority: medium, scope: backend, size:S, story, type: enhancement | — | — |
| S-225 | A | Read contract v1: module, endpoints, document | [#493](https://github.com/llipe/dev-tasks-agent-fleet/issues/493) | prd:control-tower, priority: critical, scope: api, size:L, story, type: enhancement | — | — |
| S-226 | A | Minimal /tower: repositories and tokens | [#494](https://github.com/llipe/dev-tasks-agent-fleet/issues/494) | prd:control-tower, priority: high, scope: frontend, size:M, story, type: enhancement | — | — |
| S-227 | A | Release-gate probes and runbook | [#495](https://github.com/llipe/dev-tasks-agent-fleet/issues/495) | prd:control-tower, priority: high, scope: infra, size:S, story, type: enhancement | — | — |
| S-228 | A | Wave A live: migrate, deploy, first push | [#496](https://github.com/llipe/dev-tasks-agent-fleet/issues/496) | prd:control-tower, priority: high, scope: infra, size:S, story, type: enhancement | — | — |
| S-229 | B | DESIGN.md contract and result track components | [#497](https://github.com/llipe/dev-tasks-agent-fleet/issues/497) | prd:control-tower, priority: high, scope: frontend, size:M, story, type: enhancement | — | — |
| S-230 | B | Hierarchy: repository, PRD, wave, issue | [#498](https://github.com/llipe/dev-tasks-agent-fleet/issues/498) | prd:control-tower, priority: critical, scope: frontend, size:L, story, type: enhancement | — | — |
| S-231 | B | Times and counts on issue and wave rows | [#499](https://github.com/llipe/dev-tasks-agent-fleet/issues/499) | prd:control-tower, priority: high, scope: frontend, size:M, story, type: enhancement | — | — |
| S-232 | B | Live updates with polling fallback | [#500](https://github.com/llipe/dev-tasks-agent-fleet/issues/500) | prd:control-tower, priority: high, scope: api, scope: frontend, size:M, story, type: enhancement | — | — |
| S-233 | B | Stale repositories and scope filter | [#501](https://github.com/llipe/dev-tasks-agent-fleet/issues/501) | prd:control-tower, priority: medium, scope: frontend, size:S, story, type: enhancement | — | — |
| S-234 | B | Wave B close: E2E, docs, live deploy | [#502](https://github.com/llipe/dev-tasks-agent-fleet/issues/502) | prd:control-tower, priority: high, scope: infra, size:M, story, type: enhancement | — | — |

## Notes

- **Skipped stories:** none. All 16 were published, as the owner asked.
- **Execution method:** `github-mcp`. This session has no `gh` CLI access for writes, and the `github-ops` subagent has only shell tools, so `github-ops` conventions were applied directly by `product-engineer` (fallback).
- **Conventions applied:** title `[PRD-control-tower] Story S-NNN: <title>`, each 80 characters or fewer; one `type:` and one `priority:` label on every issue; a `scope:` label on every issue; the repository's existing `story` and `size:` labels; body in the full story template with `## Summary` and `## Acceptance Criteria`.
- **New label:** `prd:control-tower` did not exist and was created by GitHub on first use, with the default color and no description. Manual follow-up: give it the color and description the other `prd:` labels carry.
- **Milestone:** none assigned. No milestone was requested, and the code-review PRD was published the same way. Assign one if the waves should be tracked by version.
- **Assignees:** none.
- **Tracking issues:** no PRD or wave tracking issue was created. This repository's installed `github-ops` conventions do not define them (they arrived in a later dev-tasks release). Wave membership is carried by the `**Wave:**` line in each issue body and by the table above.
- **Issue order:** issue numbers follow story order, S-219 → #487 through S-234 → #502.
- **Verification:** after publishing, the 16 issues were listed by label; all are open with the expected titles and labels.
- **Task checklists:** each Wave A issue carries its checklist as a comment, not in the issue body. Rewriting a body through the MCP tool means resending it whole; a comment leaves the published story text untouched. `developer` ticks the boxes by editing that comment. Wave B issues have no checklist yet.
- **Assisted-by:** not applicable; no PR was created and no issue was closed.

GitHub is now the source of truth for execution status of these stories.
