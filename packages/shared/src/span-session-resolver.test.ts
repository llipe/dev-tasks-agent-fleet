import { describe, it, expect } from "vitest";
import { resolveSessionId, resolveFieldPath } from "./span-session-resolver.js";

describe("resolveFieldPath", () => {
  it("resolves nested dot paths", () => {
    const obj = { resource: { attributes: { "session.id": "abc" } } };
    expect(resolveFieldPath(obj, "resource.attributes.session.id")).toBe("abc");
  });

  it("returns undefined for missing intermediate path", () => {
    const obj = { resource: {} };
    expect(resolveFieldPath(obj, "resource.attributes.session.id")).toBeUndefined();
  });

  it("returns undefined for null values in path", () => {
    const obj = { resource: null };
    expect(resolveFieldPath(obj, "resource.attributes.session.id")).toBeUndefined();
  });

  it("resolves top-level fields", () => {
    const obj = { duration: 5000 };
    expect(resolveFieldPath(obj, "duration")).toBe(5000);
  });

  it("resolves numeric values", () => {
    const obj = { attributes: { "gen_ai.usage.input_tokens": 1500 } };
    expect(resolveFieldPath(obj, "attributes.gen_ai.usage.input_tokens")).toBe(1500);
  });

  it("returns undefined on empty object", () => {
    expect(resolveFieldPath({}, "any.path")).toBeUndefined();
  });
});

describe("resolveSessionId", () => {
  it("returns primary session.id when present", () => {
    const span = {
      resource: {
        attributes: {
          "session.id": "primary-id",
          "llipe.session.id": "fallback-id",
        },
      },
    };
    expect(resolveSessionId(span)).toBe("primary-id");
  });

  it("falls back to llipe.session.id when session.id is absent", () => {
    const span = {
      resource: {
        attributes: {
          "llipe.session.id": "fallback-id",
        },
      },
    };
    expect(resolveSessionId(span)).toBe("fallback-id");
  });

  it("falls back to llipe.session.id when session.id is empty string", () => {
    const span = {
      resource: {
        attributes: {
          "session.id": "",
          "llipe.session.id": "fallback-id",
        },
      },
    };
    expect(resolveSessionId(span)).toBe("fallback-id");
  });

  it("returns undefined when neither path resolves", () => {
    const span = {
      resource: {
        attributes: {
          "service.name": "dep-updater",
        },
      },
    };
    expect(resolveSessionId(span)).toBeUndefined();
  });

  it("returns undefined when resource.attributes is missing entirely", () => {
    const span = { resource: {} };
    expect(resolveSessionId(span)).toBeUndefined();
  });

  it("returns undefined on empty span", () => {
    expect(resolveSessionId({})).toBeUndefined();
  });
});
