import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

/**
 * S-112 (#125) — invoke route handler, all externals mocked (task 1.13).
 *
 * Boundary: Supabase (`lib/supabase/*`), STS/AgentCore (`lib/aws/invoke`), and
 * the credential source are mocked. Asserts:
 *   - the NORMATIVE ordering: the queued insert precedes the invoke (AC7)
 *   - 202 { run_id, status: "queued" } on success (AC1/AC7)
 *   - 400 + NO insert for invalid params (security-negative #3, AC5/AC13)
 *   - 400 + NO insert for a malformed / disabled / archived repository (AC4)
 *   - 404 for unknown or disabled slug
 *   - failed_to_start written on invoke throw + 502 carrying run_id (AC12)
 *   - CREDENTIALS_UNAVAILABLE (500) distinct from INVOCATION_FAILED (502)
 */

// --- module mocks (hoisted) ---------------------------------------------

const q = vi.hoisted(() => ({
  getAgentBySlug: vi.fn(),
  getRepositoryById: vi.fn(),
  insertQueuedRun: vi.fn(),
  markRunFailedToStart: vi.fn(),
  updateRunInvocationRefs: vi.fn(),
}));
const aws = vi.hoisted(() => ({ invokeAgentRuntime: vi.fn() }));

vi.mock("@/lib/supabase/server", () => ({
  createServerClient: () => ({ __mock: "client" }),
}));
vi.mock("@/lib/supabase/queries", () => q);
vi.mock("@/lib/aws/invoke", () => aws);
vi.mock("@/lib/aws/credentials", () => ({
  credentialSource: () => "local-chain",
}));

import { POST } from "@/app/api/agents/[slug]/invoke/route";
import { CredentialsUnavailableError, InvocationFailedError } from "@/lib/aws/errors";

// --- helpers -------------------------------------------------------------

const SCHEMA = {
  type: "object",
  additionalProperties: false,
  required: ["fix_mode"],
  properties: {
    fix_mode: { type: "string", enum: ["audit_only", "llm_fix"], default: "audit_only" },
    fail_on_findings: { type: "boolean", default: true },
    max_fix_attempts: { type: "integer", minimum: 0, maximum: 5, default: 3 },
    base_branch: { type: "string", default: "main" },
  },
};

function agent(overrides: Record<string, unknown> = {}) {
  return {
    id: "agent-1",
    slug: "dependency-update",
    name: "Dependency Update",
    version: "0.1.0",
    runtime_arn: "arn:aws:bedrock-agentcore:us-east-1:1:runtime/x",
    runtime_qualifier: "DEFAULT",
    params_schema: SCHEMA,
    default_params: {},
    requires_repository: true,
    max_runtime_seconds: 3600,
    grace_seconds: 120,
    start_timeout_seconds: 300,
    is_enabled: true,
    ...overrides,
  };
}

function repo(overrides: Record<string, unknown> = {}) {
  return {
    id: "repo-1",
    installation_id: "inst-1",
    full_name: "acme/web",
    default_branch: "main",
    is_enabled: true,
    archived_at: null,
    ...overrides,
  };
}

function req(body: unknown): Request {
  return new Request("http://localhost/api/agents/dependency-update/invoke", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(body),
  });
}

const ctx = { params: Promise.resolve({ slug: "dependency-update" }) };

beforeEach(() => {
  vi.clearAllMocks();
  q.getAgentBySlug.mockResolvedValue(agent());
  q.getRepositoryById.mockResolvedValue(repo());
  q.insertQueuedRun.mockResolvedValue(undefined);
  q.markRunFailedToStart.mockResolvedValue(undefined);
  q.updateRunInvocationRefs.mockResolvedValue(undefined);
  aws.invokeAgentRuntime.mockResolvedValue(undefined);
});

afterEach(() => vi.restoreAllMocks());

// --- tests ---------------------------------------------------------------

describe("POST invoke — happy path (AC1/AC7)", () => {
  it("returns 202 { run_id, status: 'queued' } and invokes AFTER inserting", async () => {
    const order: string[] = [];
    q.insertQueuedRun.mockImplementation(async () => {
      order.push("insert");
    });
    aws.invokeAgentRuntime.mockImplementation(async () => {
      order.push("invoke");
    });

    const res = await POST(
      req({ repository_id: "repo-1", params: { fix_mode: "audit_only" } }),
      ctx,
    );
    expect(res.status).toBe(202);
    const json = await res.json();
    expect(json.status).toBe("queued");
    expect(typeof json.run_id).toBe("string");
    expect(json.run_id.length).toBeGreaterThan(0);

    // Normative ordering: insert precedes invoke.
    expect(order).toEqual(["insert", "invoke"]);
    expect(q.insertQueuedRun).toHaveBeenCalledTimes(1);
    expect(aws.invokeAgentRuntime).toHaveBeenCalledTimes(1);
  });

  it("snapshots all three timeout columns explicitly (OQ3)", async () => {
    await POST(req({ repository_id: "repo-1", params: { fix_mode: "audit_only" } }), ctx);
    const insertArg = q.insertQueuedRun.mock.calls[0][1];
    expect(insertArg.max_runtime_seconds).toBe(3600);
    expect(insertArg.grace_seconds).toBe(120);
    expect(insertArg.start_timeout_seconds).toBe(300);
    expect(insertArg.triggered_by).toBe("panel");
    expect(insertArg.status).toBe("queued");
  });

  it("forwards a payload without repository_id to the agent (contract)", async () => {
    await POST(req({ repository_id: "repo-1", params: { fix_mode: "audit_only" } }), ctx);
    const invokeArg = aws.invokeAgentRuntime.mock.calls[0];
    const payload = invokeArg[1].payload as Record<string, unknown>;
    expect(payload.repository_org).toBe("acme");
    expect(payload.repository_name).toBe("web");
    expect("repository_id" in payload).toBe(false);
    expect(invokeArg[0].runtimeArn).toBe(agent().runtime_arn);
  });
});

describe("POST invoke — params rejection (security-negative #3, AC5/AC13)", () => {
  it("returns 400 INVALID_PARAMS and writes NO run for an additional property", async () => {
    const res = await POST(
      req({ repository_id: "repo-1", params: { fix_mode: "audit_only", bogus: 1 } }),
      ctx,
    );
    expect(res.status).toBe(400);
    const json = await res.json();
    expect(json.error.code).toBe("INVALID_PARAMS");
    expect(q.insertQueuedRun).not.toHaveBeenCalled();
    expect(aws.invokeAgentRuntime).not.toHaveBeenCalled();
  });

  it("returns 400 INVALID_PARAMS for params missing a required field, no insert", async () => {
    const res = await POST(req({ repository_id: "repo-1", params: {} }), ctx);
    expect(res.status).toBe(400);
    expect((await res.json()).error.code).toBe("INVALID_PARAMS");
    expect(q.insertQueuedRun).not.toHaveBeenCalled();
  });
});

describe("POST invoke — repository rejection (AC4)", () => {
  it("returns 400 MALFORMED_REPOSITORY for a missing repository_id when required, no insert", async () => {
    const res = await POST(req({ params: { fix_mode: "audit_only" } }), ctx);
    expect(res.status).toBe(400);
    expect((await res.json()).error.code).toBe("MALFORMED_REPOSITORY");
    expect(q.insertQueuedRun).not.toHaveBeenCalled();
  });

  it("returns 400 for a disabled repository, no insert", async () => {
    q.getRepositoryById.mockResolvedValue(repo({ is_enabled: false }));
    const res = await POST(
      req({ repository_id: "repo-1", params: { fix_mode: "audit_only" } }),
      ctx,
    );
    expect(res.status).toBe(400);
    expect(q.insertQueuedRun).not.toHaveBeenCalled();
  });

  it("returns 400 for an archived repository, no insert", async () => {
    q.getRepositoryById.mockResolvedValue(repo({ archived_at: "2026-01-01T00:00:00Z" }));
    const res = await POST(
      req({ repository_id: "repo-1", params: { fix_mode: "audit_only" } }),
      ctx,
    );
    expect(res.status).toBe(400);
    expect(q.insertQueuedRun).not.toHaveBeenCalled();
  });
});

describe("POST invoke — agent resolution", () => {
  it("returns 404 for an unknown slug", async () => {
    q.getAgentBySlug.mockResolvedValue(null);
    const res = await POST(req({ repository_id: "repo-1", params: {} }), ctx);
    expect(res.status).toBe(404);
    expect(q.insertQueuedRun).not.toHaveBeenCalled();
  });

  it("returns 404 for a disabled agent", async () => {
    q.getAgentBySlug.mockResolvedValue(agent({ is_enabled: false }));
    const res = await POST(req({ repository_id: "repo-1", params: {} }), ctx);
    expect(res.status).toBe(404);
    expect(q.insertQueuedRun).not.toHaveBeenCalled();
  });
});

describe("POST invoke — failed_to_start on invoke throw (AC12)", () => {
  it("marks the run failed_to_start and returns 502 with run_id (INVOCATION_FAILED)", async () => {
    aws.invokeAgentRuntime.mockRejectedValue(new InvocationFailedError("boom"));
    const res = await POST(
      req({ repository_id: "repo-1", params: { fix_mode: "audit_only" } }),
      ctx,
    );
    expect(res.status).toBe(502);
    const json = await res.json();
    expect(json.error.code).toBe("INVOCATION_FAILED");
    expect(typeof json.run_id).toBe("string");
    // The row WAS inserted (before the throw) and then marked failed_to_start.
    expect(q.insertQueuedRun).toHaveBeenCalledTimes(1);
    expect(q.markRunFailedToStart).toHaveBeenCalledTimes(1);
    const [, runId, code] = q.markRunFailedToStart.mock.calls[0];
    expect(runId).toBe(json.run_id);
    expect(code).toBe("INVOCATION_FAILED");
  });

  it("a credential failure returns 500 CREDENTIALS_UNAVAILABLE, distinct from 502", async () => {
    aws.invokeAgentRuntime.mockRejectedValue(new CredentialsUnavailableError("no creds"));
    const res = await POST(
      req({ repository_id: "repo-1", params: { fix_mode: "audit_only" } }),
      ctx,
    );
    expect(res.status).toBe(500);
    const json = await res.json();
    expect(json.error.code).toBe("CREDENTIALS_UNAVAILABLE");
    expect(typeof json.run_id).toBe("string");
    // Still marked failed_to_start (the run should not linger queued).
    expect(q.markRunFailedToStart).toHaveBeenCalledTimes(1);
  });
});

describe("POST invoke — structured logging (AC11)", () => {
  it("logs run_id, agent_slug, repository_full_name and credential source, never the payload", async () => {
    const info = vi.spyOn(console, "info").mockImplementation(() => {});
    await POST(req({ repository_id: "repo-1", params: { fix_mode: "audit_only" } }), ctx);
    const lines = info.mock.calls.map((c) => String(c[0]));
    const invoked = lines.find((l) => l.includes('"event":"invoked"'));
    expect(invoked).toBeDefined();
    const parsed = JSON.parse(invoked!);
    expect(parsed.agent_slug).toBe("dependency-update");
    expect(parsed.repository_full_name).toBe("acme/web");
    expect(parsed.credential_source).toBe("local-chain");
    expect(typeof parsed.run_id).toBe("string");
    // Never logs the params/payload.
    expect(invoked).not.toContain("fix_mode");
    info.mockRestore();
  });
});

describe("POST invoke — bad body", () => {
  it("returns 400 for a non-JSON body", async () => {
    const badReq = new Request("http://localhost/x", {
      method: "POST",
      body: "not json{{{",
    });
    const res = await POST(badReq, ctx);
    expect(res.status).toBe(400);
  });
});
