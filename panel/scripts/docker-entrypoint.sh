#!/bin/sh
#
# docker-entrypoint.sh — panel runtime entrypoint (Issue #280, D-03/D-04).
#
# WHY THIS EXISTS. Fly creates the Machine OIDC socket `/.fly/api` at boot as
# `srwxr-xr-x 0:0` (root-owned, mode 0755). Connecting to a unix socket needs
# WRITE permission on it, which "other" lacks — so the non-root panel server
# (uid 1001, `nextjs`) gets EACCES and cannot obtain an OIDC token, which is why
# every invoke from the deployed panel failed since release v12. The image build
# cannot fix this: the socket does not exist until the Machine boots.
#
# WHAT THIS DOES. The container now starts AS ROOT (the Dockerfile no longer sets
# `USER nextjs`). This script, running as root:
#   1. If `/.fly/api` exists as a socket, grants the `nodejs` group write access
#      to it (`chgrp nodejs` + `chmod g+w`) — the minimum needed, GROUP write
#      only, NEVER world-writable. On failure it logs a warning and continues;
#      the credential provider then fails loudly at invoke time, exactly as
#      today, rather than this script failing startup.
#   2. ALWAYS drops privileges to uid/gid 1001 via `setpriv` and `exec`s node, so
#      the server is PID 1 running as `nextjs` — node is never run as root.
#
# `setpriv` ships with util-linux in node:22-slim; nothing is installed (D-04).
# `--init-groups` sets the supplementary groups for uid 1001 (so `nodejs` group
# membership — and thus the socket grant — actually applies).
#
# A MISSING SOCKET MUST NEVER FAIL STARTUP (D-04): off Fly (local `docker run`,
# CI image smoke test) there is no `/.fly/api`, so the grant is skipped and the
# server still starts and drops to uid 1001. `credentials.ts` already treats
# "app name set + socket present" as the Fly branch and otherwise uses the local
# chain, so off-Fly behavior is unchanged.
#
# `exec` is REQUIRED: node must become PID 1 so Fly's SIGTERM on stop reaches
# node directly with no shell left in between.

set -eu

SOCKET="/.fly/api"

if [ -S "$SOCKET" ]; then
  # Group-grant the socket to `nodejs` so uid 1001 can connect. Best-effort: a
  # failure (e.g. the platform forbids chmod/chgrp on the socket) is a warning,
  # not a startup failure — the deploy-time OIDC probe (deploy-panel.sh) catches
  # a non-working credential path and fails the release with exit 3.
  if chgrp nodejs "$SOCKET" && chmod g+w "$SOCKET"; then
    echo "entrypoint: granted group 'nodejs' write on $SOCKET (#280)" >&2
  else
    echo "warn: could not grant group write on $SOCKET; OIDC may fail as uid 1001 (#280)" >&2
  fi
else
  # No socket: off Fly, or Fly has not created it. Never fail startup (D-04).
  echo "entrypoint: $SOCKET absent — skipping socket grant (off-Fly or pre-boot) (#280)" >&2
fi

# Drop to the non-root runtime user and hand off PID 1 to node.
exec setpriv --reuid=1001 --regid=1001 --init-groups node panel/server.js
