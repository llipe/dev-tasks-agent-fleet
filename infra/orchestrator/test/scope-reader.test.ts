import { describe, it, expect, vi } from "vitest";
import type { DynamoDBDocumentClient } from "@aws-sdk/lib-dynamodb";
import { queryEnabledSubjects, getAgentConfig } from "../src/scope-reader.js";

// Mock DynamoDB Document Client
function mockDocClient(
  responses: {
    Items?: Record<string, unknown>[];
    Item?: Record<string, unknown>;
    LastEvaluatedKey?: Record<string, unknown>;
  }[],
) {
  let callIndex = 0;
  return {
    send: vi.fn(async () => {
      const response = responses[callIndex] ?? { Items: [] };
      callIndex++;
      return response;
    }),
  } as unknown as DynamoDBDocumentClient;
}

describe("queryEnabledSubjects", () => {
  it("returns enabled subjects from GSI1 query", async () => {
    const client = mockDocClient([
      {
        Items: [
          {
            pk: "SUBJECT#myorg/repo-a",
            sk: "AGENT#dep-updater",
            enabled: true,
            params: { allow_fixes: true },
          },
          { pk: "SUBJECT#myorg/repo-b", sk: "AGENT#dep-updater", enabled: true, params: {} },
        ],
      },
    ]);

    const result = await queryEnabledSubjects(client, "dep-updater");
    expect(result).toEqual([
      { subjectId: "myorg/repo-a", enabled: true, params: { allow_fixes: true } },
      { subjectId: "myorg/repo-b", enabled: true, params: {} },
    ]);
  });

  it("returns empty array when no items found", async () => {
    const client = mockDocClient([{ Items: [] }]);
    const result = await queryEnabledSubjects(client, "dep-updater");
    expect(result).toEqual([]);
  });

  it("skips items without SUBJECT# prefix in pk", async () => {
    const client = mockDocClient([
      {
        Items: [
          { pk: "SUBJECT#valid/repo", sk: "AGENT#dep-updater", enabled: true, params: {} },
          { pk: "CONFIG", sk: "AGENT#dep-updater", enabled: true, params: {} },
        ],
      },
    ]);

    const result = await queryEnabledSubjects(client, "dep-updater");
    expect(result).toHaveLength(1);
    const entry = result[0];
    expect(entry).toBeDefined();
    expect(entry?.subjectId).toBe("valid/repo");
  });

  it("handles pagination (LastEvaluatedKey)", async () => {
    const client = mockDocClient([
      {
        Items: [{ pk: "SUBJECT#org/repo1", sk: "AGENT#dep-updater", enabled: true, params: {} }],
        LastEvaluatedKey: { pk: "SUBJECT#org/repo1", sk: "AGENT#dep-updater" },
      },
      {
        Items: [{ pk: "SUBJECT#org/repo2", sk: "AGENT#dep-updater", enabled: true, params: {} }],
      },
    ]);

    const result = await queryEnabledSubjects(client, "dep-updater");
    expect(result).toHaveLength(2);
    expect(result.map((e) => e.subjectId)).toEqual(["org/repo1", "org/repo2"]);
  });

  it("defaults params to empty object when missing", async () => {
    const client = mockDocClient([
      {
        Items: [{ pk: "SUBJECT#org/repo", sk: "AGENT#dep-updater", enabled: true }],
      },
    ]);

    const result = await queryEnabledSubjects(client, "dep-updater");
    const entry = result[0];
    expect(entry).toBeDefined();
    expect(entry?.params).toEqual({});
  });
});

describe("getAgentConfig", () => {
  it("returns config when item exists", async () => {
    const client = mockDocClient([
      {
        Item: {
          pk: "CONFIG",
          sk: "AGENT#dep-updater",
          agent_name: "dep-updater",
          default_params: { allow_fixes: true },
        },
      },
    ]);

    const result = await getAgentConfig(client, "dep-updater");
    expect(result).toEqual({
      agentName: "dep-updater",
      defaultParams: { allow_fixes: true },
    });
  });

  it("returns null when no config item exists", async () => {
    const client = mockDocClient([{ Item: undefined }]);
    const result = await getAgentConfig(client, "dep-updater");
    expect(result).toBeNull();
  });

  it("defaults defaultParams to empty object when missing", async () => {
    const client = mockDocClient([
      { Item: { pk: "CONFIG", sk: "AGENT#dep-updater", agent_name: "dep-updater" } },
    ]);

    const result = await getAgentConfig(client, "dep-updater");
    expect(result).toBeDefined();
    expect(result?.defaultParams).toEqual({});
  });
});
