# bug-fix agent image (S-180). ARM64 only: the AgentCore runtime has no x86_64
# fallback, so `make image` builds with --platform linux/arm64.
#
# Layout (spec §7, §12; D-05, D-18, D-51):
#   - Python 3.13 for the wrapper; Node 26 + pnpm and Python for target repos
#     (JS/TS and Python stacks in v1, D-18).
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
#   - /etc/hosts is NOT set here: BuildKit bind-mounts it during the build, so
#     a COPY or RUN can't fill it and the image ships it empty. srt and the
#     CLI's Bash sandbox point their proxy at `localhost`, which must resolve
#     from /etc/hosts inside the sandbox's network namespace; sandbox.py adds
#     `127.0.0.1 localhost` at run time when the runtime (AgentCore) didn't
#     (S-182 re-probe 2b).
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
# process (D-62). The build fails if setpriv is missing or sudo is present.
RUN apt-get update && apt-get install -y --no-install-recommends \
      bubblewrap ca-certificates curl git gnupg make procps ripgrep socat util-linux && \
    rm -rf /var/lib/apt/lists/* && \
    command -v setpriv && \
    ! command -v sudo

# Node.js 26 (NodeSource, same mechanism as the sibling image).
ARG NODE_MAJOR=26
RUN curl -fsSL "https://deb.nodesource.com/setup_${NODE_MAJOR}.x" | bash - && \
    apt-get install -y --no-install-recommends nodejs && \
    rm -rf /var/lib/apt/lists/*

# pnpm, the Claude Code CLI and the sandbox runtime, all pinned. Node >= 25 no
# longer bundles corepack, so pnpm is installed directly. Everything is
# installed root-owned, so fixer can't modify or update it; the auto-updater is
# off.
ARG PNPM_VERSION=10.11.0
ARG CLAUDE_CODE_VERSION=2.1.309
ARG SANDBOX_RUNTIME_VERSION=0.0.81
RUN npm install -g --no-fund --no-audit \
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

# Work directories (spec §7, D-62):
#   /work/repo, /work/out  -> fixer: the checkout the CLI edits, and its output
#   /work/wrapper          -> root, 0700: the wrapper's own clone
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
