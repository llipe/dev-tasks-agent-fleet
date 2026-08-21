import { defineWorkspace } from "vitest/config";

export default defineWorkspace([
  "apps/control-plane/vitest.config.ts",
  "apps/control-plane/vitest.components.config.ts",
  "packages/shared/vitest.config.ts",
  "infra/vitest.config.ts",
  "infra/orchestrator/vitest.config.ts",
]);
