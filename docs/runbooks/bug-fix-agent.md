---
name: runbook-bug-fix-agent
trigger: Deploying or redeploying the bug-fix AgentCore runtime, running its sandbox probe, rotating its Anthropic key or Projects token, checking its permissions, or verifying a Wave A run
owner: operator
last_verified: 2026-10-25
related: ["agents/bug-fix/agentcore/agentcore.json", "infra/changes/20261023-bug-fix-runtime/", "infra/changes/20261024-bug-fix-spike-probe/", "infra/agentcore-invoke-policy.json", "infra/environments.yaml", "agents/bug-fix/app/bugFix/probe.py"]
---

# Bug-fix agent: deploy, probe, secrets, verification

How to deploy and verify the `bug-fix` AgentCore runtime (`bugfix_bug_fix-BiuPsdGSPK`, stack `AgentCore-bugfix-default`, account `755641879575`, `us-east-1`), how to run its sandbox probe, and how to set or rotate its two dedicated secrets.

**Blast radius:**
- A deploy replaces the runtime's image and version.
- A secret change affects every subsequent run.
- The panel invoke policy is shared with the sibling agents. Change it only by adding resources.

> **Status (Wave A):** since S-190 the image runs the Wave A orchestration (`preflight` → `refuse` → `checkout` → `claim`). With `FIX_LOOP_ENABLED=0`, a run that wins its claim posts the claim comment, then disposes "fix loop not yet enabled" and ends `needs_review`. The fix loop lands in Wave B. S-184 adds the `agents` seed row (migration `20261024130000_seed_bug_fix_agent.sql`); the panel can invoke the agent once that migration is applied to the live project (see "Seed row"). The `/bug-fix` webhook rule, the board, and live verification are documented in S-197. Follow-up #421 adds a panel Settings UI for the Projects token.

## Preconditions

- **Tools:**
  - AWS CLI 2.x, authenticated to account `755641879575` (the personal account, not Riel or ThinkFirst). Run `aws sts get-caller-identity`.
  - AgentCore CLI **0.28.0** (`npm i -g @aws/agentcore@0.28.0`; `agentcore --version`). Pinned to the version the fleet's CDK project (`@aws/agentcore-cdk` 0.1.0-alpha.49) was deployed with.
  - Node, Docker, yq 4.x.
- **Local target file (gitignored):** `agents/bug-fix/agentcore/aws-targets.json` = `[{"name":"default","account":"755641879575","region":"us-east-1"}]`.
- **CDK dependencies:** `cd agents/bug-fix/agentcore/cdk && npm ci`.
- **Infrastructure changes** go through `/infra-engineer` with a change record under `infra/changes/`.

## Design facts you need before changing anything

- **Imported execution role.** `agentcore.json` sets `executionRoleArn` = `arn:aws:iam::755641879575:role/agent-fleet-bug-fix-runtime`. With an imported role, the AgentCore construct attaches **no** permissions, so it never adds its default `bedrock:InvokeModel*` grant. **Do not remove `executionRoleArn`.**
- **The role's inline policy `bug-fix-runtime`** is versioned in `infra/changes/20261023-bug-fix-runtime/role-policy.json`. It grants:
  - runtime logs, X-Ray, and read-only configuration bundles;
  - ECR pull on `repository/bugfix/*`;
  - `kms:Decrypt` on the ECR repository key `429d9891-d1d3-4b6c-abe3-f8e8b5b6a2b8`, only through ECR;
  - `secretsmanager:GetSecretValue` on exactly four secret ARNs.

  It grants **no `bedrock:*`**.
- **Model:** the Anthropic API, through `ANTHROPIC_API_KEY` (D-50), not Bedrock.
- **The wrapper runs as root and drops to `fixer` with `setpriv` (D-110).** AgentCore runs the container with `no_new_privs` set, so setuid `sudo` can't run. Probe run 1 failed 22 checks on exactly this ("The 'no new privileges' flag is set, which prevents sudo from running as root"). The image has no `sudo`. `main.py` runs as root and starts every process that runs model output or repo code through `setpriv --reuid=10002 --regid=10002 --clear-groups --inh-caps=-all --no-new-privs`, which works under `no_new_privs`. Only wrapper code runs as root. If the runtime ever stops running the image as root, or drops `CAP_SETUID`/`CAP_SETGID`, every sandboxed step fails with a `setpriv` error. The probe's `setpriv.wrapper.root` check shows it.
- **`localhost` resolves through NSS in the image, not through `/etc/hosts` (D-111).** srt and the CLI's Bash sandbox reach their filtering proxy as `localhost` (hard-coded), and the sandbox's network namespace has no DNS. On AgentCore `/etc/hosts` is empty **and read-only** (re-probe 2c), so nothing can add an entry. The image installs `libnss-myhostname` with `hosts: files myhostname dns` in `/etc/nsswitch.conf`, and `/etc/gai.conf` (`precedence ::ffff:0:0/96 100`) puts `127.0.0.1` before `::1`. Before every sandboxed run the wrapper checks, read-only, that `localhost` resolves through `/etc/hosts` or NSS. If neither works, the run fails with `SandboxUnavailable: sandbox cannot resolve localhost: …`, naming both reasons. Without this, `npm`/`pip` fail with `getaddrinfo EAI_AGAIN localhost` (re-probe 2b). Don't remove `libnss-myhostname`, the nsswitch line or `gai.conf` from the Dockerfile. `scripts/image-smoke.sh` checks all three with an empty, read-only `/etc/hosts` mounted.

- **`FIX_LOOP_ENABLED` gates the fix step (S-190).** `agentcore.json` ships it as `0`. Absent or `0`: a run that wins its claim disposes "fix loop not yet enabled" (the diagnosis comment, and 😕 when the run came from a `/bug-fix` comment) and ends `succeeded`/`needs_review`. `1` adds the `fix` step, but this build has no fix runner, so the step disposes "the fix step is not available in this build". Don't set it to `1` before Wave B ships a fix runner. Any value other than `0` or `1` fails every run `CONFIG_INVALID`.
- **The SIGTERM backstop lives on the main thread (S-190 fix round 2).** The SDK runs the entrypoint on its `agentcore-worker-loop` thread, where no signal handler can be installed. `main.py` installs it at import and again at app start, on top of uvicorn's own handler, and chains to it; the process then exits 143. As PID 1 (the exec-form `CMD`), the kernel ignores a re-raised SIGTERM, so the handler exits with `os._exit(143)`. Keep the `CMD` and `main.serve()`; `make image-smoke` checks this under the image's server.
- **What a deployed run writes on the issue.** Before the repo gate passes, at most one refusal reply. After it, the claim comment (and 👀 on the trigger comment), then the diagnosis. Never a label, an assignee, an issue edit, or a board change (Wave A has no board client).

## Steps

### Deploy or redeploy

1. Preview: `cd agents/bug-fix && agentcore deploy --diff -y`. Confirm the runtime keeps `RoleArnOutput = …/agent-fleet-bug-fix-runtime` and that no runtime role is created.
2. Deploy: `agentcore deploy -y`. This builds the image in CodeBuild and updates the runtime.
3. If a deploy recreates the ECR repository with a **new KMS key**, update `EcrImageDecrypt` in `role-policy.json` to the new key ARN, then `aws iam put-role-policy --role-name agent-fleet-bug-fix-runtime --policy-name bug-fix-runtime --policy-document file://infra/changes/20261023-bug-fix-runtime/role-policy.json`. Otherwise the runtime can't pull its image.
4. Commit the CLI's `agents/bug-fix/agentcore/.cli/deployed-state.json`.

### Seed row (S-184): apply, verify, roll back

The `agents` row for `bug-fix` lives in `supabase/migrations/20261024130000_seed_bug_fix_agent.sql`, mirrored in `supabase/seed.sql`. It holds the runtime ARN, the 3600/120/300 timeouts, and the params schema (`issue_number` is the only required key, `additionalProperties: false`). Apply it to the live project only through `/infra-engineer`, with explicit approval.

1. Preview: `supabase db push --dry-run`. It lists every migration the live project hasn't recorded. Stop if it lists anything besides this one.
2. Apply: `supabase db push`.
3. Verify: `select slug, requires_repository, params_schema->'required' from agents where slug = 'bug-fix';` should return `bug-fix | t | ["issue_number"]`. Then open `/agents/bug-fix/invoke` and check that `issue_number` is the only required field.
4. Re-applying the upsert keeps one row and restores every field except `is_enabled`, so an operator's disable sticks.

Rollback: `delete from agents where slug = 'bug-fix';`.
- It fails while any `runs` row references the agent, because `runs.agent_id` is `ON DELETE RESTRICT`.
- It **cascades** to the agent's `webhook_rules` and `schedules`, so it would silently remove the `/bug-fix` rule. Export them first: `select * from webhook_rules where agent_id = (select id from agents where slug = 'bug-fix');`, and the same for `schedules`.

### Run the sandbox probe (S-182, D-70)

Probe mode runs the spike checks in `agents/bug-fix/app/bugFix/probe.py` on the deployed runtime. Use it only for the S-182 spike, through `/infra-engineer` with a change record (currently `infra/changes/20261024-bug-fix-spike-probe/`).

- It runs only when **both** are true:
  - the runtime has `ALLOW_PROBE=1`;
  - the payload carries a **top-level** `"__probe": true` (a JSON boolean, outside `params`).
- Without the flag the run fails `PROBE_REFUSED`. `params.__probe` is ignored.
- **Never from the panel.** The panel can't send the key (`params` is validated with `additionalProperties: false`), and it must not try. Invoke the runtime directly.

1. Set the flag: add `{"name": "ALLOW_PROBE", "value": "1"}` to `envVars` in `agents/bug-fix/agentcore/agentcore.json`, then preview and deploy as in "Deploy or redeploy". While the flag is in the file, `test_agentcore_config.py`'s never-committed test is a strict xfail.
2. Invoke directly, with a fresh run id and a session id of at least 33 characters:

   ```bash
   aws bedrock-agentcore invoke-agent-runtime --region us-east-1 --cli-read-timeout 900 \
     --agent-runtime-arn arn:aws:bedrock-agentcore:us-east-1:755641879575:runtime/bugfix_bug_fix-BiuPsdGSPK \
     --runtime-session-id "s182-probe-$(date -u +%Y%m%dT%H%M%S)-$(openssl rand -hex 8)" \
     --payload "$(printf '{"run_id":"%s","repository_org":"llipe","repository_name":"bug-fix-smoke","base_branch":"main","params":{},"__probe":true}' "$(uuidgen | tr A-Z a-z)" | base64)" \
     out.json
   ```

3. Read `out.json`. It holds the terminal JSON with `probe.checks` (one `{check, verdict, detail}` per check), `probe.passed` and `probe.failed`. Before you keep it as evidence, scan it for secret-shaped strings (`sk-ant-`, `ghp_`, `ghs_`, `github_pat_`). Details are scrubbed, but check anyway.
4. Record each check in `workstream/spike-bug-fix-sandbox.md` §5.
5. Unset the flag and redeploy (task 3.10). The strict xfail turns back into a normal test.

Reading the result:
- `setpriv.*` failing means the drop itself is broken.
- `userns.available` failing means AgentCore blocks the namespaces `bwrap`/`srt` need. D-110 then reopens the fallback (a separate CLI runtime).
- `net.localhost` runs first. Its detail is `via=… addrs=[…] hosts=[…] nsswitch='…'`:
  - `via` is the route the wrapper's preflight found: `hosts` (`/etc/hosts` maps `localhost` to loopback), `nss` (nss-myhostname, the expected value on AgentCore) or `none` (the preflight refused the run; the detail then quotes the `SandboxUnavailable` reasons).
  - `addrs` is `getaddrinfo("localhost")` inside the sandbox, in order. PASS needs every address to be loopback **and** `127.0.0.1` first.
  - `nsswitch` is the sandbox's `hosts:` line; expect `'files myhostname dns'`.
  - If `net.localhost` fails, every `net.*`, `cli.*` and sandboxed check fails with it: fix this one first. `via=none` with a changed `nsswitch` line means the runtime replaced the image's `/etc/nsswitch.conf`. `::1` first means `/etc/gai.conf` is missing.
- Each check carries its own reason in `detail`.

### Set or rotate the Anthropic key (`agent-fleet/prod/ANTHROPIC_API_KEY`)

1. At console.anthropic.com, create a **dedicated** key with a **spend limit** (currently $30 USD/month).
2. Put it in from your own terminal, never through an agent session: `aws secretsmanager put-secret-value --region us-east-1 --secret-id agent-fleet/prod/ANTHROPIC_API_KEY --secret-string "$(pbpaste)"`, then clear the clipboard. Store it as a **plaintext** SecretString, not JSON.
3. Revoke the old key in the Anthropic console.

### Set or rotate the Projects token (`agent-fleet/prod/GITHUB_PROJECTS_TOKEN`)

1. On GitHub, create a **classic** PAT with **only the `project` scope**. The current token has no expiry, so rotation is manual.
2. Put it in the same way as the key (plaintext).
3. Revoke the old PAT. Board updates are best effort, so a missing or invalid token never fails a run (D-99).

### GitHub App permissions

The fleet App (`4687256`, installation `156226839`) needs **Issues: read and write**, plus contents and pull requests write. After any App permission change, accept it on every installation.

## Verification

- **Runtime:** `aws bedrock-agentcore-control get-agent-runtime --region us-east-1 --agent-runtime-id bugfix_bug_fix-BiuPsdGSPK` shows `READY`, and `roleArn` = `agent-fleet-bug-fix-runtime`.
- **Permissions:** `aws iam simulate-principal-policy --policy-source-arn arn:aws:iam::755641879575:role/agent-fleet-bug-fix-runtime --action-names secretsmanager:GetSecretValue bedrock:InvokeModel --resource-arns <the 4 secret ARNs> <a Sonnet foundation-model ARN>` shows the four secrets `allowed` and Bedrock `implicitDeny`. The reference evidence is `infra/changes/20261023-bug-fix-runtime/backup/simulation-8a.json`.
- **Panel invoke:** simulating `bedrock-agentcore:InvokeAgentRuntime` for role `panel-agentcore-invoke` on the bug-fix runtime ARN is `allowed`, and still `allowed` for both sibling runtimes.
- **Smoke invoke:** `aws bedrock-agentcore invoke-agent-runtime --region us-east-1 --agent-runtime-arn arn:aws:bedrock-agentcore:us-east-1:755641879575:runtime/bugfix_bug_fix-BiuPsdGSPK --runtime-session-id <≥33 chars> --payload "$(printf '{"run_id":"<uuid>","repository_org":"llipe","repository_name":"bug-fix-smoke","base_branch":"main","params":{"issue_number":<N>}}' | base64)" out.json` returns HTTP 200. A direct invoke has no `runs` row (the panel inserts it), so the reporter warns that `start()` found 0 rows and the run is not visible in the panel; prefer the panel's manual invoke below for evidence.
- **Wave A run (S-190; Wave A S-180–S-190 delivered, verified live on runtime v7).** Fixture: `llipe/bug-fix-smoke` (private, App installed), issue #1. Verified live with run `a76a6c8c` on 2026-10-25. From the panel, `/agents/bug-fix/invoke`, on the fixture repo with the `issue_number` of an open issue that has no linked PR and no other active bug-fix run. The fixture repo must pass the repo gate: `.claude/agents/developer.md`, the four gates, and a lockfile (JS) or a `make install` target (Python), and its install must succeed in the sandbox. Expected:
  - the run's steps are `preflight`, `refuse`, `checkout`, `claim`, each with events, and no `fix` step. The first `checkout` event is `link protection: fs.protected_hardlinks=1 fs.protected_symlinks=1` (`warn` if either is not 1; evidence for #446, never a failure);
  - the panel's call can return before the run ends. If its stream closes mid-run, the run keeps going and still ends as below; it adds one `warn` event, "the invoke stream closed mid-run (…); the run finished the steps and reports its own outcome". A `failed` run whose `error_code` is `GeneratorExit` or `CancelledError` means an image older than the S-190 fix round;
  - the runtime's logs show `SIGTERM backstop installed at app start, chaining to Server.handle_exit` once at startup. A run `error` event "the SIGTERM backstop is not installed: …", or a log ERROR `SIGTERM backstop not installed`, means a SIGTERM would leave the run `running` until the reaper: don't use that image;
  - while the run is going, even after the panel's stream has closed, the session is busy (the SDK's `/ping` says `HealthyBusy`; the logs show `Async task started: bug-fix-run`, then `Async task completed` at the end), so the 900 s idle timeout can't reclaim it mid-run;
  - if the platform stops the session mid-run (SIGTERM), the run ends `failed` / `SIGNAL_TERMINATION` within about 10 s, and after its claim was confirmed the issue also gets the diagnosis. A run left `running` until the reaper after a stop means an image older than S-190 fix round 2;
  - a run that passes its own deadline (`max_runtime_seconds` − `grace_seconds`, 3480 s) ends `failed` / `RUNTIME_TIMEOUT` from the agent, before the reaper's own `timed_out`;
  - the issue gets exactly two new comments: the claim (`<!-- agent-fleet:bug-fix:claim run_id=<uuid> -->`, then "🔧 Bug-fix run <panel link> is working on this issue.") and the diagnosis (`<!-- agent-fleet:bug-fix:disposition run_id=<uuid> -->`, "Why it stopped: fix loop not yet enabled");
  - **no reaction**, because a manual invoke has no `trigger_comment_id`; no label, assignee or board change;
  - the run ends `succeeded` / `needs_review`, `result = {"summary": "fix loop not yet enabled", "reason": "fix_loop_disabled"}`, and `runs.metrics` has `issue_number` and `step_timings_ms` for the four steps.
  - If it ends `not_applicable` / `repo_gate`, the fixture repo is missing the item the reply names. `failed` / `INSTALL_FAILED` means its install failed in the sandbox. `failed` / `INVALID_PAYLOAD` in `preflight`, with no comment on the issue, means the payload's `run_id` is not a UUID or a repository field is missing or has the wrong type; the summary names which. A `failed` run never has an `outcome`.
- **App token:** minting an installation token shows `permissions.issues == "write"` (see `result.md`, step 10b). Print only the permissions, never the token.

## Rollback

`infra/changes/20261023-bug-fix-runtime/rollback.sh --from N` reverts steps N…1 in reverse order:
- 9: panel policy;
- 8: KMS scope;
- 7: stack;
- 5b and 5: role;
- 3 and 1: secrets.

Revoke the Anthropic key and the PAT at their providers as well. The panel policy rollback restores the four sibling resources exactly.

## Escalation

The operator (@llipe). AWS or Anthropic billing surprises: check the Anthropic key's spend limit and `runs.metrics` cost fields. The trace destination was set to CloudWatch Logs by the AgentCore CLI (X-Ray transaction search, account-wide).
