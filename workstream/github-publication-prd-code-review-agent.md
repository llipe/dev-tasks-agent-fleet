# GitHub Publication Report: Code Review Agent

## Changelog

| Version | Date       | Summary                                                                                                              | Author           |
| ------- | ---------- | -------------------------------------------------------------------------------------------------------------------- | ---------------- |
| 1.0     | 2026-10-22 | 12 stories published (#406–#417).                                                                                    | product-engineer |
| 1.1     | 2026-10-22 | Applied `github-ops` conventions: `type: enhancement` added to all 12 issues; 8 titles shortened to ≤ 80 characters. | product-engineer |

## Target Repository

- Repo: `llipe/dev-tasks-agent-fleet`
- Date: 2026-10-22
- Milestone: **none yet** (see Notes)
- Source: [`user-stories-prd-code-review-agent.md`](user-stories-prd-code-review-agent.md) v1.0

## Created Issues

| Story ID | Story Title                                 | Issue                                                             | Labels                                                                                                                          | Milestone | Assignee |
| -------- | ------------------------------------------- | ----------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------- | --------- | -------- |
| S-204    | Agent scaffold, params, and agents seed     | [#406](https://github.com/llipe/dev-tasks-agent-fleet/issues/406) | agent:code-review, phase:control-plane, prd:code-review-agent, priority:critical, scope:infra, size:M, story, type: enhancement | —         | —        |
| S-205    | GitHub client with a write allowlist        | [#407](https://github.com/llipe/dev-tasks-agent-fleet/issues/407) | agent:code-review, phase:control-plane, prd:code-review-agent, priority:critical, size:M, story, type: enhancement              | —         | —        |
| S-206    | Expanded diff and size check                | [#408](https://github.com/llipe/dev-tasks-agent-fleet/issues/408) | agent:code-review, phase:control-plane, prd:code-review-agent, priority:critical, size:M, story, type: enhancement              | —         | —        |
| S-207    | Linked issues and spec resolution           | [#409](https://github.com/llipe/dev-tasks-agent-fleet/issues/409) | agent:code-review, phase:control-plane, prd:code-review-agent, priority:high, size:M, story, type: enhancement                  | —         | —        |
| S-208    | Verifier drift candidates and conventions   | [#410](https://github.com/llipe/dev-tasks-agent-fleet/issues/410) | agent:code-review, phase:control-plane, prd:code-review-agent, priority:high, size:S, story, type: enhancement                  | —         | —        |
| S-209    | Budget fit, rubric v1, and prompt builder   | [#411](https://github.com/llipe/dev-tasks-agent-fleet/issues/411) | agent:code-review, phase:control-plane, prd:code-review-agent, priority:critical, size:M, story, type: enhancement              | —         | —        |
| S-210    | Bedrock adapter, forced schema, fallbacks   | [#412](https://github.com/llipe/dev-tasks-agent-fleet/issues/412) | agent:code-review, phase:control-plane, prd:code-review-agent, priority:critical, size:M, story, type: enhancement              | —         | —        |
| S-211    | Findings validation and verdict             | [#413](https://github.com/llipe/dev-tasks-agent-fleet/issues/413) | agent:code-review, phase:control-plane, prd:code-review-agent, priority:critical, size:S, story, type: enhancement              | —         | —        |
| S-212    | Review, budget, and failure comments        | [#414](https://github.com/llipe/dev-tasks-agent-fleet/issues/414) | agent:code-review, phase:control-plane, prd:code-review-agent, priority:high, size:S, story, type: enhancement                  | —         | —        |
| S-213    | Pipeline wiring, outcomes, and failure path | [#415](https://github.com/llipe/dev-tasks-agent-fleet/issues/415) | agent:code-review, phase:control-plane, prd:code-review-agent, priority:critical, size:L, story, type: enhancement              | —         | —        |
| S-214    | Runtime infrastructure, IAM, and runbook    | [#416](https://github.com/llipe/dev-tasks-agent-fleet/issues/416) | agent:code-review, phase:control-plane, prd:code-review-agent, priority:critical, scope:infra, size:M, story, type: enhancement | —         | —        |
| S-215    | `/review` rule and live verification        | [#417](https://github.com/llipe/dev-tasks-agent-fleet/issues/417) | agent:code-review, phase:control-plane, prd:code-review-agent, priority:critical, size:M, story, type: enhancement              | —         | —        |

12 of 12 stories published. Dependency order: S-204 → S-205 → {S-206, S-207, S-210} → S-208 → {S-209, S-211} → S-212 → S-213 → S-214 → S-215 (see the stories file, Execution Plan).

## Notes

- **Execution method:** `github-mcp`. `github-ops` delegation was not used: the subagent's documented path is the `gh` CLI, and `gh` has no valid token in this runtime. `github-ops` conventions (title format, labels, no inline `--body`) were applied directly.
- **Labels created:** `agent:code-review`, `prd:code-review-agent`, `type: enhancement` (the `github-ops` taxonomy; earlier PRDs in this repo used no `type:` label) — created implicitly on first use with GitHub's default grey color and no description. The `github-ops` color for `type: enhancement` is `#0E8A16`; set it in the GitHub UI. Reused: `story`, `size:*`, `priority:*`, `phase:control-plane`, `scope:infra`, matching the bug-fix issues.
- **Milestone not set.** The GitHub MCP tools cannot create milestones, and `gh` is unauthenticated here. Follow-up: create **"v6.0 — Phase 6 Code Review Agent"** (pattern of #4–#6) and assign #406–#417 to it.
- **ID range:** S-199–S-203 belong to the superseded bug-fix design line (issues #326–#349); S-204 onward is unique.
- **Cross-references:** issue bodies mention #315, #280, #90, #97, #98 as fixtures or patterns; GitHub shows these as backlinks on those issues.
- No assignees (single-operator repo). No issue template constraints applied. No PR created or issue closed in this run, so no `Assisted-by` line was needed.
- GitHub is now the source of truth for execution tracking of this PRD.

## v1.7 — Anthropic model (2026-11-17)

- Source: [`user-stories-prd-code-review-agent.md`](user-stories-prd-code-review-agent.md) v1.5, section "v1.7 — Anthropic model"

| Story ID | Story Title                                                    | Issue                                                             | Labels                                                                                                                      | Milestone | Assignee |
| -------- | -------------------------------------------------------------- | ----------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------- | --------- | -------- |
| S-216    | Review call on Claude Sonnet 5.5                                | [#480](https://github.com/llipe/dev-tasks-agent-fleet/issues/480) | agent:code-review, phase:control-plane, prd:code-review-agent, priority:critical, size:L, story, type: enhancement             | —         | —        |
| S-217    | Selection call, params, CDK, and runbook                        | [#481](https://github.com/llipe/dev-tasks-agent-fleet/issues/481) | agent:code-review, phase:control-plane, prd:code-review-agent, priority:high, scope:infra, size:M, story, type: enhancement     | —         | —        |
| S-218    | Infra and live verification on Sonnet 5.5                       | [#482](https://github.com/llipe/dev-tasks-agent-fleet/issues/482) | agent:code-review, phase:control-plane, prd:code-review-agent, priority:high, scope:infra, size:M, story, type: enhancement     | —         | —        |

3 of 3 stories published. Dependency order: S-216 (#480) → S-217 (#481) → S-218 (#482). Cross-links between the three bodies use issue numbers.

### Notes

- **Execution method:** `gh-cli`, delegated to `github-ops`.
- **Titles shortened** to fit the 80-character issue-title cap; the stories file keeps the full titles.
- **#479** (duplicate trigger, D-75) is out of scope and not referenced from the story issues.
- No milestone, no assignees. No PR created or issue closed, so no `Assisted-by` line was needed.
- GitHub is now the source of truth for execution tracking of v1.7.
