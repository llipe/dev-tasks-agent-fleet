import { describe, it, expect } from "vitest";
import { subjectPk, agentSk, META, CONFIG, PREFIXES } from "./keys.js";

describe("key builders", () => {
  describe("subjectPk", () => {
    it("prefixes repo with SUBJECT#", () => {
      expect(subjectPk("myorg/repo")).toBe("SUBJECT#myorg/repo");
    });

    it("handles repo with special characters", () => {
      expect(subjectPk("my-org/my-repo")).toBe("SUBJECT#my-org/my-repo");
    });
  });

  describe("agentSk", () => {
    it("prefixes agent name with AGENT#", () => {
      expect(agentSk("dep-updater")).toBe("AGENT#dep-updater");
    });

    it("handles short agent names", () => {
      expect(agentSk("ci")).toBe("AGENT#ci");
    });
  });

  describe("META constant", () => {
    it("equals 'META'", () => {
      expect(META).toBe("META");
    });
  });

  describe("CONFIG constant", () => {
    it("equals 'CONFIG'", () => {
      expect(CONFIG).toBe("CONFIG");
    });
  });

  describe("PREFIXES", () => {
    it("defines SUBJECT prefix", () => {
      expect(PREFIXES.SUBJECT).toBe("SUBJECT#");
    });

    it("defines AGENT prefix", () => {
      expect(PREFIXES.AGENT).toBe("AGENT#");
    });
  });

  describe("round-trip extraction", () => {
    it("can extract repo from subjectPk", () => {
      const repo = "myorg/repo";
      const pk = subjectPk(repo);
      const extracted = pk.replace(PREFIXES.SUBJECT, "");
      expect(extracted).toBe(repo);
    });

    it("can extract agent name from agentSk", () => {
      const name = "dep-updater";
      const sk = agentSk(name);
      const extracted = sk.replace(PREFIXES.AGENT, "");
      expect(extracted).toBe(name);
    });
  });
});
