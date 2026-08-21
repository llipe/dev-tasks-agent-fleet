import { defineConfig } from "vitest/config";
import { resolve } from "path";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      "@": resolve(import.meta.dirname, "./src"),
    },
    extensions: [".ts", ".tsx", ".js", ".jsx", ".json"],
  },
  test: {
    name: "control-plane",
    environment: "node",
    include: ["src/**/*.test.{ts,tsx}"],
    exclude: ["src/**/*.integration-test.{ts,tsx}", "src/components/__tests__/**"],
  },
});
