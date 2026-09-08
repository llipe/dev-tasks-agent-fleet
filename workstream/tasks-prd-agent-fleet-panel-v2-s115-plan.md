# Implementation Plan - S-115 Fly Deployment, Privacy Release Gate, and OIDC Probe (Issue #128)

> **Source:** [`user-stories-prd-agent-fleet-panel-v2.md`](user-stories-prd-agent-fleet-panel-v2.md) Story S-115 · Issue [#128](https://github.com/llipe/dev-tasks-agent-fleet/issues/128)
> **Scope:** deployment + live verification. Closes **AC8** and spec **Open Question 1** (OIDC socket shape + AWS `sub` normalization) and **OQ2** if not already fully settled; implements **SR2** (the privacy boundary as a release gate). No schema/data change (documented migration opt-out) — but there **are** live infrastructure actions (Fly deploy, IAM/OIDC IdP registration, Fly secrets) that require explicit user confirmation before execution.
> **Dependencies (must be merged first):** S-114 (#127 — E2E green against the local stack). The agent runtime must be deployed before the live-invocation check (spec §15 ordering).
> **Package manager:** `pnpm` (workspace root). Canonical scripts only.

## Context Notes

> - **SR2 is the highest-severity risk in the spec:** the panel's *only* security boundary is that the Fly app is not publicly reachable (no user auth in v1, D16). A future deploy that adds a public service silently removes it. That is why **privacy is a release gate, not a checklist item** — a script must *fail the release* if the app has a public IP or a public service.
> - **OQ1 can only be closed by probing a real Machine:** the Fly OIDC socket response shape and AWS's normalized `sub` claim cannot be resolved from docs (SR1). S-111 wrote `credentials.ts` to *fail loudly* (`FlyOidcShapeError` naming received keys) when reality differs from the SD9 assumption; this story runs the probe and **corrects `credentials.ts` only if the probe contradicts SD9**.
> - **No static AWS keys, any environment (D12/AC8):** `fly secrets list` must contain **no** AWS key of any kind. AWS access is Fly OIDC → `AssumeRoleWithWebIdentity` only. The Supabase service-role key *is* a Fly secret.
> - **This story does not make the app public and does not add auth (D16):** it makes the boundary explicit and checked.
> - **`DurationSeconds: 900` must be ≤ the role's `MaxSessionDuration`** — unverified until this story; a mismatch is a clear, recorded failure, not a silent one.
> - **SR7/R7 live risk:** local dev against the production Supabase remains a risk; the runbook must state which Supabase project the deployed panel vs. the local stack each point at.
> - **This is the highest-risk story in the plan** (live infra, security gate). Every irreversible/live action (deploy, IAM changes, secrets, public-exposure changes) is gated on explicit user confirmation.

## Relevant Files

- `panel/Dockerfile` - Production image for the Next.js panel (Node runtime; standalone build).
- `panel/fly.toml` - Fly app config with **no `[http_service]` and no public ports**, carrying a comment stating why (SR2/D16).
- `panel/.dockerignore` - Keep the image lean and secret-free.
- `scripts/verify-fly-private.sh` - Release-gate script: parses `fly status` / IP-list output and **fails** if any public IP or public service is present.
- `panel/tests/unit/fly-privacy-check.test.ts` - Unit test for the privacy-check parser (fails on any public IP; passes on a private-only allocation) — the gate must be observed failing.
- `panel/lib/aws/credentials.ts` - **Modified only if** the live probe contradicts SD9 (socket shape / `sub` normalization); otherwise unchanged.
- `docs/runbooks/panel-deployment.md` - The deployment + probe runbook: recorded OIDC socket response shape, normalized `sub`, `MaxSessionDuration` compatibility, Fly region + machine sizing (OQ5), which Supabase project each environment targets (SR7), rollback (redeploy prior image), and the live invocation evidence.
- `panel/README.md` - **Modified:** the private-app requirement documented as a **precondition**, not an implementation detail.
- `workstream/specification-prd-agent-fleet-panel-v2.md` - **Modified (§17):** OQ1 and OQ2 marked resolved with a changelog row (routed through the appropriate owner per meta-rules).
- `docs/requirements/prd-agent-fleet-panel-v2.md` - **Modified (§18):** open question #5 marked resolved with a changelog row.
- `.github/workflows/ci.yml` - **Possibly modified:** add the privacy-check unit test to the gate (the script's parser is unit-tested even though `fly deploy` is not run in CI).

## Tasks

- [ ] 1.0 Implement Story S-115 - [#128](https://github.com/llipe/dev-tasks-agent-fleet/issues/128): Fly deployment, privacy release gate, and OIDC probe

  ### Branch & PR setup
  - [x] 1.1 Verify HEAD is not `main`; create feature branch `story/S-115-fly-deploy-oidc` off the latest `main` **after S-114 (#127) is merged** (delegate naming/creation to `github-ops`).
  - [x] 1.2 After the first commit, open a **draft PR** targeting `main` (delegate to `github-ops`); PR body via `--body-file`, includes `Closes #128`; title Conventional Commits (`feat: deploy panel to private Fly app with verified OIDC`). — PR #154.
  - [x] 1.3 Sync issue #128 checklist with this task list (delegate to `github-ops`).

  ### Committable artifacts + privacy gate (Impl Step 1 — all local, no live action)
  - [x] 1.4 Write `panel/Dockerfile` (+ `.dockerignore`): Next.js standalone production build on the Node runtime; no secrets baked into the image; minimal layers. — verified: image builds from repo-root context and the container boots (`Ready`).
  - [x] 1.5 Write `panel/fly.toml` with **no `[http_service]`** and no public ports, plus an explicit comment referencing SR2/D16 explaining why the app is private-only.
  - [x] 1.6 Write `scripts/verify-fly-private.sh` — parses `fly status` / allocated-IP output and exits non-zero if any public IP or public service is present. (Pure decision logic in `panel/scripts/fly-privacy-check.mjs`; CLI exit 0/1 verified.)
  - [x] 1.7 Write the privacy-check unit test (`tests/unit/fly-privacy-check.test.ts`): a fixture with a public IP → the parser reports failure; a private-only fixture → pass. This is the "gate observed failing" evidence at unit level. — 21 tests pass.
  - [x] 1.8 Wire the privacy-check parser test into `make validate` / CI (`.github/workflows/ci.yml`) so a regression in the gate parser is caught even though `fly deploy` is not run in CI. (Runs in the `unit` project + a dedicated named CI step + shellcheck of the wrapper.)

  ### Live infrastructure — GATED on explicit user confirmation (Impl Steps 2–4)
  > Each task below performs a live, hard-to-reverse action. Present the exact command + expected effect and **wait for explicit user confirmation** before executing.
  - [ ] 1.9 **[confirm]** Register Fly as an OIDC IdP in AWS; create/point an IAM role whose trust policy trusts the app's `sub` (`<org>:<app>:*`) and grants **only** `bedrock-agentcore:InvokeAgentRuntime` on the runtimes ARN (never `*`). Record the role ARN + trust policy in the runbook.
  - [ ] 1.10 **[confirm]** Set Fly secrets: the Supabase service-role key + `AGENT_RUNTIME_ROLE_ARN`. Then run `fly secrets list` and assert it contains **no** AWS key of any kind (AC8/D12). Record the (redacted) secret-name list in the runbook.
  - [ ] 1.11 **[confirm]** Confirm the agent runtime is deployed (spec §15 ordering — it must exist before the live invocation check). If not, coordinate its deploy first.
  - [ ] 1.12 **[confirm]** `fly deploy` the panel image. Then run `scripts/verify-fly-private.sh` against the live app and confirm it reports private-only; confirm the app is unreachable from a network without access.

  ### Live verification — the OQ1/OQ2 closers (Impl Steps 5–6)
  - [ ] 1.13 **[confirm]** Probe the OIDC socket on a live Machine using the retained `curl` command; **record the actual JSON response shape and the normalized `sub` claim** in `docs/runbooks/panel-deployment.md`.
  - [ ] 1.14 If (and only if) the probe contradicts SD9's assumption, correct `panel/lib/aws/credentials.ts` and re-run its unit suite (`pnpm run test:unit`); if the probe matches SD9, record "no change required" with the evidence.
  - [ ] 1.15 Confirm `DurationSeconds: 900` is compatible with the role's `MaxSessionDuration`; record the value. A mismatch → clear recorded failure + fix.
  - [ ] 1.16 **[confirm]** Perform one real end-to-end invocation from the deployed panel: a run transitions `queued → running` against the deployed AgentCore runtime, with the log tailing live in the browser (PRD AC6 in production, exercising S-110). Record evidence (run id, timestamps).
  - [ ] 1.17 Settle OQ2 (the `prompt`-wrapping question) by observation if any residual remains, and record it in the runbook alongside the existing `runbooks/issue-89-live-verification.md` evidence.

  ### Acceptance-criteria verification
  - [ ] 1.18 Verify AC1: `Dockerfile` + `fly.toml` committed; `fly.toml` has no `[http_service]`/public ports with the SR2/D16 comment.
  - [ ] 1.19 Verify AC2: Fly registered as an OIDC IdP; IAM role trusts `<org>:<app>:*` and grants only `bedrock-agentcore:InvokeAgentRuntime` on the runtimes ARN (console evidence in the runbook).
  - [ ] 1.20 Verify AC3 (AC8): the Supabase service-role key is a Fly secret; `fly secrets list` contains no AWS key of any kind.
  - [ ] 1.21 Verify AC4: the OIDC socket response shape + normalized `sub` are recorded; `credentials.ts` corrected iff reality differed from SD9.
  - [ ] 1.22 Verify AC5: `DurationSeconds: 900` confirmed compatible with the role's `MaxSessionDuration`.
  - [ ] 1.23 Verify AC6: the release-process check asserts no allocated public IP and no public service, and **fails the release** if one exists (demonstrate the failure on a deliberately misconfigured public service, then revert — edge-case matrix).
  - [ ] 1.24 Verify AC7: `panel/README.md` documents the private-app requirement as a **precondition**.
  - [ ] 1.25 Verify AC8: one real end-to-end invocation from the deployed panel transitions `queued → running` with the log tailing live (recorded).
  - [ ] 1.26 Verify AC9: OQ2 (`prompt`-wrapping) settled by observation and recorded.
  - [ ] 1.27 Verify AC10: local development still works unchanged with an SSO profile (`credentialSource()` reports the local branch; no AWS env keys required) — the second half of AC8.
  - [ ] 1.28 Cover the edge-case matrix: OIDC socket returns an unexpected shape → `FlyOidcShapeError` names the received keys (SD9 paying off); STS `AccessDenied` (trust-policy `sub` mismatch) → `CREDENTIALS_UNAVAILABLE`, distinct from an AgentCore failure; role `MaxSessionDuration` < 900 → clear failure; a deliberately misconfigured public service → release check fails.
  - [ ] 1.29 Produce the acceptance-criteria → evidence mapping (AC1/AC6–AC7 → committed config + privacy-check run; AC2–AC3/AC5 → AWS/Fly console evidence; AC4/AC9 → recorded probe output; AC8 → live-run evidence; AC10 → local SSO run) in the PR.

  ### Quality gates & closeout
  - [ ] 1.30 Run quality gates: `pnpm run lint`, `pnpm run format:check`, `pnpm run typecheck`, `pnpm run test` (incl. the privacy-check unit test), `pnpm run audit`; then `make validate` at the repo root (both branches must pass).
  - [ ] 1.31 `qa-engineer` pass — confirm `coverage_gate` for the new committable code (the privacy-check parser; any `credentials.ts` correction) and that the privacy gate is observed failing at unit level; record PASS/FAIL/SKIPPED(reason). Update `TESTING.md` (privacy-check unit row).
  - [ ] 1.32 `technical-writer` doc-drift check + write-backs: `docs/runbooks/panel-deployment.md` authored; `panel/README.md` precondition; **spec §17 OQ1/OQ2 resolved + changelog row**, **PRD §18 open-question #5 resolved + changelog row**; `docs/technical-guidelines.md` §5 (live-probe results, `DurationSeconds`/`MaxSessionDuration`) + §13 (deployment now live, not scaffold) + changelog. Whether a new ADR is warranted (a live-verified OIDC/deploy decision) is the technical-writer's call — flag if yes.
  - [ ] 1.33 Run `verifier` in **audit** mode against the delivered config + recorded evidence; post the human-readable summary to issue/PR (mandatory, non-blocking on drift). Confirm the privacy gate's fail-demonstration is recorded and AC8's live evidence is present.
  - [ ] 1.34 Convert PR from draft to ready for review; notify the user for review/merge. Do not close #128 until the PR is approved AND merged.

## Notes

- **Migration lifecycle: N/A** — no schema/data-model change (documented opt-out).
- **Confirmation gate on live/irreversible actions:** tasks 1.9–1.13 and 1.16 (IAM/OIDC registration, Fly secrets, agent-runtime dependency, `fly deploy`, socket probe, live invocation) are hard-to-reverse or affect live/cloud state — each is marked **[confirm]** and MUST present the exact action + risk and wait for explicit user approval before executing. No secret material (tokens, STS responses, assumed-role credentials) is ever printed to logs or the runbook (SD9 rule).
- **Sequencing:** blocked on S-114 (#127). The agent runtime must be deployed before task 1.16 (spec §15).
- **Rollback:** the panel is stateless — rollback is redeploying the prior image; record this in the runbook.
- **This closes the Phase-2 deploy arc:** after S-115, AC8/OQ1/OQ2/SR2 are resolved and the panel is live-private. Remaining open items outside this sequence (agent-side #108/#109 Secrets Manager error classification, and #78 the dependency-update agent compliance test plan) are independent and not part of S-110→S-114→S-115.
