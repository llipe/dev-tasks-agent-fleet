/**
 * Playwright global teardown (S-114) — stop the AgentCore stub started in
 * `global-setup.ts`. The Supabase stack is intentionally NOT torn down: locally
 * a developer keeps it running between runs, and in CI the job lifecycle
 * disposes of it. Leaving it up avoids a slow restart on the next local run.
 */

import type { AgentCoreStubHandle } from "./fixtures/agentcore-stub";

declare global {
  // eslint-disable-next-line no-var
  var __AGENTCORE_STUB__: AgentCoreStubHandle | undefined;
}

export default async function globalTeardown(): Promise<void> {
  const stub = globalThis.__AGENTCORE_STUB__;
  if (stub) {
    await stub.close().catch(() => {});
    globalThis.__AGENTCORE_STUB__ = undefined;
  }
}
