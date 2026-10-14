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

# The official installer symlinks both `fly` and `flyctl`, but
# superfly/flyctl-actions/setup-flyctl (used in CI) only puts `flyctl` on
# PATH — resolve whichever is present, preferring `flyctl`.
if command -v flyctl >/dev/null 2>&1; then
  FLY_BIN="flyctl"
elif command -v fly >/dev/null 2>&1; then
  FLY_BIN="fly"
else
  echo "BLOCKED: flyctl not found on PATH." >&2
  exit 2
fi

if ! "$FLY_BIN" auth whoami >/dev/null 2>&1; then
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
  echo "# then, for EACH started Machine, the OIDC token probe as uid 1001 (#280):"
  echo "flyctl machine exec <id> \"setpriv --reuid=1001 --regid=1001 --init-groups node /app/fly-oidc-probe.mjs\" -a $FLY_APP"
  echo "#   probe POSTs {\"aud\":\"sts.amazonaws.com\"} to /v1/tokens/oidc on /.fly/api,"
  echo "#   prints only 'status=<code> token=<present|absent>' (never the token),"
  echo "#   PASS = a line matching exactly 'status=2XX token=present' in the probe OUTPUT"
  echo "#   (NOT flyctl's exit status, which is 0 even when the remote command fails);"
  echo "#   anything else => exit 3 with the rollback hint."
  exit 0
fi

echo "== deploy-panel: deploying $FLY_APP from repo root =="
# --local-only: this app's remote (Fly-hosted) builder has been unreliable in
# practice; building on the runner's local Docker daemon and pushing the
# finished image is the reliable path (see the panel-deployment runbook).
"$FLY_BIN" deploy -a "$FLY_APP" --config panel/fly.toml --local-only

echo "== deploy-panel: verifying the auth boundary against the deployed host =="
HOST="https://${FLY_APP}.fly.dev"
# The auth gate is hard-wired to scripts/verify-panel-auth.sh — the control
# ADR-007 makes the panel's security boundary. There is NO env-driven override:
# a switch that could disable a security gate from the environment (CI leak,
# operator shell, copied snippet) is itself the vulnerability. The gate is
# resolved relative to the working directory (the repo root this script cd's
# into), so a test can exercise the probe branch by running the real script
# from a temp dir that mirrors the layout with a stub scripts/verify-panel-auth.sh.
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

echo "== deploy-panel: OIDC token probe (as uid 1001) on each started Machine (#280) =="
# Regression guard for #280: the deployed server runs as uid 1001, and the Fly
# OIDC socket (/.fly/api) is created root-owned at boot — so uid 1001 could not
# obtain a token and every invoke failed. The entrypoint now group-grants the
# socket before dropping to 1001; this probe PROVES uid 1001 can actually get a
# token on every started Machine, so a recurrence FAILS the release (exit 3)
# instead of silently breaking invoke. No STS exchange — getting the token is
# the only thing that was broken. The token value is NEVER printed or logged;
# the probe emits only `status=<code> token=<present|absent>` (D-05).
#
# The probe runs AS uid 1001 (setpriv), exactly as the server does, so it
# exercises the real permission path — not root's (root always got HTTP 404,
# which hid the EACCES). It runs the UNIT-TESTED /app/fly-oidc-probe.mjs baked
# into the runtime image (PR #295 review point 3) — the same code the 26 unit
# tests cover — not an inline duplicate.
#
# CRITICAL (PR #295 review point 1): `flyctl machine exec` returns exit 0 even
# when the REMOTE command fails — the remote status is only visible in the
# `Exit code: <n>` line it prints to stdout. So we DECIDE PASS/FAIL FROM THE
# PROBE OUTPUT, not from flyctl's exit status: PASS requires a line matching
# EXACTLY `status=2XX token=present`. Anything else (token=absent, non-2xx, an
# `Exit code: <nonzero>` echo, empty output) is a failure. flyctl's own nonzero
# status is also treated as a failure.
PROBE_CMD="setpriv --reuid=1001 --regid=1001 --init-groups node /app/fly-oidc-probe.mjs"

# Enumerate STARTED Machines only — a stopped Machine has no live socket to
# probe. `flyctl machine list --json` carries a `state` field per Machine.
MACHINES_JSON="$("$FLY_BIN" machine list -a "$FLY_APP" --json 2>/dev/null || echo '[]')"
MACHINE_IDS="$(printf '%s' "$MACHINES_JSON" \
  | node -e 'let s="";process.stdin.on("data",d=>s+=d).on("end",()=>{let a=[];try{a=JSON.parse(s)}catch{};for(const m of (Array.isArray(a)?a:[]))if((m.state||"")==="started"&&m.id)console.log(m.id)})')"

if [[ -z "$MACHINE_IDS" ]]; then
  echo "VERIFY-FAIL: no started Machine found to probe for an OIDC token (#280)." >&2
  echo "  flyctl machine list -a $FLY_APP   # inspect Machine states" >&2
  echo "See docs/runbooks/panel-deployment.md § 'OIDC token probe (#280)'." >&2
  exit 3
fi

PROBE_FAILED=false
while IFS= read -r MID; do
  [[ -z "$MID" ]] && continue
  echo "-- probing Machine $MID --"
  # Capture the output regardless of flyctl's own status. `|| FLY_RC=$?` keeps
  # `set -e` from aborting on a flyctl-level error so we can report it.
  FLY_RC=0
  PROBE_OUT="$("$FLY_BIN" machine exec "$MID" "$PROBE_CMD" -a "$FLY_APP" 2>/dev/null)" || FLY_RC=$?
  echo "   ${PROBE_OUT:-<no probe output>}"
  # PASS only if the OUTPUT contains a line matching EXACTLY the healthy verdict
  # (2xx + token present), AND flyctl itself did not error. grep -q over the
  # captured output is the decision — never flyctl's exit status alone.
  if [[ "$FLY_RC" -ne 0 ]] \
    || ! printf '%s\n' "$PROBE_OUT" | grep -qxE 'status=2[0-9]{2} token=present'; then
    PROBE_FAILED=true
  fi
done <<< "$MACHINE_IDS"

if $PROBE_FAILED; then
  echo "" >&2
  echo "VERIFY-FAIL: uid 1001 could not obtain an OIDC token on at least one Machine (#280)." >&2
  echo "The deployed panel cannot invoke agents (CREDENTIALS_UNAVAILABLE). Roll back:" >&2
  echo "  fly releases -a $FLY_APP" >&2
  echo "  fly deploy -a $FLY_APP --image <prior-image-ref>   # or: fly releases rollback" >&2
  echo "Diagnose per docs/runbooks/panel-deployment.md § 'OIDC token probe (#280)'" >&2
  echo "(socket ownership/mode on /.fly/api, entrypoint grant warning in Machine logs)." >&2
  echo "NOTE: 'flyctl machine exec' exits 0 even when the remote command fails;" >&2
  echo "the verdict above comes from the probe's OUTPUT line, not flyctl's status." >&2
  exit 3
fi

echo "== deploy-panel: OK — deployed, auth gate passed, OIDC token present as uid 1001 on each Machine ($HOST) =="
