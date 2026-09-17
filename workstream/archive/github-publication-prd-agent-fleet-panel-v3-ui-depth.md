# GitHub Publication Report: Agent Fleet Control Panel v3: UI Depth

## Target Repository

- Repo: `llipe/dev-tasks-agent-fleet`
- Date: 2026-09-15

## Created Issues

| Story ID | Story Title | Issue URL | Labels | Milestone | Assignee |
| -------- | ----------- | --------- | ------ | --------- | -------- |
| S-142 | Fix the queued-status animation defect | https://github.com/llipe/dev-tasks-agent-fleet/issues/202 | `prd:panel-v3-ui-depth`, `story`, `scope:panel`, `size:XS`, `priority:medium` | — | — |
| S-143 | Run History — filter, search, and pagination | https://github.com/llipe/dev-tasks-agent-fleet/issues/203 | `prd:panel-v3-ui-depth`, `story`, `scope:panel`, `size:L`, `priority:high` | — | — |
| S-144 | Run History — inline branch and PR links | https://github.com/llipe/dev-tasks-agent-fleet/issues/204 | `prd:panel-v3-ui-depth`, `story`, `scope:panel`, `size:S`, `priority:medium` | — | — |
| S-145 | Run Detail — steps panel with step and log-level filtering | https://github.com/llipe/dev-tasks-agent-fleet/issues/205 | `prd:panel-v3-ui-depth`, `story`, `scope:panel`, `size:L`, `priority:high` | — | — |
| S-146 | All Runs — cross-agent run feed | https://github.com/llipe/dev-tasks-agent-fleet/issues/206 | `prd:panel-v3-ui-depth`, `story`, `scope:panel`, `size:M`, `priority:medium` | — | — |
| S-147 | Repositories — list and add-by-reference | https://github.com/llipe/dev-tasks-agent-fleet/issues/207 | `prd:panel-v3-ui-depth`, `story`, `scope:panel`, `size:L`, `priority:high` | — | — |
| S-148 | Repositories — archive (soft delete) | https://github.com/llipe/dev-tasks-agent-fleet/issues/208 | `prd:panel-v3-ui-depth`, `story`, `scope:panel`, `size:S`, `priority:medium` | — | — |

## PRD-Scope Label

Per the explicit request to tag every issue with a PRD scope, a new label was created (no prior label identified this specific PRD — the closest existing labels were the generic `scope:panel` and the sibling PRD's dedicated `agent:security-analyst`):

- **`prd:panel-v3-ui-depth`** — color `#BFD4F2`, description "Agent Fleet Panel v3: UI Depth PRD (run history filters, run detail depth, all runs, repositories)". Applied to all 7 issues (#202–#208).

## Dependency Cross-References

Recorded as comments on the dependent issue once real issue numbers were known:

- #204 (S-144) → depends on #203 (S-143): https://github.com/llipe/dev-tasks-agent-fleet/issues/204#issuecomment-5680258086
- #206 (S-146) → depends on #203 (S-143): https://github.com/llipe/dev-tasks-agent-fleet/issues/206#issuecomment-5680258734
- #208 (S-148) → depends on #207 (S-147): https://github.com/llipe/dev-tasks-agent-fleet/issues/208#issuecomment-5680259743

S-142 and S-145 have no dependencies and carry no cross-reference comment.

## Notes

- **Execution method used:** `gh-cli` (delegated to the `github-ops` subagent).
- **Assisted-by value used:** `Claude Sonnet 5`.
- **No milestone assigned** — mirrored the closest-precedent multi-story PRD (`security-analyst`, issues #185–#201), which also carries no milestone. The `panel-auth` PRD (#161–#162) did use one, but is the outlier between the two most recent comparable sets, not the norm.
- **No `security` label applied** — none of the 7 stories introduce new auth surface or a new credential path; S-147/S-148's repository write explicitly reuses the existing deny-all RLS posture and the existing server-only service-role client, so this reads as "preserving an existing boundary," not "security-relevant new work." Revisit this call if implementation surfaces something the story descriptions didn't anticipate.
- **No `priority:low` case arose** — all 7 stories are Medium or High priority, so the "create the label or omit" judgment call from the delegation brief was not needed.
- **One correction made during publication:** issue #203's title had its em dash mangled by shell substitution on first creation (`--` instead of `—`); fixed via `gh issue edit` immediately after.
- **No skipped stories** — all 7 stories from `workstream/user-stories-prd-agent-fleet-panel-v3-ui-depth.md` were published.
- **No template or permission limitations encountered.**
- **Manual follow-up needed:** none for publication itself. Two open items carry over from the spec/PRD (unrelated to publishing): (1) `/DESIGN.md` §5.6 for the Repositories screen should exist before S-147 implementation starts (flagged in that issue's Implementation Steps as a blocker-or-explicit-flag choice); (2) the FR8 connection-indicator resolution and the repository-restore scope both need a quick user sign-off per the spec's Open Questions — worth confirming before `plan` selects S-143/S-147 for an active task list.

GitHub is now the source of truth for execution tracking on this PRD — issues #202–#208 carry the full acceptance criteria, testing requirements, and Definition of Done checklists from the stories document.
