# bug-fix agent image (S-180). ARM64 only: the AgentCore runtime has no x86_64
# fallback, so `make image` builds with --platform linux/arm64.
#
# Layout (spec §7, §12; D-05, D-18, D-51):
#   - Python 3.13 for the wrapper; Node 22, 24 and 26 (one per repo, picked
#     from engines.node, node.py) + pnpm and Python for target repos (JS/TS
#     and Python stacks in v1, D-18).
#   - git, bubblewrap, socat and ripgrep: the Claude Code Bash sandbox runtime
#     on Linux (bwrap + a proxy for the registry-only network policy).
#   - A pinned @anthropic-ai/claude-code CLI (headless `claude -p`, D-05) and a
#     pinned @anthropic-ai/sandbox-runtime (`srt`), the same runtime as a
#     standalone CLI, for the wrapper's own fixer-run scripts (S-182).
#   - The wrapper runs as root (D-110). AgentCore starts the container with
#     no_new_privs set, so setuid sudo can't run (S-182 probe run 1, which
#     retired D-109's sudo rule). Every process that runs model output or repo
#     code is started by sandbox.py through `setpriv --reuid=10002
#     --regid=10002 --clear-groups --inh-caps=-all --no-new-privs`, which
#     drops privileges and works under no_new_privs. Only wrapper code runs as
#     root; there is one microVM per AgentCore session.
#   - One unprivileged OS user, `fixer` (uid 10002), runs the CLI and repo
#     scripts. No sudo and no sudo rule.
#   - /etc/claude-code/managed-settings.json, root-owned 0644: the managed
#     policy, which takes precedence over a target repo's own .claude/ (D-51).
#   - `localhost` resolves through NSS, not /etc/hosts. srt and the CLI's
#     Bash sandbox point their proxy at `localhost` (hard-coded), and the
#     sandbox's network namespace has no DNS (S-182 re-probe 2b). On AgentCore
#     /etc/hosts is empty and read-only (re-probe 2c), and BuildKit
#     bind-mounts it during the build, so neither the image nor the wrapper
#     can fill it. libnss-myhostname answers `localhost` without DNS, and
#     /etc/gai.conf puts 127.0.0.1 before ::1. sandbox.py only checks this
#     before each run; it never writes /etc/hosts.
#
# No secret is baked in. The runtime env carries secret IDs only.
#
# Base images come from AWS ECR Public (a mirror of the Docker Library images)
# rather than Docker Hub, to avoid anonymous pull rate limits in CodeBuild
# (sibling agent's issue #77).

FROM public.ecr.aws/docker/library/python:3.13-slim

# Custom CA certificates (e.g. a corporate proxy). Pass at build time with
# --build-arg EXTRA_CA_CERT=path/to/cert.pem; without it an empty placeholder
# is copied and skipped.
ARG EXTRA_CA_CERT=.ca-placeholder
COPY ${EXTRA_CA_CERT} /usr/local/share/ca-certificates/extra-ca.crt
RUN if [ -s /usr/local/share/ca-certificates/extra-ca.crt ]; then \
      update-ca-certificates; \
    fi

# System toolchain. bubblewrap, socat and ripgrep are the Claude Code sandbox
# runtime's Linux dependencies; git is used by the wrapper's own clone (D-62)
# and by repo scripts; make runs Python repos' gate targets (D-19); util-linux
# provides setpriv, the root -> fixer drop (D-110); procps provides
# /usr/bin/kill and /usr/bin/pkill for the post-run sweep of every fixer
# process (D-62); libnss-myhostname resolves `localhost` (see below);
# libatomic1 is the one shared library the nodejs.org Node binaries need. The
# build fails if setpriv is missing or sudo is present.
# safe_git.py (S-189, D-62) needs git >= 2.40 for `--attr-source` (the wrapper
# reads no attributes from a fixer-written .gitattributes), and spawns
# /usr/bin/tar and /usr/bin/rm as fixer; the build fails without them.
RUN apt-get update && apt-get install -y --no-install-recommends \
      bubblewrap ca-certificates curl git gnupg libatomic1 libnss-myhostname make procps ripgrep \
      socat util-linux && \
    rm -rf /var/lib/apt/lists/* && \
    command -v setpriv && \
    ! command -v sudo && \
    git --attr-source=4b825dc642cb6eb9a060e54bf8d69288fbee4904 version && \
    test -x /usr/bin/git && test -x /usr/bin/tar && test -x /usr/bin/rm

# `localhost` for the sandbox proxy (S-182 fix round 3). AgentCore's /etc/hosts
# is empty and read-only (re-probe 2c), and the sandbox's network namespace has
# no DNS, so srt's and the CLI's `http://…@localhost:<port>` proxy can only
# resolve through nss-myhostname, which must come before `dns`. The hosts line
# is written explicitly, and the grep fails the build if it didn't take.
# getaddrinfo would return ::1 before 127.0.0.1, and srt's in-namespace bridge
# may listen on IPv4 only, so gai.conf prefers IPv4-mapped addresses.
RUN sed -i -E 's/^hosts:.*/hosts:          files myhostname dns/' /etc/nsswitch.conf && \
    grep -qxE 'hosts:[[:space:]]+files myhostname dns' /etc/nsswitch.conf && \
    printf '%s\n' \
      '# bug-fix image (S-182 fix round 3): prefer 127.0.0.1 over ::1 for localhost.' \
      'precedence ::ffff:0:0/96 100' > /etc/gai.conf

# Node.js, one per supported major, side by side under /opt/node/<major>
# (node.py). A target repo pins its Node with engines.node, and pnpm refuses a
# frozen install on any other (ERR_PNPM_UNSUPPORTED_ENGINE), so the wrapper
# picks one per repo and puts /opt/node/<major>/bin first on fixer's PATH.
# NODE_VERSIONS must equal node.NODE_VERSIONS (a unit test pins both, and the
# SHA-256 below for each). Official linux-arm64 tarballs from nodejs.org, each
# checked before it is unpacked. NODE_DEFAULT is /usr/bin/node: the wrapper's
# own tools, and a repo that pins nothing.
ARG NODE_VERSIONS="22.23.4 24.22.2 26.12.1"
ARG NODE_DEFAULT=26.12.1
RUN set -eu; \
    cd /tmp; \
    printf '%s\n' \
      'f7a1e486dbc8b286847815b477d4fb5e9fb963ed4489c3e1588853d685f589f9  node-v22.23.4-linux-arm64.tar.gz' \
      '95c264150aceb7f3437a29fd6984924f5f8d1511ea3cbd6c508b83f6c555dae2  node-v24.22.2-linux-arm64.tar.gz' \
      'a6c01af459dd8972ab3fb08ee5da81244d26ba8c4944a62d5bbba8c597ae154f  node-v26.12.1-linux-arm64.tar.gz' \
      > node-sha256.txt; \
    for v in ${NODE_VERSIONS}; do \
      curl -fsSLO "https://nodejs.org/dist/v${v}/node-v${v}-linux-arm64.tar.gz"; \
    done; \
    sha256sum -c node-sha256.txt; \
    for v in ${NODE_VERSIONS}; do \
      dir="/opt/node/${v%%.*}"; \
      install -d -o root -g root -m 0755 "$dir"; \
      tar -xzf "node-v${v}-linux-arm64.tar.gz" -C "$dir" --strip-components=1 --no-same-owner; \
      test "$("$dir/bin/node" --version)" = "v${v}"; \
    done; \
    rm -f node-v*-linux-arm64.tar.gz node-sha256.txt; \
    chmod -R go-w /opt/node; \
    for tool in node npm npx; do \
      ln -s "/opt/node/${NODE_DEFAULT%%.*}/bin/${tool}" "/usr/bin/${tool}"; \
    done; \
    test "$(node --version)" = "v${NODE_DEFAULT}"

# pnpm, the Claude Code CLI and the sandbox runtime, all pinned. Node >= 25 no
# longer bundles corepack, so pnpm is installed directly. --prefix /usr keeps
# them at /usr/bin (sandbox.SandboxPaths), outside every /opt/node tree. They
# are `#!/usr/bin/env node` scripts, so each runs on the repo's Node when its
# bin is first on PATH; all three accept every shipped major (>=22.12).
# Everything is installed root-owned, so fixer can't modify or update it; the
# auto-updater is off.
ARG PNPM_VERSION=10.11.0
ARG CLAUDE_CODE_VERSION=2.1.309
ARG SANDBOX_RUNTIME_VERSION=0.0.81
RUN npm install -g --prefix /usr --no-fund --no-audit \
      "pnpm@${PNPM_VERSION}" \
      "@anthropic-ai/claude-code@${CLAUDE_CODE_VERSION}" \
      "@anthropic-ai/sandbox-runtime@${SANDBOX_RUNTIME_VERSION}" && \
    npm cache clean --force
ENV DISABLE_AUTOUPDATER=1 \
    CLAUDE_CODE_VERSION=${CLAUDE_CODE_VERSION} \
    SANDBOX_RUNTIME_VERSION=${SANDBOX_RUNTIME_VERSION}

# The fixer user: a fixed, non-zero uid and its own primary group, in no
# other group. sandbox.py pins the same uid/gid in its setpriv flags. Its home
# is private; root's home (/root) is 0700 already.
ARG FIXER_UID=10002
RUN groupadd --gid "${FIXER_UID}" fixer && \
    useradd --uid "${FIXER_UID}" --gid fixer --create-home --home-dir /home/fixer \
      --shell /bin/bash fixer && \
    chmod 0700 /home/fixer

# Work directories (spec §7, D-62, D-110):
#   /work/repo, /work/out  -> fixer: the checkout the CLI edits, and its output
#   /work/wrapper          -> root, 0700: the wrapper's own clone
#                             (/work/wrapper/repo, safe_git.py, S-189); fixer
#                             can't list it or read its .git
#   /work/secrets          -> root, 0700: never readable by fixer (and
#                             denied in the managed policy as well)
RUN install -d -o root -g root -m 0755 /work && \
    install -d -o fixer -g fixer -m 0755 /work/repo /work/out && \
    install -d -o root -g root -m 0700 /work/wrapper /work/secrets

# Managed Claude Code policy: root-owned, 0644, directory not writable by
# fixer.
COPY managed-settings.json /etc/claude-code/managed-settings.json
RUN chown -R root:root /etc/claude-code && \
    chmod 0755 /etc/claude-code && \
    chmod 0644 /etc/claude-code/managed-settings.json

# Sandbox-runtime policy for the wrapper's fixer-run scripts (S-182): the same
# registry-only network allow-list as the managed Claude Code policy.
COPY srt-settings.json /etc/bug-fix/srt-settings.json
RUN chown -R root:root /etc/bug-fix && \
    chmod 0755 /etc/bug-fix && \
    chmod 0644 /etc/bug-fix/srt-settings.json

# Python deps for the wrapper, installed system-wide as root.
WORKDIR /app
COPY pyproject.toml .
RUN pip install --no-cache-dir .

# Agent code (root-owned, read-only to fixer).
COPY . .
RUN chmod -R a+rX,go-w /app

# The wrapper runs as root and drops to fixer per process (D-110).
USER root
ENV HOME=/root
EXPOSE 8080
CMD ["python", "main.py"]
