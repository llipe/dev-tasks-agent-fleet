# Base images come from AWS ECR Public (a mirror of the official Docker Library
# images) rather than Docker Hub: anonymous Docker Hub pulls from CodeBuild's
# shared IP ranges routinely hit "429 Too Many Requests", which fails the
# container build and rolls back the whole stack (sibling agent's issue #77).
#
# This story (S-125) scaffolded the deployable no-op with no scanner
# toolchains installed. S-132 (CodeQL, this addition) was the first story to
# extend this Dockerfile per spec S15.2. Semgrep/Gitleaks/Trivy/Checkov's own
# toolchain installs (S-128-S-131) were left as a tracked, still-open gap
# across those stories to keep each one's diff scoped to its own issue --
# closed out in S-141 (below) once real-repo verification hit all four
# missing binaries at once. git + gh CLI are enough for S-125's checkout
# step; CodeQL's own toolchain needs no compiler at all (see below).

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
# rustc/cargo -- S-141 fidelity-audit finding: checkov (pip install below)
# depends on rustworkx, which as of this writing publishes no Python 3.13
# wheel for any platform -- pip falls back to building it from source,
# which needs a real Rust toolchain. Confirmed via a clean-container test
# against this exact base image: with rustc/cargo present, `pip install .`
# (including checkov) builds and installs cleanly; without them, the build
# fails with "can't find Rust compiler". Debian's own rustc/cargo packages
# (not rustup) are used deliberately -- they install over plain apt like
# every other system dep here, with no extra HTTPS-to-github.com step.
RUN apt-get update && apt-get install -y --no-install-recommends \
    git curl ca-certificates gnupg unzip rustc cargo && \
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
# C-C++ compiler is installed in this image at all. This does NOT mean the
# JS/TS extractor is dependency-free, though -- see the Node.js install
# below, a real (non-compiler) runtime requirement discovered only once a
# real TypeScript repo was scanned.
ARG CODEQL_CLI_VERSION=2.27.0
RUN curl -sSfL \
    "https://github.com/github/codeql-cli-binaries/releases/download/v${CODEQL_CLI_VERSION}/codeql-linux-arm64.zip" \
    -o /tmp/codeql.zip && \
    unzip -q /tmp/codeql.zip -d /opt && \
    rm /tmp/codeql.zip && \
    ln -s /opt/codeql/codeql /usr/local/bin/codeql
# S-141 redeploy finding: `codeql/javascript-typescript-queries` does not
# exist as a published package -- GitHub's actual published container
# package (confirmed via `gh api orgs/codeql/packages`) is
# `codeql/javascript-queries` (JS and TS share one query pack; there never
# was a separate "javascript-typescript" package name). This was the sole
# root cause of every `codeql pack download` failure this story hit,
# including in CI (anonymous requests to a nonexistent package return 403,
# not 404, so this looked like an auth/rate-limit problem and wasn't).
# Confirmed the corrected name downloads successfully fully anonymously,
# both locally and matching this exact command.
RUN codeql pack download codeql/javascript-queries codeql/python-queries

# Node.js -- S-141 real-invocation finding: CodeQL's JS/TS extractor
# (invoked by `database create` as `autobuild.sh`, even with
# --build-mode=none -- that flag only skips a *custom* build command like
# `npm run build`, it does not remove the extractor's own parsing
# dependency) shells out to a real Node.js binary to parse `.ts`/`.tsx`
# files via the TypeScript compiler API. Confirmed against a real
# TypeScript repo (llipe/memo-cli): without Node.js on PATH, `database
# create` fails with "Could not start Node.js. It is required for
# TypeScript extraction." No `npm install` runs here (--build-mode=none
# means no dependency install), so this is a Node *runtime* requirement
# only -- not a reversal of the "no build step" claim above, which is still
# true for anything --build-mode=none itself controls.
ARG NODE_MAJOR=22
RUN curl -fsSL "https://deb.nodesource.com/setup_${NODE_MAJOR}.x" | bash - && \
    apt-get install -y --no-install-recommends nodejs && \
    rm -rf /var/lib/apt/lists/*

# S-141: Gitleaks and Trivy toolchains (S-129/S-130's own tracked gap,
# closed out here alongside the CodeQL package-name fix above). Both ship
# as standalone Go binaries via GitHub Releases tarballs, same download-
# and-link pattern as the CodeQL CLI install above -- no package-registry
# involvement, so none of that step's auth/naming issues apply here.
ARG GITLEAKS_VERSION=8.30.1
RUN curl -sSfL \
    "https://github.com/gitleaks/gitleaks/releases/download/v${GITLEAKS_VERSION}/gitleaks_${GITLEAKS_VERSION}_linux_arm64.tar.gz" \
    -o /tmp/gitleaks.tar.gz && \
    tar -xzf /tmp/gitleaks.tar.gz -C /usr/local/bin gitleaks && \
    rm /tmp/gitleaks.tar.gz && \
    chmod +x /usr/local/bin/gitleaks

ARG TRIVY_VERSION=0.74.0
RUN curl -sSfL \
    "https://github.com/aquasecurity/trivy/releases/download/v${TRIVY_VERSION}/trivy_${TRIVY_VERSION}_Linux-ARM64.tar.gz" \
    -o /tmp/trivy.tar.gz && \
    tar -xzf /tmp/trivy.tar.gz -C /usr/local/bin trivy && \
    rm /tmp/trivy.tar.gz && \
    chmod +x /usr/local/bin/trivy

# Python deps -- includes semgrep and checkov (S-141: their scanner
# binaries ship as pip packages, pinned in pyproject.toml's dependencies;
# see that file for the same S-128/S-131 toolchain-gap note).
WORKDIR /app
COPY pyproject.toml .
RUN pip install --no-cache-dir .

# Agent code
COPY . .

EXPOSE 8080
CMD ["python", "main.py"]
