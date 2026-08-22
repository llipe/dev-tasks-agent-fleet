# Runbook: GitHub App Credential for the dep-updater Agent

How to move the `dep-updater` agent from a Personal Access Token to a GitHub App, and how to roll back.

**Why a GitHub App instead of a PAT**

- Tokens are installation-scoped and expire after one hour, so a leaked token has a bounded blast radius.
- Permissions are declared once on the App and apply to every installed repository, instead of a PAT's account-wide grant.
- Commits and PRs are attributed to a bot identity rather than to a human account.
- Repository access is granted and revoked per repository from the installation page, with no token rotation.

## 0. Read this first — cutover ordering

`agents/dep-updater/agentcore/agentcore.json` already declares:

```json
"envVars": [{ "name": "GITHUB_SECRET_ID", "value": "dep-agent/github-app" }]
```

**That secret does not exist until step 4 of this runbook.** Deploying before the secret exists makes every run fail at `get_github_token()` with `ResourceNotFoundException`.

The code default in `agents/dep-updater/main.py` deliberately stays `dep-agent/github-pat`:

```python
SECRET_ID = os.environ.get("GITHUB_SECRET_ID", "dep-agent/github-pat")
```

So a local run or a CLI invocation that does not set the env var still works against the existing PAT, and rollback is a single config flip.

Required order:

1. Create the App (§1)
2. Install it on the target repositories (§2)
3. Generate a private key (§3)
4. Create the `dep-agent/github-app` secret (§4)
5. Set the committer identity (§5)
6. Deploy (§6)
7. Verify (§7)

Do not reorder. Steps 1–5 make no change to the deployed agent; step 6 is the cutover.

## 1. Create the GitHub App

GitHub → Settings → Developer settings → GitHub Apps → **New GitHub App**.

| Field                    | Value                                                       |
| ------------------------ | ----------------------------------------------------------- |
| GitHub App name          | `dep-updater` (or `<org>-dep-updater` if the name is taken)  |
| Homepage URL             | The repository URL — unused, but required                    |
| Webhook                  | **Uncheck Active.** The agent polls; it receives no webhooks |
| Where can it be installed | Only on this account                                        |

### Repository permissions

Grant the minimum the pipeline needs, nothing more:

| Permission        | Access         | Why                                                    |
| ----------------- | -------------- | ------------------------------------------------------ |
| Contents          | Read and write | Clone the repo, push the update branch                 |
| Pull requests     | Read and write | Open the dependency-update PR                          |
| Metadata          | Read-only      | Mandatory, granted automatically                        |

Leave every other permission at **No access**. In particular the agent needs no Actions, Administration, Checks, Secrets or Workflows access — a `workflows` grant would let it rewrite CI definitions.

Record the **App ID** shown on the App's settings page after creation. It is not a secret, but it is needed in step 4.

## 2. Install the App

On the App's page → **Install App** → choose the account → **Only select repositories** → pick the repositories the fleet manages (e.g. `llipe/memo-cli`).

After installing, the browser URL ends in the installation ID:

```
https://github.com/settings/installations/<installation-id>
```

Or query it:

```bash
# Requires a JWT signed with the App key; simplest is to read it off the URL above.
```

Record the **installation ID**. Installing on additional repositories later does not change it.

## 3. Generate a private key

On the App's settings page → **Private keys** → **Generate a private key**. The browser downloads a `.pem` file. This is the only copy — GitHub does not retain it.

```bash
# Work in a directory that is not inside a git checkout.
cd "$(mktemp -d)"
mv ~/Downloads/dep-updater.*.private-key.pem ./app-key.pem
chmod 600 app-key.pem
```

> **Never commit key material.** `.gitignore` already excludes `*.pem` and `*.key`, but the safe habit is to keep the file outside any repository and delete it once the secret is created.

## 4. Create the Secrets Manager secret

The agent branches on the secret's shape: a `token` key means PAT, anything else is treated as GitHub App credentials (`app_id`, `installation_id`, `private_key`).

```bash
APP_ID="<app-id-from-step-1>"
INSTALLATION_ID="<installation-id-from-step-2>"

aws secretsmanager create-secret \
  --name dep-agent/github-app \
  --description "GitHub App credentials for the dep-updater agent" \
  --secret-string "$(jq -n \
      --arg app_id "$APP_ID" \
      --arg installation_id "$INSTALLATION_ID" \
      --rawfile private_key app-key.pem \
      '{app_id: $app_id, installation_id: $installation_id, private_key: $private_key}')"
```

`jq --rawfile` preserves the PEM's newlines, which RS256 signing requires. Building the JSON by hand with `$(cat app-key.pem)` collapses them and produces an unusable key.

Verify the shape without printing the key:

```bash
aws secretsmanager get-secret-value --secret-id dep-agent/github-app \
  --query SecretString --output text | jq 'keys, (.private_key | length)'
# Expected: ["app_id","installation_id","private_key"] and a length around 1700
```

Then destroy the local copy:

```bash
rm -f app-key.pem && cd - && echo "local key removed"
```

### IAM

No IAM change is needed. The runtime execution role's grant in `agents/dep-updater/agentcore/cdk/lib/cdk-stack.ts` is scoped to `secret:dep-agent/github-*`, which covers both the PAT and the App secret during migration. Once the PAT secret is deleted, tighten `FLEET_GITHUB_SECRET_NAME_PREFIX` in `lib/fleet-iam-attributes.ts` to the single full secret name.

## 5. Set the bot committer identity

Commits pushed with an installation token are authored by the App's bot account. If the git identity does not match, GitHub attributes the commits to whichever account owns the configured email.

The bot identity is:

- name: `<app-slug>[bot]` — the slug is the App name lowercased with spaces replaced by hyphens, visible in the App's public URL
- email: `<bot-user-id>+<app-slug>[bot]@users.noreply.github.com`

Get the bot user ID:

```bash
APP_SLUG="dep-updater"
curl -s "https://api.github.com/users/${APP_SLUG}%5Bbot%5D" | jq '.id, .login'
```

Add both to the runtime entry in `agents/dep-updater/agentcore/agentcore.json`:

```json
"envVars": [
  { "name": "GITHUB_SECRET_ID", "value": "dep-agent/github-app" },
  { "name": "GIT_COMMITTER_NAME", "value": "dep-updater[bot]" },
  { "name": "GIT_COMMITTER_EMAIL", "value": "<bot-user-id>+dep-updater[bot]@users.noreply.github.com" }
]
```

`main.py`'s `resolve_committer_identity()` reads these per invocation and falls back to the PAT-era `dep-update-agent` values when unset or blank, so this step is safe to defer — it affects commit attribution only, not whether the pipeline works.

## 6. Deploy

```bash
cd agents/dep-updater
agentcore deploy --dry-run   # validate + synth, no AWS changes
agentcore deploy
```

`--dry-run` catches `envVars` schema violations (the name must match `^[A-Za-z_][A-Za-z0-9_]*$`) before touching AWS.

## 7. Verify

```bash
cd agents/dep-updater
agentcore invoke '{"session_id": "app-cutover-001", "repo": "llipe/memo-cli"}'

APP_LG=$(aws logs describe-log-groups \
  --log-group-name-prefix /aws/bedrock-agentcore/runtimes/depupdater_dep_updater \
  --query 'logGroups[0].logGroupName' --output text)

aws logs filter-log-events --log-group-name "$APP_LG" \
  --filter-pattern '{ $.session_id = "app-cutover-001" }' \
  --query 'events[*].message' --output text
```

Checks:

- [ ] No `ResourceNotFoundException` on `dep-agent/github-app` — the secret exists and the role can read it
- [ ] No `401` from `api.github.com/app/installations/.../access_tokens` — the key and App ID match
- [ ] The run proceeds past cloning, so the installation token has Contents access
- [ ] If a PR was opened, its commits show the `[bot]` identity and the "bot" badge

## 8. Rollback

The App secret and the PAT secret coexist, so rollback needs no key handling.

Fast path — revert the config and redeploy:

```bash
# In agents/dep-updater/agentcore/agentcore.json, set:
#   { "name": "GITHUB_SECRET_ID", "value": "dep-agent/github-pat" }
# and remove the two GIT_COMMITTER_* entries.
cd agents/dep-updater && agentcore deploy
```

Because the IAM grant spans `secret:dep-agent/github-*`, the runtime can read either secret and no IAM change is needed in either direction.

If the App's key is suspected compromised: delete the key on the App's settings page first (this invalidates every outstanding installation token within the hour), then roll back, then generate a new key and repeat §3–§4.

## 9. Post-cutover cleanup

Only after several successful runs on the App credential:

1. Delete the PAT secret: `aws secretsmanager delete-secret --secret-id dep-agent/github-pat --recovery-window-in-days 30`
2. Revoke the PAT itself in GitHub → Settings → Developer settings → Personal access tokens
3. Tighten `FLEET_GITHUB_SECRET_NAME_PREFIX` in `agents/dep-updater/agentcore/cdk/lib/fleet-iam-attributes.ts` to `dep-agent/github-app` so the grant resolves to exactly one ARN, then redeploy
4. Update the `main.py` default from `dep-agent/github-pat` to `dep-agent/github-app`

Steps 3 and 4 are code changes and belong in a PR, not an ad-hoc edit.
