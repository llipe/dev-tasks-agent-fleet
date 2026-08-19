import { describe, it, expect } from "vitest";
import { normalizeSubjectId } from "./normalize-subject-id.js";

describe("normalizeSubjectId", () => {
  describe("bare owner/repo format", () => {
    it("passes through a simple owner/repo", () => {
      expect(normalizeSubjectId("myorg/repo")).toBe("myorg/repo");
    });

    it("passes through with hyphens", () => {
      expect(normalizeSubjectId("my-org/my-repo")).toBe("my-org/my-repo");
    });
  });

  describe("HTTPS clone URL", () => {
    it("extracts owner/repo from HTTPS URL", () => {
      expect(normalizeSubjectId("https://github.com/myorg/repo")).toBe("myorg/repo");
    });

    it("handles .git suffix", () => {
      expect(normalizeSubjectId("https://github.com/myorg/repo.git")).toBe("myorg/repo");
    });

    it("handles trailing slash", () => {
      expect(normalizeSubjectId("https://github.com/myorg/repo/")).toBe("myorg/repo");
    });

    it("handles .git suffix and trailing slash", () => {
      expect(normalizeSubjectId("https://github.com/myorg/repo.git/")).toBe("myorg/repo");
    });
  });

  describe("SSH remote format", () => {
    it("extracts owner/repo from SSH URL", () => {
      expect(normalizeSubjectId("git@github.com:myorg/repo.git")).toBe("myorg/repo");
    });

    it("handles SSH URL without .git suffix", () => {
      expect(normalizeSubjectId("git@github.com:myorg/repo")).toBe("myorg/repo");
    });
  });

  describe("edge cases", () => {
    it("handles lowercase", () => {
      expect(normalizeSubjectId("MyOrg/MyRepo")).toBe("myorg/myrepo");
    });

    it("trims whitespace", () => {
      expect(normalizeSubjectId("  myorg/repo  ")).toBe("myorg/repo");
    });

    it("handles .git suffix on bare repo name", () => {
      expect(normalizeSubjectId("myorg/repo.git")).toBe("myorg/repo");
    });

    it("handles trailing slash on bare repo name", () => {
      expect(normalizeSubjectId("myorg/repo/")).toBe("myorg/repo");
    });
  });
});
