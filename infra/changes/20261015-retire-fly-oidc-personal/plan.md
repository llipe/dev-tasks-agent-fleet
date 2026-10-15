# Change plan — 20261015-retire-fly-oidc-personal

- **ChangeId:** `infra/changes/20261015-retire-fly-oidc-personal/`
- **Environment:** `prod` · AWS account `755641879575` (IAM, global)
- **Origin:** follow-up recorded in `20261014-fly-oidc-issuer-trust` (#280, D-08) and `docs/runbooks/panel-deployment.md`
- **Cost:** none
- **Approval status:** APPROVED by @llipe 2026-10-15T18:11-03:00 ("delete the unused oidc"). Single step; plan and step approved together

## Discovery (read-only, 2026-10-15)

- Provider `arn:aws:iam::755641879575:oidc-provider/oidc.fly.io/personal` (created 2026-09-08, client `sts.amazonaws.com`, no tags).
- **No IAM role trust policy references it.** All roles were scanned with `get-role`; zero matches.
- CloudTrail `AssumeRoleWithWebIdentity` since 2026-10-08: 9 calls, all via `oidc.fly.io/felipe-mallea`, all `ok`; none via `personal`.
- Fly no longer issues tokens under the `personal` issuer (#280, D-08).

## Backup

`backup/oidc-provider-personal.before.json`: the full provider definition (URL, client IDs, thumbprint).

## Step 1 — Delete the provider

- **Kind:** delete IAM identity provider · **Touches state:** yes
- **Forward:** `aws iam delete-open-id-connect-provider --open-id-connect-provider-arn arn:aws:iam::755641879575:oidc-provider/oidc.fly.io/personal`
- **Verify:** `list-open-id-connect-providers` no longer lists it; the panel's live OIDC → STS path (`felipe-mallea`) still works
- **Revert:** `aws iam create-open-id-connect-provider --url https://oidc.fly.io/personal --client-id-list sts.amazonaws.com --thumbprint-list 3c34e356c7fc17f5acf04824bc587c6c623951a2`. Also restore any trust statement if one had existed; none did.
