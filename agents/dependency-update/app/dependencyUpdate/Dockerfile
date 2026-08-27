# Stage 1: Python base with system-level dependencies
FROM --platform=linux/arm64 python:3.13-slim AS base

# System deps
RUN apt-get update && apt-get install -y --no-install-recommends \
    git curl ca-certificates gnupg && \
    rm -rf /var/lib/apt/lists/*

# Node 26
RUN curl -fsSL https://deb.nodesource.com/setup_26.x | bash - && \
    apt-get install -y nodejs && \
    corepack enable

# pnpm + npm (npm comes with node)
RUN corepack prepare pnpm@9 --activate

# gh CLI
RUN curl -fsSL https://cli.github.com/packages/githubcli-archive-keyring.gpg \
    | dd of=/usr/share/keyrings/githubcli-archive-keyring.gpg && \
    echo "deb [arch=arm64 signed-by=/usr/share/keyrings/githubcli-archive-keyring.gpg] \
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
