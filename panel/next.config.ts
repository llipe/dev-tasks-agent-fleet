import { fileURLToPath } from "node:url";
import type { NextConfig } from "next";

// Pin the file-tracing root to the monorepo root (one level above panel/) so
// Next.js does not misinfer the workspace root from an unrelated lockfile
// elsewhere on the machine.
const monorepoRoot = fileURLToPath(new URL("..", import.meta.url));

const nextConfig: NextConfig = {
  reactStrictMode: true,
  outputFileTracingRoot: monorepoRoot,
};

export default nextConfig;
