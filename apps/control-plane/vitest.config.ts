import { defineConfig } from "vitest/config";
import { resolve } from "path";

export default defineConfig({
  resolve: {
    alias: {
      "@": resolve(import.meta.dirname, "./src"),
    },
  },
  test: {
    name: "control-plane",
    environment: "node",
    include: ["src/**/*.test.{ts,tsx}"],
    exclude: ["src/**/*.integration-test.{ts,tsx}", "src/components/__tests__/**"],
  },
});
