import { afterEach, describe, expect, it, vi } from "vitest";

import {
  SIDEBAR_STORAGE_KEY,
  readSidebarCollapsed,
  writeSidebarCollapsed,
} from "@/lib/ui/sidebar-state";

// A controllable Storage double. Each test builds one and passes it in, so the
// helper never touches a real `window.localStorage` and stays a Layer-1 unit.
function makeStorage(initial: Record<string, string> = {}): Storage {
  const map = new Map<string, string>(Object.entries(initial));
  return {
    get length() {
      return map.size;
    },
    clear: () => map.clear(),
    key: (i: number) => Array.from(map.keys())[i] ?? null,
    getItem: (k: string) => (map.has(k) ? (map.get(k) as string) : null),
    setItem: (k: string, v: string) => void map.set(k, String(v)),
    removeItem: (k: string) => void map.delete(k),
  } as Storage;
}

function throwingStorage(): Storage {
  return {
    get length(): number {
      throw new DOMException("denied", "SecurityError");
    },
    clear: () => {},
    key: () => null,
    getItem: () => {
      throw new DOMException("denied", "SecurityError");
    },
    setItem: () => {
      throw new DOMException("denied", "SecurityError");
    },
    removeItem: () => {},
  } as Storage;
}

afterEach(() => {
  vi.restoreAllMocks();
});

describe("readSidebarCollapsed", () => {
  it("returns the stored collapsed=true value", () => {
    const s = makeStorage({ [SIDEBAR_STORAGE_KEY]: "collapsed" });
    expect(readSidebarCollapsed(s)).toBe(true);
  });

  it("returns the stored expanded=false value", () => {
    const s = makeStorage({ [SIDEBAR_STORAGE_KEY]: "expanded" });
    expect(readSidebarCollapsed(s)).toBe(false);
  });

  it("defaults to expanded (false) when the key is absent", () => {
    expect(readSidebarCollapsed(makeStorage())).toBe(false);
  });

  it("defaults to expanded on a corrupt / unrecognized value", () => {
    expect(readSidebarCollapsed(makeStorage({ [SIDEBAR_STORAGE_KEY]: "kanban" }))).toBe(false);
    expect(readSidebarCollapsed(makeStorage({ [SIDEBAR_STORAGE_KEY]: "true" }))).toBe(false);
    expect(readSidebarCollapsed(makeStorage({ [SIDEBAR_STORAGE_KEY]: "{" }))).toBe(false);
    expect(readSidebarCollapsed(makeStorage({ [SIDEBAR_STORAGE_KEY]: "" }))).toBe(false);
  });

  it("defaults to expanded when storage throws (private mode), never propagating", () => {
    expect(() => readSidebarCollapsed(throwingStorage())).not.toThrow();
    expect(readSidebarCollapsed(throwingStorage())).toBe(false);
  });

  it("defaults to expanded when no storage is available at all", () => {
    expect(readSidebarCollapsed(null)).toBe(false);
    expect(readSidebarCollapsed(undefined)).toBe(false);
  });
});

describe("writeSidebarCollapsed", () => {
  it("persists the canonical string for each state and round-trips", () => {
    const s = makeStorage();
    writeSidebarCollapsed(s, true);
    expect(s.getItem(SIDEBAR_STORAGE_KEY)).toBe("collapsed");
    expect(readSidebarCollapsed(s)).toBe(true);

    writeSidebarCollapsed(s, false);
    expect(s.getItem(SIDEBAR_STORAGE_KEY)).toBe("expanded");
    expect(readSidebarCollapsed(s)).toBe(false);
  });

  it("swallows a throwing setItem (quota / private mode) without propagating", () => {
    expect(() => writeSidebarCollapsed(throwingStorage(), true)).not.toThrow();
  });

  it("is a no-op when no storage is available", () => {
    expect(() => writeSidebarCollapsed(null, true)).not.toThrow();
  });
});
