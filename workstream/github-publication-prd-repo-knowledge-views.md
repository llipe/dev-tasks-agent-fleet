# GitHub Publication Report: Repository Knowledge Views

## Changelog

| Version | Date       | Summary                                                                 | Author           |
| ------- | ---------- | ----------------------------------------------------------------------- | ---------------- |
| 1.0     | 2026-11-28 | 17 stories published: `llipe/dev-tasks` #364–#366, this repo #513–#526. | product-engineer |

## Target Repositories

- Wave A: `llipe/dev-tasks` (S-216–S-218)
- Waves B–D: `llipe/dev-tasks-agent-fleet` (S-219–S-232)
- Date: 2026-11-28
- Milestone: **`repo-knowledge-views` — not set** (see Notes)
- Source: [`user-stories-prd-repo-knowledge-views.md`](user-stories-prd-repo-knowledge-views.md) v1.1

## Created Issues

| Story ID | Story Title | Repository | Issue | Labels | Milestone | Assignee |
| -------- | ----------- | ---------- | ----- | ------ | --------- | -------- |
| S-216 | Field-guide contract and skill | `llipe/dev-tasks` | [dev-tasks#364](https://github.com/llipe/dev-tasks/issues/364) | story, skill, type: enhancement, priority: critical, prd: repo-knowledge-views | — | — |
| S-217 | graph.yml template and runbook | `llipe/dev-tasks` | [dev-tasks#365](https://github.com/llipe/dev-tasks/issues/365) | story, skill, type: enhancement, priority: critical, prd: repo-knowledge-views | — | — |
| S-218 | technical-writer owns field guides | `llipe/dev-tasks` | [dev-tasks#366](https://github.com/llipe/dev-tasks/issues/366) | story, agent, type: enhancement, priority: high, prd: repo-knowledge-views | — | — |
| S-219 | Panel role may read the App key | `llipe/dev-tasks-agent-fleet` | [dev-tasks-agent-fleet#513](https://github.com/llipe/dev-tasks-agent-fleet/issues/513) | story, type: enhancement, phase:control-plane, prd:repo-knowledge-views, priority:critical, size:S, scope:infra | — | — |
| S-220 | Read-only installation token minting | `llipe/dev-tasks-agent-fleet` | [dev-tasks-agent-fleet#514](https://github.com/llipe/dev-tasks-agent-fleet/issues/514) | story, type: enhancement, phase:control-plane, prd:repo-knowledge-views, priority:critical, size:M | — | — |
| S-221 | Artifact reader, cache and staleness | `llipe/dev-tasks-agent-fleet` | [dev-tasks-agent-fleet#515](https://github.com/llipe/dev-tasks-agent-fleet/issues/515) | story, type: enhancement, phase:control-plane, prd:repo-knowledge-views, priority:critical, size:M | — | — |
| S-222 | Gate every /api path; release gate | `llipe/dev-tasks-agent-fleet` | [dev-tasks-agent-fleet#516](https://github.com/llipe/dev-tasks-agent-fleet/issues/516) | story, type: enhancement, phase:control-plane, prd:repo-knowledge-views, priority:critical, size:S | — | — |
| S-223 | Field-guide route with sandbox CSP | `llipe/dev-tasks-agent-fleet` | [dev-tasks-agent-fleet#517](https://github.com/llipe/dev-tasks-agent-fleet/issues/517) | story, type: enhancement, phase:control-plane, prd:repo-knowledge-views, priority:critical, size:M | — | — |
| S-224 | Graph route and graph.json validation | `llipe/dev-tasks-agent-fleet` | [dev-tasks-agent-fleet#518](https://github.com/llipe/dev-tasks-agent-fleet/issues/518) | story, type: enhancement, phase:control-plane, prd:repo-knowledge-views, priority:high, size:S | — | — |
| S-225 | Repository page, tabs, agent activity | `llipe/dev-tasks-agent-fleet` | [dev-tasks-agent-fleet#519](https://github.com/llipe/dev-tasks-agent-fleet/issues/519) | story, type: enhancement, phase:control-plane, prd:repo-knowledge-views, priority:critical, size:M, scope:ui | — | — |
| S-226 | Field guide tab with staleness | `llipe/dev-tasks-agent-fleet` | [dev-tasks-agent-fleet#520](https://github.com/llipe/dev-tasks-agent-fleet/issues/520) | story, type: enhancement, phase:control-plane, prd:repo-knowledge-views, priority:high, size:S, scope:ui | — | — |
| S-227 | Graph viewer core and community view | `llipe/dev-tasks-agent-fleet` | [dev-tasks-agent-fleet#521](https://github.com/llipe/dev-tasks-agent-fleet/issues/521) | story, type: enhancement, phase:control-plane, prd:repo-knowledge-views, priority:high, size:L, scope:ui | — | — |
| S-228 | Graph search, filters, focus, report | `llipe/dev-tasks-agent-fleet` | [dev-tasks-agent-fleet#522](https://github.com/llipe/dev-tasks-agent-fleet/issues/522) | story, type: enhancement, phase:control-plane, prd:repo-knowledge-views, priority:high, size:M, scope:ui | — | — |
| S-229 | E2E with GitHub stub and security cases | `llipe/dev-tasks-agent-fleet` | [dev-tasks-agent-fleet#523](https://github.com/llipe/dev-tasks-agent-fleet/issues/523) | story, type: enhancement, phase:control-plane, prd:repo-knowledge-views, priority:high, size:M | — | — |
| S-230 | Adopt graph.yml in this repository | `llipe/dev-tasks-agent-fleet` | [dev-tasks-agent-fleet#524](https://github.com/llipe/dev-tasks-agent-fleet/issues/524) | story, type: enhancement, phase:control-plane, prd:repo-knowledge-views, priority:high, size:S | — | — |
| S-231 | This repository's field guide | `llipe/dev-tasks-agent-fleet` | [dev-tasks-agent-fleet#525](https://github.com/llipe/dev-tasks-agent-fleet/issues/525) | story, type: enhancement, phase:control-plane, prd:repo-knowledge-views, priority:high, size:L, type: docs | — | — |
| S-232 | Live verification and roadmap close-out | `llipe/dev-tasks-agent-fleet` | [dev-tasks-agent-fleet#526](https://github.com/llipe/dev-tasks-agent-fleet/issues/526) | story, type: enhancement, phase:control-plane, prd:repo-knowledge-views, priority:high, size:S | — | — |

17 of 17 stories published. Dependency order: see the stories file, Execution Plan.

## Notes

- **Execution method:** `github-mcp`. `github-ops` delegation was not used. The subagent's only path is the `gh` CLI, and `gh` is limited to search in this runtime. `github-ops` conventions were applied directly: title pattern `[PRD-<name>] Story <ID>: <Title>` at ≤ 80 characters, one `type:` and one `priority:` label per issue, no inline `--body`.
- **Label spelling follows each repository's existing convention.** `llipe/dev-tasks` uses `<category>: <value>` with a space (`priority: critical`, `type: enhancement`, `prd: repo-knowledge-views`). This repository uses `prd:code-review-agent` / `priority:critical` / `size:M` without a space (precedent #406–#417). New labels (`prd: repo-knowledge-views`, `prd:repo-knowledge-views`, and `scope:ui` / `type: docs` if absent) were created implicitly with GitHub's default colour and no description. Set the colour and description in the GitHub UI.
- **Milestone not set in either repository.** The GitHub MCP tools cannot create or list milestones, and `gh` is unauthenticated here. Follow-up: create milestone `repo-knowledge-views` in both repositories, with description "PRD repo-knowledge-views: field guide and dependency graph per repository in the panel", and assign `llipe/dev-tasks` #364–#366 and this repository's #513–#526.
- **Story text synced:** S-232's issue adds "riel is registered in the panel" as its first acceptance criterion. Stories file v1.1 carries the same change.
- No assignees (single-operator repositories). No issue template constraints. No PR created and no issue closed in this run, so no `Assisted-by` line was needed.
- GitHub is now the source of truth for execution tracking of this PRD.
