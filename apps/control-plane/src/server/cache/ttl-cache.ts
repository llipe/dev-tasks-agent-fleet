/**
 * Generic in-process TTL cache with single-flight de-duplication and LRU eviction.
 *
 * - TTL: configurable, default 5 minutes
 * - Single-flight: concurrent calls for the same key share one in-flight promise
 * - LRU: when capacity is exceeded, the least recently used entry is evicted
 *
 * Thread-safe for Node.js single-threaded event loop — no mutex needed,
 * just promise sharing for concurrent requests.
 */

interface CacheEntry<V> {
  value: V;
  expiresAt: number;
}

export interface TtlCacheOptions {
  /** TTL in milliseconds (default: 300_000 = 5 min) */
  ttlMs?: number;
  /** Maximum entries before LRU eviction (default: 500) */
  maxEntries?: number;
}

const DEFAULT_TTL_MS = 300_000; // 5 minutes
const DEFAULT_MAX_ENTRIES = 500;

export class TtlCache<K = string, V = unknown> {
  private readonly cache = new Map<K, CacheEntry<V>>();
  private readonly inflight = new Map<K, Promise<V>>();
  private readonly ttlMs: number;
  private readonly maxEntries: number;

  constructor(options?: TtlCacheOptions) {
    this.ttlMs = options?.ttlMs ?? DEFAULT_TTL_MS;
    this.maxEntries = options?.maxEntries ?? DEFAULT_MAX_ENTRIES;
  }

  /**
   * Get a value from cache, or call the fetcher to populate it.
   * Concurrent calls for the same key share one in-flight promise (single-flight).
   */
  async get(key: K, fetcher: () => Promise<V>): Promise<V> {
    // Check cache first
    const entry = this.cache.get(key);
    if (entry && entry.expiresAt > Date.now()) {
      // Move to end for LRU ordering (Map iteration order is insertion order)
      this.cache.delete(key);
      this.cache.set(key, entry);
      return entry.value;
    }

    // Remove expired entry if present
    if (entry) {
      this.cache.delete(key);
    }

    // Check if there's an in-flight request for this key (single-flight)
    const existing = this.inflight.get(key);
    if (existing) {
      return existing;
    }

    // Start a new fetch
    const promise = fetcher().then(
      (value) => {
        this.inflight.delete(key);
        this.set(key, value);
        return value;
      },
      (error) => {
        this.inflight.delete(key);
        throw error;
      },
    );

    this.inflight.set(key, promise);
    return promise;
  }

  /** Manually set a value in the cache */
  private set(key: K, value: V): void {
    // Evict LRU entries if at capacity
    while (this.cache.size >= this.maxEntries) {
      // Map iterates in insertion order; first key is the LRU
      const firstKey = this.cache.keys().next().value;
      if (firstKey !== undefined) {
        this.cache.delete(firstKey);
      } else {
        break;
      }
    }

    this.cache.set(key, {
      value,
      expiresAt: Date.now() + this.ttlMs,
    });
  }

  /** Clear all entries and in-flight promises */
  clear(): void {
    this.cache.clear();
    this.inflight.clear();
  }

  /** Current number of cached entries (not including in-flight) */
  get size(): number {
    return this.cache.size;
  }

  /** Check if a non-expired entry exists for the key */
  has(key: K): boolean {
    const entry = this.cache.get(key);
    return entry !== undefined && entry.expiresAt > Date.now();
  }

  /** Delete a specific entry */
  delete(key: K): boolean {
    this.inflight.delete(key);
    return this.cache.delete(key);
  }
}
