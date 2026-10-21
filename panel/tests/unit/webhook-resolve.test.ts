import { describe, expect, it, vi } from "vitest";
import { resolveRoute, type ResolveDeps, type ResolvableRule } from "@/lib/domain/webhook-resolve";
import type { AgentRow, RepositoryRow } from "@/lib/supabase/types";

// Layer 1 — S-171 (#316): turn a matched rule into a concrete, validated
// (agent, repository, params) or a recorded rejection (D-W8, D-W9, FR12–FR14).

const schema = {
  type: "object",
  additionalProperties: false,
  required: ["mode"],
  properties: {
    mode: { type: "string", enum: ["audit_only", "fix"] },
    pr_number: { type: "integer" },
    note: { type: "string" },
  },
};

function agent(over: Partial<AgentRow> = {}): AgentRow {
  return {
    id: "ag-1",
    slug: "security-analyst",
    name: "Security analyst",
    description: null,
    version: "1",
    runtime_arn: "arn:x",
    runtime_qualifier: "DEFAULT",
    params_schema: schema,
    default_params: {},
    requires_repository: true,
    max_runtime_seconds: 3600,
    grace_seconds: 60,
    start_timeout_seconds: 120,
    is_enabled: true,
    created_at: "",
    updated_at: "",
    ...over,
  };
}

function repo(over: Partial<RepositoryRow> = {}): RepositoryRow {
  return {
    id: "rp-1",
    installation_id: "in-1",
    github_repo_id: 1,
    full_name: "llipe/repo-a",
    default_branch: "main",
    is_enabled: true,
    metadata: {},
    archived_at: null,
    created_at: "",
    updated_at: "",
    ...over,
  };
}

function rule(over: Partial<ResolvableRule> = {}): ResolvableRule {
  return {
    id: "rule-1",
    agent_id: "ag-1",
    repo_mode: "payload_field",
    repository_id: null,
    repo_payload_field: "repository.full_name",
    params: { static: { mode: "audit_only" } },
    ...over,
  };
}

function deps(
  opts: {
    agent?: AgentRow | null;
    byId?: RepositoryRow | null;
    byName?: RepositoryRow | null;
  } = {},
): ResolveDeps {
  return {
    getAgent: vi.fn(async () => (opts.agent === undefined ? agent() : opts.agent)),
    getRepositoryById: vi.fn(async () => (opts.byId === undefined ? repo() : opts.byId)),
    getRepositoryByFullName: vi.fn(async () => (opts.byName === undefined ? repo() : opts.byName)),
  };
}

const payload = {
  repository: { full_name: "llipe/repo-a" },
  pull_request: { number: 42, title: "x" },
  comment: { body: "note text" },
};

describe("resolveRoute", () => {
  it("resolves a payload-field repo, static params and declared interpolation (AC4)", async () => {
    const d = deps();
    const r = await resolveRoute(
      d,
      rule({
        params: {
          static: { mode: "audit_only" },
          from_payload: { pr_number: "pull_request.number" },
        },
      }),
      payload,
    );
    expect(r).toEqual({
      ok: true,
      agent: expect.objectContaining({ id: "ag-1" }),
      repository: expect.objectContaining({ id: "rp-1", full_name: "llipe/repo-a" }),
      params: { mode: "audit_only", pr_number: 42 },
      droppedKeys: [],
    });
    expect(d.getRepositoryByFullName).toHaveBeenCalledWith("llipe/repo-a");
  });

  it("resolves a fixed repo by id without reading the payload", async () => {
    const d = deps();
    const r = await resolveRoute(
      d,
      rule({ repo_mode: "fixed", repository_id: "rp-1", repo_payload_field: null }),
      {},
    );
    expect(r.ok).toBe(true);
    expect(d.getRepositoryById).toHaveBeenCalledWith("rp-1");
    expect(d.getRepositoryByFullName).not.toHaveBeenCalled();
  });

  it("skips the repo entirely for an agent that doesn't need one", async () => {
    const d = deps({ agent: agent({ requires_repository: false }) });
    const r = await resolveRoute(d, rule(), {});
    expect(r).toMatchObject({ ok: true, repository: null });
    expect(d.getRepositoryByFullName).not.toHaveBeenCalled();
  });

  describe("agent rejections", () => {
    it.each([
      ["missing", null],
      ["disabled", agent({ is_enabled: false })],
    ])("rejects a %s agent (EC-13)", async (_label, a) => {
      expect(await resolveRoute(deps({ agent: a }), rule(), payload)).toEqual({
        ok: false,
        reason: "agent_unavailable",
      });
    });
  });

  describe("repository rejections (AC5, never auto-create)", () => {
    it.each([
      ["unknown", null],
      ["disabled", repo({ is_enabled: false })],
      ["archived", repo({ archived_at: "2026-01-01T00:00:00Z" })],
    ])("rejects a payload repo that is %s", async (_label, r) => {
      expect(await resolveRoute(deps({ byName: r }), rule(), payload)).toEqual({
        ok: false,
        reason: "repository_not_allowed",
      });
    });

    it.each([
      ["missing", {}],
      ["not a string", { repository: { full_name: 7 } }],
      ["not owner/name", { repository: { full_name: "just-a-name" } }],
      ["a URL (EC-7)", { repository: { full_name: "https://github.com/llipe/repo-a" } }],
      ["with .git (EC-7)", { repository: { full_name: "llipe/repo-a.git/x" } }],
      ["too long", { repository: { full_name: "a/" + "b".repeat(300) } }],
    ])("rejects a payload repo field that is %s without a lookup", async (_label, p) => {
      const d = deps();
      expect(await resolveRoute(d, rule(), p)).toEqual({
        ok: false,
        reason: "repository_not_allowed",
      });
      expect(d.getRepositoryByFullName).not.toHaveBeenCalled();
    });

    it.each([
      ["unknown", null],
      ["disabled", repo({ is_enabled: false })],
    ])("rejects a fixed repo that is %s", async (_label, r) => {
      const fixed = rule({ repo_mode: "fixed", repository_id: "rp-1", repo_payload_field: null });
      expect(await resolveRoute(deps({ byId: r }), fixed, payload)).toEqual({
        ok: false,
        reason: "repository_not_allowed",
      });
    });

    it("rejects a fixed rule with no repository_id", async () => {
      const fixed = rule({ repo_mode: "fixed", repository_id: null, repo_payload_field: null });
      expect(await resolveRoute(deps(), fixed, payload)).toEqual({
        ok: false,
        reason: "repository_not_allowed",
      });
    });
  });

  describe("params (D-W9, I-5)", () => {
    it("rejects params that fail the agent schema (AC5)", async () => {
      expect(
        await resolveRoute(deps(), rule({ params: { static: { mode: "destroy" } } }), payload),
      ).toEqual({
        ok: false,
        reason: "invalid_params",
      });
    });

    it("rejects when a required key is absent", async () => {
      expect(await resolveRoute(deps(), rule({ params: {} }), payload)).toEqual({
        ok: false,
        reason: "invalid_params",
      });
    });

    it("rejects a payload value of the wrong type for its key", async () => {
      const r = rule({
        params: { static: { mode: "fix" }, from_payload: { pr_number: "pull_request.title" } },
      });
      expect(await resolveRoute(deps(), r, payload)).toEqual({
        ok: false,
        reason: "invalid_params",
      });
    });

    it("drops an undeclared from_payload key and reports it, never sending it to the agent", async () => {
      const r = rule({
        params: {
          static: { mode: "fix" },
          from_payload: { token: "comment.body", note: "comment.body" },
        },
      });
      const out = await resolveRoute(deps(), r, payload);
      expect(out).toMatchObject({
        ok: true,
        params: { mode: "fix", note: "note text" },
        droppedKeys: ["token"],
      });
      expect(JSON.stringify(out)).not.toContain('"token":');
    });

    it("rejects an undeclared static key when the schema forbids extras (same as manual invoke)", async () => {
      expect(
        await resolveRoute(
          deps(),
          rule({ params: { static: { mode: "fix", extra: 1 } } }),
          payload,
        ),
      ).toEqual({
        ok: false,
        reason: "invalid_params",
      });
    });

    it("lets a payload value override a static value for the same declared key", async () => {
      const r = rule({
        params: { static: { mode: "fix", note: "static" }, from_payload: { note: "comment.body" } },
      });
      const out = await resolveRoute(deps(), r, payload);
      expect(out.ok && out.params).toEqual({ mode: "fix", note: "note text" });
    });

    it("leaves a key unset when its payload path is missing", async () => {
      const r = rule({
        params: { static: { mode: "fix" }, from_payload: { note: "comment.missing" } },
      });
      const out = await resolveRoute(deps(), r, payload);
      expect(out.ok && out.params).toEqual({ mode: "fix" });
    });

    it("never interpolates an object or array from the payload", async () => {
      const r = rule({
        params: { static: { mode: "fix" }, from_payload: { note: "pull_request" } },
      });
      expect(await resolveRoute(deps(), r, payload)).toEqual({
        ok: false,
        reason: "invalid_params",
      });
    });

    // The scalar guard is the only thing standing between a payload object and
    // the agent when the schema key has no type, so test it there.
    it.each([
      ["an object", "pull_request"],
      ["an array", "labels"],
    ])("never interpolates %s, even into an untyped schema key", async (_label, path) => {
      const loose = agent({
        params_schema: {
          type: "object",
          required: ["mode"],
          properties: { mode: { type: "string" }, anything: {} },
        },
      });
      const r = rule({ params: { static: { mode: "fix" }, from_payload: { anything: path } } });
      const p = { ...payload, labels: [{ name: "x" }] };
      expect(await resolveRoute(deps({ agent: loose }), r, p)).toEqual({
        ok: false,
        reason: "invalid_params",
      });
    });

    it("refuses a forbidden path in from_payload", async () => {
      const r = rule({ params: { static: { mode: "fix" }, from_payload: { note: "__proto__" } } });
      const parsed: unknown = JSON.parse(
        '{"__proto__":"x","repository":{"full_name":"llipe/repo-a"}}',
      );
      const out = await resolveRoute(deps(), r, parsed);
      expect(out.ok && out.params).toEqual({ mode: "fix" });
    });

    it.each([
      ["a non-object params", "nope"],
      ["a non-object static", { static: [1] }],
      ["a non-object from_payload", { from_payload: "x" }],
    ])("treats %s as invalid_params", async (_label, params) => {
      const r = rule({ params: params as unknown as ResolvableRule["params"] });
      expect(await resolveRoute(deps(), r, payload)).toEqual({
        ok: false,
        reason: "invalid_params",
      });
    });
  });

  it("propagates a lookup failure (the route answers 5xx)", async () => {
    const d = deps();
    vi.mocked(d.getAgent).mockRejectedValueOnce(new Error("db down"));
    await expect(resolveRoute(d, rule(), payload)).rejects.toThrow("db down");
  });
});
