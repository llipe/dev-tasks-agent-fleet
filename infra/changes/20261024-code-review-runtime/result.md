# Result: 20261024-code-review-runtime

| Step | Status | Backup id | Restore command | Verified at | Evidence |
| ---- | ------ | --------- | --------------- | ----------- | -------- |
| 1 — AgentCore project, CDK, assertion test (repo) | verified | n/a (repo) | `git revert 676799b` | 2026-10-24 | `npx jest` in `agents/code-review/agentcore/cdk`: 15/15 pass; `tsc --noEmit` OK. Mutation check: dropping `executionRoleArn` turns 4 tests red (the construct's `foundation-model/*` grant returns). Commit `676799b`. |
| 2 — IAM role `agent-fleet-code-review-runtime` | verified | n/a (new; pre-check `GetRole` → NoSuchEntity) | `aws iam delete-role-policy --role-name agent-fleet-code-review-runtime --policy-name code-review-runtime && aws iam delete-role --role-name agent-fleet-code-review-runtime` | 2026-10-24T15:24:22Z | Created `arn:aws:iam::755641879575:role/agent-fleet-code-review-runtime`; live inline policy `code-review-runtime` and trust policy equal the committed files; 0 attached policies; 4 tags. |
| 3 — simulate the role (read-only) | verified | n/a (read-only) | n/a | 2026-10-24 | `SimulatePrincipalPolicy`: 11/11 as expected (`backup/simulation-step3.json`). Allowed: InvokeModel on the 6.1 Sol profile and us-east-2/us-west-2 models; the two secrets. Implicit deny: GPT-5.6 Sol (profile and model), Sonnet 4.6, InvokeModelWithResponseStream, `ANTHROPIC_API_KEY`, `s3:PutObject`. |
| 4 — deploy runtime `code_review` | verified | n/a (new stack; pre-check: no `codereview_*` runtime) | `aws cloudformation delete-stack --stack-name AgentCore-codereview-default`, then `aws ecr delete-repository --repository-name codereview/code_review --force` if retained | 2026-10-24T15:56:56Z | Stack `AgentCore-codereview-default`, deployHash `54745d1a15907a75`. Runtime `arn:aws:bedrock-agentcore:us-east-1:755641879575:runtime/codereview_code_review-g73KtjA3MT` READY, version 1; `roleArn` = `agent-fleet-code-review-runtime`; lifecycle 900/1800; PUBLIC; env vars = `agentcore.json`. Image `codereview/code_review@sha256:e4396fc697173f01ba838c7f140b75c8e77118b0475f34f1fd44a37b8b510841` (79 MB), built by the construct's ARM CodeBuild project (architecture not separately inspected). ECR KMS key `883d383e-570e-4bdc-bc37-43c3ed50bf9b`. |

## Notes

- Identity: AWS root, explicitly accepted by @llipe on 2026-10-24 for this change.
- Model: GPT-6.1 Sol (`us.openai.gpt-6.1-sol`), D-58, superseding D-17's GPT-5.6 Sol.
- The CDK project is not in CI (same as the siblings); its tests run locally: `npm --prefix agents/code-review/agentcore/cdk test`.

status: in_progress
