# bug-fix agent image (S-180). ARM64 only: the AgentCore runtime has no x86_64
# fallback, so `make image` builds with --platform linux/arm64.
#
# Layout (spec §7, §12; D-05, D-18, D-51):
#   - Python 3.13 for the wrapper; Node 26 + pnpm and Python for target repos
#     (JS/TS and Python stacks in v1, D-18).
#   - git, bubblewrap and socat: the Claude Code Bash sandbox runtime on Linux.
#   - A pinned @anthropic-ai/claude-code CLI (headless `claude -p`, D-05).
#   - Two OS users with different uids: `wrapper` (runs this process and holds
#     every secret in memory) and `fixer` (runs the CLI and repo scripts).
#   - /etc/claude-code/managed-settings.json, root-owned 0644: the managed
#     policy, which takes precedence over a target repo's own .claude/ (D-51).
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

# System toolchain. bubblewrap + socat are the Claude Code sandbox runtime's
# Linux dependencies; git is used by the wrapper's own clone (D-62) and by
# repo scripts; make runs Python repos' gate targets (D-19).
RUN apt-get update && apt-get install -y --no-install-recommends \
      bubblewrap ca-certificates curl git gnupg make socat && \
    rm -rf /var/lib/apt/lists/*

# Node.js 26 (NodeSource, same mechanism as the sibling image).
ARG NODE_MAJOR=26
RUN curl -fsSL "https://deb.nodesource.com/setup_${NODE_MAJOR}.x" | bash - && \
    apt-get install -y --no-install-recommends nodejs && \
    rm -rf /var/lib/apt/lists/*

# pnpm and the Claude Code CLI, both pinned. Node >= 25 no longer bundles
# corepack, so pnpm is installed directly. The CLI is installed root-owned, so
# neither runtime user can modify or update it; the auto-updater is off.
ARG PNPM_VERSION=10.11.0
ARG CLAUDE_CODE_VERSION=2.1.309
RUN npm install -g --no-fund --no-audit \
      "pnpm@${PNPM_VERSION}" \
      "@anthropic-ai/claude-code@${CLAUDE_CODE_VERSION}" && \
    npm cache clean --force
ENV DISABLE_AUTOUPDATER=1 \
    CLAUDE_CODE_VERSION=${CLAUDE_CODE_VERSION}

# Users. Fixed, distinct, non-zero uids and separate primary groups; `fixer`
# is in no group of `wrapper`'s and has no sudo. Home directories are private.
ARG WRAPPER_UID=10001
ARG FIXER_UID=10002
RUN groupadd --gid "${WRAPPER_UID}" wrapper && \
    useradd --uid "${WRAPPER_UID}" --gid wrapper --create-home --home-dir /home/wrapper \
      --shell /usr/sbin/nologin wrapper && \
    groupadd --gid "${FIXER_UID}" fixer && \
    useradd --uid "${FIXER_UID}" --gid fixer --create-home --home-dir /home/fixer \
      --shell /bin/bash fixer && \
    chmod 0700 /home/wrapper /home/fixer

# Work directories (spec §7, D-62):
#   /work/repo, /work/out  -> fixer: the checkout the CLI edits, and its output
#   /work/wrapper          -> wrapper, 0700: the wrapper's own clone
#   /work/secrets          -> wrapper, 0700: never readable by fixer (and
#                             denied in the managed policy as well)
RUN install -d -o root -g root -m 0755 /work && \
    install -d -o fixer -g fixer -m 0755 /work/repo /work/out && \
    install -d -o wrapper -g wrapper -m 0700 /work/wrapper /work/secrets

# Managed Claude Code policy: root-owned, 0644, directory not writable by
# either runtime user.
COPY managed-settings.json /etc/claude-code/managed-settings.json
RUN chown -R root:root /etc/claude-code && \
    chmod 0755 /etc/claude-code && \
    chmod 0644 /etc/claude-code/managed-settings.json

# Python deps for the wrapper, installed system-wide as root.
WORKDIR /app
COPY pyproject.toml .
RUN pip install --no-cache-dir .

# Agent code (root-owned, read-only to the runtime users).
COPY . .
RUN chmod -R a+rX,go-w /app

USER wrapper
ENV HOME=/home/wrapper
EXPOSE 8080
CMD ["python", "main.py"]
