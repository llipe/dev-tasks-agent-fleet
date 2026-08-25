import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  output: "standalone",
  // The codebase uses TypeScript's ESM-style `.js` import specifiers (e.g.
  // `./runs-data.js` resolving to `runs-data.ts`). `tsc` and Vitest handle this
  // natively, but the webpack build needs an explicit extensionAlias or every
  // such import fails with "Module not found". Without this, `next build` fails.
  webpack: (config) => {
    config.resolve.extensionAlias = {
      ...config.resolve.extensionAlias,
      ".js": [".ts", ".tsx", ".js"],
      ".jsx": [".tsx", ".jsx"],
      ".mjs": [".mts", ".mjs"],
    };
    return config;
  },
  async headers() {
    return [
      {
        source: "/(.*)",
        headers: [
          {
            key: "Strict-Transport-Security",
            value: "max-age=63072000; includeSubDomains; preload",
          },
        ],
      },
    ];
  },
};

export default nextConfig;
