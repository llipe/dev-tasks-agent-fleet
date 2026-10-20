import { describe, expect, it } from "vitest";
import {
  evaluateCondition,
  MAX_PATH_DEPTH,
  MAX_STRING_LENGTH,
  routeDelivery,
  selectField,
  validateConditions,
  type RoutableRule,
} from "@/lib/domain/webhook-routing";
import type { WebhookCondition } from "@/lib/supabase/types";
import { mulberry32, testSeed } from "../helpers/prng";

// Layer 1 — S-170 (#315): the pure, bounded routing engine (D-W7, D-W12).
// No regex, no code, own properties only; never throws on hostile payloads.

const BOT = "dev-tasks-agent-fleet[bot]";

const payload = {
  action: "created",
  comment: { body: "security review", user: { login: "alice", type: "User" } },
  repository: { full_name: "llipe/repo-a", topics: ["web", "api"] },
  commits: [{ id: "c1" }, { id: "c2" }],
  count: 3,
  draft: false,
  nothing: null,
  sender: { login: "alice", type: "User" },
};

function rule(over: Partial<RoutableRule> & { id: string; position: number }): RoutableRule {
  return {
    event_types: ["issue_comment"],
    conditions: [],
    is_default: false,
    is_enabled: true,
    ...over,
  };
}

describe("selectField", () => {
  it.each([
    ["action", "created"],
    ["comment.body", "security review"],
    ["comment.user.login", "alice"],
    ["commits[1].id", "c2"],
    ["repository.topics[0]", "web"],
    ["count", 3],
    ["draft", false],
    ["nothing", null],
  ])("resolves %s", (path, expected) => {
    expect(selectField(payload, path)).toEqual(expected);
  });

  it.each([
    ["a missing key", "comment.missing"],
    ["a path through a primitive", "action.length"],
    ["an out-of-range index (EC-5)", "commits[99].id"],
    ["an index on an object", "comment[0]"],
    ["a key on an array", "commits.id"],
  ])("returns undefined for %s", (_label, path) => {
    expect(selectField(payload, path)).toBeUndefined();
  });

  it.each([
    ["empty", ""],
    ["a leading dot", ".action"],
    ["a trailing dot", "action."],
    ["a double dot", "comment..body"],
    ["a negative index (EC-5)", "commits[-1]"],
    ["a non-numeric index (EC-5)", "commits[x]"],
    ["an unclosed bracket", "commits[0"],
    ["a space", "comment body"],
    ["a wildcard", "commits[*].id"],
  ])("rejects %s as an invalid path (undefined)", (_label, path) => {
    expect(selectField(payload, path)).toBeUndefined();
  });

  it.each([
    "__proto__",
    "constructor",
    "prototype",
    "comment.__proto__",
    "comment.constructor.name",
  ])("never traverses %s", (path) => {
    expect(selectField(payload, path)).toBeUndefined();
  });

  it("reads only own properties, never inherited ones", () => {
    const child = Object.create({ inherited: "x" }) as Record<string, unknown>;
    expect(selectField({ child }, "child.inherited")).toBeUndefined();
    expect(selectField({ a: {} }, "a.toString")).toBeUndefined();
  });

  // JSON.parse (the receive core's parser) turns "__proto__" into an OWN key, so
  // the own-property check alone doesn't stop it; the forbidden-key list does.
  it.each(["__proto__", "__proto__.polluted", "constructor", "a.prototype"])(
    "refuses %s even when JSON.parse made it an own key",
    (path) => {
      const parsed: unknown = JSON.parse(
        '{"__proto__":{"polluted":"yes"},"constructor":"c","a":{"prototype":"p"}}',
      );
      expect(selectField(parsed, path)).toBeUndefined();
    },
  );

  it("resolves exactly MAX_PATH_DEPTH segments and rejects one more (EC-30)", () => {
    let deep: Record<string, unknown> = { v: "end" };
    for (let i = 0; i < MAX_PATH_DEPTH - 1; i++) deep = { n: deep };
    const ok = Array(MAX_PATH_DEPTH - 1)
      .fill("n")
      .concat("v")
      .join(".");
    expect(selectField(deep, ok)).toBe("end");
    expect(selectField({ n: deep }, "n." + ok)).toBeUndefined();
  });
});

describe("evaluateCondition", () => {
  const cases: [string, WebhookCondition, boolean][] = [
    ["equals hit", { field: "comment.body", op: "equals", value: "security review" }, true],
    ["equals miss", { field: "comment.body", op: "equals", value: "Security review" }, false],
    ["not_equals hit", { field: "action", op: "not_equals", value: "deleted" }, true],
    ["not_equals on missing field", { field: "missing", op: "not_equals", value: "x" }, false],
    ["contains hit", { field: "comment.body", op: "contains", value: "review" }, true],
    ["contains miss", { field: "comment.body", op: "contains", value: "deploy" }, false],
    ["prefix hit", { field: "repository.full_name", op: "prefix", value: "llipe/" }, true],
    ["prefix miss", { field: "repository.full_name", op: "prefix", value: "other/" }, false],
    ["suffix hit", { field: "repository.full_name", op: "suffix", value: "/repo-a" }, true],
    ["in hit", { field: "action", op: "in", value: ["created", "edited"] }, true],
    ["in miss", { field: "action", op: "in", value: ["deleted"] }, false],
    ["exists hit", { field: "comment.user.login", op: "exists" }, true],
    ["exists on null", { field: "nothing", op: "exists" }, false],
    ["exists miss", { field: "comment.missing", op: "exists" }, false],
    // EC-6: no coercion of non-string values.
    ["prefix on a number", { field: "count", op: "prefix", value: "3" }, false],
    ["equals on a boolean", { field: "draft", op: "equals", value: "false" }, false],
    ["contains on an array", { field: "repository.topics", op: "contains", value: "web" }, false],
  ];
  it.each(cases)("%s", (_label, cond, expected) => {
    expect(evaluateCondition(payload, "issue_comment", cond)).toBe(expected);
  });

  it("matches_event compares against the event header, not the payload", () => {
    expect(
      evaluateCondition(payload, "issue_comment", {
        field: "",
        op: "matches_event",
        value: "issue_comment",
      }),
    ).toBe(true);
    expect(
      evaluateCondition(payload, "push", {
        field: "",
        op: "matches_event",
        value: "issue_comment",
      }),
    ).toBe(false);
  });

  it("is false for a payload string longer than MAX_STRING_LENGTH", () => {
    const big = { s: "a".repeat(MAX_STRING_LENGTH + 1) };
    expect(evaluateCondition(big, "e", { field: "s", op: "prefix", value: "a" })).toBe(false);
  });

  it("is false (never throws) for an unknown op or a wrong-typed value", () => {
    const bad = [
      { field: "action", op: "regex", value: ".*" },
      { field: "action", op: "in", value: "created" },
      { field: "action", op: "equals", value: ["created"] },
      { field: "action", op: "equals" },
    ] as unknown as WebhookCondition[];
    for (const c of bad) expect(evaluateCondition(payload, "e", c)).toBe(false);
  });
});

describe("validateConditions (stored shape, CT-4)", () => {
  it("accepts a well-formed list", () => {
    expect(
      validateConditions([
        { field: "comment.body", op: "equals", value: "x" },
        { field: "action", op: "in", value: ["a", "b"] },
        { field: "comment.user.login", op: "exists" },
      ]),
    ).toEqual({ valid: true, errors: [] });
  });

  it.each([
    ["not an array", { field: "a", op: "equals", value: "x" }],
    ["missing field", [{ op: "equals", value: "x" }]],
    ["missing op", [{ field: "a", value: "x" }]],
    ["unknown op", [{ field: "a", op: "regex", value: "x" }]],
    ["an unknown key (B-2)", [{ field: "a", op: "equals", value: "x", extra: 1 }]],
    ["prefix with a non-string value", [{ field: "a", op: "prefix", value: 3 }]],
    ["in without an array", [{ field: "a", op: "in", value: "x" }]],
    ["equals without a value", [{ field: "a", op: "equals" }]],
    ["an invalid path", [{ field: "a..b", op: "equals", value: "x" }]],
    ["a __proto__ path", [{ field: "__proto__.x", op: "exists" }]],
    [
      "a value over the length cap (EC-31)",
      [{ field: "a", op: "equals", value: "x".repeat(MAX_STRING_LENGTH + 1) }],
    ],
    ["too many conditions", Array(51).fill({ field: "a", op: "exists" })],
  ])("rejects %s", (_label, input) => {
    expect(validateConditions(input).valid).toBe(false);
  });

  it("accepts a value of exactly MAX_STRING_LENGTH (EC-31)", () => {
    expect(
      validateConditions([{ field: "a", op: "equals", value: "x".repeat(MAX_STRING_LENGTH) }])
        .valid,
    ).toBe(true);
  });
});

describe("routeDelivery", () => {
  const endpoint = { ignore_bot_author: true, bot_login: BOT };

  it("returns the first enabled matching rule by position (AC4)", () => {
    const rules = [
      rule({ id: "r2", position: 2 }),
      rule({
        id: "r1",
        position: 1,
        conditions: [{ field: "comment.body", op: "equals", value: "security review" }],
      }),
      rule({
        id: "r0",
        position: 0,
        conditions: [{ field: "comment.body", op: "equals", value: "deploy" }],
      }),
    ];
    expect(routeDelivery(payload, "issue_comment", endpoint, rules)).toEqual({
      kind: "match",
      ruleId: "r1",
    });
  });

  it("skips a disabled rule that would match (EC-9)", () => {
    const rules = [
      rule({ id: "off", position: 0, is_enabled: false }),
      rule({ id: "on", position: 1 }),
    ];
    expect(routeDelivery(payload, "issue_comment", endpoint, rules)).toEqual({
      kind: "match",
      ruleId: "on",
    });
  });

  it("scopes rules by event type", () => {
    const rules = [
      rule({ id: "push", position: 0, event_types: ["push"] }),
      rule({ id: "ic", position: 1 }),
    ];
    expect(routeDelivery(payload, "issue_comment", endpoint, rules)).toEqual({
      kind: "match",
      ruleId: "ic",
    });
  });

  it("ANDs a rule's conditions", () => {
    const rules = [
      rule({
        id: "both",
        position: 0,
        conditions: [
          { field: "comment.body", op: "contains", value: "security" },
          { field: "repository.full_name", op: "prefix", value: "other/" },
        ],
      }),
    ];
    expect(routeDelivery(payload, "issue_comment", endpoint, rules)).toEqual({ kind: "no_match" });
  });

  it("falls through to the default rule, whatever its position (FR15)", () => {
    const rules = [
      rule({ id: "def", position: 0, is_default: true, event_types: [] }),
      rule({
        id: "miss",
        position: 1,
        conditions: [{ field: "action", op: "equals", value: "deleted" }],
      }),
    ];
    expect(routeDelivery(payload, "issue_comment", endpoint, rules)).toEqual({
      kind: "default",
      ruleId: "def",
    });
  });

  it("prefers a matching non-default rule over the default", () => {
    const rules = [
      rule({ id: "def", position: 0, is_default: true }),
      rule({ id: "hit", position: 1 }),
    ];
    expect(routeDelivery(payload, "issue_comment", endpoint, rules)).toEqual({
      kind: "match",
      ruleId: "hit",
    });
  });

  it("ignores a disabled default rule", () => {
    const rules = [rule({ id: "def", position: 0, is_default: true, is_enabled: false })];
    expect(routeDelivery(payload, "push", endpoint, rules)).toEqual({ kind: "no_match" });
  });

  it("returns no_match with no rules", () => {
    expect(routeDelivery(payload, "issue_comment", endpoint, [])).toEqual({ kind: "no_match" });
  });

  describe("bot-author guard (AC7, D-W12)", () => {
    const botPayload = { ...payload, sender: { login: BOT, type: "Bot" } };
    const rules = [rule({ id: "r", position: 0 })];

    it("excludes an event sent by the fleet's own bot", () => {
      expect(routeDelivery(botPayload, "issue_comment", endpoint, rules)).toEqual({
        kind: "bot_author",
      });
    });

    it("excludes it even when a default rule exists", () => {
      const withDefault = [...rules, rule({ id: "def", position: 1, is_default: true })];
      expect(routeDelivery(botPayload, "issue_comment", endpoint, withDefault)).toEqual({
        kind: "bot_author",
      });
    });

    it("does not exclude a human whose login is the bot login (type User, EC-28)", () => {
      const human = { ...payload, sender: { login: BOT, type: "User" } };
      expect(routeDelivery(human, "issue_comment", endpoint, rules).kind).toBe("match");
    });

    it("does not exclude a different app's bot", () => {
      const other = { ...payload, sender: { login: "renovate[bot]", type: "Bot" } };
      expect(routeDelivery(other, "issue_comment", endpoint, rules).kind).toBe("match");
    });

    it("lets the bot through when the endpoint toggle is off", () => {
      const off = { ignore_bot_author: false, bot_login: BOT };
      expect(routeDelivery(botPayload, "issue_comment", off, rules).kind).toBe("match");
    });

    it("lets an explicit condition exclude the bot with the toggle off", () => {
      const off = { ignore_bot_author: false, bot_login: BOT };
      const guarded = [
        rule({
          id: "r",
          position: 0,
          conditions: [{ field: "sender.login", op: "not_equals", value: BOT }],
        }),
      ];
      expect(routeDelivery(botPayload, "issue_comment", off, guarded)).toEqual({
        kind: "no_match",
      });
    });

    it("guards nothing when no bot login is configured", () => {
      const unset = { ignore_bot_author: true, bot_login: null };
      expect(routeDelivery(botPayload, "issue_comment", unset, rules).kind).toBe("match");
    });
  });

  it("returns within a time bound on resource-exhaustion payloads (EC-33/EC-34)", () => {
    let deep: unknown = { v: 1 };
    for (let i = 0; i < 10_000; i++) deep = { n: deep };
    const hostile = {
      deep,
      wide: Array.from({ length: 100_000 }, (_, i) => i),
      big: "a".repeat(4 * 1024 * 1024),
      sender: { login: "x", type: "User" },
    };
    const rules = Array.from({ length: 100 }, (_, i) =>
      rule({
        id: `r${i}`,
        position: i,
        event_types: ["e"],
        conditions: [
          { field: "big", op: "contains", value: "zzz" },
          { field: "wide[99999]", op: "exists" },
          { field: Array(10).fill("n").join("."), op: "exists" },
        ],
      }),
    );
    const start = performance.now();
    expect(routeDelivery(hostile, "e", endpoint, rules)).toEqual({ kind: "no_match" });
    expect(performance.now() - start).toBeLessThan(50);
  });
});

// ---------------------------------------------------------------------------
// Randomized tactics (test plan §6).
// ---------------------------------------------------------------------------

const KEYS = [
  "a",
  "b",
  "c",
  "comment",
  "body",
  "__proto__",
  "constructor",
  "prototype",
  "0",
  "login",
];

function randomTree(rand: () => number, depth: number): unknown {
  const r = rand();
  if (depth <= 0 || r < 0.25) {
    const leaf = Math.floor(rand() * 5);
    return [null, true, 42, "s" + Math.floor(rand() * 9), "security review"][leaf];
  }
  if (r < 0.5)
    return Array.from({ length: Math.floor(rand() * 4) }, () => randomTree(rand, depth - 1));
  const obj: Record<string, unknown> = {};
  for (let i = 0; i < Math.floor(rand() * 4); i++) {
    // defineProperty so "__proto__" becomes an own key, the way JSON.parse makes it.
    Object.defineProperty(obj, KEYS[Math.floor(rand() * KEYS.length)]!, {
      value: randomTree(rand, depth - 1),
      enumerable: true,
      configurable: true,
      writable: true,
    });
  }
  return obj;
}

function randomPath(rand: () => number): string {
  const parts: string[] = [];
  for (let i = 0; i < 1 + Math.floor(rand() * 6); i++) {
    parts.push(
      rand() < 0.2
        ? `[${Math.floor(rand() * 3)}]`
        : (i ? "." : "") + KEYS[Math.floor(rand() * KEYS.length)],
    );
  }
  return parts.join("");
}

const OPS = ["equals", "not_equals", "contains", "prefix", "suffix", "in", "exists"] as const;

function randomCondition(rand: () => number): WebhookCondition {
  const op = OPS[Math.floor(rand() * OPS.length)]!;
  const field = randomPath(rand);
  if (op === "exists") return { field, op };
  if (op === "in") return { field, op, value: ["s1", "security review"] };
  return { field, op, value: rand() < 0.5 ? "s1" : "security" };
}

describe("RT-2: hostile random trees never throw or pollute (seed 315001)", () => {
  it("routeDelivery always returns a valid result and Object.prototype is untouched", () => {
    const seed = testSeed(315001);
    const rand = mulberry32(seed);
    const protoKeys = Object.getOwnPropertyNames(Object.prototype).sort();
    for (let i = 0; i < 5000; i++) {
      const tree = randomTree(rand, Math.floor(rand() * 40));
      const rules = [
        rule({ id: "r", position: 0, event_types: ["e"], conditions: [randomCondition(rand)] }),
      ];
      let result: ReturnType<typeof routeDelivery> | undefined;
      expect(() => {
        result = routeDelivery(tree, "e", { ignore_bot_author: true, bot_login: BOT }, rules);
      }, `iter ${i} seed ${seed}`).not.toThrow();
      expect(["match", "default", "no_match", "bot_author"], `iter ${i} seed ${seed}`).toContain(
        result!.kind,
      );
      expect(() => selectField(tree, randomPath(rand))).not.toThrow();
    }
    expect(Object.getOwnPropertyNames(Object.prototype).sort()).toEqual(protoKeys);
    expect(({} as Record<string, unknown>).polluted).toBeUndefined();
  });
});

describe("RT-3: first-match equals a brute-force reference (seed 315002)", () => {
  it("returns the enabled matching rule with the lowest position", () => {
    const seed = testSeed(315002);
    const rand = mulberry32(seed);
    for (let i = 0; i < 3000; i++) {
      const tree = randomTree(rand, 4);
      const count = 1 + Math.floor(rand() * 20);
      const positions = Array.from({ length: count }, (_, k) => k).sort(() => rand() - 0.5);
      const rules = positions.map((p, k) =>
        rule({
          id: `r${k}`,
          position: p,
          event_types: rand() < 0.8 ? ["e"] : ["other"],
          is_enabled: rand() < 0.85,
          conditions: rand() < 0.3 ? [] : [randomCondition(rand)],
        }),
      );
      const reference = [...rules]
        .sort((a, b) => a.position - b.position)
        .find(
          (r) =>
            r.is_enabled &&
            !r.is_default &&
            r.event_types.includes("e") &&
            r.conditions.every((c) => evaluateCondition(tree, "e", c)),
        );
      const got = routeDelivery(tree, "e", { ignore_bot_author: false, bot_login: null }, rules);
      expect(got, `iter ${i} seed ${seed}`).toEqual(
        reference ? { kind: "match", ruleId: reference.id } : { kind: "no_match" },
      );
    }
  });
});
