import { fileURLToPath } from "node:url";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

// Three Vitest projects mirror the TESTING.md layer taxonomy:
//   unit        -> Layer 1 (deterministic, no I/O)          tests/unit/
//   component   -> Layer 2 (mocked externals, jsdom)        tests/component/
//   integration -> Layer 2.5 (real DB; wired fully in S-102) tests/integration/
export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      "@": fileURLToPath(new URL(".", import.meta.url)),
      // Test-only: neutralize the `server-only` guard so modules that import it
      // (lib/supabase/server.ts) can be unit-tested under the node environment.
      // The real guard still fires in `next build`. See tests/stubs/server-only.ts.
      "server-only": fileURLToPath(new URL("./tests/stubs/server-only.ts", import.meta.url)),
    },
  },
  test: {
    coverage: {
      provider: "v8",
      reporter: ["text", "html"],
      reportsDirectory: "./coverage",
    },
    projects: [
      {
        extends: true,
        test: {
          name: "unit",
          environment: "node",
          include: ["tests/unit/**/*.test.{ts,tsx}", "tests/smoke.test.ts"],
        },
      },
      {
        extends: true,
        test: {
          name: "component",
          environment: "jsdom",
          include: ["tests/component/**/*.test.{ts,tsx}"],
          setupFiles: ["./tests/setup.ts"],
        },
      },
      {
        extends: true,
        test: {
          name: "integration",
          environment: "node",
          include: ["tests/integration/**/*.test.{ts,tsx}"],
          // Layer 2.5 tests all mutate ONE shared local Supabase Postgres, and
          // reap_stale_runs() is a GLOBAL operation (it reaps every stale run in
          // the DB). Under parallelism, one file's reap_stale_runs() call can reap
          // another file's freshly-inserted stale run before that file closes its
          // run_steps, producing a cross-file race (e.g. "expected 'running' to be
          // 'failed'"). `singleFork` runs every integration file in ONE worker
          // process, sequentially, so the shared-DB tests never interleave.
          // Scoped to `integration` ONLY — `unit` and `component` keep their
          // parallel speed.
          pool: "forks",
          poolOptions: {
            forks: {
              singleFork: true,
            },
          },
          sequence: {
            concurrent: false,
          },
        },
      },
    ],
  },
});
