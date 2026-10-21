# Issue Refinement: #280 - fix(panel): invoke fails on Fly — non-root user gets EACCES on /.fly/api

## Changelog

| Version | Date       | Summary            | Author           |
| ------- | ---------- | ------------------ | ---------------- |
| 1.0     | 2026-10-13 | Initial refinement | product-engineer |

## Summary

- Goal: the deployed panel can invoke agents again. The Next.js server keeps running as a non-root user, and a recurrence fails the release instead of breaking invocation silently.
- Primary user impact: **Invoke** from `https://dt-agent-fleet-panel.fly.dev` works again. Since release v12 (2026-09-20), every invoke from the deployed panel ends `failed_to_start` / `CREDENTIALS_UNAVAILABLE`.
- Non-goals:
  - running the server as root
  - an OIDC sidecar
  - changes to `panel/lib/aws/credentials.ts` error classification (already correct)
  - an STS exchange in the probe
  - determining whether Fly or flyctl 0.4.104 changed the socket mode (D-02)
  - fixing `flyctl ssh console`'s 502

## Root cause (D-01, D-02)

Fly creates `/.fly/api` at Machine boot as `srwxr-xr-x 0:0`. Connecting to a unix socket requires write permission, so only root can connect. A probe on machine `845de5f2e502e8` connected as uid 0 (HTTP 404) and got `EACCES` as uid 1001. The server runs as uid 1001: `Dockerfile.panel` sets `USER nextjs`, unchanged since 2026-09-08.

The OIDC path was confirmed working on the deployed Machine on 2026-09-11. The only Machine relaunch since then is release v12 (2026-09-20 00:14 UTC), the first deploy through the CI pipeline (`setup-flyctl@master`, flyctl 0.4.104). The current socket carries that boot's timestamp. The fix therefore must not rely on the socket's boot-time mode.

## Refined Scope

- **Entrypoint (D-03, D-04).** Add a POSIX `sh` entrypoint script (e.g. `panel/scripts/docker-entrypoint.sh`, copied into the runner image) that the container starts **as root**:
  - If `/.fly/api` exists as a socket: `chgrp nodejs /.fly/api && chmod g+w /.fly/api`. On failure, log a warning and continue; the credential provider will then fail loudly as today.
  - Always `exec setpriv --reuid=1001 --regid=1001 --init-groups node panel/server.js`, so PID 1 becomes the server running as `nextjs`. `setpriv` ships with util-linux in `node:22-slim`, so nothing is installed.
  - A missing socket (local `docker run`, CI) never blocks startup.
- **Dockerfile.panel.** Remove the trailing `USER nextjs` (the entrypoint drops privileges). Add `ENTRYPOINT ["/app/docker-entrypoint.sh"]` (or equivalent). Keep `--chown=nextjs:nodejs` on app files, `EXPOSE 8080`, and the server command. Document in the Dockerfile why the container starts as root and where privileges drop.
- **Token probe in `scripts/deploy-panel.sh` (D-05).** After the auth gate passes:
  - Run `flyctl machine exec` on each started Machine of the app with a small Node probe executed as uid 1001 (`setpriv`). It POSTs `/v1/tokens/oidc` (`{"aud":"sts.amazonaws.com"}`) on `/.fly/api`.
  - The probe prints only `status=<code> token=<present|absent>`; the token value is never printed or logged.
  - Pass = HTTP 200 and a token present (same extraction rule as `extractOidcToken`: a string `value` or `token` key).
  - Fail = exit 3 with the existing rollback hint, plus a pointer to #280's runbook section.
  - `--dry-run` describes the probe without running it. No STS exchange.
- **Runbook (D-06, FR-49a).** Update `docs/runbooks/panel-deployment.md`:
  - The OIDC probe runs **as the runtime user** via `flyctl machine exec … setpriv --reuid=1001 …`, not from a root SSH session.
  - Document the deploy-time token probe and its exit-3 meaning.
  - Note that `flyctl ssh console` may 502, with `machine exec` as the fallback.
- **CI (D-06).** Keep the existing `shellcheck scripts/deploy-panel.sh` step and add shellcheck for the new entrypoint script. Add an image smoke test in `ci.yml` (Docker is available in `panel-quality`): build `Dockerfile.panel`, run it, and assert that with no `/.fly/api` the server starts, answers on `:8080`, and its process uid is 1001.

## Acceptance Criteria

- [ ] AC1: Given a deployed Machine where `/.fly/api` is `0755 root:root` at boot, when the container starts, then the socket is group-writable by `nodejs`. Validation: `flyctl machine exec … ls -ln /.fly/api` → `srwxrwxr-x 0 1001`.
- [ ] AC2: The server process runs as uid 1001 / gid 1001, not root. Validation: `flyctl machine exec` reading `/proc/<server pid>/status` on Fly; the CI image smoke test asserts the same off-Fly.
- [ ] AC3: Given the container is started without `/.fly/api`, then it starts normally, serves `:8080`, and runs as uid 1001, with no error exit. Validation: CI image smoke test.
- [ ] AC4: Given the fix is deployed, when the operator invokes `dependency-update` from the **deployed** panel, then the run reaches `running` (`credentialSource: fly-oidc`, no `CREDENTIALS_UNAVAILABLE`). Validation: manual live check; record the run id on #280.
- [ ] AC5: Given a deploy where uid 1001 cannot obtain an OIDC token, when `deploy-panel.sh` runs, then it exits 3 after deploying and prints the rollback hint. The token value never appears in any output. Validation: a negative demonstration against a deliberately broken probe (e.g. a wrong socket path via an env override), recorded in the PR; plus shellcheck.
- [ ] AC6: Given a healthy deploy, the probe prints `status=200 token=present` for each started Machine and the script exits 0. Validation: the next real release-pipeline run's log.
- [ ] AC7: `docs/runbooks/panel-deployment.md` documents the runtime-user probe, the deploy-time token probe, and the `machine exec` fallback.

## Constraints

- No new packages in the runner image; `setpriv` comes from util-linux in `node:22-slim`.
- The grant is the minimum needed: group write for `nodejs` only, never world-writable.
- The token is never printed, logged, or written to a file (same posture as `credentials.ts`).
- The `deploy-panel.sh` exit-code contract is unchanged: 0 ok · 1 error · 2 blocked · 3 verify-fail.
- Tags and releases are human-only; the fix ships through `scripts/release-panel.sh` → tag → `deploy-panel.yml`.

## Risks and Edge Cases

- If Fly recreates or re-modes the socket after container start (e.g. a platform agent restart), the boot-time grant is lost. The deploy-time probe catches it at release time, but not between releases. Accepted residual risk; noted in the runbook.
- If Fly forbids `chmod`/`chgrp` on the socket, the entrypoint logs a warning and the probe fails the release with exit 3. That would be a reason to revisit the root/sidecar alternatives.
- A multi-Machine app must probe every started Machine, not only the first.
- With `exec`, the server is PID 1. Signal handling (SIGTERM on Fly stop) must reach Node directly, so `exec` is required and there must be no shell left in between.
- `flyctl machine exec` needs the app's API token in CI. `FLY_API_TOKEN` is already present for `fly deploy`; confirm its scope allows `machine exec`.

## Dependencies

- None blocking. #217 (Next 16) touches `Dockerfile.panel` and should land after this to avoid conflicts.

## Testing Notes

- Unit: none (shell scripts). If the probe parsing lives in a `.mjs` helper, unit-test it next to `panel-auth-check` (status/token-presence parsing, no token echo).
- Integration: CI image smoke test (AC2 off-Fly, AC3).
- Manual: AC1, AC2 on Fly, AC4 live invoke, AC6 release log.
- Edge cases: missing socket (AC3); probe failure (AC5 negative demo); multiple Machines.
- AC-to-test mapping: AC1 → `machine exec ls -ln`; AC2 → `/proc` status on Fly plus the CI smoke test; AC3 → CI smoke test; AC4 → live invoke; AC5 → negative demo plus shellcheck; AC6 → release log; AC7 → runbook diff review.

## Decisions

| ID   | Decision (short form) |
| ---- | --------------------- |
| D-01 | The socket is root-only `0755`; uid 1001 gets EACCES (confirmed) |
| D-02 | Our image is unchanged; the break coincides with the v12 relaunch (first CI deploy); cause undeterminable, so the fix must not rely on the boot mode |
| D-03 | A root entrypoint grants `nodejs` group write, then `setpriv` drops to uid 1001 |
| D-04 | Missing socket → skip the grant, still drop privileges, never fail startup |
| D-05 | OIDC token probe in `deploy-panel.sh` as uid 1001; no token echo; exit 3 |
| D-06 | Runbook in the same PR; ship via the release pipeline; accept on a deployed-panel invoke; CI image smoke test |

## Open Questions

- None.
