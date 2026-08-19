import { defineProject } from "vitest/config";

export default defineProject({
  test: {
    name: "dep-updater",
    environment: "node",
  },
});
