# GitHub Publication Report: Bug Fix Agent

## Changelog

| Version | Date       | Summary                       | Author           |
| ------- | ---------- | ----------------------------- | ---------------- |
| 1.1 | 2026-10-20 | Supersedes the parallel design line merged in PR #350 (D-87, @llipe, 2026-10-20). Decision IDs from this line are renumbered D-25–D-67 → D-44–D-86 after main's D-43. The superseded line's changelog rows remain in git history (`875299a`, PR #350). Issues #326–#349 from the superseded line are closed as superseded, each pointing to its counterpart in #362–#380. | product-engineer |
| 1.0     | 2026-10-20 | 19 stories published (#362–#380). | product-engineer |

## Target Repository

- Repo: `llipe/dev-tasks-agent-fleet`
- Date: 2026-10-20
- Milestone: [v5.0 — Phase 5 Bug Fix Agent](https://github.com/llipe/dev-tasks-agent-fleet/milestone/6) (#6, no due date)
- Source: [`user-stories-prd-bug-fix-agent.md`](user-stories-prd-bug-fix-agent.md) v1.0

## Created Issues

| Story ID | Story Title | Issue | Labels | Milestone | Assignee |
| -------- | ----------- | ----- | ------ | --------- | -------- |
| S-180 | Agent scaffold, image, and sandbox policy | [#362](https://github.com/llipe/dev-tasks-agent-fleet/issues/362) | agent:bug-fix, phase:control-plane, prd:bug-fix-agent, priority:critical, size:M, story | v5.0 | — |
| S-181 | Infra: key, runtime, invoke policy, App issues | [#363](https://github.com/llipe/dev-tasks-agent-fleet/issues/363) | agent:bug-fix, phase:control-plane, prd:bug-fix-agent, priority:critical, scope:infra, size:M, story | v5.0 | — |
| S-182 | Sandbox spike on the deployed runtime | [#364](https://github.com/llipe/dev-tasks-agent-fleet/issues/364) | agent:bug-fix, phase:control-plane, prd:bug-fix-agent, priority:critical, size:M, story | v5.0 | — |
| S-183 | Panel string-list schema-form control | [#365](https://github.com/llipe/dev-tasks-agent-fleet/issues/365) | agent:bug-fix, phase:control-plane, prd:bug-fix-agent, priority:high, scope:panel, size:M, story | v5.0 | — |
| S-184 | Agents seed row, params schema, typed params | [#366](https://github.com/llipe/dev-tasks-agent-fleet/issues/366) | agent:bug-fix, phase:control-plane, prd:bug-fix-agent, priority:critical, scope:infra, size:S, story | v5.0 | — |
| S-185 | Preflight: permission, labels, assignee | [#367](https://github.com/llipe/dev-tasks-agent-fleet/issues/367) | agent:bug-fix, phase:control-plane, prd:bug-fix-agent, priority:critical, size:S, story | v5.0 | — |
| S-186 | Claim markers and idempotent disposition | [#368](https://github.com/llipe/dev-tasks-agent-fleet/issues/368) | agent:bug-fix, phase:control-plane, prd:bug-fix-agent, priority:critical, size:M, story | v5.0 | — |
| S-187 | Selection: oldest ready bug, linked-PR skip | [#369](https://github.com/llipe/dev-tasks-agent-fleet/issues/369) | agent:bug-fix, phase:control-plane, prd:bug-fix-agent, priority:critical, size:M, story | v5.0 | — |
| S-188 | Claim with post-claim race check | [#370](https://github.com/llipe/dev-tasks-agent-fleet/issues/370) | agent:bug-fix, phase:control-plane, prd:bug-fix-agent, priority:critical, size:M, story | v5.0 | — |
| S-189 | Checkout, repo gate, toolchain, gate runner | [#371](https://github.com/llipe/dev-tasks-agent-fleet/issues/371) | agent:bug-fix, phase:control-plane, prd:bug-fix-agent, priority:critical, size:M, story | v5.0 | — |
| S-190 | Orchestration and outcomes through the claim | [#372](https://github.com/llipe/dev-tasks-agent-fleet/issues/372) | agent:bug-fix, phase:control-plane, prd:bug-fix-agent, priority:critical, size:M, story | v5.0 | — |
| S-191 | Fix runner: confined claude -p | [#373](https://github.com/llipe/dev-tasks-agent-fleet/issues/373) | agent:bug-fix, phase:control-plane, prd:bug-fix-agent, priority:critical, size:L, story | v5.0 | — |
| S-192 | Change validation: caps, paths, gates | [#374](https://github.com/llipe/dev-tasks-agent-fleet/issues/374) | agent:bug-fix, phase:control-plane, prd:bug-fix-agent, priority:critical, size:M, story | v5.0 | — |
| S-193 | Red-to-green on the changed tests | [#375](https://github.com/llipe/dev-tasks-agent-fleet/issues/375) | agent:bug-fix, phase:control-plane, prd:bug-fix-agent, priority:critical, size:M, story | v5.0 | — |
| S-194 | Draft PR, artifact, and fix-loop enablement | [#376](https://github.com/llipe/dev-tasks-agent-fleet/issues/376) | agent:bug-fix, phase:control-plane, prd:bug-fix-agent, priority:critical, size:M, story | v5.0 | — |
| S-195 | In-container confinement tests (AC-5, AC-6) | [#377](https://github.com/llipe/dev-tasks-agent-fleet/issues/377) | agent:bug-fix, phase:control-plane, prd:bug-fix-agent, priority:high, size:S, story | v5.0 | — |
| S-196 | Stale-claim sweep | [#378](https://github.com/llipe/dev-tasks-agent-fleet/issues/378) | agent:bug-fix, phase:control-plane, prd:bug-fix-agent, priority:high, size:M, story | v5.0 | — |
| S-197 | Deploy script, runbook, fixture schedule | [#379](https://github.com/llipe/dev-tasks-agent-fleet/issues/379) | agent:bug-fix, phase:control-plane, prd:bug-fix-agent, priority:high, scope:infra, size:M, story | v5.0 | — |
| S-198 | Live verification on fixture repo (AC-16) | [#380](https://github.com/llipe/dev-tasks-agent-fleet/issues/380) | agent:bug-fix, phase:control-plane, prd:bug-fix-agent, priority:high, size:S, story | v5.0 | — |

## Notes

- **Skipped stories:** none (19/19).
- **Labels:** repo story convention: `story`, `priority:*`, `size:*`, `phase:control-plane`, `prd:bug-fix-agent`, `agent:bug-fix`, plus `scope:infra` (S-181, S-184, S-197) and `scope:panel` (S-183). The `github-ops` rule of a `type:` label is met by `story`, as in the scheduler and webhook batches. The empty description of `prd:bug-fix-agent` was filled in.
- **Titles** are shortened to stay within the 80-character limit. Full story titles are in the issue bodies and the stories file.
- **Body links** point to `main`. The PRD v1.2, spec, stories and this report are not on `main` until the docs branch merges, so the links return 404 until then.
- **No assignee, no epic.** This was the user's choice. `planner` assigns at execution.
- **Execution method:** `gh-cli`, delegated to the `github-ops` subagent. The bodies were passed with `--body-file`.
- **Assisted-by:** not applicable. No PR was created and no issue was closed.
