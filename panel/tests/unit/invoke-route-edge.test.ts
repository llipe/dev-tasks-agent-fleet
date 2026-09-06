import { beforeEach, describe, expect, it, vi } from "vitest";

/**
 * S-112 (#125) — invoke route edge cases (task 1.16).
 *
 * Covers the remaining matrix rows not asserted in invoke-route.test.ts:
 *   - params: {} against a schema with required fields -> INVALID_PARAMS, no insert
 *   - an agent with an empty {} schema and no repository requirement -> 202
 *   - concurrent double-submit -> two distinct run ids, two inserts (no
 *     idempotency claim in v1)
 *   - STS-success-then-AgentCore-throw -> row ends failed_to_start, not queued
 */

const q = vi.hoisted(() => ({
  getAgentBySlug: vi.fn(),
  getRepositoryById: vi.fn(),
  insertQueuedRun: vi.fn(),
  markRunFailedToStart: vi.fn(),
  updateRunInvocationRefs: vi.fn(),
}));
const aws = vi.hoisted(() => ({ invokeAgentRuntime: vi.fn() }));

vi.mock("@/lib/supabase/server", () => ({ createServerClient: () => ({ __mock: "client" }) }));
vi.mock("@/lib/supabase/queries", () => q);
vi.mock("@/lib/aws/invoke", () => aws);
vi.mock("@/lib/aws/credentials", () => ({ credentialSource: () => "fly-oidc" }));

import { POST } from "@/app/api/agents/[slug]/invoke/route";
import { InvocationFailedError } from "@/lib/aws/errors";

const REQUIRED_SCHEMA = {
  type: "object",
  additionalProperties: false,
  required: ["fix_mode"],
  properties: { fix_mode: { type: "string", enum: ["audit_only", "llm_fix"] } },
};

function repoAgent(overrides: Record<string, unknown> = {}) {
  return {
    id: "agent-1",
    slug: "dependency-update",
    version: "0.1.0",
    runtime_arn: "arn:aws:bedrock-agentcore:us-east-1:1:runtime/x",
    runtime_qualifier: "DEFAULT",
    params_schema: REQUIRED_SCHEMA,
    default_params: {},
    requires_repository: true,
    max_runtime_seconds: 3600,
    grace_seconds: 120,
    start_timeout_seconds: 300,
    is_enabled: true,
    ...overrides,
  };
}

function req(body: unknown, slug = "dependency-update"): Request {
  return new Request(`http://localhost/api/agents/${slug}/invoke`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(body),
  });
}

const ctx = { params: Promise.resolve({ slug: "dependency-update" }) };

beforeEach(() => {
  vi.clearAllMocks();
  q.getAgentBySlug.mockResolvedValue(repoAgent());
  q.getRepositoryById.mockResolvedValue({
    id: "repo-1",
    installation_id: "inst-1",
    full_name: "acme/web",
    default_branch: "main",
    is_enabled: true,
    archived_at: null,
  });
  q.insertQueuedRun.mockResolvedValue(undefined);
  q.markRunFailedToStart.mockResolvedValue(undefined);
  q.updateRunInvocationRefs.mockResolvedValue(undefined);
  aws.invokeAgentRuntime.mockResolvedValue(undefined);
});

describe("edge — params: {} against a required-field schema", () => {
  it("rejects INVALID_PARAMS with no insert", async () => {
    const res = await POST(req({ repository_id: "repo-1", params: {} }), ctx);
    expect(res.status).toBe(400);
    expect((await res.json()).error.code).toBe("INVALID_PARAMS");
    expect(q.insertQueuedRun).not.toHaveBeenCalled();
  });
});

describe("edge — empty {} schema, no repository requirement", () => {
  it("accepts an empty params object and returns 202", async () => {
    q.getAgentBySlug.mockResolvedValue(
      repoAgent({ requires_repository: false, params_schema: {} }),
    );
    const res = await POST(req({ params: {} }), ctx);
    expect(res.status).toBe(202);
    expect(q.insertQueuedRun).toHaveBeenCalledTimes(1);
    // No-repository agent -> payload carries no org/name.
    const payload = aws.invokeAgentRuntime.mock.calls[0][1].payload as Record<string, unknown>;
    expect("repository_org" in payload).toBe(false);
  });
});

describe("edge — concurrent double-submit (no idempotency in v1)", () => {
  it("produces two distinct run ids and two inserts", async () => {
    const [r1, r2] = await Promise.all([
      POST(req({ repository_id: "repo-1", params: { fix_mode: "audit_only" } }), ctx),
      POST(req({ repository_id: "repo-1", params: { fix_mode: "audit_only" } }), ctx),
    ]);
    const j1 = await r1.json();
    const j2 = await r2.json();
    expect(j1.run_id).not.toBe(j2.run_id);
    expect(q.insertQueuedRun).toHaveBeenCalledTimes(2);
  });
});

describe("edge — STS success then AgentCore throw", () => {
  it("ends failed_to_start, never left queued", async () => {
    aws.invokeAgentRuntime.mockRejectedValue(new InvocationFailedError("downstream 500"));
    const res = await POST(
      req({ repository_id: "repo-1", params: { fix_mode: "audit_only" } }),
      ctx,
    );
    expect(res.status).toBe(502);
    const runId = (await res.json()).run_id;
    expect(q.insertQueuedRun).toHaveBeenCalledTimes(1);
    expect(q.markRunFailedToStart).toHaveBeenCalledTimes(1);
    expect(q.markRunFailedToStart.mock.calls[0][1]).toBe(runId);
    expect(q.markRunFailedToStart.mock.calls[0][2]).toBe("INVOCATION_FAILED");
  });
});
