# Recorded GitHub fixtures — `issue-315`

Responses for a story PR that implements issue #315 of
`llipe/dev-tasks-agent-fleet` (S-207, AC-6, TC-207-22).

- `issue_315.json` — issue #315 in the shape dev-tasks publishes a story issue:
  the real title `[PRD-webhook-triggers] Story S-170: pure routing engine + safe
  condition language + bot guard`, the published labels (including
  `prd:webhook-triggers`), and a body built from Story S-170 in
  `workstream/user-stories-prd-webhook-triggers.md` ("Spec §8.1" in Technical
  Notes) followed by the `## Task Checklist` the `plan` skill appends (task 6.0 of
  `workstream/tasks-prd-webhook-triggers-plan.md`). `closed_by_pull_requests`
  is 0, as found for D-22. The body was rebuilt from those documents, not
  captured from the API.
- `pull.json` — PR #330 (invented number and SHAs), head
  `story/S-170-webhook-routing`, base an `integration/*` branch, body
  `Closes #315` plus a cross-repository reference that must be ignored.
- `specification-prd-webhook-triggers.md` — byte copy of
  `workstream/specification-prd-webhook-triggers.md` from
  `integration/code-review-agent` at b5f690e, served raw at the PR's head SHA.

No real tokens or accounts.
