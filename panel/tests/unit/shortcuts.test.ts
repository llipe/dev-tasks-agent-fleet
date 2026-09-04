import { describe, expect, it } from "vitest";

import { isSidebarToggleShortcut, isTypingTarget } from "@/lib/ui/shortcuts";

// Minimal stand-in for the fields isSidebarToggleShortcut reads off a
// KeyboardEvent, so these stay pure Layer-1 unit tests (no jsdom, no DOM).
function key(
  overrides: Partial<{
    key: string;
    metaKey: boolean;
    ctrlKey: boolean;
    altKey: boolean;
    shiftKey: boolean;
  }>,
): KeyboardEvent {
  return {
    key: "\\",
    metaKey: false,
    ctrlKey: false,
    altKey: false,
    shiftKey: false,
    ...overrides,
  } as KeyboardEvent;
}

describe("isSidebarToggleShortcut — /DESIGN.md §6.5 (Cmd+\\ / Ctrl+\\)", () => {
  it("matches Cmd+\\ on macOS", () => {
    expect(isSidebarToggleShortcut(key({ metaKey: true }), "mac")).toBe(true);
  });

  it("matches Ctrl+\\ off macOS", () => {
    expect(isSidebarToggleShortcut(key({ ctrlKey: true }), "other")).toBe(true);
  });

  it("does NOT match Ctrl+\\ on macOS (must be the platform's own modifier)", () => {
    expect(isSidebarToggleShortcut(key({ ctrlKey: true }), "mac")).toBe(false);
  });

  it("does NOT match Cmd+\\ off macOS", () => {
    expect(isSidebarToggleShortcut(key({ metaKey: true }), "other")).toBe(false);
  });

  it("does not match the backslash key with no modifier", () => {
    expect(isSidebarToggleShortcut(key({}), "mac")).toBe(false);
    expect(isSidebarToggleShortcut(key({}), "other")).toBe(false);
  });

  it("does not match the modifier with a different key", () => {
    expect(isSidebarToggleShortcut(key({ key: "k", metaKey: true }), "mac")).toBe(false);
  });

  it("does not match when an extra modifier is held (Cmd+Shift+\\)", () => {
    expect(isSidebarToggleShortcut(key({ metaKey: true, shiftKey: true }), "mac")).toBe(false);
    expect(isSidebarToggleShortcut(key({ ctrlKey: true, altKey: true }), "other")).toBe(false);
  });
});

describe("isTypingTarget — a shortcut must not fire while the user is typing", () => {
  function el(tag: string, attrs: Record<string, string> = {}): EventTarget {
    const node = { tagName: tag.toUpperCase() } as Record<string, unknown>;
    if ("isContentEditable" in attrs) {
      node.isContentEditable = attrs.isContentEditable === "true";
    }
    return node as unknown as EventTarget;
  }

  it("is true for INPUT, TEXTAREA, SELECT", () => {
    expect(isTypingTarget(el("input"))).toBe(true);
    expect(isTypingTarget(el("textarea"))).toBe(true);
    expect(isTypingTarget(el("select"))).toBe(true);
  });

  it("is true for a contenteditable element", () => {
    expect(isTypingTarget(el("div", { isContentEditable: "true" }))).toBe(true);
  });

  it("is false for a plain div or button", () => {
    expect(isTypingTarget(el("div"))).toBe(false);
    expect(isTypingTarget(el("button"))).toBe(false);
  });

  it("is false for a null target", () => {
    expect(isTypingTarget(null)).toBe(false);
  });
});
