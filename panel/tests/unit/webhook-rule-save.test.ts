import { describe, expect, it, vi } from "vitest";
import {
  resolveReorderRules,
  resolveSaveRule,
  validateRuleInput,
  type RuleValidationContext,
  type SaveRuleDeps,
} from "@/lib/domain/webhook-rule-save";

// Layer 1 — S-177 (#322): save-time validation of a webhook rule. The rule
// must be able to fire and resolve: the same checks the runtime applies
// (S-170 conditions, S-171 resolution: agent, repository, declared-key params)
// run here, so a broken rule is flagged before it is stored.

const AGENT = "11111111-1111-4111-8111-111111111111";
const NO_REPO_AGENT = "22222222-2222-4222-8222-222222222222";
const OFF_AGENT = "33333333-3333-4333-8333-333333333333";
const REPO = "44444444-4444-4444-8444-444444444444";
const ARCHIVED = "55555555-5555-4555-8555-555555555555";
const OTHER_RULE = "66666666-6666-4666-8666-666666666666";

const schema = {
  type: "object",
  additionalProperties: false,
  required: ["mode"],
  properties: {
    mode: { type: "string", enum: ["audit_only", "fix"] },
    pr_number: { type: "integer", minimum: 1 },
    note: { type: "string" },
    options: { type: "object" },
  },
};

const ctx: RuleValidationContext = {
  endpointEvents: ["issue_comment", "pull_request"],
  agents: new Map([
    [AGENT, { id: AGENT, isEnabled: true, requiresRepository: true, paramsSchema: schema }],
    [
      NO_REPO_AGENT,
      {
        id: NO_REPO_AGENT,
        isEnabled: true,
        requiresRepository: false,
        paramsSchema: { type: "object", properties: {} },
      },
    ],
    [
      OFF_AGENT,
      { id: OFF_AGENT, isEnabled: false, requiresRepository: true, paramsSchema: schema },
    ],
  ]),
  usableRepositoryIds: new Set([REPO]),
  otherDefaultRuleId: null,
};

const good = {
  name: "comment → audit",
  eventTypes: ["issue_comment"],
  conditions: [{ field: "comment.body", op: "contains", value: "/audit" }],
  isDefault: false,
  agentId: AGENT,
  repoMode: "payload_field",
  repositoryId: null,
  repoPayloadField: "repository.full_name",
  params: { static: { mode: "audit_only" }, from_payload: { pr_number: "issue.number" } },
  autoDisableThreshold: 3,
  notifyOnSuccess: false,
  isEnabled: true,
};

function errorsOf(raw: unknown, c: RuleValidationContext = ctx) {
  const r = validateRuleInput(raw, c);
  return r.ok ? {} : r.fieldErrors;
}

describe("validateRuleInput — valid rules", () => {
  it("accepts a payload-repo rule and normalizes it for the DB", () => {
    const r = validateRuleInput(good, ctx);
    expect(r).toEqual({
      ok: true,
      value: {
        name: "comment → audit",
        eventTypes: ["issue_comment"],
        conditions: [{ field: "comment.body", op: "contains", value: "/audit" }],
        isDefault: false,
        agentId: AGENT,
        repoMode: "payload_field",
        repositoryId: null,
        repoPayloadField: "repository.full_name",
        params: { static: { mode: "audit_only" }, from_payload: { pr_number: "issue.number" } },
        autoDisableThreshold: 3,
        notifyOnSuccess: false,
        isEnabled: true,
      },
    });
  });

  it("accepts a fixed-repo rule and drops the unused payload path", () => {
    const r = validateRuleInput(
      { ...good, repoMode: "fixed", repositoryId: REPO, repoPayloadField: "x" },
      ctx,
    );
    expect(r.ok && r.value).toMatchObject({
      repoMode: "fixed",
      repositoryId: REPO,
      repoPayloadField: null,
    });
  });

  it("stores a default rule without event types or conditions (they never apply to it)", () => {
    const r = validateRuleInput({ ...good, isDefault: true, eventTypes: [], conditions: [] }, ctx);
    expect(r.ok && r.value).toMatchObject({ isDefault: true, eventTypes: [], conditions: [] });
    const r2 = validateRuleInput({ ...good, isDefault: true }, ctx);
    expect(r2.ok && r2.value).toMatchObject({ eventTypes: [], conditions: [] });
  });

  it("lets a payload value fill a required key (required is not flagged when from_payload covers it)", () => {
    const r = validateRuleInput(
      { ...good, params: { static: {}, from_payload: { mode: "comment.body" } } },
      ctx,
    );
    expect(r.ok).toBe(true);
  });

  it('drops empty static values so a blank optional field isn\'t stored as ""', () => {
    const r = validateRuleInput({ ...good, params: { static: { mode: "fix", note: "" } } }, ctx);
    expect(r.ok && r.value.params).toEqual({ static: { mode: "fix" }, from_payload: {} });
  });

  it("allows the editor's own rule to stay the default", () => {
    expect(
      validateRuleInput({ ...good, isDefault: true }, { ...ctx, otherDefaultRuleId: null }).ok,
    ).toBe(true);
  });
});

describe("validateRuleInput — flagged before save", () => {
  it.each<[string, Record<string, unknown>, string]>([
    [
      "an empty event list on a non-default rule (it could never match)",
      { eventTypes: [] },
      "eventTypes",
    ],
    ["an event the endpoint doesn't accept", { eventTypes: ["push"] }, "eventTypes"],
    [
      "an unknown condition operator",
      { conditions: [{ field: "a", op: "regex", value: "x" }] },
      "conditions",
    ],
    ["a missing condition value", { conditions: [{ field: "a", op: "equals" }] }, "conditions"],
    [
      "an unknown condition key (B-2)",
      { conditions: [{ field: "a", op: "exists", extra: 1 }] },
      "conditions",
    ],
    ["a malformed condition path", { conditions: [{ field: "a..b", op: "exists" }] }, "conditions"],
    [
      "a forbidden path segment",
      { conditions: [{ field: "__proto__.x", op: "exists" }] },
      "conditions",
    ],
    ["an unknown agent", { agentId: "77777777-7777-4777-8777-777777777777" }, "agentId"],
    ["a disabled agent", { agentId: OFF_AGENT }, "agentId"],
    ["payload repo mode without a path", { repoPayloadField: "" }, "repoPayloadField"],
    [
      "payload repo mode with a bad path",
      { repoPayloadField: "repository..name" },
      "repoPayloadField",
    ],
    ["fixed mode without a repository", { repoMode: "fixed", repositoryId: null }, "repositoryId"],
    [
      "fixed mode with an archived repository",
      { repoMode: "fixed", repositoryId: ARCHIVED },
      "repositoryId",
    ],
    [
      "a from_payload key the agent doesn't declare",
      { params: { static: { mode: "fix" }, from_payload: { token: "x" } } },
      "params",
    ],
    [
      "a from_payload key that isn't a scalar",
      { params: { static: { mode: "fix" }, from_payload: { options: "x" } } },
      "params",
    ],
    [
      "a payload value with no parameter chosen",
      { params: { static: { mode: "fix" }, from_payload: { "": "issue.number" } } },
      "params",
    ],
    [
      "a from_payload path that doesn't parse",
      { params: { static: { mode: "fix" }, from_payload: { note: "a..b" } } },
      "params",
    ],
    [
      "static params failing the schema",
      { params: { static: { mode: "delete_everything" } } },
      "params",
    ],
    ["a missing required param", { params: { static: {} } }, "params"],
    ["an undeclared static key", { params: { static: { mode: "fix", evil: 1 } } }, "params"],
    ["a threshold below 1", { autoDisableThreshold: 0 }, "autoDisableThreshold"],
    ["a non-integer threshold", { autoDisableThreshold: 2.5 }, "autoDisableThreshold"],
    ["a name over 100 characters", { name: "x".repeat(101) }, "name"],
    ["a non-boolean enabled flag", { isEnabled: "yes" }, "isEnabled"],
  ])("flags %s", (_label, patch, field) => {
    expect(Object.keys(errorsOf({ ...good, ...patch }))).toContain(field);
  });

  it("flags a second default rule, naming the conflict", () => {
    const e = errorsOf({ ...good, isDefault: true }, { ...ctx, otherDefaultRuleId: OTHER_RULE });
    expect(e.isDefault).toMatch(/already has a default/i);
  });

  it("does not require a repository for an agent that runs without one", () => {
    const r = validateRuleInput(
      {
        ...good,
        agentId: NO_REPO_AGENT,
        repoMode: "payload_field",
        repoPayloadField: "repository.full_name",
        params: {},
      },
      ctx,
    );
    expect(r.ok).toBe(true);
  });

  it("reports the failing condition row by its number", () => {
    const e = errorsOf({
      ...good,
      conditions: [
        { field: "a", op: "exists" },
        { field: "b", op: "equals" },
      ],
    });
    expect(e.conditions).toMatch(/condition 2/i);
  });

  it("is total over garbage input", () => {
    for (const raw of [null, undefined, 1, "x", [], { params: "x" }, { conditions: "x" }]) {
      expect(validateRuleInput(raw, ctx).ok).toBe(false);
    }
  });
});

// ---- the Server Action core: builds the context from the DB, then writes ----

const ENDPOINT = "88888888-8888-4888-8888-888888888888";
const RULE = "99999999-9999-4999-8999-999999999999";

function deps(over: Partial<SaveRuleDeps> = {}): SaveRuleDeps {
  return {
    getEndpoint: vi.fn(async () => ({
      id: ENDPOINT,
      event_allowlist: ["issue_comment", "pull_request"],
    })),
    getAgents: vi.fn(async () => [
      { id: AGENT, is_enabled: true, requires_repository: true, params_schema: schema },
    ]),
    getRepositoryIds: vi.fn(async () => [REPO]),
    getRules: vi.fn(async () => [] as { id: string; is_default: boolean }[]),
    create: vi.fn(async () => RULE),
    update: vi.fn(async () => {}),
    ...over,
  };
}

describe("resolveSaveRule", () => {
  it("creates a valid rule on the endpoint and returns its id", async () => {
    const d = deps();
    expect(await resolveSaveRule(ENDPOINT, null, good, d)).toEqual({ ok: true, id: RULE });
    expect(d.create).toHaveBeenCalledWith(
      ENDPOINT,
      expect.objectContaining({ name: "comment → audit", agentId: AGENT }),
    );
  });

  it("updates an existing rule of that endpoint", async () => {
    const d = deps({ getRules: vi.fn(async () => [{ id: RULE, is_default: false }]) });
    expect(await resolveSaveRule(ENDPOINT, RULE, good, d)).toEqual({ ok: true, id: RULE });
    expect(d.update).toHaveBeenCalledWith(
      RULE,
      expect.objectContaining({ name: "comment → audit" }),
    );
  });

  it("refuses to update a rule that belongs to another endpoint", async () => {
    const d = deps({ getRules: vi.fn(async () => []) });
    expect(await resolveSaveRule(ENDPOINT, RULE, good, d)).toMatchObject({
      ok: false,
      code: "INVALID_ID",
    });
    expect(d.update).not.toHaveBeenCalled();
  });

  it("returns field errors and writes nothing for an invalid rule", async () => {
    const d = deps();
    const r = await resolveSaveRule(ENDPOINT, null, { ...good, eventTypes: ["push"] }, d);
    expect(r).toMatchObject({
      ok: false,
      code: "INVALID_INPUT",
      fieldErrors: { eventTypes: expect.any(String) },
    });
    expect(d.create).not.toHaveBeenCalled();
  });

  it("flags a second default, but lets the current default stay default", async () => {
    const d = deps({
      getRules: vi.fn(async () => [
        { id: "other", is_default: true },
        { id: RULE, is_default: false },
      ]),
    });
    const r = await resolveSaveRule(ENDPOINT, RULE, { ...good, isDefault: true }, d);
    expect(r).toMatchObject({
      ok: false,
      fieldErrors: { isDefault: expect.stringMatching(/already has a default/i) },
    });
    const d2 = deps({ getRules: vi.fn(async () => [{ id: RULE, is_default: true }]) });
    expect((await resolveSaveRule(ENDPOINT, RULE, { ...good, isDefault: true }, d2)).ok).toBe(true);
  });

  it("rejects an unknown endpoint and bad ids", async () => {
    expect(
      await resolveSaveRule(ENDPOINT, null, good, deps({ getEndpoint: vi.fn(async () => null) })),
    ).toMatchObject({
      ok: false,
      code: "INVALID_ID",
    });
    expect(await resolveSaveRule("nope", null, good, deps())).toMatchObject({
      ok: false,
      code: "INVALID_ID",
    });
    expect(await resolveSaveRule(ENDPOINT, "nope", good, deps())).toMatchObject({
      ok: false,
      code: "INVALID_ID",
    });
  });

  it("maps a DB failure to a generic error", async () => {
    const d = deps({
      create: vi.fn(async () => {
        throw new Error(
          "duplicate key value violates unique constraint uq_webhook_rules_one_default",
        );
      }),
    });
    const r = await resolveSaveRule(ENDPOINT, null, good, d);
    expect(r).toMatchObject({ ok: false, code: "DATABASE_ERROR" });
    expect(JSON.stringify(r)).not.toContain("uq_webhook_rules");
  });
});

describe("resolveReorderRules", () => {
  it("passes a uuid list through and rejects anything else", async () => {
    const reorder = vi.fn(async () => {});
    expect(await resolveReorderRules(ENDPOINT, [RULE, AGENT], { reorder })).toEqual({ ok: true });
    expect(reorder).toHaveBeenCalledWith(ENDPOINT, [RULE, AGENT]);
    expect((await resolveReorderRules(ENDPOINT, [RULE, "x"], { reorder })).ok).toBe(false);
    expect((await resolveReorderRules(ENDPOINT, "x", { reorder })).ok).toBe(false);
    expect(reorder).toHaveBeenCalledTimes(1);
  });
});

describe("validateRuleInput — payload row messages", () => {
  it("names a half-filled row by its number instead of an empty key", () => {
    const e = errorsOf({
      ...good,
      params: { static: { mode: "fix" }, from_payload: { "": "a..b" } },
    });
    expect(e.params).toBe(
      "Payload value 1: choose a parameter; Payload value 1: not a valid payload path",
    );
  });
});
