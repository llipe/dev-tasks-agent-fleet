# ──────────────────────────────────────────────────────────────────────────────
# Multi-stage Dockerfile for standalone Next.js control-plane app
# Target: <512 MB runtime memory on Fly Machines
# ──────────────────────────────────────────────────────────────────────────────

# ── Stage 1: Install deps + build ─────────────────────────────────────────────
FROM node:22-alpine AS builder

RUN corepack enable && corepack prepare pnpm@latest --activate

WORKDIR /app

# Copy workspace root files needed for install
COPY package.json pnpm-lock.yaml pnpm-workspace.yaml ./
COPY .nvmrc ./

# Copy package manifests for workspace packages needed by control-plane
COPY apps/control-plane/package.json apps/control-plane/
COPY packages/shared/package.json packages/shared/

# Install all dependencies (frozen lockfile for reproducibility)
RUN pnpm install --frozen-lockfile

# Copy source for shared package and build it
COPY packages/shared/ packages/shared/
COPY tsconfig.base.json ./

# Copy control-plane source and build
COPY apps/control-plane/ apps/control-plane/

RUN pnpm --filter @fleet/control-plane run build

# ── Stage 2: Production runtime ───────────────────────────────────────────────
FROM node:22-alpine AS runner

RUN addgroup --system --gid 1001 nodejs && \
    adduser --system --uid 1001 nextjs

WORKDIR /app

ENV NODE_ENV=production
ENV PORT=3000
ENV HOSTNAME="0.0.0.0"

# Copy standalone output from builder
COPY --from=builder --chown=nextjs:nodejs /app/apps/control-plane/.next/standalone ./
COPY --from=builder --chown=nextjs:nodejs /app/apps/control-plane/.next/static ./apps/control-plane/.next/static
COPY --from=builder --chown=nextjs:nodejs /app/apps/control-plane/public ./apps/control-plane/public

USER nextjs

EXPOSE 3000

CMD ["node", "apps/control-plane/server.js"]
