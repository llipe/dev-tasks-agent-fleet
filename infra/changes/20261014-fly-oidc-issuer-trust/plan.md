# Change plan — 20261014-fly-oidc-issuer-trust

- **ChangeId:** `infra/changes/20261014-fly-oidc-issuer-trust/`
- **Issue:** #280 (AC4: a deployed-panel invoke reaches `running`)
- **Environment:** `prod` (`production: true`)
- **Resolved identity:** AWS account `755641879575` (IAM is global); Fly org slug `felipe-mallea` (alias `personal`), app `dt-agent-fleet-panel`
- **Cost:** none (IAM OIDC providers, role trust policies, and inline policies are free)
- **Approval status:** plan APPROVED by @llipe 2026-10-14T15:27-03:00; each step requires its own approval. Steps 1, 2, 3, 3b, 4, 5 approved and applied 2026-10-14 (see result.md); 3b was added after step 4's first attempt surfaced the endpoint-ARN requirement

## Discovery (read-only, 2026-10-14)

After `panel-v1.1.1` (Fly v14), uid 1001 now obtains the OIDC token (the D-03 grant and the D-07 raw-JWT parse both work). `AssumeRoleWithWebIdentity` then fails: run `f64324f6-94d4-4a8e-b2da-b6b70f2f8265`, `CREDENTIALS_UNAVAILABLE`.

The token's decoded claims (payload only; signature and token never printed):

| Claim | Token issued today | What IAM trusts |
| --- | --- | --- |
| `iss` | `https://oidc.fly.io/felipe-mallea` | provider `oidc.fly.io/personal` (the only Fly provider in the account) |
| `aud` | `sts.amazonaws.com` | `oidc.fly.io/personal:aud = sts.amazonaws.com` |
| `sub` | `felipe-mallea:dt-agent-fleet-panel:frosty-fog-8830` | `oidc.fly.io/personal:sub LIKE personal:dt-agent-fleet-panel:*` |

STS has no IAM OIDC provider for the issuer `oidc.fly.io/felipe-mallea`, so it rejects the token, and the `sub` pattern would not match either. Fly now issues tokens under the org **slug** instead of the `personal` alias. This is the third Fly-side change behind #280, after the socket mode (D-01/D-02) and the response shape (D-07). The issuer's discovery document is live: `https://oidc.fly.io/felipe-mallea/.well-known/openid-configuration` → `issuer=https://oidc.fly.io/felipe-mallea`.

**Second finding (same role):** the `invoke-runtime` inline policy allows `bedrock-agentcore:InvokeAgentRuntime` only on the `dependency-update` runtime. Once STS works, a `security-analyst` invoke from the deployed panel would still fail with `AccessDenied` (`INVOCATION_FAILED`).

## Backup

- `backup/trust-policy.before.json`: the role `panel-agentcore-invoke` trust policy, captured before any change
- `backup/runtime-invoke-policy.before.json`: the role's `invoke-runtime` inline policy, captured before any change

## Steps

### Step 1 — Create the IAM OIDC provider for the new Fly issuer
- **Kind:** create IAM identity provider · **Tool:** aws · **Touches state:** yes (new resource, additive)
- **Forward:** `aws iam create-open-id-connect-provider --url https://oidc.fly.io/felipe-mallea --client-id-list sts.amazonaws.com --tags Key=environment,Value=prod Key=owner,Value=llipe Key=ChangeId,Value=20261014-fly-oidc-issuer-trust` (no thumbprint: IAM obtains and validates it for HTTPS issuers)
- **Verify:** `aws iam get-open-id-connect-provider --open-id-connect-provider-arn arn:aws:iam::755641879575:oidc-provider/oidc.fly.io/felipe-mallea` → url, client `sts.amazonaws.com`
- **Revert:** `aws iam delete-open-id-connect-provider --open-id-connect-provider-arn arn:aws:iam::755641879575:oidc-provider/oidc.fly.io/felipe-mallea`

### Step 2 — Point the role's trust policy at the new issuer
- **Kind:** IAM trust-policy update · **Tool:** aws · **Touches state:** yes
- **Forward:** `aws iam update-assume-role-policy --role-name panel-agentcore-invoke --policy-document file://infra/trust-policy.json`. The repo file is updated to a single statement: Federated `…:oidc-provider/oidc.fly.io/felipe-mallea`; `StringEquals oidc.fly.io/felipe-mallea:aud = sts.amazonaws.com`; `StringLike oidc.fly.io/felipe-mallea:sub = felipe-mallea:dt-agent-fleet-panel:*`. The dead `personal` statement is **replaced, not kept**, so no unused trust path remains.
- **Verify:** `aws iam get-role --role-name panel-agentcore-invoke --query Role.AssumeRolePolicyDocument` matches the file
- **Revert:** `aws iam update-assume-role-policy --role-name panel-agentcore-invoke --policy-document file://infra/changes/20261014-fly-oidc-issuer-trust/backup/trust-policy.before.json`

### Step 3 — Allow the panel to invoke security-analyst (optional; separate approval)
- **Kind:** IAM inline-policy update · **Tool:** aws · **Touches state:** yes
- **Forward:** `aws iam put-role-policy --role-name panel-agentcore-invoke --policy-name invoke-runtime --policy-document file://infra/agentcore-invoke-policy.json`, where `Resource` lists exactly the two runtime ARNs (dependency-update, security-analyst). Still action-scoped to `InvokeAgentRuntime`, with no wildcard.
- **Verify:** `aws iam get-role-policy --role-name panel-agentcore-invoke --policy-name invoke-runtime` matches the file
- **Revert:** `aws iam put-role-policy … --policy-document file://infra/changes/20261014-fly-oidc-issuer-trust/backup/runtime-invoke-policy.before.json`

### Step 4 — Verify live (AC4)
- **Kind:** verification invocation · **Touches state:** one normal `runs` row
- **Forward:** the operator invokes `dependency-update` from https://dt-agent-fleet-panel.fly.dev (and `security-analyst` `audit_only`, if Step 3 was applied)
- **Verify:** the run reaches `running` with `credential_source: fly-oidc` and no `CREDENTIALS_UNAVAILABLE`
- **Revert:** none (on failure, revert Steps 2→1)

### Step 5 — Record and close
- **Forward:** commit `infra/trust-policy.json`, `infra/agentcore-invoke-policy.json` (new in the repo; named to avoid the `invoke-*.json` payload ignore pattern), and this change record; update the runbook (`panel-deployment.md`: the issuer is the org slug, with a socket/claims probe recipe); append D-08 to `workstream/decisions-panel-fly-oidc.md`; open a draft PR; close #280
- **Revert:** n/a
