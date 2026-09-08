import { fileURLToPath } from "node:url";
import type { NextConfig } from "next";

// Pin the file-tracing root to the monorepo root (one level above panel/) so
// Next.js does not misinfer the workspace root from an unrelated lockfile
// elsewhere on the machine.
const monorepoRoot = fileURLToPath(new URL("..", import.meta.url));

const nextConfig: NextConfig = {
  reactStrictMode: true,
  outputFileTracingRoot: monorepoRoot,
  // Emit a self-contained server bundle (.next/standalone) so the production
  // Docker image can run `node server.js` without the full node_modules tree
  // or a pnpm install at runtime (S-115 deploy).
  output: "standalone",
};

export default nextConfig;
