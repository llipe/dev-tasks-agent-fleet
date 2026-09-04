/**
 * Sidebar collapse-state persistence.
 *
 * The collapse preference lives in `localStorage`, which the server cannot
 * read. The shell therefore renders a fixed server default (expanded) and the
 * client reconciles from storage after mount — so these helpers must be
 * defensive on every axis a browser can fail: storage absent (SSR), storage
 * throwing (Safari private mode, disabled storage, quota), and a corrupt or
 * unrecognized stored value (a shape written by a future or tampered build).
 *
 * The stored value is a closed vocabulary of two literals rather than a JSON
 * boolean, so an unknown string is trivially distinguishable from a valid one
 * and always falls back to the documented default.
 */

export const SIDEBAR_STORAGE_KEY = "panel.sidebar.collapsed";

const COLLAPSED = "collapsed";
const EXPANDED = "expanded";

/** The documented default: a fresh visitor sees the expanded sidebar. */
export const DEFAULT_COLLAPSED = false;

type MaybeStorage = Storage | null | undefined;

/**
 * Reads the persisted collapse state. Returns {@link DEFAULT_COLLAPSED} for
 * every failure mode — absent storage, a throwing accessor, and any value that
 * is not exactly `"collapsed"` or `"expanded"`. Never throws.
 */
export function readSidebarCollapsed(storage: MaybeStorage): boolean {
  if (!storage) return DEFAULT_COLLAPSED;
  try {
    const raw = storage.getItem(SIDEBAR_STORAGE_KEY);
    if (raw === COLLAPSED) return true;
    if (raw === EXPANDED) return false;
    return DEFAULT_COLLAPSED;
  } catch {
    // Private mode / disabled storage: behave as a fresh visitor.
    return DEFAULT_COLLAPSED;
  }
}

/**
 * Persists the collapse state as its canonical literal. A throwing `setItem`
 * (quota exceeded, private mode) is swallowed — a preference that cannot be
 * saved must not break the session. No-op when storage is unavailable.
 */
export function writeSidebarCollapsed(storage: MaybeStorage, collapsed: boolean): void {
  if (!storage) return;
  try {
    storage.setItem(SIDEBAR_STORAGE_KEY, collapsed ? COLLAPSED : EXPANDED);
  } catch {
    // Ignore: persistence is best-effort.
  }
}
