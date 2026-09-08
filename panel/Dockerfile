# syntax=docker/dockerfile:1

# ---------------------------------------------------------------------------
# Production image for the Next.js panel (Story S-115).
#
# Build CONTEXT is the monorepo ROOT (not panel/), because the panel is a pnpm
# workspace member and Next.js standalone tracing is rooted at the monorepo
# root (next.config.ts `outputFileTracingRoot`). Build from the repo root:
#
#   docker build -f panel/Dockerfile -t panel:local .
#
# The image bakes NO secrets. All runtime configuration (Supabase service-role
# key, AGENT_RUNTIME_ROLE_ARN, AWS_REGION, FLY_APP_NAME) arrives at runtime as
# Fly secrets / env — never as build args or COPY'd files (SD2/D12/D15).
#
# Multi-stage: deps -> build -> runner. Only the standalone server, the static
# assets, and the traced node_modules reach the final stage, so the runtime
# image carries no build toolchain and no dev dependencies.
# ---------------------------------------------------------------------------

ARG NODE_VERSION=22
ARG PNPM_VERSION=10.11.0

# --- Stage 1: dependencies -------------------------------------------------
FROM node:${NODE_VERSION}-slim AS deps
ARG PNPM_VERSION
ENV PNPM_HOME="/pnpm" \
    PATH="/pnpm:$PATH"
RUN corepack enable && corepack prepare pnpm@${PNPM_VERSION} --activate
WORKDIR /repo

# Copy only the manifests first so the dependency layer caches independently of
# source changes. The workspace root + every declared member manifest is needed
# for `pnpm install` to resolve the workspace graph.
COPY package.json pnpm-lock.yaml pnpm-workspace.yaml ./
COPY panel/package.json panel/package.json
COPY agents/dependency-update/agentcore/cdk/package.json agents/dependency-update/agentcore/cdk/package.json

# Full install (incl. dev deps) — the build stage needs them. --frozen-lockfile
# guarantees the image matches the committed lockfile exactly.
RUN --mount=type=cache,id=pnpm-store,target=/pnpm/store \
    pnpm install --frozen-lockfile

# --- Stage 2: build --------------------------------------------------------
FROM node:${NODE_VERSION}-slim AS build
ARG PNPM_VERSION
ENV PNPM_HOME="/pnpm" \
    PATH="/pnpm:$PATH" \
    NEXT_TELEMETRY_DISABLED=1
RUN corepack enable && corepack prepare pnpm@${PNPM_VERSION} --activate
WORKDIR /repo

COPY --from=deps /repo/node_modules ./node_modules
COPY --from=deps /repo/panel/node_modules ./panel/node_modules
# Bring in the whole repo so the workspace graph + panel source are present.
COPY . .

# Produce .next/standalone (+ .next/static). The panel build must be green —
# this is the production build that S-115 requires.
RUN pnpm --filter panel run build

# --- Stage 3: runner (minimal) ---------------------------------------------
FROM node:${NODE_VERSION}-slim AS runner
ENV NODE_ENV=production \
    NEXT_TELEMETRY_DISABLED=1 \
    PORT=8080 \
    HOSTNAME=0.0.0.0
WORKDIR /app

# Run as a non-root user.
RUN groupadd --system --gid 1001 nodejs \
    && useradd --system --uid 1001 --gid nodejs nextjs

# The standalone output is rooted at the monorepo root, so the traced tree is
# nested under panel/. Copy the self-contained server + its traced node_modules
# and the static assets. Nothing else from the build stage is needed.
COPY --from=build --chown=nextjs:nodejs /repo/panel/.next/standalone ./
COPY --from=build --chown=nextjs:nodejs /repo/panel/.next/static ./panel/.next/static

USER nextjs
EXPOSE 8080

# `server.js` lives under panel/ inside the standalone tree because tracing is
# rooted one level above the package.
CMD ["node", "panel/server.js"]
