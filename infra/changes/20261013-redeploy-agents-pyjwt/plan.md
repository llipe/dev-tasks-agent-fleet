# Change plan — 20261013-redeploy-agents-pyjwt

- **ChangeId:** `infra/changes/20261013-redeploy-agents-pyjwt/`
- **Issue:** #252 (tasks 1.16 / 1.17, AC6; decision D-10)
- **Environment:** `prod` (`production: true`)
- **Resolved identity:** Supabase `hegxeycmbmjfgzqpdiik`; Fly org `personal` (`dt-agent-fleet-panel`); AWS account `755641879575`, `us-east-1`, IAM user (from `aws sts get-caller-identity`, 2026-10-13); AgentCore CLI 0.28.0; target `default`
- **Source ref to deploy:** `main` @ `85c8503` (contains #257: PyJWT 2.15.1, semgrep 1.180.0)
- **Revert ref:** `main` @ `feae3f8` (pre-#257; PyJWT 2.13.0, semgrep 1.177.0)
- **Cost summary:** no new resources. Each deploy runs one container build plus an ECR push (new image layers, ~1 GB storage per agent) and an AgentCore runtime version update. Incremental cost is ECR storage (~$0.10/GB-month, https://aws.amazon.com/ecr/pricing/) plus the verification invocations' model/compute usage. Below threshold; listed for awareness.
- **Approval status:** plan APPROVED by @llipe 2026-10-13T14:49-03:00; each step still requires its own approval. Steps 1–5 approved and applied 2026-10-13 (see result.md)

## Preconditions

- Docker Desktop running (CDK builds the Container asset locally): ✅ 29.7.2 aarch64 (re-checked before Step 1)
- `agents/*/agentcore/aws-targets.json` present (copied from the operator's original checkout; gitignored).

## Backup (pre-change state, recorded as the restore point)

| Agent | Runtime version | Container image tag (ECR, verified present) | deployHash |
| --- | --- | --- | --- |
| dependency-update | 7 (READY, 2026-09-06) | `dependencyupdate/dependency_update:0cc70f3b18f7…2e00f` | `6a1aa34b2792b9bb` |
| security-analyst | 9 (READY, 2026-09-17) | `securityanalyst/security_analyst:760f3a2cc31e…296a4` | `cc10c0dbc802b839` |

## Steps

### Step 1 — Redeploy dependency-update
- **Kind:** build image + deploy app · **Tool:** agentcore (CDK) · **Touches state:** yes (runtime version 7 → 8)
- **Backup:** runtime v7 / image `0cc70f3b…` (above), confirmed present in ECR
- **Forward:** `cd agents/dependency-update && agentcore deploy -y`
- **Verify:** `agentcore status` → READY; `get-agent-runtime` shows a new version and image; the built image resolves `PyJWT==2.15.1` (from the build log / `pip show` in the image)
- **Revert:** `git worktree add /tmp/revert-feae3f8 feae3f8 && cp agents/dependency-update/agentcore/aws-targets.json /tmp/revert-feae3f8/agents/dependency-update/agentcore/ && cd /tmp/revert-feae3f8/agents/dependency-update && agentcore deploy -y`

### Step 2 — Verify dependency-update live (AC6)
- **Kind:** verification invocation · **Tool:** panel invoke (or `agentcore invoke`) · **Touches state:** writes one `runs` row (normal operation)
- **Forward:** invoke `dependency-update` on `llipe/memo-cli` (S-141 precedent target)
- **Verify:** the run passes GitHub App auth (no `CredentialError`) and reaches a terminal status; record the run id
- **Revert:** none needed (read-mostly; a dependency-update PR, if one is opened, can be closed). On auth failure, run Step 1's revert.

### Step 3 — Redeploy security-analyst
- **Kind:** build image + deploy app · **Tool:** agentcore (CDK) · **Touches state:** yes (runtime version 9 → 10)
- **Backup:** runtime v9 / image `760f3a2c…`, confirmed present in ECR
- **Forward:** `cd agents/security-analyst && agentcore deploy -y`
- **Verify:** READY; new version and image; the image resolves `PyJWT==2.15.1` and `semgrep==1.180.0`
- **Revert:** same as Step 1's, for `agents/security-analyst`

### Step 4 — Verify security-analyst live (AC6 + R-03)
- **Kind:** verification invocation · **Touches state:** writes one `runs` row
- **Forward:** invoke `security-analyst` with `mode=audit_only` on `llipe/security-analyst-fixture` (produces findings, which exercises semgrep 1.180.0's output parsing)
- **Verify:** GitHub App auth OK; terminal status; an `audit_report` artifact with semgrep findings present; record the run id
- **Revert:** none needed (audit_only opens no PR). On failure, run Step 3's revert.

### Step 5 — Record and close
- **Kind:** repo and PR operation · **Tool:** gh · **Touches state:** no
- **Forward:** write `result.md` / `rollback.sh`; post hashes and run ids on #252; update the runbook; open a draft PR with this change record; tick #252 tasks 1.16/1.17 and close #252
- **Revert:** n/a (records only)
