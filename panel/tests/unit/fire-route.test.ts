import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

/**
 * S-153 (#265) — fire endpoint handler, all externals mocked.
 *
 * Asserts the SD-T9 ordering + outcomes:
 *   - 401 BEFORE any work on a missing/wrong secret (AC3) — no insert, no invoke
 *   - 409 on a stale/disabled/paused schedule (no insert)
 *   - insert-then-invoke with the SCHEDULE trigger descriptor (AC2)
 *   - failed_to_start + counter increment on invoke throw
 *   - 202 { run_id } on success + counter reset
 */

const q = vi.hoisted(() => ({
  getScheduleById: vi.fn(),
  getAgentById: vi.fn(),
  getRepositoryById: vi.fn(),
  insertQueuedRun: vi.fn(),
  markRunFailedToStart: vi.fn(),
  recordScheduleFired: vi.fn(),
  recordScheduleFireFailure: vi.fn(),
}));
const aws = vi.hoisted(() => ({ invokeAgentRuntime: vi.fn() }));

vi.mock("@/lib/supabase/server", () => ({ createServerClient: () => ({ __mock: "client" }) }));
vi.mock("@/lib/supabase/queries", () => q);
vi.mock("@/lib/aws/invoke", () => aws);
vi.mock("@/lib/aws/credentials", () => ({ credentialSource: () => "local-chain" }));

import { POST } from "@/app/api/internal/schedules/[id]/fire/route";
import { InvocationFailedError } from "@/lib/aws/errors";

const SCHEMA = {
  type: "object",
  additionalProperties: false,
  required: ["fix_mode"],
  properties: { fix_mode: { type: "string", enum: ["audit_only", "llm_fix"] } },
};

function schedule(over: Record<string, unknown> = {}) {
  return {
    id: "sch-1",
    agent_id: "agent-1",
    repository_id: "repo-1",
    is_enabled: true,
    state: "active",
    params: { fix_mode: "audit_only" },
    consecutive_failures: 0,
    ...over,
  };
}
function agent(over: Record<string, unknown> = {}) {
  return {
    id: "agent-1",
    slug: "dependency-update",
    version: "0.1.0",
    is_enabled: true,
    requires_repository: true,
    runtime_arn: "arn:runtime",
    runtime_qualifier: "DEFAULT",
    params_schema: SCHEMA,
    max_runtime_seconds: 3600,
    grace_seconds: 120,
    start_timeout_seconds: 300,
    ...over,
  };
}
function repo(over: Record<string, unknown> = {}) {
  return {
    id: "repo-1",
    installation_id: "inst-1",
    full_name: "acme/web",
    default_branch: "main",
    is_enabled: true,
    archived_at: null,
    ...over,
  };
}

const SECRET = "unit-secret";
function fire(headerSecret?: string) {
  const headers = new Headers();
  if (headerSecret !== undefined) headers.set("x-scheduler-secret", headerSecret);
  const req = new Request("http://x/api/internal/schedules/sch-1/fire", {
    method: "POST",
    headers,
  });
  return POST(req, { params: Promise.resolve({ id: "sch-1" }) });
}

beforeEach(() => {
  vi.clearAllMocks();
  process.env.SCHEDULER_TRIGGER_SECRET = SECRET;
  q.getScheduleById.mockResolvedValue(schedule());
  q.getAgentById.mockResolvedValue(agent());
  q.getRepositoryById.mockResolvedValue(repo());
  q.insertQueuedRun.mockResolvedValue(undefined);
  q.recordScheduleFired.mockResolvedValue(undefined);
  q.recordScheduleFireFailure.mockResolvedValue(undefined);
  aws.invokeAgentRuntime.mockResolvedValue(undefined);
});
afterEach(() => {
  delete process.env.SCHEDULER_TRIGGER_SECRET;
});

describe("fire endpoint — auth (AC3)", () => {
  it("401 with no secret header — before any DB work", async () => {
    const res = await fire();
    expect(res.status).toBe(401);
    expect(q.getScheduleById).not.toHaveBeenCalled();
    expect(q.insertQueuedRun).not.toHaveBeenCalled();
    expect(aws.invokeAgentRuntime).not.toHaveBeenCalled();
  });
  it("401 with a wrong secret — before any DB work", async () => {
    const res = await fire("nope");
    expect(res.status).toBe(401);
    expect(q.getScheduleById).not.toHaveBeenCalled();
  });
});

describe("fire endpoint — schedule state", () => {
  it("409 on a disabled schedule (no insert)", async () => {
    q.getScheduleById.mockResolvedValue(schedule({ is_enabled: false }));
    const res = await fire(SECRET);
    expect(res.status).toBe(409);
    expect(q.insertQueuedRun).not.toHaveBeenCalled();
  });
  it("409 on a non-active (paused/blocked) schedule", async () => {
    q.getScheduleById.mockResolvedValue(schedule({ state: "paused" }));
    expect((await fire(SECRET)).status).toBe(409);
  });
  it("409 when the schedule is absent", async () => {
    q.getScheduleById.mockResolvedValue(null);
    expect((await fire(SECRET)).status).toBe(409);
  });
});

describe("fire endpoint — happy path (AC2)", () => {
  it("inserts the queued run BEFORE invoking, with the schedule trigger descriptor", async () => {
    const order: string[] = [];
    q.insertQueuedRun.mockImplementation(async () => void order.push("insert"));
    aws.invokeAgentRuntime.mockImplementation(async () => void order.push("invoke"));

    const res = await fire(SECRET);
    expect(res.status).toBe(202);
    expect(order).toEqual(["insert", "invoke"]);

    const insertArg = q.insertQueuedRun.mock.calls[0]![1];
    expect(insertArg.trigger_type).toBe("schedule");
    expect(insertArg.triggered_by).toBe("schedule:sch-1");
    expect(insertArg.status).toBe("queued");
    expect(q.recordScheduleFired).toHaveBeenCalledWith(expect.anything(), "sch-1", insertArg.id);
  });

  it("returns 202 { run_id, status: queued }", async () => {
    const res = await fire(SECRET);
    const body = await res.json();
    expect(body.status).toBe("queued");
    expect(typeof body.run_id).toBe("string");
  });
});

describe("fire endpoint — invoke failure", () => {
  it("marks failed_to_start, increments the G3 counter, and returns 502 with run_id", async () => {
    aws.invokeAgentRuntime.mockRejectedValue(new Error("InvokeAgentRuntime failed"));
    const res = await fire(SECRET);
    expect(res.status).toBe(502);
    const body = await res.json();
    expect(typeof body.run_id).toBe("string");
    expect(q.markRunFailedToStart).toHaveBeenCalled();
    expect(q.recordScheduleFireFailure).toHaveBeenCalledWith(
      expect.anything(),
      "sch-1",
      expect.any(String),
    );
    expect(q.recordScheduleFired).not.toHaveBeenCalled();
  });
});

describe("fire endpoint — invalid params (counts toward G3)", () => {
  it("422 + counter increment + NO insert when stored params fail the schema", async () => {
    q.getScheduleById.mockResolvedValue(schedule({ params: { fix_mode: "nonsense" } }));
    const res = await fire(SECRET);
    expect(res.status).toBe(422);
    expect(q.insertQueuedRun).not.toHaveBeenCalled();
    expect(q.recordScheduleFireFailure).toHaveBeenCalledWith(
      expect.anything(),
      "sch-1",
      "INVALID_PARAMS",
    );
  });
});

describe("fire endpoint — AWS error name on the invocation_failed event (#306)", () => {
  it("adds aws_error/http/request_id, never the SDK message or params", async () => {
    const error = vi.spyOn(console, "error").mockImplementation(() => {});
    const sdkErr = Object.assign(new Error("not authorized: SENTINEL-DO-NOT-LOG"), {
      name: "AccessDeniedException",
      $metadata: { httpStatusCode: 403, requestId: "req-fire" },
    });
    aws.invokeAgentRuntime.mockRejectedValue(
      new InvocationFailedError("InvokeAgentRuntime failed.", { cause: sdkErr }),
    );

    const res = await fire(SECRET);
    expect(res.status).toBe(502);

    const lines = error.mock.calls.map((c) => String(c[0]));
    const failed = lines.find((l) => l.includes('"event":"invocation_failed"'));
    expect(failed).toBeDefined();
    const parsed = JSON.parse(failed!);
    expect(parsed.error_code).toBe("INVOCATION_FAILED");
    expect(parsed.aws_error).toBe("AccessDeniedException");
    expect(parsed.http).toBe(403);
    expect(parsed.request_id).toBe("req-fire");

    const all = lines.join(" ");
    expect(all).not.toContain("SENTINEL-DO-NOT-LOG");
    expect(all).not.toContain("fix_mode");
    error.mockRestore();
  });

  it("logs aws_error=unknown for a non-AWS invoke failure", async () => {
    const error = vi.spyOn(console, "error").mockImplementation(() => {});
    aws.invokeAgentRuntime.mockRejectedValue(new Error("plain non-aws failure"));
    await fire(SECRET);
    const failed = error.mock.calls
      .map((c) => String(c[0]))
      .find((l) => l.includes('"event":"invocation_failed"'));
    expect(failed).toBeDefined();
    expect(JSON.parse(failed!).aws_error).toBe("unknown");
    error.mockRestore();
  });
});
