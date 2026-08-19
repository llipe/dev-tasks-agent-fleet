import { defineWorkspace } from "vitest/config";

export default defineWorkspace([
  "apps/control-plane",
  "agents/dep-updater",
  "packages/shared",
  "infra",
]);
