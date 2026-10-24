---
name: runbook-ci-quality-gates
trigger: A CI run on a PR or push to `main` or an `integration/**` branch is red, or CI did not run on such a PR
owner: operator
last_verified: never (trigger change not yet exercised; first run is the PR that adds this runbook)
related: [".github/workflows/ci.yml", "Makefile", "TESTING.md"]
---

# CI quality gates

`.github/workflows/ci.yml` runs the Python quality gate (one job per agent and
Python version) and the panel quality gate on every push and pull request to
`main` and to any `integration/**` branch. Planner runs merge story PRs into an
`integration/<feature>` branch and only the consolidated PR reaches `main`, so
the `integration/**` triggers give each story PR the same gates as `main`.
CI only reads the repository; it holds no secrets and deploys nothing.

## Preconditions

- A PR (or push) targeting `main` or a branch matching `integration/**`.
  Story branches (`story/S-*`) and fix branches are covered through their PR,
  not on push.
- Read access to the repository's Actions tab.

## Steps

1. Open the PR's checks, or list recent runs for the branch:
   `gh run list --workflow ci.yml --branch <branch> --limit 5`.
2. For a red job, read the failing step's log:
   `gh run view <run-id> --log-failed`.
3. Decide whose failure it is before fixing:
   - Reproduce locally with the package's gate, for example
     `make -C agents/code-review/app/codeReview validate`, or
     `pnpm --filter panel run <script>` for the panel.
   - If the same job is red on the base branch's latest run, the failure is
     not the PR's. Fix it on its own branch against `main` and port the
     commit into the PR.
4. Push the fix to the PR branch. A new run starts automatically; a newer push
   to the same ref cancels the older run (`concurrency: ci-${{ github.ref }}`).

## Verification

`gh pr checks <pr-number>` lists every job as `pass`. For a push to an
integration branch, `gh run list --workflow ci.yml --branch <branch> --limit 1`
shows `completed success`.

## Rollback

To stop running CI on integration branches, remove `"integration/**"` from both
`branches` lists in `.github/workflows/ci.yml` and merge that change to `main`.
Nothing else depends on the trigger; already-finished runs are unaffected.

## Escalation

The repository owner. Collect the run URL, the failing job name, and whether
the same job is red on `main`'s latest run.
