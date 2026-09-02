import { defineConfig } from "@playwright/test";

// E2E config stub. The scenario suite lands in S-114 (#127). This file exists
// from S-101 so the harness and the `test:e2e` script are wired from the first
// commit; `testDir` points at a directory that fills in later.
export default defineConfig({
  testDir: "./tests/e2e",
  fullyParallel: true,
  reporter: "list",
  use: {
    baseURL: "http://localhost:3000",
  },
});
