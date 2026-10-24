#!/usr/bin/env bash
# Image smoke test for the bug-fix agent (S-180: TC-180-06..09).
#
# Usage: scripts/image-smoke.sh [image]     (default: bug-fix:local)
#
# Runs throwaway containers from the image and asserts:
#   - toolchain: Python 3.13.x, Node v26.x, pnpm, git, bwrap, socat, and
#     `claude --version` equal to the version pinned in the Dockerfile;
#   - users: `wrapper` and `fixer` have different, non-zero uids, fixer is in
#     none of wrapper's groups, the default user is wrapper;
#   - uid switch (S-182 task 3.16, D-109): /etc/sudoers.d/bug-fix is root:root
#     0440 and valid; as wrapper, `sudo -n -u fixer id -u` is 10002 with a
#     clean environment; wrapper can't become root or pick a group; fixer
#     can't sudo at all; `sudo -u fixer kill -9 -- -1` leaves no fixer process;
#   - sandbox runtime: `srt --version` equals the pinned version, `rg` works,
#     /etc/bug-fix/srt-settings.json is root:root 0644;
#   - dirs: /work/repo and /work/out owned by fixer, /home/fixer exists,
#     /work/wrapper and /work/secrets are wrapper-only (0700);
#   - policy: /etc/claude-code/managed-settings.json is root:root 0644, and as
#     fixer it can't be appended to and the directory isn't writable;
#   - isolation: as fixer, /home/wrapper and /work/secrets can't be read.
#
# Exits non-zero on the first failed assertion. Needs Docker and a locally
# built image; needs no credentials and no network.

set -euo pipefail

IMAGE="${1:-bug-fix:local}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DOCKERFILE="${SCRIPT_DIR}/../Dockerfile"
PLATFORM="linux/arm64"

pass=0
fail() { echo "FAIL: $*" >&2; exit 1; }
ok() { echo "ok: $*"; pass=$((pass + 1)); }

# Run a shell snippet in a fresh container as the given user.
as_user() {
  local user="$1"; shift
  docker run --rm --platform "$PLATFORM" --user "$user" --entrypoint /bin/sh "$IMAGE" -c "$*"
}
as_root() { as_user root "$@"; }

docker image inspect "$IMAGE" >/dev/null 2>&1 || fail "image $IMAGE not found (run \`make image\` first)"

# --- Architecture ------------------------------------------------------------
arch="$(docker image inspect --format '{{.Architecture}}' "$IMAGE")"
[ "$arch" = "arm64" ] || fail "image architecture is $arch, expected arm64"
ok "architecture arm64"

# --- Toolchain (TC-180-06) ---------------------------------------------------
py="$(as_root 'python --version')"
echo "$py" | grep -qE '^Python 3\.13\.' || fail "expected Python 3.13.x, got: $py"
ok "$py"

node="$(as_root 'node --version')"
echo "$node" | grep -qE '^v26\.' || fail "expected Node v26.x, got: $node"
ok "node $node"

as_root 'pnpm --version' >/dev/null || fail "pnpm not runnable"
ok "pnpm $(as_root 'pnpm --version')"
as_root 'git --version' >/dev/null || fail "git not runnable"
ok "$(as_root 'git --version')"
as_root 'bwrap --version' >/dev/null || fail "bwrap --version failed"
ok "$(as_root 'bwrap --version')"
as_root 'socat -V' >/dev/null || fail "socat -V failed"
ok "socat present"

as_root 'rg --version' >/dev/null || fail "rg (ripgrep) not runnable"
ok "$(as_root 'rg --version | head -1')"

srt_pinned="$(sed -n 's/^ARG SANDBOX_RUNTIME_VERSION=//p' "$DOCKERFILE")"
[ -n "$srt_pinned" ] || fail "no ARG SANDBOX_RUNTIME_VERSION in the Dockerfile"
srt_v="$(as_user fixer 'srt --version')"
echo "$srt_v" | grep -qF "$srt_pinned" || fail "srt --version is '$srt_v', expected $srt_pinned"
ok "srt $srt_v (pinned $srt_pinned)"

pinned="$(sed -n 's/^ARG CLAUDE_CODE_VERSION=//p' "$DOCKERFILE")"
[ -n "$pinned" ] || fail "no ARG CLAUDE_CODE_VERSION in the Dockerfile"
claude_v="$(as_user fixer 'claude --version')"
echo "$claude_v" | grep -qF "$pinned" || fail "claude --version is '$claude_v', expected $pinned"
ok "claude $claude_v (pinned $pinned)"

# --- Users and dirs (TC-180-07, TC-180-08) -----------------------------------
wrapper_uid="$(as_root 'id -u wrapper')"
fixer_uid="$(as_root 'id -u fixer')"
[ "$wrapper_uid" != "$fixer_uid" ] || fail "wrapper and fixer share uid $wrapper_uid"
[ "$wrapper_uid" != 0 ] && [ "$fixer_uid" != 0 ] || fail "a runtime user is uid 0"
ok "uids differ: wrapper=$wrapper_uid fixer=$fixer_uid"

default_user="$(docker run --rm --platform "$PLATFORM" --entrypoint /bin/sh "$IMAGE" -c 'id -un')"
[ "$default_user" = "wrapper" ] || fail "default user is $default_user, expected wrapper"
ok "default user is wrapper"

wrapper_groups="$(as_root 'id -Gn wrapper')"
fixer_groups="$(as_root 'id -Gn fixer')"
for g in $wrapper_groups; do
  for f in $fixer_groups; do
    [ "$g" != "$f" ] || fail "fixer shares group $g with wrapper"
  done
done
echo " $fixer_groups " | grep -qE ' (sudo|wheel|root|adm) ' && fail "fixer is in a privileged group: $fixer_groups"
ok "fixer groups ($fixer_groups) disjoint from wrapper's ($wrapper_groups)"

# --- uid switch: the narrow sudo rule (S-182 task 3.16, D-109) ---------------
sudoers=/etc/sudoers.d/bug-fix
om="$(as_root "stat -c '%U:%G %a' $sudoers")"
[ "$om" = "root:root 440" ] || fail "$sudoers is $om, expected root:root 440"
ok "$sudoers $om"
as_root "visudo -cf $sudoers" >/dev/null || fail "visudo -cf $sudoers failed"
ok "$sudoers passes visudo -cf"
extra="$(as_root 'ls -A /etc/sudoers.d | grep -v -x -e README -e bug-fix || true')"
[ -z "$extra" ] || fail "unexpected files in /etc/sudoers.d: $extra"
ok "/etc/sudoers.d holds only bug-fix"

switched="$(as_user wrapper 'sudo -n -u fixer id -u')"
[ "$switched" = "10002" ] || fail "as wrapper, sudo -n -u fixer id -u gave '$switched', expected 10002"
ok "wrapper -> fixer: sudo -n -u fixer id -u = $switched"

if as_user fixer 'sudo -n true' >/dev/null 2>&1; then
  fail "fixer can run sudo -n true"
fi
ok "fixer can't sudo"
if as_user wrapper 'sudo -n -u root true' >/dev/null 2>&1; then
  fail "wrapper can become root"
fi
if as_user wrapper 'sudo -n true' >/dev/null 2>&1; then
  fail "wrapper can run sudo -n true (root by default)"
fi
ok "wrapper can't become root"
if as_user wrapper 'sudo -n -u fixer -g root true' >/dev/null 2>&1; then
  fail "wrapper can pick group root"
fi
ok "wrapper can't pick a group"

leaked="$(as_user wrapper 'env AWS_ACCESS_KEY_ID=leak-7f3a SUPABASE_URL=leak-7f3a sudo -n -u fixer env' | grep -c 'leak-7f3a' || true)"
[ "$leaked" = "0" ] || fail "sudo -u fixer inherited $leaked caller variable(s)"
ok "sudo -u fixer starts from a clean environment (env_reset)"

# The post-run sweep sandbox.py uses: every fixer process, daemons included.
# Zombies are not counted: the throwaway container's pid 1 is a plain shell
# that doesn't reap orphans (in the runtime, the wrapper reaps them).
fixer_procs="$(as_user wrapper "sudo -n -u fixer sh -c 'setsid sleep 1000 >/dev/null 2>&1 < /dev/null &'; sleep 0.3; \
  sudo -n -u fixer /usr/bin/kill -9 -- -1; sleep 0.3; \
  ps -u 10002 -o stat= | grep -vc '^Z' || true")"
[ "$fixer_procs" = "0" ] || fail "$fixer_procs fixer process(es) survived the kill sweep"
ok "kill sweep as fixer leaves no fixer process (setsid daemon included)"

as_root 'test -x /usr/local/bin/python3' || fail "/usr/local/bin/python3 missing (fixer_exec.py interpreter)"
envout="$(as_user wrapper 'env AWS_ACCESS_KEY_ID=leak-7f3a CI=1 LANG=C.UTF-8 sudo -n -u fixer --preserve-env=CI,LANG -- /usr/local/bin/python3 -I /app/fixer_exec.py /usr/bin/env')"
names="$(echo "$envout" | cut -d= -f1 | sort | tr '\n' ' ')"
[ "$names" = "CI HOME LANG PATH " ] || fail "fixer_exec.py env is '$names', expected 'CI HOME LANG PATH '"
ok "fixer_exec.py rebuilds the env from the allow-list ($names)"

owner_mode() { as_root "stat -c '%U:%G %a' $1"; }
for d in /work/repo /work/out; do
  om="$(owner_mode "$d")"
  echo "$om" | grep -qE '^fixer:fixer ' || fail "$d is $om, expected owner fixer"
  ok "$d $om"
done
as_root 'test -d /home/fixer' || fail "/home/fixer missing"
ok "/home/fixer exists"
for d in /work/wrapper /work/secrets; do
  om="$(owner_mode "$d")"
  [ "$om" = "wrapper:wrapper 700" ] || fail "$d is $om, expected wrapper:wrapper 700"
  ok "$d $om"
done

if as_user fixer 'ls /home/wrapper' >/dev/null 2>&1; then
  fail "fixer can list /home/wrapper"
fi
ok "fixer can't list /home/wrapper"
if as_user fixer 'ls /work/secrets' >/dev/null 2>&1; then
  fail "fixer can list /work/secrets"
fi
ok "fixer can't read /work/secrets"
if as_user fixer 'ls /work/wrapper' >/dev/null 2>&1; then
  fail "fixer can list /work/wrapper"
fi
ok "fixer can't read /work/wrapper"

# --- Managed policy (TC-180-09) ----------------------------------------------
policy=/etc/claude-code/managed-settings.json
om="$(owner_mode "$policy")"
[ "$om" = "root:root 644" ] || fail "$policy is $om, expected root:root 644"
ok "$policy $om"
om="$(owner_mode /etc/claude-code)"
[ "$om" = "root:root 755" ] || fail "/etc/claude-code is $om, expected root:root 755"
ok "/etc/claude-code $om"

for user in fixer wrapper; do
  if as_user "$user" "echo '{}' >> $policy" >/dev/null 2>&1; then
    fail "$user can append to $policy"
  fi
  if as_user "$user" "touch /etc/claude-code/x" >/dev/null 2>&1; then
    fail "$user can write to /etc/claude-code"
  fi
  ok "$user can't modify the policy or its directory"
done

as_user fixer "python -c 'import json,sys; json.load(open(\"$policy\"))'" || fail "$policy is not valid JSON"
ok "policy is readable JSON for fixer"

srt_policy=/etc/bug-fix/srt-settings.json
om="$(owner_mode "$srt_policy")"
[ "$om" = "root:root 644" ] || fail "$srt_policy is $om, expected root:root 644"
ok "$srt_policy $om"
if as_user fixer "echo '{}' >> $srt_policy" >/dev/null 2>&1; then
  fail "fixer can append to $srt_policy"
fi
ok "fixer can't modify $srt_policy"

echo "image-smoke: ${pass} checks passed for ${IMAGE}"
