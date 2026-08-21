# Deployment Runbook — Control Plane

This runbook documents the full deployment lifecycle for the Agent Fleet Control Plane on Fly.io, including Cloudflare Access and Tunnel configuration.

---

## Table of Contents

1. [Prerequisites](#prerequisites)
2. [Fly.io App Setup](#flyio-app-setup)
3. [Secrets Management](#secrets-management)
4. [Fly OIDC → AWS IAM Role](#fly-oidc--aws-iam-role)
5. [Cloudflare Access Application](#cloudflare-access-application)
6. [Cloudflare Tunnel Configuration](#cloudflare-tunnel-configuration)
7. [Deploy](#deploy)
8. [Rollback](#rollback)
9. [Health Check Verification](#health-check-verification)
10. [Origin Lockdown Verification](#origin-lockdown-verification)
11. [HTTPS and HSTS Verification](#https-and-hsts-verification)
12. [Monthly Cost Estimate](#monthly-cost-estimate)
13. [Troubleshooting](#troubleshooting)

---

## Prerequisites

- Fly CLI (`flyctl`) installed and authenticated
- Cloudflare account with Zero Trust enabled
- AWS IAM access for trust policy changes
- `FLY_API_TOKEN` configured in GitHub repository secrets

---

## Fly.io App Setup

Create the Fly app (one-time):

```bash
flyctl apps create agent-fleet-control-plane --org <your-org>
```

The app configuration lives in `infra/control-plane.fly.toml`:

- Region: `iad` (US East)
- Single machine with auto-stop/auto-start
- Internal port: 3000
- Health check: `/healthz` every 30s

---

## Secrets Management

All secrets are managed via `fly secrets`. **No secrets in the image, repo, or build output.**

Required secrets:

```bash
# Cloudflare Access validation
fly secrets set CF_ACCESS_TEAM_NAME="<your-team-name>" --app agent-fleet-control-plane
fly secrets set CF_ACCESS_AUD="<your-access-audience-tag>" --app agent-fleet-control-plane

# AWS region for SDK clients
fly secrets set AWS_REGION="us-east-1" --app agent-fleet-control-plane

# AWS credentials (only if OIDC fallback is needed — see below)
# fly secrets set AWS_ACCESS_KEY_ID="<key>" --app agent-fleet-control-plane
# fly secrets set AWS_SECRET_ACCESS_KEY="<secret>" --app agent-fleet-control-plane
```

List current secrets:

```bash
fly secrets list --app agent-fleet-control-plane
```

Verify no secrets leak into the image:

```bash
# After deploy, inspect the image layers
flyctl ssh console --app agent-fleet-control-plane -C "env" | grep -v FLY_
# Should show only CF_ACCESS_TEAM_NAME, CF_ACCESS_AUD, AWS_REGION, and optionally AWS_* keys
# No other sensitive values should appear
```

---

## Fly OIDC → AWS IAM Role

### Primary: OIDC Token (Recommended)

Fly Machines expose an OIDC token at `FLY_OIDC_TOKEN_PATH`. The credentials module (`src/server/aws/credentials.ts`) uses `fromWebToken` with this path.

**IAM Trust Policy:**

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Principal": {
        "Federated": "arn:aws:iam::<ACCOUNT_ID>:oidc-provider/oidc.fly.io/<ORG_SLUG>"
      },
      "Action": "sts:AssumeRoleWithWebIdentity",
      "Condition": {
        "StringEquals": {
          "oidc.fly.io/<ORG_SLUG>:aud": "urn:fly:machine:<APP_NAME>",
          "oidc.fly.io/<ORG_SLUG>:sub": "app:<APP_NAME>"
        }
      }
    }
  ]
}
```

**Steps to configure:**

1. Register the Fly OIDC provider in IAM:

   ```bash
   aws iam create-open-id-connect-provider \
     --url "https://oidc.fly.io/<ORG_SLUG>" \
     --client-id-list "urn:fly:machine:agent-fleet-control-plane" \
     --thumbprint-list "<fly-oidc-thumbprint>"
   ```

2. Attach the trust policy above to the `control-plane-role` IAM role.

3. Set the role ARN as a Fly secret:
   ```bash
   fly secrets set AWS_ROLE_ARN="arn:aws:iam::<ACCOUNT_ID>:role/control-plane-role" \
     --app agent-fleet-control-plane
   ```

### Fallback: Static Credentials

If Fly OIDC proves unworkable (provider not recognized, token format incompatible, etc.):

1. Create an IAM user with the `control-plane-role` permissions attached directly.
2. Generate access keys.
3. Set them as Fly secrets:
   ```bash
   fly secrets set AWS_ACCESS_KEY_ID="<key>" --app agent-fleet-control-plane
   fly secrets set AWS_SECRET_ACCESS_KEY="<secret>" --app agent-fleet-control-plane
   ```

The credentials module (`src/server/aws/credentials.ts`) automatically falls back to `fromEnv()` when OIDC is unavailable.

**Note:** Static keys should be rotated every 90 days maximum. Set a calendar reminder.

---

## Cloudflare Access Application

### Configuration Steps

1. Navigate to Cloudflare Zero Trust Dashboard → Access → Applications.

2. Add a **Self-hosted** application:
   - **Application name:** Agent Fleet Control Plane
   - **Session duration:** 24h
   - **Application domain:** `controlplane.yourdomain.com`

3. Create an Access Policy:
   - **Policy name:** Authorized Operators
   - **Action:** Allow
   - **Include rules:** Email addresses or identity provider groups authorized for access

4. Note the **Application Audience (AUD) Tag** — this is `CF_ACCESS_AUD`.

5. The **Team Name** is your Zero Trust organization name — this is `CF_ACCESS_TEAM_NAME`.

6. Set both as Fly secrets (see [Secrets Management](#secrets-management)).

### How It Works

- Cloudflare Access fronts the application domain.
- Users authenticate via the configured identity provider.
- Authenticated requests receive a signed JWT in the `Cf-Access-Jwt-Assertion` header.
- The Next.js middleware validates this JWT using Cloudflare's public signing keys (JWKS endpoint).
- Requests without a valid JWT are rejected with 401.

---

## Cloudflare Tunnel Configuration

### Overview

A Cloudflare Tunnel provides a secure, outbound-only connection from Cloudflare's edge to the Fly.io origin. Direct access to `agent-fleet-control-plane.fly.dev` is refused because:

1. The middleware requires a valid `Cf-Access-Jwt-Assertion` header.
2. Direct requests to `.fly.dev` bypass Cloudflare and lack this header.
3. The middleware returns 401 for any request without a valid CF Access JWT.

### Setup Steps

1. Create a Cloudflare Tunnel:

   ```bash
   cloudflared tunnel create agent-fleet-cp
   ```

2. Configure the tunnel in the Cloudflare dashboard or via `config.yml`:

   ```yaml
   tunnel: <TUNNEL_ID>
   credentials-file: /root/.cloudflared/<TUNNEL_ID>.json

   ingress:
     - hostname: controlplane.yourdomain.com
       service: https://agent-fleet-control-plane.fly.dev
       originRequest:
         noTLSVerify: false
     - service: http_status:404
   ```

3. Route DNS: In Cloudflare DNS, create a CNAME:
   - **Name:** `controlplane`
   - **Target:** `<TUNNEL_ID>.cfargotunnel.com`
   - **Proxy status:** Proxied (orange cloud)

4. Run the tunnel (or configure it as a Cloudflare-managed tunnel in the dashboard):
   ```bash
   cloudflared tunnel run agent-fleet-cp
   ```

### Alternative: Cloudflare-Managed Tunnel (Recommended)

Using the Zero Trust dashboard:

1. Go to Networks → Tunnels → Create a tunnel.
2. Name: `agent-fleet-control-plane`.
3. Install the connector (or use dashboard-managed).
4. Add public hostname: `controlplane.yourdomain.com` → `https://agent-fleet-control-plane.fly.dev`.
5. The tunnel handles TLS termination and routes through Cloudflare's network.

---

## Deploy

### From CI (Automatic)

Deploys automatically when code is pushed to `main` and the `validate` job passes:

```yaml
# .github/workflows/control-plane.yml — deploy job
flyctl deploy --config infra/control-plane.fly.toml --remote-only
```

### Manual Deploy

```bash
flyctl deploy --config infra/control-plane.fly.toml --remote-only --app agent-fleet-control-plane
```

### First Deploy

```bash
# Ensure secrets are set first
fly secrets list --app agent-fleet-control-plane

# Deploy
flyctl deploy --config infra/control-plane.fly.toml --remote-only

# Verify health check
curl -s https://agent-fleet-control-plane.fly.dev/healthz
# Expected: {"status":"ok"}
```

---

## Rollback

The control plane is **stateless** — all state lives in DynamoDB and CloudWatch. Rollback is a simple image swap.

### Rollback Steps

1. List recent deployments:

   ```bash
   fly releases --app agent-fleet-control-plane
   ```

2. Identify the previous working image version from the releases list.

3. Deploy the previous image:

   ```bash
   flyctl deploy --image <previous-image-ref> --app agent-fleet-control-plane
   ```

   Or roll back to the previous release:

   ```bash
   fly releases rollback --app agent-fleet-control-plane
   ```

4. Verify health:

   ```bash
   curl -s https://agent-fleet-control-plane.fly.dev/healthz
   # Expected: {"status":"ok"}
   ```

5. Verify the app is functional (through Cloudflare Access):
   - Navigate to `https://controlplane.yourdomain.com/agents`
   - Confirm data loads correctly

### Stateless Recovery Verification

After rollback:

- No data loss occurs (all state is in DynamoDB).
- No cache warm-up required (TTL cache rebuilds on demand).
- Sessions are re-authenticated via Cloudflare Access (no server-side session state).
- Agent runs continue unaffected (orchestrator is independent).

---

## Health Check Verification

The `/healthz` endpoint is excluded from authentication and returns 200 with `{"status":"ok"}`.

```bash
# Direct health check (always accessible, even without CF Access)
curl -s https://agent-fleet-control-plane.fly.dev/healthz
# Expected: {"status":"ok"}

# Fly dashboard also shows health status via the configured check
fly status --app agent-fleet-control-plane
```

---

## Origin Lockdown Verification

### Verification Steps

Direct `.fly.dev` access must be refused for all authenticated routes:

```bash
# 1. Health check — should succeed (no auth required)
curl -s -o /dev/null -w "%{http_code}" https://agent-fleet-control-plane.fly.dev/healthz
# Expected: 200

# 2. Data route without CF Access header — should be refused
curl -s -o /dev/null -w "%{http_code}" https://agent-fleet-control-plane.fly.dev/agents
# Expected: 401

# 3. Data route with invalid CF Access header — should be refused
curl -s -o /dev/null -w "%{http_code}" \
  -H "Cf-Access-Jwt-Assertion: invalid-token" \
  https://agent-fleet-control-plane.fly.dev/agents
# Expected: 401

# 4. Access through Cloudflare Tunnel (with valid session) — should succeed
# Navigate to https://controlplane.yourdomain.com/agents in browser after authenticating
# Expected: 200 with agents list
```

### Evidence Recording

Document the results of the above commands after first deployment:

```
Date: YYYY-MM-DD
Direct /healthz: 200 OK ✓
Direct /agents (no header): 401 ✓
Direct /agents (invalid header): 401 ✓
Tunnel /agents (authenticated): 200 ✓
Conclusion: Origin lockdown verified — direct access refused for all protected routes.
```

---

## HTTPS and HSTS Verification

### HTTPS Enforcement

`force_https = true` in `fly.toml` ensures all HTTP requests are redirected to HTTPS:

```bash
# HTTP request should redirect to HTTPS
curl -s -o /dev/null -w "%{http_code}" http://agent-fleet-control-plane.fly.dev/healthz
# Expected: 301 (redirect to HTTPS)
```

### HSTS Header

The `Strict-Transport-Security` header is set in `next.config.ts`:

```bash
curl -s -I https://agent-fleet-control-plane.fly.dev/healthz | grep -i strict
# Expected: strict-transport-security: max-age=63072000; includeSubDomains; preload
```

---

## Monthly Cost Estimate

### Fly.io Pricing (as of 2024)

| Resource               | Configuration            | Estimated Monthly Cost      |
| ---------------------- | ------------------------ | --------------------------- |
| Shared CPU 1x (256 MB) | auto-stop enabled        | ~$1.94 (prorated to uptime) |
| Persistent bandwidth   | Minimal (API calls only) | ~$0.00 (included)           |
| IPv4 address           | Shared                   | $2.00                       |
| **Total**              |                          | **~$3.94 – $5.00**          |

With auto-stop enabled and low traffic:

- Machine stops after idle period → charged only while running.
- Estimated active hours: ~2-4 hours/day with occasional access.
- **Well under USD 10/month budget.**

### Cloudflare

- Cloudflare Access (free tier): 50 users included → $0
- Cloudflare Tunnel: included in free/pro plans → $0

### AWS (Control Plane usage)

- DynamoDB on-demand reads: negligible for dashboard usage
- CloudWatch Logs Insights queries: ~$0.005/GB scanned

**Total estimated monthly cost: USD 4–6 (confirmed under USD 10).**

---

## Troubleshooting

### Deploy Fails

```bash
# Check build logs
fly logs --app agent-fleet-control-plane

# Check machine status
fly status --app agent-fleet-control-plane

# Force a fresh deploy
flyctl deploy --config infra/control-plane.fly.toml --remote-only --strategy immediate
```

### Health Check Failing

```bash
# SSH into the machine
fly ssh console --app agent-fleet-control-plane

# Check if the process is running
ps aux | grep node

# Check env vars are set
echo $NODE_ENV $PORT
```

### OIDC Token Issues

```bash
# SSH and check token availability
fly ssh console --app agent-fleet-control-plane -C "cat \$FLY_OIDC_TOKEN_PATH"

# If empty or missing, fall back to static credentials
fly secrets set AWS_ACCESS_KEY_ID="<key>" AWS_SECRET_ACCESS_KEY="<secret>" --app agent-fleet-control-plane
```

### Machine Not Starting

```bash
# Check machine events
fly machines list --app agent-fleet-control-plane

# Restart explicitly
fly machines restart <machine-id> --app agent-fleet-control-plane
```
