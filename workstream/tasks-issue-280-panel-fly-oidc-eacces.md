# Implementation Plan - Issue #280: panel Fly OIDC EACCES

> Source: `workstream/issue-280-panel-fly-oidc-eacces-refinement.md`; decisions: `workstream/decisions-panel-fly-oidc.md` (D-01..D-06). Single issue, so `developer` Execute Mode applies directly (no planner batch needed).

## Relevant Files

- `Dockerfile.panel` - runner stage: drop `USER nextjs`, add the entrypoint
- `panel/scripts/docker-entrypoint.sh` - new: grant socket group write, `exec setpriv` → uid 1001
- `scripts/deploy-panel.sh` - add the post-gate OIDC token probe (exit 3 on failure)
- `panel/scripts/fly-oidc-probe.mjs` - new (optional): the Node probe run on the Machine as uid 1001; prints only status and token presence. **PR #295 review:** now ALSO shipped into the runtime image (`/app/fly-oidc-probe.mjs`) and run by `deploy-panel.sh` via `machine exec`, so the unit-tested code is what runs on Fly (inline `PROBE_JS` deleted)
- `panel/tests/unit/fly-oidc-probe.test.ts` - new (if the probe has parse logic): status/token-presence parsing, no token echo
- `panel/tests/unit/deploy-panel-probe.test.ts` - **new (PR #295 review):** drives the real `deploy-panel.sh` with a realistic fake `flyctl` (exits 0, echoes `Exit code: N`) to prove the probe verdict is taken from the OUTPUT line, not flyctl's exit status
- `.github/workflows/ci.yml` - shellcheck the entrypoint; add the image smoke test
- `docs/runbooks/panel-deployment.md` - runtime-user OIDC probe, deploy-time probe, `machine exec` fallback

## Tasks

- [ ] 1.0 Implement Issue #280 - https://github.com/llipe/dev-tasks-agent-fleet/issues/280: fix(panel): invoke fails on Fly — non-root user gets EACCES on /.fly/api

  - [x] 1.1 [repo root] Add the CI image smoke test first in `.github/workflows/ci.yml` (`panel-quality` job): build `Dockerfile.panel`, `docker run -d -p 8080:8080` with no `/.fly/api`, wait for `:8080`, and assert the server process (PID 1) runs as uid 1001 (`docker exec <c> grep ^Uid /proc/1/status`). Today's image already passes (it is `USER nextjs`); the test exists to guard the switch to start-as-root + `setpriv` in 1.2/1.3, which would silently leave the server as root if the drop broke (D-06)
  - [x] 1.2 [panel] Add `panel/scripts/docker-entrypoint.sh` (POSIX `sh`, `set -eu`). If `[ -S /.fly/api ]`, run `chgrp nodejs /.fly/api && chmod g+w /.fly/api || echo "warn: …" >&2`; then `exec setpriv --reuid=1001 --regid=1001 --init-groups node panel/server.js` (D-03, D-04)
  - [x] 1.3 [repo root] `Dockerfile.panel` runner stage: copy the entrypoint (`--chmod=0755`), remove `USER nextjs`, and set `ENTRYPOINT`. Keep `--chown=nextjs:nodejs`, `EXPOSE 8080`, and the server command. Add a comment explaining start-as-root → drop to 1001 and referencing #280 (D-03)
  - [x] 1.4 [repo root] Confirm `setpriv` exists in `node:22-slim` (`docker run --rm node:22-slim setpriv --version`); add no package
  - [x] 1.5 [panel] Write the probe (`panel/scripts/fly-oidc-probe.mjs`, or inline in the script): POST `/v1/tokens/oidc` `{"aud":"sts.amazonaws.com"}` on `/.fly/api`; print only `status=<code> token=<present|absent>`; exit 0 only on 200 with a string `value`/`token` key. If it has parse logic, unit-test it first (`panel/tests/unit/fly-oidc-probe.test.ts`), including a test that the token value never appears in stdout/stderr (D-05)
  - [x] 1.6 [repo root] `scripts/deploy-panel.sh`: after the auth gate, for **each started Machine** (`flyctl machine list -a $FLY_APP --json`), run the probe via `flyctl machine exec <id> 'setpriv --reuid=1001 --regid=1001 --init-groups node …'`. On any failure, print the rollback hint plus a pointer to the #280 runbook section and `exit 3`. `--dry-run` describes the probe only. The exit-code contract is unchanged (D-05)
  - [x] 1.7 [repo root] `ci.yml`: add `shellcheck panel/scripts/docker-entrypoint.sh` next to the existing shellcheck steps
  - [x] 1.8 [repo root] Update `docs/runbooks/panel-deployment.md` (FR-49a): the OIDC probe runs as the runtime user via `flyctl machine exec`; the deploy-time token probe and exit 3; the `ssh console` 502 → `machine exec` fallback; the residual risk of a post-boot socket re-mode (D-06)
  - [x] 1.9 Verify Acceptance Criterion AC3: the CI smoke test passes: the container starts without `/.fly/api`, serves `:8080`, and runs as uid 1001
  - [x] 1.10 Verify Acceptance Criterion AC5: negative demonstration. Run the probe with a wrong socket path (env override), confirm `deploy-panel.sh` exits 3 and no token text is printed; record in the PR body
  - [x] 1.11 Run Tests: `make validate` (both branches) passes; the new shellcheck and smoke-test steps pass in CI on the PR
  - [x] 1.12 AC-to-test mapping: record AC1→`machine exec ls -ln`, AC2→`/proc` on Fly + CI smoke, AC3→CI smoke, AC4→live invoke, AC5→negative demo + shellcheck, AC6→release log, AC7→runbook diff, in the PR body
  - [ ] 1.13 **Post-merge (operator, human-only tag):** cut the release through `scripts/release-panel.sh` → tag → `deploy-panel.yml`. Confirm the pipeline log shows `status=200 token=present` for each Machine (AC6) and `deploy-panel.sh` exit 0
  - [ ] 1.14 Verify Acceptance Criterion AC1 and AC2 on Fly: `flyctl machine exec <id> 'ls -ln /.fly/api'` → group 1001 writable; the server pid's `/proc/<pid>/status` shows Uid/Gid 1001
  - [ ] 1.15 Verify Acceptance Criterion AC4: invoke `dependency-update` from the **deployed** panel; the run reaches `running` with `credentialSource: fly-oidc`. Record the run id on #280, then close #280
  - [ ] 1.16 Verify Acceptance Criterion AC7: runbook diff reviewed

## Decisions Consumed

| ID   | Decision (short form) |
| ---- | --------------------- |
| D-03 | A root entrypoint grants `nodejs` group write, then `setpriv` drops to uid 1001 |
| D-04 | Missing socket → skip the grant, still drop privileges, never fail startup |
| D-05 | OIDC token probe in `deploy-panel.sh` as uid 1001; no token echo; exit 3 |
| D-06 | Runbook in the same PR; ship via the release pipeline; accept on a deployed-panel invoke; CI image smoke test |
