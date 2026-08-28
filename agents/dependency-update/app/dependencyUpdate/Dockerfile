# Base images come from AWS ECR Public (a mirror of the official Docker Library
# images) rather than Docker Hub: anonymous Docker Hub pulls from CodeBuild's
# shared IP ranges routinely hit "429 Too Many Requests", which fails the
# container build and rolls back the whole stack (issue #77).

# Stage 1: Node 26 binaries
FROM public.ecr.aws/docker/library/node:26-slim AS node-base

# Stage 2: Python base with system-level dependencies
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
RUN apt-get update && apt-get install -y --no-install-recommends \
    git curl ca-certificates gnupg libatomic1 && \
    rm -rf /var/lib/apt/lists/*

# Copy Node.js 26 runtime from official image
COPY --from=node-base /usr/local/bin/ /usr/local/bin/
COPY --from=node-base /usr/local/lib/node_modules /usr/local/lib/node_modules

# Install pnpm globally via npm
RUN npm install -g pnpm@9

# gh CLI (from Debian repos as fallback when GitHub apt has SSL issues)
RUN curl -fsSL https://cli.github.com/packages/githubcli-archive-keyring.gpg \
    | dd of=/usr/share/keyrings/githubcli-archive-keyring.gpg && \
    echo "deb [signed-by=/usr/share/keyrings/githubcli-archive-keyring.gpg] \
    https://cli.github.com/packages stable main" \
    > /etc/apt/sources.list.d/github-cli.list && \
    apt-get update && apt-get install -y gh && \
    rm -rf /var/lib/apt/lists/*

# Python deps
WORKDIR /app
COPY pyproject.toml .
RUN pip install --no-cache-dir .

# Agent code
COPY . .

EXPOSE 8080
CMD ["python", "main.py"]
