# ADR-002: Document the implemented `open_pr` step and `pull_request` run artifact

## Status

Accepted

## Context

`docs/technical-guidelines.md` §9 (Code Organization & Structure) and §11
(Testing Strategy) described the `dependency-update` agent as having its
**PR-creation and artifact emission deferred to issues #76/#77**. Issue #76
("Pull Request Creation and PR Body Builder") has since been implemented on
branch `issue/76-pr-creation-body-builder` (Draft PR #86):

- A new module `agents/dependency-update/app/dependencyUpdate/pull_request.py`
  provides branch naming (`deps/update-YYYYMMDD-HHMMSS`), an idempotency check
  (`existing_pr` via `gh pr list`), an ephemeral credential-helper push
  (token never in the remote URL), `create_pr` (`gh pr create --body-file`,
  never inline), a conditional PR body builder, and `open_pr_if_needed`
  orchestration.
- `main.py` wires the `open_pr` step, re-mints the installation token when it is
  stale (>45 min) before push, records a `pull_request` run artifact for both
  newly created and pre-existing PRs, opens the PR **before** a
  `MAJOR_UPDATE_REQUIRED` terminal state (req 43), and maps `PullRequestError`
  to `failed / needs_review / <code>`.

Leaving the guideline text saying these were "deferred" would misrepresent the
current implemented state. This ADR exists to satisfy the repository rule that
**every modification to `docs/technical-guidelines.md` is accompanied by an
ADR** — even when the modification is a factual current-state correction rather
than a new decision.

## Decision

Update the current-state descriptions in `technical-guidelines.md` to reflect
the implemented `open_pr` step and `pull_request` artifact:

1. §9 status line — the deterministic pipeline now includes the idempotent
   `open_pr` step and the `pull_request` run artifact (issue #76). Only the
   fix-budget test-output artifact, full `runs.metrics` persistence, and
   deploy/E2E remain deferred (→ issue #77).
2. §11 test surface — record the PR-creation Layer 1 (`test_pr_body.py`) and
   Layer 2 (`test_pr_creation.py`, `test_pipeline.py` additions) tests; note the
   full suite is now **328 tests passing** and `pull_request.py` reports ~95%
   line coverage.

No enforceable guideline rule (§3 architecture patterns, §5 auth, §6 security)
is changed. The security posture the implementation follows — token supplied via
an ephemeral credential helper (§5, "The token **MUST** be supplied to
`git push` only for the duration of that call"), `--body-file` never inline
(git-guard invariant), no push to the default branch — was already mandated;
this change only records that the implementation now honors it.

## Alternatives Considered

- **Amend ADR-001 instead of a new ADR.** Rejected: ADR-001 documents the LLM
  fix-agent escape hatch (issue #75), a distinct decision. Conflating an
  unrelated status update into it would muddy that record. ADRs are immutable
  once Accepted except for status transitions.
- **Update the guideline without an ADR** because this is a status correction,
  not a new decision. Rejected: the repository rule is literal — any change to
  `technical-guidelines.md` requires an ADR. This ADR is deliberately scoped as
  a documentation/status-correction record.

## Consequences

- **Positive:** the foundation doc now matches the implemented pipeline; readers
  no longer see PR-creation as pending work. The ADR trail explains why the
  guideline text changed.
- **Negative / cost:** a low-substance ADR for what is essentially a status
  update. Accepted as the cost of the "ADR-per-guideline-change" invariant.
- **Follow-up:** when issue #77 lands (`runs.metrics` persistence, deploy, E2E),
  the §9 status line and §11 will need another current-state refresh.

## Related

- Requirements:
  - `docs/requirements/prd-dependency-update-agent.md` (reqs 53–58, req 43; §7.7)
  - `workstream/specification-prd-dependency-update-agent.md` (§8.9 PR body
    builder, §8.10 open_pr outcome mapping, §13.1 error codes)
- Workstream:
  - `workstream/fidelity-report-issue-76.md` (AC coverage + drift log)
  - `workstream/user-stories-prd-dependency-update-agent.md` (PR-creation story)
- Docs updated:
  - `docs/technical-guidelines.md` (§9, §11, changelog 1.3)
  - `TESTING.md` (layer taxonomy, coverage baseline, structural gap table)
  - `agents/dependency-update/README.md` (Pipeline / Open PR step)
- Implementation:
  - `agents/dependency-update/app/dependencyUpdate/pull_request.py`
  - `agents/dependency-update/app/dependencyUpdate/main.py` (`open_pr` step)
