import { createHmac, randomBytes } from "node:crypto";
import { readFileSync, readdirSync } from "node:fs";
import { fileURLToPath } from "node:url";
import type { AnySchema } from "ajv";
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";
import { resolveRoute, type ResolvableRule, type ResolveDeps } from "@/lib/domain/webhook-resolve";
import { validateParams } from "@/lib/schema/validate";
import type { AgentRow, RepositoryRow } from "@/lib/supabase/types";
import { probeLocalDb, withDb } from "./db";

// Layer 2.5 — S-184 (#366): the `bug-fix` agents seed row, its issue-mode
// params_schema (spec §5.2 v2.0) and the webhook mapping, against the REAL
// seeded row on local Supabase (never mocked — TESTING.md Layer 2.5 boundary).
// Only the AgentCore network call is stubbed, as in webhook-fire.test.ts.
//
// Test plan: TC-184-01..03, -05, -06, -15, -16; CT-03, CT-04, CT-06, CT-19,
// CT-23, CT-24. The webhook-route case also covers the S-181 AC4 deferral: a
// `bug-fix` invoke resolves the seeded runtime ARN.
//
// The `issue_comment.created` fixture is modeled on GitHub's documented
// payload shape, not recorded from a live delivery (TESTING.md harness defect 4).

const aws = vi.hoisted(() => ({ invokeAgentRuntime: vi.fn(async () => undefined) }));
vi.mock("@/lib/aws/invoke", () => aws);

const probe = await probeLocalDb();

const ROOT = fileURLToPath(new URL("../../../", import.meta.url));
const MIGRATIONS = `${ROOT}supabase/migrations`;
const SEED = `${ROOT}supabase/seed.sql`;
const FIXTURE_SCHEMA = `${ROOT}agents/bug-fix/app/bugFix/tests/fixtures/contract/params_schema.json`;
const FIXTURE_PAYLOAD = fileURLToPath(
  new URL("../fixtures/github/issue_comment.created.json", import.meta.url),
);

/** S-181 deployed runtime (infra/changes/20261023-bug-fix-runtime, deployed-state.json). */
const RUNTIME_ARN =
  "arn:aws:bedrock-agentcore:us-east-1:755641879575:runtime/bugfix_bug_fix-BiuPsdGSPK";
const ARN_SHAPE = /^arn:aws:bedrock-agentcore:[a-z0-9-]+:\d{12}:runtime\/[A-Za-z0-9_-]+$/;

/** The runbook's webhook mapping (FR-28, D-88). */
const RUNBOOK_MAPPING = { issue_number: "issue.number", trigger_comment_id: "comment.id" };

interface SchemaProp {
  type: string;
  default?: unknown;
  [k: string]: unknown;
}
interface ParamsSchema {
  type: string;
  additionalProperties: boolean;
  required: string[];
  properties: Record<string, SchemaProp>;
}
interface SeedRow {
  id: string;
  slug: string;
  name: string;
  runtime_arn: string;
  runtime_qualifier: string;
  requires_repository: boolean;
  max_runtime_seconds: number;
  grace_seconds: number;
  start_timeout_seconds: number;
  is_enabled: boolean;
  params_schema: ParamsSchema;
  default_params: Record<string, unknown>;
}

const fixtureSchema = JSON.parse(readFileSync(FIXTURE_SCHEMA, "utf8")) as ParamsSchema;
const fixturePayload = JSON.parse(readFileSync(FIXTURE_PAYLOAD, "utf8")) as Record<string, unknown>;

function migrationFile(): string {
  const found = readdirSync(MIGRATIONS).filter((f) => f.endsWith("_seed_bug_fix_agent.sql"));
  expect(found, "exactly one *_seed_bug_fix_agent.sql migration").toHaveLength(1);
  return `${MIGRATIONS}/${found[0]}`;
}

/** The `insert into agents … 'bug-fix' … on conflict (slug)` statement of a SQL file. */
function bugFixStatement(sql: string): string {
  const at = sql.indexOf("'bug-fix',");
  expect(at, "the SQL carries a 'bug-fix' agents row").toBeGreaterThan(-1);
  const start = sql.lastIndexOf("insert into agents", at);
  const end = sql.indexOf("on conflict (slug) do update", at);
  expect(start).toBeGreaterThan(-1);
  expect(end).toBeGreaterThan(at);
  return sql.slice(start, end);
}

function seededJson(sql: string): { schema: unknown; defaults: unknown } {
  const stmt = bugFixStatement(sql);
  const schema = /\$json\$([\s\S]*?)\$json\$/.exec(stmt)?.[1];
  const defaults = /'(\{[^']*\})'::jsonb/.exec(stmt)?.[1];
  expect(schema, "params_schema $json$ block").toBeDefined();
  expect(defaults, "default_params literal").toBeDefined();
  return { schema: JSON.parse(schema!), defaults: JSON.parse(defaults!) };
}

async function readRow(): Promise<SeedRow> {
  const rows = await withDb((c) =>
    c.query<SeedRow>(`select * from agents where slug = 'bug-fix'`).then((r) => r.rows),
  );
  expect(rows).toHaveLength(1);
  return rows[0]!;
}

// ---------------------------------------------------------------------------
// File-level contract: runs with or without the local stack.
// ---------------------------------------------------------------------------

describe("panel L2.5 — bug-fix seed files (S-184)", () => {
  it("the migration upserts with the siblings' on-conflict shape (AC1)", () => {
    const sql = readFileSync(migrationFile(), "utf8");
    expect(sql).toMatch(/insert into agents \(/);
    expect(sql).toMatch(/on conflict \(slug\) do update/);
    expect(sql).toMatch(/delete from agents where slug = 'bug-fix'/); // rollback header (5.4)
  });

  it("seed.sql mirrors the migration's params_schema and default_params (TC-184-02)", () => {
    const fromMigration = seededJson(readFileSync(migrationFile(), "utf8"));
    const fromSeed = seededJson(readFileSync(SEED, "utf8"));
    expect(fromSeed).toEqual(fromMigration);
    expect(fromMigration.schema).toEqual(fixtureSchema);
  });

  it("both files carry the S-181 runtime ARN and 3600/120/300 (AC2)", () => {
    for (const path of [migrationFile(), SEED]) {
      const stmt = bugFixStatement(readFileSync(path, "utf8"));
      expect(stmt).toContain(`'${RUNTIME_ARN}'`);
      expect(stmt).toMatch(/\b3600,\s*-- max_runtime_seconds/);
      expect(stmt).toMatch(/\b120,\s*-- grace_seconds/);
      expect(stmt).toMatch(/\b300\s*,\s*-- start_timeout_seconds/);
    }
  });
});

// ---------------------------------------------------------------------------
// Against the live local stack.
// ---------------------------------------------------------------------------

describe.skipIf(!probe.available)("panel L2.5 — bug-fix seed row (S-184)", () => {
  let row: SeedRow;

  beforeAll(async () => {
    console.log(`[integration] ${probe.reason}`);
    row = await readRow();
  });

  it("has exactly one row with requires_repository, 3600/120/300 and the ARN (TC-184-01, -03)", () => {
    expect(row).toMatchObject({
      slug: "bug-fix",
      name: "Bug Fix",
      requires_repository: true,
      max_runtime_seconds: 3600,
      grace_seconds: 120,
      start_timeout_seconds: 300,
      runtime_arn: RUNTIME_ARN,
      runtime_qualifier: "DEFAULT",
      is_enabled: true,
    });
    expect(row.runtime_arn).toMatch(ARN_SHAPE);
  });

  it("re-applying the migration keeps one row and restores its fields (TC-184-01, EC-13)", async () => {
    const sql = readFileSync(migrationFile(), "utf8");
    await withDb(async (c) => {
      await c.query(
        `update agents set grace_seconds = 1, params_schema = '{}'::jsonb, default_params = '{}'::jsonb
          where slug = 'bug-fix'`,
      );
      await c.query(sql);
    });
    const again = await readRow();
    expect(again.id).toBe(row.id);
    expect(again.grace_seconds).toBe(120);
    expect(again.params_schema).toEqual(fixtureSchema);
    expect(again.default_params).toEqual(row.default_params);
  });

  it("params_schema deep-equals the spec §5.2 v2.0 fixture (CT-06, TC-184-15)", () => {
    expect(row.params_schema).toEqual(fixtureSchema);
    expect(row.params_schema.required).toEqual(["issue_number"]);
    expect(row.params_schema.additionalProperties).toBe(false);
  });

  it("default_params holds only the budget, cap and status defaults, equal to each default (CT-06)", () => {
    const withDefault = Object.entries(row.params_schema.properties)
      .filter(([, p]) => "default" in p)
      .map(([k]) => k)
      .sort();
    expect(Object.keys(row.default_params).sort()).toEqual(withDefault);
    expect(withDefault).toEqual([
      "cli_timeout_minutes",
      "max_code_files",
      "max_code_lines",
      "max_turns",
      "run_budget_minutes",
      "status_in_progress",
      "status_in_review",
      "status_ready",
    ]);
    for (const [key, value] of Object.entries(row.default_params)) {
      expect(value, key).toEqual(row.params_schema.properties[key]!.default);
    }
    expect(row.default_params.run_budget_minutes).toBe(55);
    const merged = validateParams(row.id, row.params_schema as AnySchema, {
      issue_number: 1,
      ...row.default_params,
    });
    expect(merged.valid).toBe(true);
  });

  describe("validateParams against the seeded schema", () => {
    const check = (params: unknown) =>
      validateParams(row.id, row.params_schema as AnySchema, params);

    it("accepts {issue_number: 7} (TC-184-15)", () => {
      expect(check({ issue_number: 7 })).toEqual({ valid: true, params: { issue_number: 7 } });
    });

    it.each([
      ["{}", {}],
      ["issue_number 0", { issue_number: 0 }],
      ["select_labels", { issue_number: 7, select_labels: ["status: ready"] }],
      ["assignee", { issue_number: 7, assignee: "x" }],
    ])("rejects %s (TC-184-15)", (_label, params) => {
      expect(check(params).valid).toBe(false);
    });

    it.each([
      ["issue_number", { issue_number: "12" }],
      ["trigger_comment_id", { issue_number: 7, trigger_comment_id: "123" }],
      ["max_turns", { issue_number: 7, max_turns: 40.5 }],
      ["project", { issue_number: 7, project: 5 }],
      ["status_ready", { issue_number: 7, status_ready: 7 }],
      ["run_budget_minutes", { issue_number: 7, run_budget_minutes: 600 }],
    ])("rejects a type or range mismatch on %s (CT-03)", (key, params) => {
      const res = check(params);
      expect(res.valid).toBe(false);
      if (!res.valid) expect(res.errors.map((e) => e.instancePath)).toContain(`/${key}`);
    });

    it.each(["repo", "__probe", "select_labels", "assignee", "foo"])(
      "rejects the extra key %s (CT-04)",
      (key) => {
        const res = check({ issue_number: 7, [key]: true });
        expect(res.valid).toBe(false);
        if (!res.valid) expect(res.errors.map((e) => e.keyword)).toContain("additionalProperties");
      },
    );
  });

  it("every outcome and artifact type the agent emits exists in the enums (CT-19)", async () => {
    const values = await withDb(async (c) => ({
      outcomes: (
        await c.query<{ v: string }>(`select unnest(enum_range(null::run_outcome))::text as v`)
      ).rows.map((r) => r.v),
      artifacts: (
        await c.query<{ v: string }>(`select unnest(enum_range(null::artifact_type))::text as v`)
      ).rows.map((r) => r.v),
    }));
    expect(values.outcomes).toEqual(
      expect.arrayContaining(["fixed", "needs_review", "not_applicable"]),
    );
    expect(values.artifacts).toContain("pull_request");
  });
});

// ---------------------------------------------------------------------------
// resolveRoute with the runbook mapping (AC5, D-88): CT-23, CT-24.
// ---------------------------------------------------------------------------

function dbDeps(): ResolveDeps {
  return {
    getAgent: (id) =>
      withDb((c) =>
        c
          .query<AgentRow>(`select * from agents where id = $1`, [id])
          .then((r) => r.rows[0] ?? null),
      ),
    getRepositoryById: (id) =>
      withDb((c) =>
        c
          .query<RepositoryRow>(`select * from repositories where id = $1`, [id])
          .then((r) => r.rows[0] ?? null),
      ),
    getRepositoryByFullName: (name) =>
      withDb((c) =>
        c
          .query<RepositoryRow>(`select * from repositories where lower(full_name) = lower($1)`, [
            name,
          ])
          .then((r) => r.rows[0] ?? null),
      ),
  };
}

function payloadFor(repo: string, patch: (p: Record<string, unknown>) => void = () => {}) {
  const p = structuredClone(fixturePayload);
  (p.repository as Record<string, unknown>).full_name = repo;
  patch(p);
  return p;
}

describe.skipIf(!probe.available)("panel L2.5 — bug-fix resolveRoute (S-184 AC5)", () => {
  let agentId = "";
  let repoName = "";
  const rule = (fromPayload: Record<string, string> = RUNBOOK_MAPPING): ResolvableRule => ({
    id: "s184-rule",
    agent_id: agentId,
    repo_mode: "payload_field",
    repository_id: null,
    repo_payload_field: "repository.full_name",
    params: { from_payload: fromPayload },
  });

  beforeAll(async () => {
    ({ agentId, repoName } = await withDb(async (c) => ({
      agentId: (await c.query<{ id: string }>(`select id from agents where slug = 'bug-fix'`))
        .rows[0]!.id,
      repoName: (
        await c.query<{ full_name: string }>(
          `select full_name from repositories where is_enabled and archived_at is null
            order by full_name limit 1`,
        )
      ).rows[0]!.full_name,
    })));
  });

  it("maps issue.number and comment.id into valid integer params (CT-23, TC-184-16)", async () => {
    const res = await resolveRoute(dbDeps(), rule(), payloadFor(repoName));
    expect(res.ok).toBe(true);
    if (!res.ok) return;
    expect(res.repository?.full_name).toBe(repoName);
    // No default is injected (useDefaults: false): budgets come from the agent (CT-21).
    expect(res.params).toEqual({ issue_number: 42, trigger_comment_id: 2_500_000_000 });
    expect(Number.isInteger(res.params.trigger_comment_id)).toBe(true);
    expect(res.droppedKeys).toEqual([]);
  });

  it.each([
    ["issue.number missing", (p: Record<string, unknown>) => delete (p.issue as never)["number"]],
    ["issue.number null", (p: Record<string, unknown>) => ((p.issue as never)["number"] = null)],
    [
      "issue.number a string",
      (p: Record<string, unknown>) => ((p.issue as never)["number"] = "12"),
    ],
  ])("rejects %s as invalid_params (CT-24 a-c)", async (_label, patch) => {
    const res = await resolveRoute(dbDeps(), rule(), payloadFor(repoName, patch));
    expect(res).toEqual({ ok: false, reason: "invalid_params" });
  });

  it("rejects a mapping to an object as invalid_params (CT-24 d)", async () => {
    const res = await resolveRoute(
      dbDeps(),
      rule({ issue_number: "issue.number", trigger_comment_id: "comment.user" }),
      payloadFor(repoName),
    );
    expect(res).toEqual({ ok: false, reason: "invalid_params" });
  });

  it("drops an undeclared mapping and never sends it (CT-24 e)", async () => {
    const res = await resolveRoute(
      dbDeps(),
      rule({ ...RUNBOOK_MAPPING, commenter: "comment.user.login" }),
      payloadFor(repoName),
    );
    expect(res.ok).toBe(true);
    if (!res.ok) return;
    expect(res.droppedKeys).toEqual(["commenter"]);
    expect(res.params).not.toHaveProperty("commenter");
  });

  it.each(["attacker/not-registered", "a/b/c"])(
    "rejects the payload repo %s (CT-24 f)",
    async (repo) => {
      const res = await resolveRoute(dbDeps(), rule(), payloadFor(repo));
      expect(res).toEqual({ ok: false, reason: "repository_not_allowed" });
    },
  );

  it("rejects a disabled bug-fix agent (CT-24 g)", async () => {
    await withDb((c) => c.query(`update agents set is_enabled = false where id = $1`, [agentId]));
    try {
      const res = await resolveRoute(dbDeps(), rule(), payloadFor(repoName));
      expect(res).toEqual({ ok: false, reason: "agent_unavailable" });
    } finally {
      await withDb((c) => c.query(`update agents set is_enabled = true where id = $1`, [agentId]));
    }
  });
});

// ---------------------------------------------------------------------------
// The real webhook route fires bug-fix at the seeded runtime ARN
// (AC5 end to end; S-181 AC4 deferral, panel invoke resolves the ARN).
// ---------------------------------------------------------------------------

const SECRET = "s184-l25-secret";

describe.skipIf(!probe.available)("panel L2.5 — /bug-fix webhook fires bug-fix (S-184)", () => {
  let token = "";
  let endpointId = "";
  let ruleId = "";
  let repoName = "";

  async function post(payload: unknown) {
    const body = JSON.stringify(payload);
    const { POST } = await import("@/app/api/webhooks/[token]/route");
    const res = await POST(
      new Request(`http://local/api/webhooks/${token}`, {
        method: "POST",
        body,
        headers: {
          "x-github-event": "issue_comment",
          "x-github-delivery": randomBytes(8).toString("hex"),
          "x-hub-signature-256":
            "sha256=" + createHmac("sha256", SECRET).update(body).digest("hex"),
        },
      }),
      { params: Promise.resolve({ token }) },
    );
    return { status: res.status, json: (await res.json()) as Record<string, unknown> };
  }

  beforeEach(async () => {
    aws.invokeAgentRuntime.mockReset();
    aws.invokeAgentRuntime.mockResolvedValue(undefined);
    token = randomBytes(32).toString("base64url");
    ({ endpointId, ruleId, repoName } = await withDb(async (c) => {
      const ep = (
        await c.query<{ id: string }>(
          `insert into webhook_endpoints (name, url_token, event_allowlist)
           values ('s184', $1, array['issue_comment']) returning id`,
          [token],
        )
      ).rows[0]!.id;
      await c.query(`select webhook.set_endpoint_secret($1, $2)`, [ep, SECRET]);
      const r = (
        await c.query<{ id: string }>(
          `insert into webhook_rules (endpoint_id, position, event_types, conditions, agent_id,
                                      repo_mode, repo_payload_field, params)
           select $1, 0, array['issue_comment'], $2::jsonb, id,
                  'payload_field', 'repository.full_name', $3::jsonb
             from agents where slug = 'bug-fix' returning id`,
          [
            ep,
            JSON.stringify([
              { field: "action", op: "equals", value: "created" },
              { field: "comment.body", op: "prefix", value: "/bug-fix" },
            ]),
            JSON.stringify({ from_payload: RUNBOOK_MAPPING }),
          ],
        )
      ).rows[0]!.id;
      const name = (
        await c.query<{ full_name: string }>(
          `select full_name from repositories where is_enabled and archived_at is null
            order by full_name limit 1`,
        )
      ).rows[0]!.full_name;
      return { endpointId: ep, ruleId: r, repoName: name };
    }));
  });

  afterEach(async () => {
    await withDb(async (c) => {
      await c.query(`delete from runs where triggered_by = $1`, [
        `webhook:${endpointId}:${ruleId}`,
      ]);
      await c.query(`select webhook.delete_endpoint_secret($1)`, [endpointId]);
      await c.query(`delete from webhook_endpoints where id = $1`, [endpointId]);
    });
  });

  it("queues a webhook run and invokes the seeded bug-fix runtime ARN", async () => {
    const res = await post(payloadFor(repoName));
    expect(res.status).toBe(202);
    expect(res.json).toMatchObject({ status: "queued" });
    const runId = res.json.run_id as string;

    const run = await withDb((c) =>
      c
        .query(
          `select r.trigger_type::text as trigger_type, r.params, a.slug,
                  r.max_runtime_seconds, r.grace_seconds, r.start_timeout_seconds
             from runs r join agents a on a.id = r.agent_id where r.id = $1`,
          [runId],
        )
        .then((x) => x.rows[0]),
    );
    expect(run).toEqual({
      trigger_type: "webhook",
      params: { issue_number: 42, trigger_comment_id: 2_500_000_000 },
      slug: "bug-fix",
      max_runtime_seconds: 3600,
      grace_seconds: 120,
      start_timeout_seconds: 300,
    });

    expect(aws.invokeAgentRuntime).toHaveBeenCalledTimes(1);
    const [target, options] = aws.invokeAgentRuntime.mock.calls[0] as unknown as [
      { runtimeArn: string; runtimeQualifier: string },
      { payload: Record<string, unknown> },
    ];
    expect(target).toEqual({ runtimeArn: RUNTIME_ARN, runtimeQualifier: "DEFAULT" });
    const [org, name] = repoName.split("/");
    // Exactly the D-60 contract keys: no __probe, no defaults (CT-22, CT-23).
    expect(options.payload).toEqual({
      run_id: runId,
      repository_org: org,
      repository_name: name,
      base_branch: expect.any(String),
      params: { issue_number: 42, trigger_comment_id: 2_500_000_000 },
    });
  });

  it("does not match a comment that isn't /bug-fix", async () => {
    const res = await post(
      payloadFor(repoName, (p) => ((p.comment as Record<string, unknown>).body = "thanks!")),
    );
    expect(res.json).toEqual({ skipped: true, reason: "no_match" });
    expect(aws.invokeAgentRuntime).not.toHaveBeenCalled();
  });
});

if (!probe.available) {
  describe("panel L2.5 — bug-fix seed (skipped)", () => {
    it.skip(`SKIPPED: ${probe.reason}`, () => {});
  });
}
