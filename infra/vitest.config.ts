import { defineProject } from "vitest/config";

export default defineProject({
  test: {
    name: "infra",
    environment: "node",
  },
});
