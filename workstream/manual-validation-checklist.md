# Manual Validation Checklist — Agent Control Plane v1

All automated tests pass (609 tests). This document lists the manual validation steps that require deployed infrastructure or a running application.

---

## Prerequisites

Before running any manual validation:

```bash
# Ensure you're on the integration branch with all fixes
git checkout integration/acp-v1-control-plane
git pull origin integration/acp-v1-control-plane
pnpm install

# Set required env vars
export AWS_ACCOUNT_ID=<your-account-id>
export AWS_ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
export AWS_REGION=us-east-1
```

---

## Phase 1: Infrastructure Integration Tests (Already Deployed)

These use the DynamoDB table and IAM roles you already deployed.

### 1.1 DynamoDB Access Patterns (S-003)

```bash
# Requires: DynamoDB Local running on port 8000
docker run -d --rm -p 8000:8000 amazon/dynamodb-local:latest

pnpm --filter @fleet/infra run test:integration
```

**Expected:** 8 access pattern tests pass.

### 1.2 IAM Denial Tests (S-004)

```bash
export AWS_ACCOUNT_ID=<your-account-id>
pnpm --filter @fleet/infra run test:integration -- iam
```

**Expected:** 4 tests pass confirming IAM denials work against the live roles.

### 1.3 Agent DynamoDB Writes (S-011)

```bash
export AWS_ACCOUNT_ID=<your-account-id>
pnpm --filter @fleet/infra run test:integration -- agent-writes
```

**Expected:** Tests confirm agent-exec-role can write `last_status`/`last_outcome_url` but NOT `enabled`/`params`.

---

## Phase 2: Agent Deployment to AgentCore (S-006–S-011)

### 2.1 Build the Container (optional local check)

The Dockerfile lives at the **repository root** as `Dockerfile.dep-updater`, and
the build context is the repository root — the agent imports the generated shared
contract from `packages/shared/generated`. See the note in
`workstream/pending-deployments.md` for why the Dockerfile cannot be nested.

```bash
docker build --platform linux/arm64 -f Dockerfile.dep-updater -t dep-updater:local .
```

**Expected:** Build succeeds. Verify:

```bash
docker image inspect dep-updater:local --format 'Arch: {{.Architecture}}/{{.Os}}'
# Expected: arm64/linux

docker run --rm --platform linux/arm64 --entrypoint sh dep-updater:local \
  -c "python --version && node --version && pnpm --version && gh --version | head -1"
# Expected: Python 3.13.x, v26.6.0, 11.21.0, gh version 2.97.0
```

The final build stage runs an import smoke check
(`python -c "import main, logging_json, payload, emission, outcome_store"`), so
a missing module fails the build rather than the first invocation.

Note that `agentcore deploy` does **not** use this local image — it builds the
same Dockerfile in CodeBuild. This step only catches Dockerfile breakage early.

**Behind a TLS-intercepting proxy?** If the build fails with
`curl: (60) SSL certificate problem: self-signed certificate in certificate
chain`, install your proxy's root CA into `agents/dep-updater/ca/` as a `.crt`
file. `ca/*.crt` is gitignored.

Netskope on macOS:

```bash
cp "/Library/Application Support/Netskope/STAgent/data/nscacert.pem" \
   agents/dep-updater/ca/netskope-root-ca.crt
cp "/Library/Application Support/Netskope/STAgent/data/nstenantcert.pem" \
   agents/dep-updater/ca/netskope-tenant-ca.crt
```

### 2.2 Deploy to AgentCore

Deployment is owned by the AgentCore CLI, which vends its own CDK app at
`agents/dep-updater/agentcore/cdk` and creates stack
`AgentCore-depupdater-default`.

One-time: install the vended CDK app's dependencies (gitignored, npm-managed):

```bash
cd agents/dep-updater/agentcore/cdk && npm ci
```

Then preview and deploy:

```bash
cd agents/dep-updater
agentcore deploy --dry-run   # validate + synth only, no AWS changes
agentcore deploy             # real deploy
```

**Expected:** `--dry-run` ends with
`✓ Dry run complete for 'default' (stack: AgentCore-depupdater-default)`.

Confirm the discovery tags reached the runtime in the synthesized template:

```bash
python3 - <<'PY'
import glob, json
tpl = json.load(open(glob.glob(
    'agents/dep-updater/agentcore/cdk/cdk.out/AgentCore-depupdater-default.template.json')[0]))
for lid, res in tpl['Resources'].items():
    if res['Type'] == 'AWS::BedrockAgentCore::Runtime':
        print(json.dumps(res['Properties'].get('Tags'), indent=2))
PY
# Expected to include: agent:managed=true, agent:name=dep-updater, agent:domain=security
```

### 2.3 Trigger a Test Run

```bash
# Via AgentCore CLI or API
agentcore invoke dep-updater \
  --payload '{"session_id":"manual-test__myorg-myrepo__2025-01-28T00-00-00Z","repo":"myorg/myrepo","params":{}}'
```

### 2.4 Verify Non-Blocking Entrypoint (S-007)

**Check:** Run continues past 5 minutes without being killed.

```bash
# After triggering a run on a repo with a long pipeline:
aws logs filter-log-events \
  --log-group-name /aws/agentcore/dep-updater \
  --filter-pattern '{ $.session_id = "manual-test__myorg-myrepo__2025-01-28T00-00-00Z" }' \
  --limit 50 | jq '.events[-1].message' 
# Look for completion message after >5 min from start
```

### 2.5 Verify Structured JSON Logging (S-008)

```bash
aws logs filter-log-events \
  --log-group-name /aws/agentcore/dep-updater \
  --filter-pattern '{ $.session_id = "<session-id>" }' \
  --limit 5
```

**Expected:** Each line is valid JSON with `ts`, `level`, `msg`, `session_id`, `agent`, `repo` fields.

### 2.6 Verify Span Attributes (S-010)

```bash
aws logs filter-log-events \
  --log-group-name /aws/vendedlogs/agentcore/dep-updater/spans \
  --limit 5
```

**Expected:** Root span has `llipe.subject.id`, `llipe.run.status`, `llipe.outcome.type`, `llipe.outcome.url`.

### 2.7 Verify DynamoDB Outcome Stamp (S-011)

```bash
aws dynamodb get-item \
  --table-name agent-fleet-config \
  --key '{"pk":{"S":"SUBJECT#myorg/myrepo"},"sk":{"S":"AGENT#dep-updater"}}' \
  --projection-expression "last_status, last_outcome_url, enabled, params"
```

**Expected:** `last_status` and `last_outcome_url` updated; `enabled` and `params` unchanged from seed values.

---

## Phase 3: Observability Setup (S-005, S-012)

### 3.1 Enable CloudWatch Transaction Search

1. Open AWS Console → CloudWatch → Settings → Traces and Metrics
2. Under "Transaction Search", click **Edit**
3. Set indexing to **1% sampling**
4. Confirm and save

### 3.2 Set Span Log Group Retention

```bash
aws logs put-retention-policy \
  --log-group-name /aws/vendedlogs/agentcore/dep-updater/spans \
  --retention-in-days 30
```

### 3.3 Verify Discovery Tags (S-005)

```bash
aws resourcegroupstaggingapi get-resources \
  --tag-filters Key=agent:managed,Values=true \
  --query 'ResourceTagMappingList[].{ARN:ResourceARN,Tags:Tags}' \
  --output json
```

**Expected:** The dep-updater agent runtime appears with all three tags.

### 3.4 Verify Telemetry Assumptions (S-012)

After one successful run with model calls:

```bash
# Query root span with llipe.* attributes
aws logs start-query \
  --log-group-name /aws/vendedlogs/agentcore/dep-updater/spans \
  --start-time $(date -d '-24 hours' +%s) \
  --end-time $(date +%s) \
  --query-string 'fields @message | filter ispresent(resource.attributes.`llipe.run.status`) | limit 5'
```

**Verify:**
- [ ] `session.id` is present in resource attributes (or fallback `llipe.session.id`)
- [ ] `gen_ai.usage.input_tokens` and `gen_ai.usage.output_tokens` on child spans only
- [ ] `duration` field present at top level
- [ ] Root span identifiable by empty `parentSpanId` + presence of `llipe.run.status`

---

## Phase 4: Orchestrator (S-013)

### 4.1 Deploy Orchestrator Stack

```bash
cd infra
pnpm run cdk deploy AgentFleetOrchestrationStack
```

### 4.2 Manual Trigger

```bash
aws lambda invoke \
  --function-name agent-fleet-orchestrator \
  --payload '{"agent":"dep-updater","scheduledAt":"2025-01-28T10:00:00Z"}' \
  /tmp/orchestrator-output.json

cat /tmp/orchestrator-output.json
```

**Expected:** N repos invoked (matches enabled count in DynamoDB).

### 4.3 Verify Dynamic Scope (S-013, S-022)

1. Add a new repo via control plane (S-022) or directly:
   ```bash
   aws dynamodb transact-write-items --transact-items '[...]'
   ```
2. Trigger orchestrator again
3. **Expected:** New repo included without any deployment

---

## Phase 5: Control Plane Application (S-014–S-024)

### 5.1 Local Development

```bash
# Set env vars for local dev
export CF_ACCESS_TEAM_NAME=your-team
export CF_ACCESS_AUD=your-aud-tag
export AWS_REGION=us-east-1

cd apps/control-plane
pnpm run dev
```

### 5.2 Verify Health Check (S-014)

```bash
curl -s http://localhost:3000/healthz
```

**Expected:** `{"status":"ok"}` — no auth required.

### 5.3 Verify JWT Rejection (S-014)

```bash
curl -s -o /dev/null -w "%{http_code}" http://localhost:3000/agents
```

**Expected:** `401` — missing CF Access JWT.

### 5.4 Verify Agents List (S-019)

With valid credentials (or temporarily bypass auth for local testing):
- Navigate to `/agents`
- **Expected:** Table shows discovered agents with name, domain, status, repos, cost

### 5.5 Verify Agent Detail + Runs Tab (S-020)

- Navigate to `/agents/dep-updater`
- **Expected:** Runs tab shows with date, repo, status, duration, tokens, cost columns
- Apply status filter → URL updates
- Change date range → data refreshes
- Reload page → filters restored from URL

### 5.6 Verify Run Side Panel (S-021)

- Click a run row
- **Expected:** Panel slides in from right with metadata, timeline, logs
- Press Escape → panel closes
- Click backdrop → panel closes
- Browser back → panel closes

### 5.7 Verify Repos Tab (S-022)

- Navigate to `/agents/dep-updater?tab=repos`
- **Expected:** Table shows repos with enabled toggle, last run, status
- Toggle enabled → immediate optimistic update
- Open params editor → validates against schema

### 5.8 Verify Repos List (S-023)

- Navigate to `/repos`
- **Expected:** Table shows repos with agent count, last activity, status
- Click a repo → navigates to `/repos/owner/repo`
- Per-repo view shows runs across all agents with Agent column

### 5.9 Verify Keyboard Accessibility

- Tab through navigation links
- Arrow keys through DataTable rows
- Enter/Space to activate row (opens run panel)
- Escape to close panel
- Focus returns to previously-focused row

---

## Phase 6: Fly Deployment (S-024)

Follow `docs/runbook-deployment.md` for full steps. Quick summary:

### 6.1 First Deploy

```bash
flyctl apps create agent-fleet-control-plane --org <your-org>
fly secrets set CF_ACCESS_TEAM_NAME="<team>" CF_ACCESS_AUD="<aud>" AWS_REGION="us-east-1"
flyctl deploy --config infra/control-plane.fly.toml --remote-only
```

### 6.2 Verify Origin Lockdown

```bash
# Health check (should work)
curl -s -o /dev/null -w "%{http_code}" https://agent-fleet-control-plane.fly.dev/healthz
# Expected: 200

# Data route without CF JWT (should be refused)
curl -s -o /dev/null -w "%{http_code}" https://agent-fleet-control-plane.fly.dev/agents
# Expected: 401
```

### 6.3 Verify HSTS

```bash
curl -sI https://agent-fleet-control-plane.fly.dev/healthz | grep -i strict-transport
# Expected: strict-transport-security: max-age=63072000; includeSubDomains; preload
```

### 6.4 Exercise Rollback

```bash
fly releases --app agent-fleet-control-plane
fly releases rollback --app agent-fleet-control-plane
curl -s https://agent-fleet-control-plane.fly.dev/healthz
# Expected: {"status":"ok"} — stateless recovery
```

---

## Summary of Deferred Sub-tasks by Story

| Story | Sub-task | Description | Requires |
|-------|----------|-------------|----------|
| S-005 | 5.9 | Verify spans arrive at destination | Deployed agent + one run |
| S-006 | 6.8, 6.9 | Deploy and verify pipeline unchanged | AgentCore deploy |
| S-007 | 7.9 | Confirm run survives past 5 min | Deployed agent + long repo |
| S-008 | 8.9 | FilterLogEvents by session_id | Deployed agent + one run |
| S-010 | 10.9 | Confirm span attributes in CloudWatch | Deployed agent + one run |
| S-011 | 11.10 | Inspect DynamoDB item post-run | Deployed agent + one run |
| S-012 | 12.1, 12.7, 12.9 | Trigger run, verify HealthyBusy, update spec | Deployed agent |
| S-013 | 13.16, 13.17 | Manual trigger + dynamic scope verify | Deployed orchestrator |
| S-019 | 19.8 | Compare with real DynamoDB/console | Running control plane + data |
| S-020 | 20.10 | E2E filter persistence | Running app |
| S-021 | 21.11 | E2E focus/keyboard | Running app |
| S-022 | 22.15 | E2E toggle + add repo | Running app |
| S-023 | 23.9 | E2E navigate/filter from repos | Running app |
| S-024 | All | Deploy, lockdown, rollback, cost | Fly.io + Cloudflare |

---

## Recommended Execution Order

1. **Phase 1** (infrastructure integration tests) — already deployable
2. **Phase 2** (agent deploy) — enables Phases 3, 4, and data for Phase 5
3. **Phase 3** (observability) — enables telemetry verification
4. **Phase 4** (orchestrator deploy) — enables scheduled runs
5. **Phase 5** (control-plane local) — can run locally against deployed AWS
6. **Phase 6** (Fly deploy) — production deployment
