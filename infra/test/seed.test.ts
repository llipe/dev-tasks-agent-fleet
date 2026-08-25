import { describe, it, expect } from "vitest";
import { normalizeSubjectId } from "@fleet/shared";
import { parseSeedInput, buildSeedItems } from "../seed/seed-logic.js";

describe("seed input parsing", () => {
  it("parses a valid repos.json structure", () => {
    const input = { repositories: ["owner/repo", "org/project"] };
    const result = parseSeedInput(input);
    expect(result).toEqual(["owner/repo", "org/project"]);
  });

  it("normalizes repository names via normalizeSubjectId", () => {
    const input = {
      repositories: [
        "https://github.com/Owner/Repo.git",
        "git@github.com:Org/Project.git",
        "Simple/Name",
      ],
    };
    const result = parseSeedInput(input);
    expect(result).toEqual(["owner/repo", "org/project", "simple/name"]);
  });

  it("deduplicates repositories after normalization", () => {
    const input = {
      repositories: ["owner/repo", "https://github.com/Owner/Repo.git", "Owner/Repo"],
    };
    const result = parseSeedInput(input);
    expect(result).toEqual(["owner/repo"]);
  });

  it("rejects empty repository list", () => {
    const input = { repositories: [] };
    expect(() => parseSeedInput(input)).toThrow("empty");
  });

  it("rejects missing repositories field", () => {
    const input = {};
    expect(() => parseSeedInput(input)).toThrow();
  });

  it("trims whitespace from repo names", () => {
    const input = { repositories: ["  owner/repo  "] };
    const result = parseSeedInput(input);
    expect(result).toEqual(["owner/repo"]);
  });
});

describe("buildSeedItems", () => {
  it("generates META and AGENT items for each repo", () => {
    const repos = ["owner/repo"];
    const items = buildSeedItems(repos, "dep-updater");
    expect(items).toHaveLength(2);
    expect(items[0]).toMatchObject({
      pk: "SUBJECT#owner/repo",
      sk: "META",
      subject_id: "owner/repo",
    });
    expect(items[1]).toMatchObject({
      pk: "SUBJECT#owner/repo",
      sk: "AGENT#dep-updater",
      enabled: true,
    });
  });

  it("generates items for multiple repos", () => {
    const repos = ["owner/repo-a", "owner/repo-b"];
    const items = buildSeedItems(repos, "dep-updater");
    // 2 items per repo
    expect(items).toHaveLength(4);
  });

  it("uses normalizeSubjectId for pk construction", () => {
    // repos should already be normalized by parseSeedInput, but verify key format
    const repos = ["owner/repo"];
    const items = buildSeedItems(repos, "dep-updater");
    const metaItem = items[0];
    expect(metaItem).toBeDefined();
    expect(metaItem?.pk).toBe(`SUBJECT#${normalizeSubjectId("owner/repo")}`);
  });

  it("includes created_at as ISO 8601 UTC string on META items", () => {
    const repos = ["owner/repo"];
    const items = buildSeedItems(repos, "dep-updater");
    const metaItem = items[0];
    expect(metaItem).toBeDefined();
    expect(metaItem).toHaveProperty("created_at");
    // Verify ISO format
    const createdAt = metaItem?.created_at as string;
    expect(new Date(createdAt).toISOString()).toBe(createdAt);
  });

  it("sets default params as empty object on agent items", () => {
    const repos = ["owner/repo"];
    const items = buildSeedItems(repos, "dep-updater");
    const agentItem = items[1];
    expect(agentItem).toBeDefined();
    expect(agentItem?.params).toEqual({});
  });
});
