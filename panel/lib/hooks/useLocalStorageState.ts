"use client";

/**
 * `useLocalStorageState` — a hydration-safe, localStorage-backed UI preference
 * hook built on `useSyncExternalStore` (issue 217).
 *
 * The panel's density and sidebar-collapse preferences live in `localStorage`,
 * which the server cannot read. The former implementation rendered a fixed
 * default and reconciled from storage in a mount effect that called
 * `setState` — the exact `react-hooks/set-state-in-effect` pattern React 19's
 * lint flags, because an effect that synchronously sets state to mirror an
 * external mutable source should instead *subscribe* to that source via
 * `useSyncExternalStore`.
 *
 * Behavior is identical to the old effect-based reconcile:
 *   - Server render and the first client render both return the `default`
 *     (the server snapshot), so hydration never mismatches.
 *   - Immediately after hydration React reads the client snapshot (the stored
 *     value) and re-renders — the same "reconcile after mount" the effect did.
 *   - `set(next)` persists through `write` and notifies subscribers so the
 *     component re-renders with the new value.
 *   - A cross-tab `storage` event re-reads and re-renders.
 *
 * `read`/`write` are injected (the existing defensive `readDensity`/`writeDensity`
 * and sidebar equivalents), so storage-failure handling is unchanged and the
 * hook stays unit-testable.
 */

import { useCallback, useMemo, useSyncExternalStore } from "react";

type MaybeStorage = Storage | null | undefined;

function browserStorage(): MaybeStorage {
  if (typeof window === "undefined") return null;
  try {
    return window.localStorage;
  } catch {
    return null;
  }
}

export interface LocalStorageStateOptions<T> {
  /** The server/first-client snapshot — must be stable across renders. */
  default: T;
  /** Defensive reader (never throws), e.g. `readDensity`. */
  read: (storage: MaybeStorage) => T;
  /** Defensive writer (never throws), e.g. `writeDensity`. */
  write: (storage: MaybeStorage, value: T) => void;
  /** The storage key, used to filter cross-tab `storage` events. */
  storageKey: string;
}

export function useLocalStorageState<T>(
  options: LocalStorageStateOptions<T>,
): [T, (next: T | ((prev: T) => T)) => void] {
  const { default: serverDefault, read, write, storageKey } = options;

  const subscribe = useCallback(
    (onStoreChange: () => void) => {
      if (typeof window === "undefined") return () => {};
      // Same-tab writes dispatch a synthetic event on this key; cross-tab
      // writes arrive as native `storage` events. Both trigger a re-read.
      const handler = (event: Event) => {
        if (event instanceof StorageEvent && event.key !== null && event.key !== storageKey) {
          return;
        }
        onStoreChange();
      };
      window.addEventListener("storage", handler);
      window.addEventListener(`localstoragestate:${storageKey}`, handler);
      return () => {
        window.removeEventListener("storage", handler);
        window.removeEventListener(`localstoragestate:${storageKey}`, handler);
      };
    },
    [storageKey],
  );

  const getSnapshot = useCallback(() => read(browserStorage()), [read]);
  // The server snapshot (and therefore the first client render) is the default,
  // so hydration matches; React reconciles to the client snapshot right after.
  const getServerSnapshot = useCallback(() => serverDefault, [serverDefault]);

  const value = useSyncExternalStore(subscribe, getSnapshot, getServerSnapshot);

  const set = useCallback(
    (next: T | ((prev: T) => T)) => {
      // Support the React updater form: resolve against the current snapshot so
      // a toggle `(c) => !c` reads the live value, not a stale closure capture.
      const current = read(browserStorage());
      const resolved = typeof next === "function" ? (next as (prev: T) => T)(current) : next;
      write(browserStorage(), resolved);
      if (typeof window !== "undefined") {
        // Notify this tab's subscriber synchronously so the UI updates now.
        window.dispatchEvent(new Event(`localstoragestate:${storageKey}`));
      }
    },
    [read, write, storageKey],
  );

  return useMemo(() => [value, set], [value, set]);
}
