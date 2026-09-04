/**
 * Dashboard density-variant persistence (task 2.9 / AC-107.3).
 *
 * The chosen density variant lives in `localStorage`, which the server cannot
 * read — so, exactly like the sidebar collapse state, the page renders a fixed
 * server default and the client reconciles from storage after mount. These
 * helpers are defensive on every axis a browser storage can fail: absent (SSR),
 * throwing (Safari private mode / disabled / quota), and a corrupt or
 * unrecognized value (a variant name from a previous or tampered build).
 *
 * The stored value is a closed vocabulary of three literals. An unknown string
 * (`"kanban"`, a numeric index from a hypothetical older release, `"{"`, `""`)
 * is trivially distinguishable from a valid one and always falls back to the
 * documented default — the crash CT-4/CT-5 exist to prevent.
 */

export const DENSITY_STORAGE_KEY = "panel.dashboard.density";

/** The three §5.1 variants. `dense` is the documented default (variant 1a). */
export type Density = "dense" | "cards" | "ledger";

const VALID: readonly Density[] = ["dense", "cards", "ledger"] as const;

/** The documented default: a fresh visitor sees the dense-rows variant. */
export const DEFAULT_DENSITY: Density = "dense";

type MaybeStorage = Storage | null | undefined;

/** Whether an arbitrary string is one of the three known variant literals. */
export function isDensity(value: unknown): value is Density {
  return typeof value === "string" && (VALID as readonly string[]).includes(value);
}

/**
 * Reads the persisted density. Returns {@link DEFAULT_DENSITY} for every
 * failure mode — absent storage, a throwing accessor, and any value not in the
 * closed vocabulary. Never throws.
 */
export function readDensity(storage: MaybeStorage): Density {
  if (!storage) return DEFAULT_DENSITY;
  try {
    const raw = storage.getItem(DENSITY_STORAGE_KEY);
    return isDensity(raw) ? raw : DEFAULT_DENSITY;
  } catch {
    return DEFAULT_DENSITY;
  }
}

/**
 * Persists the density as its canonical literal. A throwing `setItem` (quota,
 * private mode) is swallowed — a preference that cannot be saved must not break
 * the session. No-op when storage is unavailable.
 */
export function writeDensity(storage: MaybeStorage, density: Density): void {
  if (!storage) return;
  try {
    storage.setItem(DENSITY_STORAGE_KEY, density);
  } catch {
    // Ignore: persistence is best-effort.
  }
}
