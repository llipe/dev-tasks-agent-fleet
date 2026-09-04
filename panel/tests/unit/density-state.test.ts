import { describe, expect, it, vi } from "vitest";

import {
  DEFAULT_DENSITY,
  DENSITY_STORAGE_KEY,
  isDensity,
  readDensity,
  writeDensity,
  type Density,
} from "@/lib/ui/density-state";

/**
 * Layer 1 tests for the density persistence helper (task 2.9 / CT-4, CT-5,
 * EC-12, EC-24). The provider here is an earlier version of our own code and
 * the user's own browser — untrusted — so every failure mode falls back to the
 * documented default rather than crashing.
 */

function memoryStorage(seed?: Record<string, string>): Storage {
  const map = new Map<string, string>(Object.entries(seed ?? {}));
  return {
    get length() {
      return map.size;
    },
    clear: () => map.clear(),
    key: (i) => Array.from(map.keys())[i] ?? null,
    getItem: (k) => (map.has(k) ? (map.get(k) as string) : null),
    setItem: (k, v) => void map.set(k, String(v)),
    removeItem: (k) => void map.delete(k),
  };
}

describe("isDensity", () => {
  it("accepts exactly the three known variants", () => {
    expect(isDensity("dense")).toBe(true);
    expect(isDensity("cards")).toBe(true);
    expect(isDensity("ledger")).toBe(true);
  });
  it("rejects everything else", () => {
    for (const v of ["kanban", "", "DENSE", "0", 1, null, undefined, {}]) {
      expect(isDensity(v)).toBe(false);
    }
  });
});

describe("readDensity — valid values (CT-4)", () => {
  it.each(["dense", "cards", "ledger"] as Density[])("reads %s back", (value) => {
    const storage = memoryStorage({ [DENSITY_STORAGE_KEY]: value });
    expect(readDensity(storage)).toBe(value);
  });
});

describe("readDensity — fallback to default (CT-4, CT-5, EC-24)", () => {
  it.each([
    ["unknown variant", "kanban"],
    ["malformed", "{"],
    ["empty", ""],
    ["numeric index from an older release", "2"],
    ["uppercase (case-sensitive vocabulary)", "DENSE"],
  ])("falls back to the default on %s", (_label, stored) => {
    const storage = memoryStorage({ [DENSITY_STORAGE_KEY]: stored });
    expect(readDensity(storage)).toBe(DEFAULT_DENSITY);
  });

  it("falls back to the default when the key is absent", () => {
    expect(readDensity(memoryStorage())).toBe(DEFAULT_DENSITY);
  });

  it("falls back to the default when storage is unavailable (SSR)", () => {
    expect(readDensity(null)).toBe(DEFAULT_DENSITY);
    expect(readDensity(undefined)).toBe(DEFAULT_DENSITY);
  });

  it("falls back to the default when getItem throws (EC-12)", () => {
    const storage = memoryStorage();
    vi.spyOn(storage, "getItem").mockImplementation(() => {
      throw new DOMException("denied", "SecurityError");
    });
    expect(readDensity(storage)).toBe(DEFAULT_DENSITY);
  });
});

describe("writeDensity", () => {
  it("persists the canonical literal", () => {
    const storage = memoryStorage();
    writeDensity(storage, "ledger");
    expect(storage.getItem(DENSITY_STORAGE_KEY)).toBe("ledger");
  });

  it("round-trips through read", () => {
    const storage = memoryStorage();
    writeDensity(storage, "cards");
    expect(readDensity(storage)).toBe("cards");
  });

  it("swallows a throwing setItem (EC-12) and is a no-op with no storage", () => {
    const storage = memoryStorage();
    vi.spyOn(storage, "setItem").mockImplementation(() => {
      throw new DOMException("quota", "QuotaExceededError");
    });
    expect(() => writeDensity(storage, "cards")).not.toThrow();
    expect(() => writeDensity(null, "cards")).not.toThrow();
  });
});
