# Result: 20261023-bug-fix-runtime

| Step | Status | Backup id | Restore command | Verified at | Evidence |
| ---- | ------ | --------- | --------------- | ----------- | -------- |
| 1 — create secret `ANTHROPIC_API_KEY` | verified | n/a (new resource) | `rollback.sh --from 1` | 2026-10-23T21:54:28Z | ARN `arn:aws:secretsmanager:us-east-1:755641879575:secret:agent-fleet/prod/ANTHROPIC_API_KEY-Oo8jsf`; no versions (empty, as intended); tags environment, owner, ChangeId, agent |
| 2 — operator sets the Anthropic key value | applied (operator-confirmed) | n/a | revoke the key in the Anthropic console + `rollback.sh --from 1` | 2026-10-23 (operator) | @llipe confirmed the value is stored as a **plaintext** SecretString in `…ANTHROPIC_API_KEY-Oo8jsf`; dedicated key, **spend limit $30 USD/month**. Not probed (operator did not authorize the version check); the value was never read by the agent. |
| 3 — create secret `GITHUB_PROJECTS_TOKEN` | verified | n/a (new resource) | `rollback.sh --from 3` | 2026-10-23T23:09:41Z | ARN `arn:aws:secretsmanager:us-east-1:755641879575:secret:agent-fleet/prod/GITHUB_PROJECTS_TOKEN-XrtwPz`; no versions (empty, as intended); tags environment, owner, ChangeId, agent |
| 4 — operator sets the Projects token value | applied (operator-confirmed) | n/a | revoke the PAT on GitHub + `rollback.sh --from 3` | 2026-10-23 (operator) | @llipe confirmed a classic PAT with **`project` scope only**, stored as plaintext in `…GITHUB_PROJECTS_TOKEN-XrtwPz`; **no expiration** (operator choice; rotation is manual and is documented in the runbook; follow-up #421 adds a Settings UI). Not probed; the value was never read by the agent. |
| 5 — IAM role `agent-fleet-bug-fix-runtime` | verified | n/a (new resource) | `rollback.sh --from 5` | 2026-10-23T23:15:17Z | Role ARN `arn:aws:iam::755641879575:role/agent-fleet-bug-fix-runtime`; live inline policy `bug-fix-runtime` == `role-policy.json`; trust == `role-trust.json`; 0 `bedrock:` actions. Permission simulation in step 8. |
| 6 — `executionRoleArn` in `agentcore.json`; local `aws-targets.json` | verified | n/a (repo) | `git revert <step-6 commit>`; delete local `aws-targets.json` | 2026-10-23 | agent tests 213 passed (incl. the no-`bedrock` assertion); `aws-targets.json` is gitignored (`.gitignore:25`) |

status: in-progress (steps 1–6 of 12 done)
