#!/usr/bin/env bash
#
# verify-fly-private.sh — the Fly privacy RELEASE GATE (Story S-115, SR2 / AC6).
#
# The panel has no user auth in v1 (D16); its only security boundary is that the
# Fly app is NOT publicly reachable. This script is run AFTER every `fly deploy`
# (and may be run any time) and FAILS THE RELEASE (exit 1) if the app has any
# public IP or any public service. A private-only app exits 0.
#
# It captures the machine-readable `fly` output and hands the decision to the
# unit-tested pure parser (panel/scripts/fly-privacy-check.mjs), so the gate's
# logic is the same code the test suite observes failing on a public fixture.
#
# Usage:
#   scripts/verify-fly-private.sh [-a <app-name>]
#
# Requires: `flyctl` (aka `fly`) authenticated, and `node`.
#
# Fail-closed: if `fly` output cannot be obtained or parsed, the gate FAILS.
set -euo pipefail

APP=""
while getopts "a:" opt; do
  case "$opt" in
    a) APP="$OPTARG" ;;
    *) echo "usage: $0 [-a <app-name>]" >&2; exit 2 ;;
  esac
done

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PARSER="$REPO_ROOT/panel/scripts/fly-privacy-check.mjs"

if ! command -v node >/dev/null 2>&1; then
  echo "[fly-privacy] FAIL — node is required to run the privacy parser." >&2
  exit 1
fi
if ! command -v fly >/dev/null 2>&1; then
  echo "[fly-privacy] FAIL — flyctl (fly) is not installed or not on PATH." >&2
  exit 1
fi
if [[ ! -f "$PARSER" ]]; then
  echo "[fly-privacy] FAIL — parser not found at $PARSER." >&2
  exit 1
fi

APP_ARGS=()
if [[ -n "$APP" ]]; then
  APP_ARGS=(-a "$APP")
fi

TMP_DIR="$(mktemp -d)"
trap 'rm -rf "$TMP_DIR"' EXIT
IPS_JSON="$TMP_DIR/ips.json"
STATUS_JSON="$TMP_DIR/status.json"

echo "[fly-privacy] Collecting allocated IPs and service status from Fly..."

# `fly ips list --json` → allocated IPs (public vs private/6PN).
if ! fly ips list "${APP_ARGS[@]}" --json > "$IPS_JSON" 2>/dev/null; then
  echo "[fly-privacy] FAIL — could not read 'fly ips list --json' (fail-closed)." >&2
  exit 1
fi

# `fly status --json` → service/port configuration.
if ! fly status "${APP_ARGS[@]}" --json > "$STATUS_JSON" 2>/dev/null; then
  echo "[fly-privacy] FAIL — could not read 'fly status --json' (fail-closed)." >&2
  exit 1
fi

# The parser exits 0 (private-only) or 1 (public exposure found) and prints the
# reasons. `set -e` would abort before we can echo, so capture the code.
set +e
node "$PARSER" "$IPS_JSON" "$STATUS_JSON"
code=$?
set -e

if [[ "$code" -eq 0 ]]; then
  echo "[fly-privacy] RELEASE ALLOWED — app is private-only."
else
  echo "[fly-privacy] RELEASE BLOCKED — public exposure detected (see above)." >&2
fi
exit "$code"
