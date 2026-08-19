import { defineConfig } from "vitest/config";

export default defineConfig({
  test: {
    name: "infra-integration",
    environment: "node",
    include: ["**/*.integration-test.ts"],
    testTimeout: 30000,
  },
});
