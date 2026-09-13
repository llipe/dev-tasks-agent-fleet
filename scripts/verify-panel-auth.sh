#!/usr/bin/env bash
#
# verify-panel-auth.sh — the panel AUTH RELEASE GATE (Story S-122, SR2 inversion / PRD AC17).
#
# This REPLACES scripts/verify-fly-private.sh. That old gate mechanized "privacy
# is the only boundary" (SR2/D16) and FAILED the release if the app was public.
# This feature reverses that decision — the panel gains a login and (in the
# separate Phase B / S-123) goes public — so the mechanical check is REPLACED,
# never merely deleted: a release must never run with no boundary check at all.
#
# The new boundary is asserted BY OBSERVATION against the DEPLOYED app, at a
# hostname you pass in, so the SAME gate works over the private Fly network in
# Phase A (e.g. `fly proxy 8080:8080` → http://localhost:8080) and publicly in
# Phase B (https://<app>.fly.dev). It collects four live inputs and hands the
# verdict to the unit-tested pure parser (panel/scripts/panel-auth-check.mjs),
# so the gate's decision logic is the same code the test suite observes failing.
#
# Checks (all must pass; fail-closed on anything unconfirmable):
#   1. The auth env-var NAMES are present on the Fly app  (`fly secrets list` —
#      NAMES ONLY, never values).
#   2. An unauthenticated GET of a protected UI path returns 302 → /login (not 200).
#   3. An unauthenticated GET of the SSE path returns 401 (not 200).
#   4. An attempted signUp is REJECTED. A SUCCESSFUL signup FAILS the release
#      (PRD AC17 / R9). Uses a clearly-marked disposable address and DELETES any
#      account it somehow creates.
#
# SECURITY: this script prints only NAMES, status codes, and pass/fail reasons.
# It never prints secret values, tokens, cookies, or the anon/service keys.
#
# Usage:
#   scripts/verify-panel-auth.sh <base-url> [-a <fly-app-name>] [-p <protected-path>] [-r <run-uuid>]
#
# Examples:
#   # Phase A, over the private network (after `fly proxy 8080:8080 -a dt-agent-fleet-panel`):
#   scripts/verify-panel-auth.sh http://localhost:8080 -a dt-agent-fleet-panel
#   # Phase B, public:
#   scripts/verify-panel-auth.sh https://dt-agent-fleet-panel.fly.dev -a dt-agent-fleet-panel
#
# Requires: `curl`, `node`. `fly` (flyctl) is required for check 1 unless the
# env-name list is supplied out-of-band via PANEL_AUTH_ENV_NAMES (comma-sep).
# The client key + Supabase URL for check 4 come from env: NEXT_PUBLIC_SUPABASE_URL
# and NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY (the publishable key, #172; the legacy
# NEXT_PUBLIC_SUPABASE_ANON_KEY is accepted as a fallback). Either is safe to hold
# here; it is NOT a secret value in the SR2 sense and is never printed.
#
# Fail-closed: if any input cannot be obtained or parsed, the gate FAILS (exit 1).
set -euo pipefail

BASE_URL="${1:-}"
if [[ -z "$BASE_URL" || "$BASE_URL" == -* ]]; then
  echo "[panel-auth] FAIL — usage: $0 <base-url> [-a <app>] [-p <protected-path>] [-r <run-uuid>]" >&2
  exit 2
fi
shift

APP=""
PROTECTED_PATH="/"
RUN_UUID="00000000-0000-0000-0000-000000000000"
while getopts "a:p:r:" opt; do
  case "$opt" in
    a) APP="$OPTARG" ;;
    p) PROTECTED_PATH="$OPTARG" ;;
    r) RUN_UUID="$OPTARG" ;;
    *) echo "usage: $0 <base-url> [-a <app>] [-p <protected-path>] [-r <run-uuid>]" >&2; exit 2 ;;
  esac
done

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PARSER="$REPO_ROOT/panel/scripts/panel-auth-check.mjs"

# HTTP timeouts (seconds) — a hung probe must FAIL the gate, not hang the release.
CONNECT_TIMEOUT="${PANEL_AUTH_CONNECT_TIMEOUT:-10}"
MAX_TIME="${PANEL_AUTH_MAX_TIME:-20}"

if ! command -v node >/dev/null 2>&1; then
  echo "[panel-auth] FAIL — node is required to run the auth-gate parser." >&2
  exit 1
fi
if ! command -v curl >/dev/null 2>&1; then
  echo "[panel-auth] FAIL — curl is required to probe the deployed app." >&2
  exit 1
fi
if [[ ! -f "$PARSER" ]]; then
  echo "[panel-auth] FAIL — parser not found at $PARSER." >&2
  exit 1
fi

BASE_URL="${BASE_URL%/}"
TMP_DIR="$(mktemp -d)"
trap 'rm -rf "$TMP_DIR"' EXIT
INPUT_JSON="$TMP_DIR/gate-input.json"

# --- Small JSON helpers (avoid printing any secret values) -----------------
json_str() { node -e 'process.stdout.write(JSON.stringify(process.argv[1] ?? ""))' "$1"; }

# ---------------------------------------------------------------------------
# CHECK 1 — auth env-var NAMES present on the app (NAMES ONLY).
# ---------------------------------------------------------------------------
echo "[panel-auth] (1/4) Collecting auth env-var NAMES (names only, never values)..."
ENV_NAMES_JSON="[]"
if [[ -n "${PANEL_AUTH_ENV_NAMES:-}" ]]; then
  # Explicit override (comma-separated), e.g. for local/dev runs without flyctl.
  ENV_NAMES_JSON="$(node -e '
    const names = String(process.argv[1] || "").split(",").map(s => s.trim()).filter(Boolean);
    process.stdout.write(JSON.stringify(names));
  ' "$PANEL_AUTH_ENV_NAMES")"
elif command -v fly >/dev/null 2>&1 && [[ -n "$APP" ]]; then
  # `fly secrets list` reports NAMES + digests (never values). Prefer the
  # `--json` output (a stable contract, immune to the drawn-table column layout
  # and its leading-space/`│`-separator rows that broke the original inline
  # regex — #162 task 1.27); fall back to the table if this flyctl lacks --json.
  # Name extraction is delegated to the unit-tested pure parser so the real
  # flyctl output shape is covered by a regression test. Fail-closed: if the
  # call fails, leave the list empty so the env-name check fails.
  if SECRETS_JSON="$(fly secrets list --json -a "$APP" 2>/dev/null)" && [[ -n "$SECRETS_JSON" ]]; then
    ENV_NAMES_JSON="$(SECRETS_RAW="$SECRETS_JSON" node -e '
      import("'"$PARSER"'").then((m) => {
        const names = m.extractSecretNames(process.env.SECRETS_RAW || "", { json: true });
        process.stdout.write(JSON.stringify(names));
      });
    ')"
  elif SECRETS_RAW="$(fly secrets list -a "$APP" 2>/dev/null)"; then
    ENV_NAMES_JSON="$(SECRETS_RAW="$SECRETS_RAW" node -e '
      import("'"$PARSER"'").then((m) => {
        const names = m.extractSecretNames(process.env.SECRETS_RAW || "", { json: false });
        process.stdout.write(JSON.stringify(names));
      });
    ')"
  else
    echo "[panel-auth]   WARN — could not read 'fly secrets list' (check will fail-closed)." >&2
  fi
else
  echo "[panel-auth]   WARN — no flyctl/app and no PANEL_AUTH_ENV_NAMES; env-name check will fail-closed." >&2
fi

# ---------------------------------------------------------------------------
# CHECK 2 — unauthenticated protected UI path → 302 /login.
# `-i` to capture headers; do NOT follow redirects (`-L` would hide the 302).
# We extract the status code and the Location header only.
# ---------------------------------------------------------------------------
echo "[panel-auth] (2/4) Probing protected UI path ${PROTECTED_PATH} (expect 302 -> /login)..."
PROTECTED_JSON='{"error":"probe not run"}'
if HDRS="$(curl -sS -i -o - -D - \
    --connect-timeout "$CONNECT_TIMEOUT" --max-time "$MAX_TIME" \
    "${BASE_URL}${PROTECTED_PATH}" 2>"$TMP_DIR/perr")"; then
  PSTATUS="$(printf '%s\n' "$HDRS" | awk 'NR==1{print $2}')"
  PLOC="$(printf '%s\n' "$HDRS" | awk 'BEGIN{IGNORECASE=1} /^location:/{sub(/^[Ll]ocation:[ \t]*/,""); gsub(/\r/,""); print; exit}')"
  PROTECTED_JSON="$(node -e '
    const status = Number.parseInt(process.argv[1] || "", 10);
    const out = { status: Number.isInteger(status) ? status : null };
    if (process.argv[2]) out.location = process.argv[2];
    process.stdout.write(JSON.stringify(out));
  ' "$PSTATUS" "$PLOC")"
else
  ERR="$(tr -d '\n' < "$TMP_DIR/perr" | head -c 200)"
  PROTECTED_JSON="{\"error\":$(json_str "curl: ${ERR:-request failed/timeout}")}"
fi

# ---------------------------------------------------------------------------
# CHECK 3 — unauthenticated SSE path → 401. Status code is authoritative.
# ---------------------------------------------------------------------------
SSE_PATH="/api/runs/${RUN_UUID}/events/stream"
echo "[panel-auth] (3/4) Probing SSE path ${SSE_PATH} (expect 401)..."
SSE_JSON='{"error":"probe not run"}'
if SSTATUS="$(curl -sS -o /dev/null -w '%{http_code}' \
    -H 'Accept: text/event-stream' \
    --connect-timeout "$CONNECT_TIMEOUT" --max-time "$MAX_TIME" \
    "${BASE_URL}${SSE_PATH}" 2>"$TMP_DIR/serr")"; then
  SSE_JSON="$(node -e '
    const status = Number.parseInt(process.argv[1] || "", 10);
    process.stdout.write(JSON.stringify({ status: Number.isInteger(status) ? status : null }));
  ' "$SSTATUS")"
else
  ERR="$(tr -d '\n' < "$TMP_DIR/serr" | head -c 200)"
  SSE_JSON="{\"error\":$(json_str "curl: ${ERR:-request failed/timeout}")}"
fi

# ---------------------------------------------------------------------------
# CHECK 4 — attempted signUp is REJECTED (PRD AC17 / R9). The MOST important
# check: an open signup on an internet-reachable panel lets anyone self-register
# into the invoke surface. POST /auth/v1/signup with the anon key to a clearly-
# marked disposable address. A rejection (error) is PASS; a success is FAIL, and
# we DELETE any account that was somehow created.
# ---------------------------------------------------------------------------
echo "[panel-auth] (4/4) Attempting a signUp (expect REJECTED — signups must be disabled)..."
SIGNUP_JSON='{"error":"probe not run"}'
SB_URL="${NEXT_PUBLIC_SUPABASE_URL:-}"
# Prefer the new publishable client key (#172); fall back to the legacy anon
# name for one release. Either is a valid Auth `apikey` and is never printed.
SB_ANON="${NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY:-${NEXT_PUBLIC_SUPABASE_ANON_KEY:-}}"
if [[ -z "$SB_URL" || -z "$SB_ANON" ]]; then
  echo "[panel-auth]   WARN — NEXT_PUBLIC_SUPABASE_URL / NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY (or legacy _ANON_KEY) not set;" >&2
  echo "[panel-auth]          signup check will fail-closed (cannot confirm signups are off)." >&2
  SIGNUP_JSON='{"error":"anon key / url not provided; cannot confirm signups are off"}'
else
  SB_URL="${SB_URL%/}"
  DISPOSABLE="panel-auth-gate-probe+$(date +%s)-$$@release-gate.invalid"
  RANDPW="Gate-$(date +%s)-$$-$RANDOM-Xx!"
  SIGNUP_BODY="$(node -e '
    process.stdout.write(JSON.stringify({ email: process.argv[1], password: process.argv[2] }));
  ' "$DISPOSABLE" "$RANDPW")"
  if SU_RESP="$(curl -sS -o "$TMP_DIR/su_body" -w '%{http_code}' \
      -X POST "${SB_URL}/auth/v1/signup" \
      -H "apikey: ${SB_ANON}" \
      -H "Authorization: Bearer ${SB_ANON}" \
      -H 'Content-Type: application/json' \
      --connect-timeout "$CONNECT_TIMEOUT" --max-time "$MAX_TIME" \
      -d "$SIGNUP_BODY" 2>"$TMP_DIR/suerr")"; then
    # Classify WITHOUT printing the body (it may echo the email). Node reads the
    # body file and derives only { rejected, createdUserId? } — never prints it.
    SIGNUP_JSON="$(SU_HTTP="$SU_RESP" node -e '
      const fs = require("fs");
      const http = Number.parseInt(process.env.SU_HTTP || "", 10);
      let body = {};
      try { body = JSON.parse(fs.readFileSync(process.argv[1], "utf8")); } catch { body = null; }
      // Supabase returns 200 + a user/session on a SUCCESSFUL signup, and a 4xx
      // with an error/error_code (e.g. "signup_disabled") when signups are off.
      const hasError = body && (body.error || body.error_code || body.msg || body.code || body.message);
      const createdId = body && (body.id || (body.user && body.user.id));
      let rejected;
      let createdUserId;
      if (Number.isInteger(http) && http >= 400) {
        rejected = true;                 // an error status = rejection = PASS
      } else if (createdId) {
        rejected = false; createdUserId = String(createdId);   // a user exists = FAIL
      } else if (http === 200 && !hasError) {
        rejected = false;                // 200 with no error = accepted = FAIL
      } else if (hasError) {
        rejected = true;                 // error body = rejection = PASS
      } else {
        rejected = undefined;            // unrecognized -> parser fails closed
      }
      const out = { rejected };
      if (createdUserId) out.createdUserId = createdUserId;
      process.stdout.write(JSON.stringify(out));
    ' "$TMP_DIR/su_body")"

    # Belt-and-suspenders: if a user WAS created, delete it via the admin API if
    # a service-role key is available. The gate still FAILS (signups were on),
    # but we do not leave a stray account behind.
    CREATED_ID="$(node -e '
      try { const o = JSON.parse(process.argv[1]); process.stdout.write(o.createdUserId || ""); }
      catch { process.stdout.write(""); }
    ' "$SIGNUP_JSON")"
    if [[ -n "$CREATED_ID" && -n "${SUPABASE_SERVICE_ROLE_KEY:-}" ]]; then
      echo "[panel-auth]   NOTE — a signup account was created; deleting it (id names only)." >&2
      curl -sS -o /dev/null -X DELETE "${SB_URL}/auth/v1/admin/users/${CREATED_ID}" \
        -H "apikey: ${SUPABASE_SERVICE_ROLE_KEY}" \
        -H "Authorization: Bearer ${SUPABASE_SERVICE_ROLE_KEY}" \
        --connect-timeout "$CONNECT_TIMEOUT" --max-time "$MAX_TIME" || \
        echo "[panel-auth]   WARN — could not auto-delete the created account; delete it manually." >&2
    elif [[ -n "$CREATED_ID" ]]; then
      echo "[panel-auth]   WARN — a signup account was created but no SUPABASE_SERVICE_ROLE_KEY to delete it; delete it manually." >&2
    fi
  else
    ERR="$(tr -d '\n' < "$TMP_DIR/suerr" | head -c 200)"
    SIGNUP_JSON="{\"error\":$(json_str "curl: ${ERR:-signup request failed/timeout}")}"
  fi
fi

# --- Assemble the gate input and hand it to the pure parser ----------------
node -e '
  const [envNames, protectedProbe, sseProbe, signupProbe] = process.argv.slice(1).map((a) => JSON.parse(a));
  process.stdout.write(JSON.stringify({ envNames, protectedProbe, sseProbe, signupProbe }));
' "$ENV_NAMES_JSON" "$PROTECTED_JSON" "$SSE_JSON" "$SIGNUP_JSON" > "$INPUT_JSON"

# The parser exits 0 (boundary holds) or 1 (any failure). `set -e` would abort
# before we can echo, so capture the code.
set +e
node "$PARSER" "$INPUT_JSON"
code=$?
set -e

if [[ "$code" -eq 0 ]]; then
  echo "[panel-auth] RELEASE ALLOWED — the auth boundary holds on ${BASE_URL}."
else
  echo "[panel-auth] RELEASE BLOCKED — the auth boundary is NOT proven (see above)." >&2
fi
exit "$code"
