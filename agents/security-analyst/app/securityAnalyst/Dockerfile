# Base images come from AWS ECR Public (a mirror of the official Docker Library
# images) rather than Docker Hub: anonymous Docker Hub pulls from CodeBuild's
# shared IP ranges routinely hit "429 Too Many Requests", which fails the
# container build and rolls back the whole stack (sibling agent's issue #77).
#
# This story (S-125) scaffolded the deployable no-op with no scanner
# toolchains installed. S-132 (CodeQL, this addition) is the first story to
# extend this Dockerfile per spec S15.2 -- Semgrep/Gitleaks/Trivy/Checkov's
# own toolchain installs (S-128-S-131) are tracked as a separate, still-open
# gap flagged to planner (this story's own task list scopes only task 8.1,
# "add the two query packs to the Dockerfile") -- not fixed here to keep this
# story's diff scoped to its own issue (#192). git + gh CLI are enough for
# S-125's checkout step; CodeQL's own toolchain needs no compiler at all
# (see below).

FROM public.ecr.aws/docker/library/python:3.13-slim AS base

# Custom CA certificates (e.g. corporate proxy like Netskope)
# Pass at build time: --build-arg EXTRA_CA_CERT=path/to/cert.pem
# Without the arg, an empty placeholder is copied and skipped.
ARG EXTRA_CA_CERT=.ca-placeholder
COPY ${EXTRA_CA_CERT} /usr/local/share/ca-certificates/extra-ca.crt
RUN if [ -s /usr/local/share/ca-certificates/extra-ca.crt ]; then \
      update-ca-certificates; \
    fi

# System deps
# unzip -- added for the CodeQL CLI install below (task 8.1); the CLI ships
# as a .zip archive, not a .tar.gz like Gitleaks/Trivy's install scripts.
RUN apt-get update && apt-get install -y --no-install-recommends \
    git curl ca-certificates gnupg unzip && \
    rm -rf /var/lib/apt/lists/*

# gh CLI (from Debian repos as fallback when GitHub apt has SSL issues)
RUN curl -fsSL https://cli.github.com/packages/githubcli-archive-keyring.gpg \
    | dd of=/usr/share/keyrings/githubcli-archive-keyring.gpg && \
    echo "deb [signed-by=/usr/share/keyrings/githubcli-archive-keyring.gpg] \
    https://cli.github.com/packages stable main" \
    > /etc/apt/sources.list.d/github-cli.list && \
    apt-get update && apt-get install -y gh && \
    rm -rf /var/lib/apt/lists/*

# CodeQL CLI -- pinned v2.27.0 (task 8.0.1 blocking pre-check, PRD OQ5,
# spec S15.2): confirmed via the public GitHub Releases API that
# github/codeql-cli-binaries' v2.27.0 release ships a native
# `codeql-linux-arm64.zip` build, and github/codeql-action's matching
# `codeql-bundle-v2.27.0` tag ships a matching `codeql-bundle-linux-arm64`
# asset -- AgentCore Runtime is ARM64-only (no x86_64 fallback), so this
# confirmation was required before this stage could be written.
#
# Only 2 query packs, per PRD S7.4a -- no compiled-language packs (Java, Go,
# C/C++, etc.) ship in v1, and neither `javascript-typescript` nor `python`
# needs a compiled build step (PRD requirement 14), so no JDK/Go toolchain/
# C-C++ compiler is installed in this image at all.
ARG CODEQL_CLI_VERSION=2.27.0
RUN curl -sSfL \
    "https://github.com/github/codeql-cli-binaries/releases/download/v${CODEQL_CLI_VERSION}/codeql-linux-arm64.zip" \
    -o /tmp/codeql.zip && \
    unzip -q /tmp/codeql.zip -d /opt && \
    rm /tmp/codeql.zip && \
    ln -s /opt/codeql/codeql /usr/local/bin/codeql
RUN codeql pack download codeql/javascript-typescript-queries codeql/python-queries

# Python deps
WORKDIR /app
COPY pyproject.toml .
RUN pip install --no-cache-dir .

# Agent code
COPY . .

EXPOSE 8080
CMD ["python", "main.py"]
