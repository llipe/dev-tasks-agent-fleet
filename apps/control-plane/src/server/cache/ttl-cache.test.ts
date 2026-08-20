import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { TtlCache } from "./ttl-cache.js";

describe("TtlCache", () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  describe("cache hit/miss", () => {
    it("returns cached value on hit", async () => {
      const cache = new TtlCache<string, number>({ ttlMs: 5000 });
      const fetcher = vi.fn().mockResolvedValue(42);

      const first = await cache.get("key", fetcher);
      const second = await cache.get("key", fetcher);

      expect(first).toBe(42);
      expect(second).toBe(42);
      expect(fetcher).toHaveBeenCalledTimes(1);
    });

    it("calls fetcher on cache miss", async () => {
      const cache = new TtlCache<string, string>({ ttlMs: 5000 });
      const fetcher = vi.fn().mockResolvedValue("hello");

      const result = await cache.get("new-key", fetcher);

      expect(result).toBe("hello");
      expect(fetcher).toHaveBeenCalledTimes(1);
    });

    it("different keys result in different fetcher calls", async () => {
      const cache = new TtlCache<string, string>({ ttlMs: 5000 });
      const fetcherA = vi.fn().mockResolvedValue("A");
      const fetcherB = vi.fn().mockResolvedValue("B");

      const a = await cache.get("key-a", fetcherA);
      const b = await cache.get("key-b", fetcherB);

      expect(a).toBe("A");
      expect(b).toBe("B");
      expect(fetcherA).toHaveBeenCalledTimes(1);
      expect(fetcherB).toHaveBeenCalledTimes(1);
    });
  });

  describe("TTL expiry", () => {
    it("re-fetches after TTL expires", async () => {
      const cache = new TtlCache<string, number>({ ttlMs: 5000 });
      let callCount = 0;
      const fetcher = vi.fn().mockImplementation(() => Promise.resolve(++callCount));

      const first = await cache.get("key", fetcher);
      expect(first).toBe(1);

      // Advance time past TTL
      vi.advanceTimersByTime(5001);

      const second = await cache.get("key", fetcher);
      expect(second).toBe(2);
      expect(fetcher).toHaveBeenCalledTimes(2);
    });

    it("does not re-fetch before TTL expires", async () => {
      const cache = new TtlCache<string, number>({ ttlMs: 5000 });
      const fetcher = vi.fn().mockResolvedValue(100);

      await cache.get("key", fetcher);
      vi.advanceTimersByTime(4999);
      const result = await cache.get("key", fetcher);

      expect(result).toBe(100);
      expect(fetcher).toHaveBeenCalledTimes(1);
    });
  });

  describe("single-flight de-duplication", () => {
    it("collapses concurrent calls for the same key into one fetcher call", async () => {
      const cache = new TtlCache<string, number>({ ttlMs: 5000 });
      let resolvePromise: ((value: number) => void) | undefined;
      const fetcherPromise = new Promise<number>((resolve) => {
        resolvePromise = resolve;
      });
      const fetcher = vi.fn().mockReturnValue(fetcherPromise);

      // Fire multiple concurrent requests
      const promise1 = cache.get("key", fetcher);
      const promise2 = cache.get("key", fetcher);
      const promise3 = cache.get("key", fetcher);

      // Only one fetcher call should have been made
      expect(fetcher).toHaveBeenCalledTimes(1);

      // Resolve the single flight
      resolvePromise?.(99);

      const [r1, r2, r3] = await Promise.all([promise1, promise2, promise3]);
      expect(r1).toBe(99);
      expect(r2).toBe(99);
      expect(r3).toBe(99);
    });

    it("does not share flights between different keys", async () => {
      const cache = new TtlCache<string, string>({ ttlMs: 5000 });
      const fetcherA = vi.fn().mockResolvedValue("A");
      const fetcherB = vi.fn().mockResolvedValue("B");

      const [a, b] = await Promise.all([
        cache.get("key-a", fetcherA),
        cache.get("key-b", fetcherB),
      ]);

      expect(a).toBe("A");
      expect(b).toBe("B");
      expect(fetcherA).toHaveBeenCalledTimes(1);
      expect(fetcherB).toHaveBeenCalledTimes(1);
    });

    it("propagates errors to all waiters in a single flight", async () => {
      const cache = new TtlCache<string, number>({ ttlMs: 5000 });
      const fetcher = vi.fn().mockRejectedValue(new Error("boom"));

      const promise1 = cache.get("key", fetcher);
      const promise2 = cache.get("key", fetcher);

      await expect(promise1).rejects.toThrow("boom");
      await expect(promise2).rejects.toThrow("boom");
      expect(fetcher).toHaveBeenCalledTimes(1);
    });

    it("allows re-fetch after failed single flight", async () => {
      const cache = new TtlCache<string, number>({ ttlMs: 5000 });
      const fetcher = vi.fn().mockRejectedValueOnce(new Error("fail")).mockResolvedValueOnce(42);

      await expect(cache.get("key", fetcher)).rejects.toThrow("fail");

      const result = await cache.get("key", fetcher);
      expect(result).toBe(42);
      expect(fetcher).toHaveBeenCalledTimes(2);
    });
  });

  describe("LRU eviction", () => {
    it("evicts the least recently used entry when at capacity", async () => {
      const cache = new TtlCache<string, number>({ ttlMs: 60000, maxEntries: 3 });

      await cache.get("a", () => Promise.resolve(1));
      await cache.get("b", () => Promise.resolve(2));
      await cache.get("c", () => Promise.resolve(3));

      // Cache is now full: [a, b, c]
      // Adding a new entry should evict "a" (LRU)
      await cache.get("d", () => Promise.resolve(4));

      expect(cache.has("a")).toBe(false);
      expect(cache.has("b")).toBe(true);
      expect(cache.has("c")).toBe(true);
      expect(cache.has("d")).toBe(true);
    });

    it("accessing an entry refreshes its LRU position", async () => {
      const cache = new TtlCache<string, number>({ ttlMs: 60000, maxEntries: 3 });

      await cache.get("a", () => Promise.resolve(1));
      await cache.get("b", () => Promise.resolve(2));
      await cache.get("c", () => Promise.resolve(3));

      // Access "a" to refresh its position
      await cache.get("a", () => Promise.resolve(999)); // Should return cached 1

      // Adding "d" should evict "b" (now LRU), not "a"
      await cache.get("d", () => Promise.resolve(4));

      expect(cache.has("a")).toBe(true);
      expect(cache.has("b")).toBe(false);
      expect(cache.has("c")).toBe(true);
      expect(cache.has("d")).toBe(true);
    });

    it("respects maxEntries of 500 (default)", async () => {
      const cache = new TtlCache<string, number>({ ttlMs: 60000 });

      // Fill to 500
      for (let i = 0; i < 500; i++) {
        await cache.get(`key-${i}`, () => Promise.resolve(i));
      }
      expect(cache.size).toBe(500);

      // Adding one more should evict the first
      await cache.get("overflow", () => Promise.resolve(999));
      expect(cache.size).toBe(500);
      expect(cache.has("key-0")).toBe(false);
      expect(cache.has("overflow")).toBe(true);
    });
  });

  describe("utility methods", () => {
    it("clear() removes all entries", async () => {
      const cache = new TtlCache<string, number>({ ttlMs: 5000 });
      await cache.get("a", () => Promise.resolve(1));
      await cache.get("b", () => Promise.resolve(2));

      cache.clear();

      expect(cache.size).toBe(0);
      expect(cache.has("a")).toBe(false);
      expect(cache.has("b")).toBe(false);
    });

    it("delete() removes a specific entry", async () => {
      const cache = new TtlCache<string, number>({ ttlMs: 5000 });
      await cache.get("a", () => Promise.resolve(1));

      const deleted = cache.delete("a");
      expect(deleted).toBe(true);
      expect(cache.has("a")).toBe(false);
    });
  });
});
