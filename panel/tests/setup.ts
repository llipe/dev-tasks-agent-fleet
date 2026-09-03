import { cleanup } from "@testing-library/react";
import { afterEach } from "vitest";

import "@testing-library/jest-dom/vitest";

// Vitest is not configured with `globals: true`, so RTL's automatic
// per-test cleanup (which keys off a global `afterEach`) is not registered
// automatically. Register it explicitly so each component test starts with a
// fresh DOM — without this, repeated renders of the same element accumulate
// and role/text queries find duplicates.
afterEach(() => {
  cleanup();
});
