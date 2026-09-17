#!/usr/bin/env bash
#
# deploy-panel.sh — deploy the panel to Fly.io and verify the auth boundary.
#
# The panel is already live and public (dt-agent-fleet-panel.fly.dev, see
# docs/runbooks/panel-deployment.md). Auth (not network privacy) is the only
# release boundary now, so every deploy through this script re-runs the auth
# release gate (scripts/verify-panel-auth.sh) against the deployed host before
# declaring success — a deploy that ships but leaves the app unguarded is a
# release failure, not a partial success.
#
# Build context: Fly resolves panel/fly.toml's [build] paths (../Dockerfile.panel,
# ../.dockerignore) relative to panel/, so this script always runs `fly deploy`
# from the REPO ROOT regardless of the caller's cwd.
#
# Usage:
#   scripts/deploy-panel.sh [--dry-run]
#
# Required env:
#   NEXT_PUBLIC_SUPABASE_URL             — for the post-deploy auth gate
#   NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY  (or legacy NEXT_PUBLIC_SUPABASE_ANON_KEY)
# Optional env:
#   SUPABASE_SERVICE_ROLE_KEY  — lets the gate auto-delete its disposable signup probe
#   FLY_APP                   — override the app name (default: dt-agent-fleet-panel)
#
# Exit codes: 0 ok · 1 error · 2 blocked (preflight/env) · 3 verify-fail (deployed, gate failed)

set -euo pipefail

DRY_RUN=false
for arg in "$@"; do
  case "$arg" in
    --dry-run) DRY_RUN=true ;;
    --help|-h)
      sed -n '2,25p' "$0"
      exit 0
      ;;
    *)
      echo "Unknown argument: $arg" >&2
      exit 2
      ;;
  esac
done

FLY_APP="${FLY_APP:-dt-agent-fleet-panel}"
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

echo "== deploy-panel: preflight =="

if ! command -v fly >/dev/null 2>&1; then
  echo "BLOCKED: flyctl not found on PATH." >&2
  exit 2
fi

if ! fly auth whoami >/dev/null 2>&1; then
  echo "BLOCKED: not authenticated with flyctl (fly auth login / FLY_API_TOKEN)." >&2
  exit 2
fi

if [[ -z "${NEXT_PUBLIC_SUPABASE_URL:-}" ]]; then
  echo "BLOCKED: NEXT_PUBLIC_SUPABASE_URL must be exported (needed for the post-deploy auth gate)." >&2
  exit 2
fi

if [[ -z "${NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY:-}" && -z "${NEXT_PUBLIC_SUPABASE_ANON_KEY:-}" ]]; then
  echo "BLOCKED: export NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY (or legacy NEXT_PUBLIC_SUPABASE_ANON_KEY)." >&2
  exit 2
fi

if $DRY_RUN; then
  echo "-- DRY RUN: would run --"
  echo "fly deploy -a $FLY_APP --config panel/fly.toml --local-only"
  echo "scripts/verify-panel-auth.sh https://${FLY_APP}.fly.dev -a $FLY_APP"
  exit 0
fi

echo "== deploy-panel: deploying $FLY_APP from repo root =="
# --local-only: this app's remote (Fly-hosted) builder has been unreliable in
# practice; building on the runner's local Docker daemon and pushing the
# finished image is the reliable path (see the panel-deployment runbook).
fly deploy -a "$FLY_APP" --config panel/fly.toml --local-only

echo "== deploy-panel: verifying the auth boundary against the deployed host =="
HOST="https://${FLY_APP}.fly.dev"
if ! scripts/verify-panel-auth.sh "$HOST" -a "$FLY_APP"; then
  echo "" >&2
  echo "VERIFY-FAIL: the auth gate failed against $HOST after a successful deploy." >&2
  echo "CONTAIN FIRST if this is a surprise regression:" >&2
  echo "  fly ips list -a $FLY_APP" >&2
  echo "  fly ips release <public-addr> -a $FLY_APP   # private again, no redeploy" >&2
  echo "Then roll back:" >&2
  echo "  fly releases -a $FLY_APP" >&2
  echo "  fly deploy -a $FLY_APP --image <prior-image-ref>   # or: fly releases rollback" >&2
  exit 3
fi

echo "== deploy-panel: OK — deployed and auth gate passed against $HOST =="
