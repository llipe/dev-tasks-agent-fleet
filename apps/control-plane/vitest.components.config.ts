import { defineConfig } from "vitest/config";
import { resolve } from "path";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      "@": resolve(import.meta.dirname, "./src"),
    },
  },
  test: {
    name: "control-plane-components",
    environment: "jsdom",
    include: ["src/components/__tests__/**/*.test.{ts,tsx}"],
    setupFiles: ["src/test/setup.ts"],
  },
});
