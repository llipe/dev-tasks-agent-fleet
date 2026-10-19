# GitHub Publication Report — Bug Fix Agent

Published 2026-10-18 to [`llipe/dev-tasks-agent-fleet`](https://github.com/llipe/dev-tasks-agent-fleet)
from [`user-stories-prd-bug-fix-agent.md`](user-stories-prd-bug-fix-agent.md) v1.0.
Execution method: `github-mcp` (the `gh` CLI is installed but its token is invalid in this session).
`github-ops` delegation was unavailable (the subagent has no GitHub write tools here), so its issue,
label, and title conventions were applied directly; this note is the required fallback disclosure.

## Story → issue map (24 issues, #326–#349)

| Story | Issue | Title | Wave | Size | Priority | Extra labels | Depends on |
| --- | --- | --- | --- | --- | --- | --- | --- |
| S-180 | [#326](https://github.com/llipe/dev-tasks-agent-fleet/issues/326) | Package scaffold, configuration, clock invariant, CI | A | M | Critical | — | — |
| S-181 | [#327](https://github.com/llipe/dev-tasks-agent-fleet/issues/327) | Container image, pinned CLI, managed settings | A | M | Critical | scope:infra, security | S-180 |
| S-182 | [#328](https://github.com/llipe/dev-tasks-agent-fleet/issues/328) | Agent registration, params schema, payload validation | A | S | High | scope:infra | S-180 |
| S-183 | [#329](https://github.com/llipe/dev-tasks-agent-fleet/issues/329) | GitHub REST client and permission preflight | A | M | Critical | — | S-180 |
| S-184 | [#330](https://github.com/llipe/dev-tasks-agent-fleet/issues/330) | Selection, linked-PR index, applicability gate | A | M | Critical | — | S-183 |
| S-185 | [#331](https://github.com/llipe/dev-tasks-agent-fleet/issues/331) | Claim, claim marker, disposition protocol | A | M | Critical | — | S-183 |
| S-186 | [#332](https://github.com/llipe/dev-tasks-agent-fleet/issues/332) | Stale-claim sweep | A | M | High | — | S-185 |
| S-187 | [#333](https://github.com/llipe/dev-tasks-agent-fleet/issues/333) | Orchestrator through applicability, reporting, outcome mapping | A | M | Critical | — | S-184, S-185, S-186 |
| S-188 | [#334](https://github.com/llipe/dev-tasks-agent-fleet/issues/334) | Operator prerequisites, infra pass, Wave A deploy | A | M | Critical | scope:infra, security | S-181, S-182, S-187 |
| S-189 | [#335](https://github.com/llipe/dev-tasks-agent-fleet/issues/335) | Canary mode and the Wave A canary run | A | M | Critical | security | S-188 |
| S-190 | [#336](https://github.com/llipe/dev-tasks-agent-fleet/issues/336) | Fake claude CLI harness and stream-json fixtures | B | S | High | — | S-189 |
| S-191 | [#337](https://github.com/llipe/dev-tasks-agent-fleet/issues/337) | CLI runner: argv, env allow-list, settings, termination | B | M | Critical | security | S-190 |
| S-192 | [#338](https://github.com/llipe/dev-tasks-agent-fleet/issues/338) | Stream-json parser, events, metrics, limit detection | B | M | High | — | S-191 |
| S-193 | [#339](https://github.com/llipe/dev-tasks-agent-fleet/issues/339) | Dependency installer | B | M | High | — | S-184 |
| S-194 | [#340](https://github.com/llipe/dev-tasks-agent-fleet/issues/340) | Task list: checklist, plan pass, prompts | B | M | High | — | S-191 |
| S-195 | [#341](https://github.com/llipe/dev-tasks-agent-fleet/issues/341) | Measure: classification, caps, forbidden paths, commit message | B | M | Critical | — | S-180 |
| S-196 | [#342](https://github.com/llipe/dev-tasks-agent-fleet/issues/342) | Gate runner and audit baseline | B | M | Critical | — | S-193 |
| S-197 | [#343](https://github.com/llipe/dev-tasks-agent-fleet/issues/343) | Red-to-green verification | B | M | Critical | — | S-195, S-196 |
| S-198 | [#344](https://github.com/llipe/dev-tasks-agent-fleet/issues/344) | Pull request: branch, commit, push, Draft PR, artifact | B | M | Critical | — | S-195 |
| S-199 | [#345](https://github.com/llipe/dev-tasks-agent-fleet/issues/345) | Pipeline wiring and enable the pipeline | B | L | Critical | — | S-192, S-194, S-197, S-198 |
| S-200 | [#346](https://github.com/llipe/dev-tasks-agent-fleet/issues/346) | Disposition wiring: failure paths, ceilings, deadline | B | M | Critical | — | S-199 |
| S-201 | [#347](https://github.com/llipe/dev-tasks-agent-fleet/issues/347) | Live verification on a fixture repository | C | M | Critical | scope:infra | S-200 |
| S-202 | [#348](https://github.com/llipe/dev-tasks-agent-fleet/issues/348) | First schedule and enablement criteria | C | S | High | scope:infra | S-201 + S-189 decision |
| S-203 | [#349](https://github.com/llipe/dev-tasks-agent-fleet/issues/349) | Documentation close-out | C | S | Medium | — | S-202 |

Every issue carries `story`, `size:X`, `priority:<level>`, `prd:bug-fix-agent`, `agent:bug-fix`.
Titles follow `[PRD-bug-fix-agent] Story S-NNN: <title>`. Dependencies are stated by story ID in each
body (the prior batches' convention); the table above maps them to issue numbers.

## Notes

- **Renumbered before publishing.** The stories were drafted as S-165–S-188. `[PRD-webhook-triggers]`
  already holds S-165–S-179 (#309–#324), so the stories were shifted by +15 to **S-180–S-203** and the
  stories file and roadmap were updated first. If the webhook-triggers PRD plans further stories past
  S-179 that are not yet published, a clash is still possible; check before it publishes.
- **No milestone.** The GitHub MCP tools available here cannot list or create milestones. Prior batches
  used `v3.0 — Phase 4 Agent Scheduler` and `v4.0 — Phase 1 Webhook Triggers`. Create a milestone for this
  PRD and assign #326–#349 (one `gh` or UI action).
- **Two new labels with default grey color.** `prd:bug-fix-agent` and `agent:bug-fix` were created by
  GitHub on first use; these tools cannot set a color or description. The scheduler batch used `#0E8A16`
  for its `prd:` label. Recolor in the UI if wanted.
- **Label taxonomy deviation.** `github-ops.md` requires `type:` and spaced `priority: ` labels; this
  repository's actual practice (and the labels that exist) is `story`, `size:X`, `priority:x`, `prd:`,
  `agent:`, `scope:`. The existing practice was followed. `github-ops.md` and the repo disagree; that is
  worth a `github-ops` audit.
- **Spec additions recorded.** `FIX_PIPELINE_ENABLED` (S-187, S-199) and the gated canary mode (S-189)
  are story-level additions to the specification; recorded as specification changelog 1.1.
- **PR #325 was already merged** (it contained only the PRD v1.0 and decision log). The branch was
  rebased onto `main`; the specification, stories, PRD v1.1, and this report are unmerged commits on
  `claude/bug-fixing-agent-fleet-0yb54w` and need a new PR.
- No issue was assigned, and none was pinned to a project board.

## Dependency order (for `plan`)

Wave A: #326 → (#327, #328, #329) → (#330, #331) → #332 → #333 → #334 → #335 (canary gate).
Wave B: #336 → #337 → #338; #339, #340, #341 in parallel; #342, #344 → #343; #345 → #346.
Wave C: #347 → #348 → #349. #348 is also blocked by the credential decision recorded in #335.

GitHub is now the source of truth for execution tracking. The stories file is the design record; status
lives on the issues.
