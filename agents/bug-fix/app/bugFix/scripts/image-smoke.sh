#!/usr/bin/env bash
# Image smoke test for the bug-fix agent (S-180: TC-180-06..09; S-182 3.17: D-110).
#
# Usage: scripts/image-smoke.sh [image]     (default: bug-fix:local)
#
# Runs throwaway containers from the image and asserts:
#   - toolchain: Python 3.13.x, Node v26.x, pnpm, git, bwrap, socat, and
#     `claude --version` (run as fixer through setpriv + fixer_exec.py, under
#     no-new-privileges) equal to the version pinned in the Dockerfile;
#   - users: the default user is root (the wrapper, D-110); `fixer` is uid
#     10002 in no other group; there is no `wrapper` user;
#   - root -> fixer drop (D-110), under `--security-opt no-new-privileges` to
#     emulate AgentCore (which sets no_new_privs; probe run 1): no sudo binary
#     or sudoers file; setpriv present; the drop gives uid/gid 10002 (real,
#     effective, saved, fs), no supplementary groups, no capabilities and
#     NoNewPrivs 1 (also without the container flag); fixer can't get back to
#     root (setuid(0), su, setpriv --reuid=0); fixer can't read a root
#     process's /proc/<pid>/environ or mem; fixer_exec.py rebuilds the env
#     and refuses to run as root; sandbox.py's own paths and prefix work;
#     Sandbox().sweep() leaves no fixer process and spares root's;
#   - sandbox runtime: `srt --version` equals the pinned version, `rg` works,
#     /etc/bug-fix/srt-settings.json is root:root 0644;
#   - dirs: /work/repo and /work/out owned by fixer, /home/fixer exists,
#     /work/wrapper and /work/secrets are root:root 0700 and fixer can't read
#     them, /root or /home of anyone else;
#   - policy: /etc/claude-code/managed-settings.json is root:root 0644, and as
#     fixer it can't be appended to and the directory isn't writable;
#   - wrapper git (S-189, D-62, D-110): git supports --attr-source; as the
#     root wrapper under no_new_privs, safe_git.clone puts a local bare remote
#     into /work/wrapper/repo (mode 0700), materialize writes /work/repo as
#     fixer (files owned by 10002, no .git) through the real setpriv drop, a
#     fixer-planted .git/hooks and core.fsmonitor in /work/repo never run in
#     the wrapper's capture, which sees only the fixer's file edit; as fixer,
#     /work/wrapper can't be listed and /work/wrapper/repo/.git/config can't
#     be read (TC-189-19);
#   - S-189 fix round: fs.protected_hardlinks and fs.protected_symlinks are 1
#     (QA-189-01); the image's tar is GNU tar, the clone's fsckObjects refuses
#     a symlink-plus-directory tree, and with fsck off materialize writes
#     nothing through the link (gap 6);
#   - localhost (S-182 re-probes 2b, 2c; fix round 3): the image's /etc/hosts
#     is empty; nsswitch has `hosts: files myhostname dns`; /etc/gai.conf
#     prefers IPv4; with an empty, read-only /etc/hosts bind-mounted (as on
#     AgentCore), `getent ahostsv4 localhost` gives 127.0.0.1, sandbox.py's
#     preflight reports `nss` without writing, and fixer's getaddrinfo returns
#     127.0.0.1 first; the pinned CLI accepts the
#     `--disallowedTools=WebFetch,WebSearch` flag sandbox.py adds.
#
# Exits non-zero on the first failed assertion. Needs Docker and a locally
# built image; needs no credentials and no network.

set -euo pipefail

IMAGE="${1:-bug-fix:local}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DOCKERFILE="${SCRIPT_DIR}/../Dockerfile"
PLATFORM="linux/arm64"

# The exact drop sandbox.py uses (D-110), and the production exec shim.
SETPRIV="setpriv --reuid=10002 --regid=10002 --clear-groups --inh-caps=-all --no-new-privs --"
FIXER_EXEC="$SETPRIV /usr/local/bin/python3 -I /app/fixer_exec.py"

pass=0
fail() { echo "FAIL: $*" >&2; exit 1; }
ok() { echo "ok: $*"; pass=$((pass + 1)); }

# Run a shell snippet in a fresh container as the given user.
as_user() {
  local user="$1"; shift
  docker run --rm --platform "$PLATFORM" --user "$user" --entrypoint /bin/sh "$IMAGE" -c "$*"
}
as_root() { as_user root "$@"; }
# As AgentCore runs the wrapper: the image's default user, no_new_privs set.
as_agentcore() {
  docker run --rm --platform "$PLATFORM" --security-opt no-new-privileges \
    --entrypoint /bin/sh "$IMAGE" -c "$*"
}

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
# As AgentCore runs it: root wrapper, no_new_privs, setpriv + fixer_exec.py.
claude_v="$(as_agentcore "$FIXER_EXEC claude --version")"
echo "$claude_v" | grep -qF "$pinned" || fail "claude --version is '$claude_v', expected $pinned"
ok "claude $claude_v (pinned $pinned)"

# --- Users (TC-180-07) --------------------------------------------------------
default_user="$(docker run --rm --platform "$PLATFORM" --entrypoint /bin/sh "$IMAGE" -c 'id -un')"
[ "$default_user" = "root" ] || fail "default user is $default_user, expected root (D-110)"
ok "default user is root (the wrapper, D-110)"

fixer_uid="$(as_root 'id -u fixer')"
[ "$fixer_uid" = "10002" ] || fail "fixer uid is $fixer_uid, expected 10002"
fixer_groups="$(as_root 'id -Gn fixer')"
[ "$fixer_groups" = "fixer" ] || fail "fixer groups are '$fixer_groups', expected 'fixer' only"
ok "fixer uid $fixer_uid, groups: $fixer_groups"
if as_root 'id wrapper' >/dev/null 2>&1; then
  fail "a wrapper user still exists (the wrapper is root, D-110)"
fi
ok "no wrapper user"

# --- Root -> fixer drop under no_new_privs (S-182 3.17, D-110) ------------------
nnp_root="$(as_agentcore "awk '/^NoNewPrivs:/ {print \$2}' /proc/self/status")"
[ "$nnp_root" = "1" ] || fail "--security-opt no-new-privileges not in effect (NoNewPrivs=$nnp_root)"
ok "AgentCore emulation: root wrapper runs with NoNewPrivs 1"

if as_agentcore 'command -v sudo' >/dev/null 2>&1; then
  fail "a sudo binary is present"
fi
as_agentcore 'test ! -e /etc/sudoers.d/bug-fix && test ! -e /etc/sudoers' || fail "a sudoers file is present"
ok "no sudo binary and no sudoers file (/etc/sudoers.d/bug-fix gone)"
as_agentcore 'test -x /usr/bin/setpriv' || fail "/usr/bin/setpriv missing"
ok "$(as_agentcore 'setpriv --version')"

# Identity after the drop, from /proc/self/status.
check_status() {
  local label="$1" status="$2"
  field() { echo "$status" | awk -v k="$1:" '$1 == k { $1 = ""; sub(/^ +/, ""); print }'; }
  [ "$(field Uid)" = "10002 10002 10002 10002" ] || fail "$label: Uid is '$(field Uid)'"
  [ "$(field Gid)" = "10002 10002 10002 10002" ] || fail "$label: Gid is '$(field Gid)'"
  [ -z "$(field Groups)" ] || fail "$label: supplementary Groups '$(field Groups)'"
  for cap in CapInh CapPrm CapEff CapAmb; do
    [ "$(field "$cap")" = "0000000000000000" ] || fail "$label: $cap is '$(field "$cap")'"
  done
  [ "$(field NoNewPrivs)" = "1" ] || fail "$label: NoNewPrivs is '$(field NoNewPrivs)'"
  ok "$label: Uid/Gid 10002 x4, no Groups, CapInh/CapPrm/CapEff/CapAmb 0, NoNewPrivs 1 (CapBnd $(field CapBnd))"
}
check_status "setpriv drop under no-new-privileges" "$(as_agentcore "$SETPRIV cat /proc/self/status")"
# The flag itself sets no_new_privs, not only the container.
check_status "setpriv drop without the container flag" "$(as_root "$SETPRIV cat /proc/self/status")"

# No way back to root. Run without the container flag too, so it is
# setpriv's own --no-new-privs that neutralises the setuid binaries.
for runner in as_agentcore as_root; do
  if $runner "$SETPRIV python3 -c 'import os; os.setuid(0)'" >/dev/null 2>&1; then
    fail "$runner: fixer can os.setuid(0)"
  fi
  if $runner "$SETPRIV python3 -c 'import os; os.setgid(0)'" >/dev/null 2>&1; then
    fail "$runner: fixer can os.setgid(0)"
  fi
  if $runner "$SETPRIV su root -c true </dev/null" >/dev/null 2>&1; then
    fail "$runner: fixer can su root"
  fi
  if $runner "$SETPRIV setpriv --reuid=0 --regid=0 -- true" >/dev/null 2>&1; then
    fail "$runner: fixer can setpriv --reuid=0"
  fi
  # A setuid-root binary must not raise fixer's euid (no_new_privs).
  suid_euid="$($runner "cp /usr/bin/id /tmp/id-suid && chmod 4755 /tmp/id-suid && $SETPRIV /tmp/id-suid -u")"
  [ "$suid_euid" = "10002" ] || fail "$runner: a setuid-root binary ran as euid $suid_euid"
  ok "$runner: fixer can't regain root (os.setuid(0), os.setgid(0), su root, setpriv --reuid=0, setuid-root binary)"
done
# Control: the same setuid-root binary without --no-new-privs (and without the
# container flag) does run as root, so the check above is not vacuous.
control="$(as_root 'cp /usr/bin/id /tmp/id-suid && chmod 4755 /tmp/id-suid && setpriv --reuid=10002 --regid=10002 --clear-groups -- /tmp/id-suid -u')"
[ "$control" = "0" ] || fail "control: setuid-root id without no_new_privs gave euid $control, expected 0"
ok "control: without no_new_privs the setuid-root binary runs as euid 0, so --no-new-privs is what stops it"

# /proc isolation from the root wrapper (SC-IC-03).
proc_out="$(as_agentcore "env SECRET_SENTINEL=leak-7f3a sleep 30 & pid=\$!; sleep 0.3; \
  $SETPRIV cat /proc/\$pid/environ 2>/dev/null || echo environ:denied; \
  $SETPRIV python3 -c \"import sys; open('/proc/' + sys.argv[1] + '/mem', 'rb').read(1)\" \$pid 2>/dev/null || echo mem:denied; \
  $SETPRIV cat /proc/1/environ 2>/dev/null || echo init:denied; \
  kill \$pid")"
echo "$proc_out" | grep -q 'leak-7f3a' && fail "fixer read the root wrapper's /proc/<pid>/environ"
for want in environ:denied mem:denied init:denied; do
  echo "$proc_out" | grep -qx "$want" || fail "expected $want, got: $proc_out"
done
ok "fixer can't read a root process's /proc/<pid>/environ or /proc/<pid>/mem, nor /proc/1/environ"

# fixer_exec.py: the env is rebuilt from the allow-list; it refuses root.
as_agentcore 'test -x /usr/local/bin/python3' || fail "/usr/local/bin/python3 missing (fixer_exec.py interpreter)"
envout="$(as_agentcore "env AWS_ACCESS_KEY_ID=leak-7f3a CI=1 LANG=C.UTF-8 $FIXER_EXEC /usr/bin/env")"
names="$(echo "$envout" | cut -d= -f1 | sort | tr '\n' ' ')"
[ "$names" = "CI HOME LANG PATH " ] || fail "fixer_exec.py env is '$names', expected 'CI HOME LANG PATH '"
ok "fixer_exec.py rebuilds the env from the allow-list ($names)"
set +e
as_agentcore '/usr/local/bin/python3 -I /app/fixer_exec.py /usr/bin/true' >/dev/null 2>&1
rc=$?
set -e
[ "$rc" = "3" ] || fail "fixer_exec.py as root exited $rc, expected 3 (refuses root)"
ok "fixer_exec.py refuses to exec as root (exit 3)"

# sandbox.py's own paths and prefix, as the wrapper uses them.
as_agentcore "cd /app && python3 -c 'from sandbox import Sandbox, Mode; s = Sandbox(); s.check_available(Mode.SCRIPT); s.check_available(Mode.CLI)'" \
  || fail "sandbox.py DEFAULT_PATHS don't match the image"
ok "sandbox.py DEFAULT_PATHS exist in the image (setpriv, python, fixer_exec, srt, settings, claude)"
switched="$(as_agentcore "cd /app && python3 -c 'import subprocess; from sandbox import DEFAULT_PATHS, build_env, fixer_prefix; \
print(subprocess.run([*fixer_prefix(DEFAULT_PATHS), \"/usr/bin/id\", \"-u\"], env=build_env(None), capture_output=True, text=True).stdout.strip())'")"
[ "$switched" = "10002" ] || fail "sandbox.fixer_prefix ran 'id -u' as '$switched', expected 10002"
ok "sandbox.fixer_prefix runs as 10002 under no_new_privs"

# The production sweep: every fixer process (daemon included), no root process.
# Zombies are not counted: the throwaway container's pid 1 is a plain shell
# that doesn't reap orphans (in the runtime, the wrapper reaps them).
sweep_out="$(as_agentcore "sleep 1000 & root_pid=\$!; \
  $SETPRIV sh -c 'setsid sleep 1000 >/dev/null 2>&1 </dev/null &'; sleep 0.3; \
  cd /app && python3 -c 'from sandbox import Sandbox; Sandbox().sweep()'; sleep 0.3; \
  echo fixer=\$(ps -u 10002 -o stat= | grep -vc '^Z'); \
  kill -0 \$root_pid && echo root=alive; kill \$root_pid")"
echo "$sweep_out" | grep -qx 'fixer=0' || fail "fixer process(es) survived Sandbox().sweep(): $sweep_out"
echo "$sweep_out" | grep -qx 'root=alive' || fail "Sandbox().sweep() killed a root process: $sweep_out"
ok "Sandbox().sweep() leaves no fixer process (setsid daemon included) and spares root's"

# localhost for the sandbox proxy (S-182 re-probes 2b, 2c; fix round 3). srt
# and the CLI point their proxy at `localhost`, the sandbox's net namespace has
# no DNS, and AgentCore's /etc/hosts is empty and read-only. The image resolves
# `localhost` with nss-myhostname and prefers IPv4 through gai.conf. AgentCore
# is emulated by bind-mounting an empty, read-only file over /etc/hosts.
cid="$(docker create --platform "$PLATFORM" "$IMAGE")"
img_hosts="$(docker export "$cid" | tar -xOf - etc/hosts | wc -c | tr -d ' ')"
docker rm "$cid" >/dev/null
[ "$img_hosts" = "0" ] || fail "image /etc/hosts is ${img_hosts} bytes; expected empty (update sandbox.py's note if this changed)"
ok "image /etc/hosts is empty (localhost must come from NSS)"

nss_line="$(as_root "grep -E '^hosts:' /etc/nsswitch.conf")"
echo "$nss_line" | grep -qxE 'hosts:[[:space:]]+files myhostname dns' \
  || fail "nsswitch hosts line is '$nss_line', expected 'files myhostname dns'"
ok "nsswitch: $nss_line (myhostname before dns)"

as_root "grep -qxF 'precedence ::ffff:0:0/96 100' /etc/gai.conf" \
  || fail "/etc/gai.conf missing or without 'precedence ::ffff:0:0/96 100'"
ok "/etc/gai.conf prefers IPv4 (precedence ::ffff:0:0/96 100)"

hosts_tmp="$(mktemp)"
: > "$hosts_tmp"
# `getent hosts` asks for AF_INET6 first and always prints ::1, so the IPv4
# answer is checked with ahostsv4 and the order with getaddrinfo (as Python,
# Node and pip use it).
hosts_out="$(docker run --rm --platform "$PLATFORM" --security-opt no-new-privileges \
  --mount "type=bind,src=$hosts_tmp,dst=/etc/hosts,readonly" --entrypoint /bin/sh "$IMAGE" -c \
  "if { echo x >> /etc/hosts; } 2>/dev/null; then echo hosts=writable; else echo hosts=read-only; fi; \
   echo getent=\$(getent ahostsv4 localhost | awk 'NR == 1 {print \$1}'); \
   cd /app && python3 -c 'from sandbox import Sandbox; print(\"via=\" + Sandbox().check_localhost())'; \
   echo hosts_bytes=\$(wc -c < /etc/hosts); \
   $SETPRIV python3 -c 'import socket; print(\"first=\" + socket.getaddrinfo(\"localhost\", None)[0][4][0])'")"
rm -f "$hosts_tmp"
want="$(printf 'hosts=read-only\ngetent=127.0.0.1\nvia=nss\nhosts_bytes=0\nfirst=127.0.0.1')"
[ "$hosts_out" = "$want" ] || fail "empty read-only /etc/hosts: expected '$want', got: $hosts_out"
ok "empty read-only /etc/hosts (AgentCore): the mount is read-only; getent ahostsv4 localhost = 127.0.0.1 through NSS"
ok "empty read-only /etc/hosts: Sandbox().check_localhost() = nss, /etc/hosts left untouched; fixer's getaddrinfo(localhost) gives 127.0.0.1 first"

# Defence in depth for WebFetch/WebSearch: the pinned CLI accepts the flag
# sandbox.py adds to every headless run.
flag="$(as_agentcore "cd /app && python3 -c 'from sandbox import CLI_DISALLOWED_FLAG; print(CLI_DISALLOWED_FLAG)'")"
[ "$flag" = "--disallowedTools=WebFetch,WebSearch" ] || fail "unexpected CLI_DISALLOWED_FLAG: $flag"
as_agentcore "$FIXER_EXEC /usr/bin/claude $flag --version" | grep -qF "$pinned" \
  || fail "claude rejects $flag"
ok "pinned claude accepts $flag"

# --- Dirs (TC-180-08) -----------------------------------------------------------
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
  [ "$om" = "root:root 700" ] || fail "$d is $om, expected root:root 700"
  ok "$d $om"
done
for d in /work/wrapper /work/secrets /root; do
  if as_agentcore "$SETPRIV ls $d" >/dev/null 2>&1; then
    fail "fixer can list $d"
  fi
  ok "fixer can't list $d"
done

# --- Managed policy (TC-180-09) -------------------------------------------------
policy=/etc/claude-code/managed-settings.json
om="$(owner_mode "$policy")"
[ "$om" = "root:root 644" ] || fail "$policy is $om, expected root:root 644"
ok "$policy $om"
om="$(owner_mode /etc/claude-code)"
[ "$om" = "root:root 755" ] || fail "/etc/claude-code is $om, expected root:root 755"
ok "/etc/claude-code $om"

if as_agentcore "$SETPRIV sh -c \"echo '{}' >> $policy\"" >/dev/null 2>&1; then
  fail "fixer can append to $policy"
fi
if as_agentcore "$SETPRIV touch /etc/claude-code/x" >/dev/null 2>&1; then
  fail "fixer can write to /etc/claude-code"
fi
ok "fixer can't modify the policy or its directory"

as_agentcore "$SETPRIV python3 -c 'import json; json.load(open(\"$policy\"))'" || fail "$policy is not valid JSON for fixer"
ok "policy is readable JSON for fixer"

srt_policy=/etc/bug-fix/srt-settings.json
om="$(owner_mode "$srt_policy")"
[ "$om" = "root:root 644" ] || fail "$srt_policy is $om, expected root:root 644"
ok "$srt_policy $om"
if as_agentcore "$SETPRIV sh -c \"echo '{}' >> $srt_policy\"" >/dev/null 2>&1; then
  fail "fixer can append to $srt_policy"
fi
ok "fixer can't modify $srt_policy"

# --- Wrapper git (S-189: TC-189-18, TC-189-19; D-62, D-110) -----------------------
as_root 'git --attr-source=4b825dc642cb6eb9a060e54bf8d69288fbee4904 version' >/dev/null \
  || fail "git does not support --attr-source (safe_git.py needs git >= 2.40)"
ok "$(as_root 'git --version') supports --attr-source"

# One container, as AgentCore runs it (root, no_new_privs): a local bare
# remote, then safe_git's clone, materialize as fixer, a fixer plant, capture.
git_out="$(docker run --rm -i --platform "$PLATFORM" --security-opt no-new-privileges \
  -w /app --entrypoint python3 "$IMAGE" - <<'PY'
import os, stat, subprocess, sys
sys.path.insert(0, "/app")
from safe_git import clone
from sandbox import DEFAULT_PATHS, as_fixer

E = {"PATH": "/usr/bin:/bin", "HOME": "/root", "GIT_CONFIG_GLOBAL": "/dev/null",
     "GIT_AUTHOR_NAME": "s", "GIT_AUTHOR_EMAIL": "s@s", "GIT_COMMITTER_NAME": "s",
     "GIT_COMMITTER_EMAIL": "s@s"}
def sh(*a, **k): subprocess.run(list(a), check=True, env=E, stdout=subprocess.DEVNULL, **k)
os.makedirs("/tmp/src/src")
open("/tmp/src/src/app.py", "w").write("x = 1\n")
sh("git", "init", "-q", "-b", "main", "/tmp/src")
sh("git", "-C", "/tmp/src", "add", "-A")
sh("git", "-C", "/tmp/src", "commit", "-q", "-m", "s")
sh("git", "clone", "-q", "--bare", "/tmp/src", "/tmp/remote.git")

git = clone("file:///tmp/remote.git", "main", "/work/wrapper/repo")
print("clone_mode=" + oct(stat.S_IMODE(os.stat("/work/wrapper/repo").st_mode)))
print("clone_owner=%d" % os.stat("/work/wrapper/repo").st_uid)
git.materialize(git.base_sha, "/work/repo")
print("file_owner=%d" % os.lstat("/work/repo/src/app.py").st_uid)
print("dotgit=%s" % os.path.exists("/work/repo/.git"))

fixer = [*as_fixer(DEFAULT_PATHS), "/usr/bin/env", "HOME=/home/fixer", "PATH=/usr/bin:/bin"]
plant = ("cd /work/repo && git init -q && "
         "printf '#!/bin/sh\\ntouch /tmp/canary-hook\\n' > .git/hooks/post-index-change && "
         "chmod +x .git/hooks/post-index-change && "
         "git config core.fsmonitor 'touch /tmp/canary-fsmonitor; false' && "
         "echo edit > src/app.py")
subprocess.run([*fixer, "sh", "-c", plant], check=True)
tree = git.capture("/work/repo")
print("changes=" + ",".join(sorted(c.path for c in git.changes(git.tree_of(git.base_sha), tree))))
print("canary=%s" % (os.path.exists("/tmp/canary-hook") or os.path.exists("/tmp/canary-fsmonitor")))
r = subprocess.run([*fixer, "cat", "/work/wrapper/repo/.git/config"], capture_output=True)
print("fixer_reads_config=%s" % (r.returncode == 0))
r = subprocess.run([*fixer, "ls", "/work/wrapper"], capture_output=True)
print("fixer_lists_wrapper=%s" % (r.returncode == 0))
# Control: the plants are live when git does use the fixer repository.
subprocess.run([*fixer, "sh", "-c", "cd /work/repo && git add -A"], capture_output=True)
print("control=%s" % (os.path.exists("/tmp/canary-hook") or os.path.exists("/tmp/canary-fsmonitor")))
PY
)" || fail "wrapper git smoke failed: $git_out"
want_git="$(printf 'clone_mode=0o700\nclone_owner=0\nfile_owner=10002\ndotgit=False\nchanges=src/app.py\ncanary=False\nfixer_reads_config=False\nfixer_lists_wrapper=False\ncontrol=True')"
[ "$git_out" = "$want_git" ] || fail "wrapper git: expected '$want_git', got: $git_out"
ok "safe_git.clone as root under no_new_privs: /work/wrapper/repo is root-owned 0700"
ok "materialize: /work/repo files owned by fixer (10002) through setpriv, no .git"
ok "a fixer-planted .git/hooks and core.fsmonitor never run in the wrapper's capture; the capture sees only src/app.py"
ok "as fixer, /work/wrapper can't be listed and /work/wrapper/repo/.git/config can't be read (TC-189-19)"
ok "control: the plants do fire when git uses the fixer repository"

# --- S-189 fix round: link protection (QA-189-01) and GNU tar (gap 6) -----------
# The kernel's link protection stops fixer from hardlinking a file it can't
# read into /work/repo. safe_git.check_work_tree refuses hardlinks anyway;
# the run-time preflight only logs these (the AgentCore value is probe #446's).
links="$(as_agentcore 'cat /proc/sys/fs/protected_hardlinks /proc/sys/fs/protected_symlinks' | tr '\n' ' ')"
[ "$links" = "1 1 " ] || fail "fs.protected_hardlinks / fs.protected_symlinks are '$links', expected '1 1'"
ok "fs.protected_hardlinks and fs.protected_symlinks are 1 in the image"

# A tree with a symlink `zlink -> /tmp/outside` and a file `zlink/b.txt` (a
# duplicate name git add never writes), through materialize with the image's
# GNU tar as fixer. fsck refuses it at the clone (the control); with fsck off
# for this clone only, nothing may be written through the link.
tar_out="$(docker run --rm -i --platform "$PLATFORM" --security-opt no-new-privileges \
  -w /app --entrypoint python3 "$IMAGE" - <<'PY'
import os, subprocess, sys
sys.path.insert(0, "/app")
import safe_git
from safe_git import GitError, clone

E = {"PATH": "/usr/bin:/bin", "HOME": "/root", "GIT_CONFIG_GLOBAL": "/dev/null",
     "GIT_AUTHOR_NAME": "s", "GIT_AUTHOR_EMAIL": "s@s", "GIT_COMMITTER_NAME": "s",
     "GIT_COMMITTER_EMAIL": "s@s"}
def g(*a, inp=None):
    return subprocess.run(["git", *a], cwd="/tmp/src", env=E, input=inp,
                          capture_output=True, check=True).stdout.decode().strip()
v = subprocess.run(["/usr/bin/tar", "--version"], capture_output=True, text=True).stdout
print("gnu_tar=%s" % v.startswith("tar (GNU tar)"))
os.makedirs("/tmp/src")
os.makedirs("/tmp/outside")
os.chmod("/tmp/outside", 0o777)  # writable by fixer: the check is not vacuous
g("init", "-q", "-b", "main")
link = g("hash-object", "-w", "--stdin", inp=b"/tmp/outside")
blob = g("hash-object", "-w", "--stdin", inp=b"through\n")
sub = g("mktree", inp=("100644 blob %s\tb.txt\n" % blob).encode())
raw = b"120000 zlink\0" + bytes.fromhex(link) + b"40000 zlink\0" + bytes.fromhex(sub)
tree = g("hash-object", "-t", "tree", "--literally", "-w", "--stdin", inp=raw)
g("update-ref", "refs/heads/main", g("commit-tree", tree, "-m", "hostile"))
subprocess.run(["git", "clone", "-q", "--bare", "/tmp/src", "/tmp/remote.git"], env=E, check=True)
try:
    clone("file:///tmp/remote.git", "main", "/work/wrapper/fsck")
    print("fsck_refuses=False")
except GitError:
    print("fsck_refuses=True")
safe_git.CLONE_FSCK_ARGS = ()
git = clone("file:///tmp/remote.git", "main", "/work/wrapper/repo")
try:
    git.materialize(git.base_sha, "/work/repo")
except GitError:
    pass
print("outside_empty=%s" % (os.listdir("/tmp/outside") == []))
print("through=%s" % os.path.exists("/tmp/outside/b.txt"))
PY
)" || fail "GNU tar smoke failed: $tar_out"
want_tar="$(printf 'gnu_tar=True\nfsck_refuses=True\noutside_empty=True\nthrough=False')"
[ "$tar_out" = "$want_tar" ] || fail "GNU tar: expected '$want_tar', got: $tar_out"
ok "the image's tar is GNU tar"
ok "the clone's fsckObjects refuses a tree with a symlink and a directory under one name"
ok "with fsck off, materialize through GNU tar as fixer writes nothing through the symlink"

echo "image-smoke: ${pass} checks passed for ${IMAGE}"
