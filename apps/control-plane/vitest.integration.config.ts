import { defineConfig } from "vitest/config";
import { resolve } from "path";

export default defineConfig({
  resolve: {
    alias: {
      "@": resolve(import.meta.dirname, "./src"),
    },
  },
  test: {
    name: "control-plane-integration",
    environment: "node",
    include: ["**/*.integration-test.ts"],
    testTimeout: 30000,
  },
});
