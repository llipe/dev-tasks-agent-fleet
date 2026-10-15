import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import { useLocalStorageState } from "@/lib/hooks/useLocalStorageState";

/**
 * Direct behavior contract for the useSyncExternalStore-backed localStorage hook
 * introduced in issue 217 to replace the mount-reconcile setState-in-effect
 * pattern (react-hooks/set-state-in-effect). These assert the behavior the
 * former effect provided — initialize to a default, reconcile from storage,
 * persist on change, support the updater form — plus cross-tab sync.
 */

const KEY = "panel.test.pref";

// jsdom here has no backing localStorage ("--localstorage-file not provided"),
// so install an in-memory Storage — mirrors AppShell.test.tsx.
function installMemoryStorage(): void {
  const map = new Map<string, string>();
  const storage: Storage = {
    get length() {
      return map.size;
    },
    clear: () => map.clear(),
    key: (i: number) => Array.from(map.keys())[i] ?? null,
    getItem: (k: string) => (map.has(k) ? (map.get(k) as string) : null),
    setItem: (k: string, v: string) => void map.set(k, String(v)),
    removeItem: (k: string) => void map.delete(k),
  };
  Object.defineProperty(window, "localStorage", {
    value: storage,
    configurable: true,
    writable: true,
  });
}

type Pref = "a" | "b";
const DEFAULT: Pref = "a";

function read(storage: Storage | null | undefined): Pref {
  if (!storage) return DEFAULT;
  const raw = storage.getItem(KEY);
  return raw === "b" ? "b" : "a";
}
function write(storage: Storage | null | undefined, value: Pref): void {
  storage?.setItem(KEY, value);
}

function options() {
  return { default: DEFAULT, read, write, storageKey: KEY } as const;
}

describe("useLocalStorageState (issue 217)", () => {
  beforeEach(() => {
    installMemoryStorage();
    window.localStorage.clear();
  });
  afterEach(() => {
    window.localStorage.clear();
  });

  it("returns the stored value once mounted (reconcile)", () => {
    window.localStorage.setItem(KEY, "b");
    const { result } = renderHook(() => useLocalStorageState<Pref>(options()));
    // In jsdom there is no SSR pass, so the client snapshot (stored "b") is read
    // on the first commit — the post-hydration reconcile the old effect did.
    expect(result.current[0]).toBe("b");
  });

  it("falls back to the default when storage is empty", () => {
    const { result } = renderHook(() => useLocalStorageState<Pref>(options()));
    expect(result.current[0]).toBe(DEFAULT);
  });

  it("persists a direct set and re-renders with the new value", () => {
    const { result } = renderHook(() => useLocalStorageState<Pref>(options()));
    act(() => result.current[1]("b"));
    expect(window.localStorage.getItem(KEY)).toBe("b");
    expect(result.current[0]).toBe("b");
  });

  it("supports the functional updater form against the live value", () => {
    const { result } = renderHook(() => useLocalStorageState<Pref>(options()));
    act(() => result.current[1]((prev) => (prev === "a" ? "b" : "a")));
    expect(result.current[0]).toBe("b");
    act(() => result.current[1]((prev) => (prev === "a" ? "b" : "a")));
    expect(result.current[0]).toBe("a");
  });

  it("re-reads on a cross-tab storage event for the same key", () => {
    const { result } = renderHook(() => useLocalStorageState<Pref>(options()));
    expect(result.current[0]).toBe("a");
    act(() => {
      window.localStorage.setItem(KEY, "b");
      window.dispatchEvent(new StorageEvent("storage", { key: KEY }));
    });
    expect(result.current[0]).toBe("b");
  });

  it("ignores a storage event for an unrelated key", () => {
    const { result } = renderHook(() => useLocalStorageState<Pref>(options()));
    act(() => {
      window.localStorage.setItem(KEY, "b");
      window.dispatchEvent(new StorageEvent("storage", { key: "some.other.key" }));
    });
    // No re-read triggered by the unrelated key: still the first snapshot.
    expect(result.current[0]).toBe("a");
  });
});
