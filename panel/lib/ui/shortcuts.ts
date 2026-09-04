/**
 * Keyboard-shortcut matchers for the app shell.
 *
 * Pure predicates over the fields of a KeyboardEvent — no DOM, no React — so
 * they are Layer-1 unit-testable in isolation. The shell's client component
 * wires them to a `keydown` listener.
 */

export type Platform = "mac" | "other";

/**
 * Detects the current platform. `navigator.platform` is deprecated but still
 * the most reliable synchronous signal for "is this an Apple keyboard where
 * the command key is the primary modifier". Falls back to `other` on the
 * server or when navigator is unavailable.
 */
export function detectPlatform(): Platform {
  if (typeof navigator === "undefined") return "other";
  const p = `${navigator.platform ?? ""} ${navigator.userAgent ?? ""}`;
  return /Mac|iPhone|iPad|iPod/i.test(p) ? "mac" : "other";
}

/**
 * `/DESIGN.md` §6.5 — toggle the sidebar with `Cmd+\` on macOS and `Ctrl+\`
 * elsewhere. The match requires the platform's *primary* modifier and no other
 * modifier, so `Cmd+Shift+\` and `Ctrl+Alt+\` do not toggle.
 */
export function isSidebarToggleShortcut(event: KeyboardEvent, platform: Platform): boolean {
  if (event.key !== "\\") return false;
  if (event.altKey || event.shiftKey) return false;
  if (platform === "mac") {
    return event.metaKey && !event.ctrlKey;
  }
  return event.ctrlKey && !event.metaKey;
}

/**
 * Whether the event target is a text-entry context, so a single-key or
 * modifier shortcut must not steal the keystroke. Covers form controls and any
 * `contenteditable` host.
 */
export function isTypingTarget(target: EventTarget | null): boolean {
  if (target === null) return false;
  const node = target as { tagName?: string; isContentEditable?: boolean };
  if (node.isContentEditable === true) return true;
  const tag = (node.tagName ?? "").toUpperCase();
  return tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT";
}
