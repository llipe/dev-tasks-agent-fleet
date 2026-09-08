/**
 * Cursor / dedupe reducer (Story S-110, SD6) — pure, the heart of gap-free
 * reconnect.
 *
 * `run_events.seq` is monotonic and agent-assigned. Because the agent buffers
 * (D5), arrival order is not emission order and timestamps are unreliable for
 * ordering — so the relay orders and de-duplicates strictly by `seq`.
 *
 * The relay's contract (SD6): backfill `seq > after_seq` first, then open the
 * Realtime subscription, and drop any pushed row whose `seq` is at or below the
 * highest already sent. `SeqCursor` is the state that enforces "at or below the
 * highest already sent"; `dedupeAndOrder` is the batch form used for backfill.
 *
 * The invariant both uphold (RT-1): the emitted `seq` stream is strictly
 * increasing, contains every input `seq > after_seq` exactly once, and the
 * cursor is monotonic non-decreasing — a late lower `seq` (already covered) is
 * dropped, and a reconnect never rewinds the cursor.
 */

/** The minimal shape the reducer needs: a monotonic `seq`. */
export interface SeqItem {
  seq: number;
}

/**
 * Parse the `after_seq` query parameter — a non-negative integer, else 0
 * (CT-2/CT-3). Non-finite, negative, or absent values coerce to 0 (a full
 * backfill); non-integer floats are floored.
 *
 * This lives here (a pure `lib/` module), not in the SSE route handler: the
 * Next.js App Router route-type validator rejects any non-standard named export
 * from a `route.ts` file, so a `parseAfterSeq` export there fails `next build`.
 * Keeping it in the cursor module preserves its unit-testability and unblocks
 * the production build the S-115 deploy requires.
 */
export function parseAfterSeq(raw: string | null): number {
  if (raw === null) return 0;
  const n = Number(raw);
  if (!Number.isFinite(n) || n < 0) return 0;
  return Math.floor(n);
}

/**
 * Tracks the highest `seq` emitted so far and decides whether a candidate is
 * genuinely new. Stateful by design — one instance per open stream.
 */
export class SeqCursor {
  private _highest: number;

  constructor(afterSeq = 0) {
    // A NaN/negative/undefined initial cursor is normalized to 0 so the stream
    // never starts from an impossible position.
    this._highest = Number.isFinite(afterSeq) && afterSeq > 0 ? Math.floor(afterSeq) : 0;
  }

  /** The highest `seq` admitted so far (the resume cursor). */
  get highest(): number {
    return this._highest;
  }

  /**
   * Admit `seq` if it is strictly greater than the highest already emitted.
   * On admission the cursor advances; on a duplicate or regression it does not
   * move (monotonic non-decreasing). Returns whether the caller should emit it.
   */
  admit(seq: number): boolean {
    if (!Number.isFinite(seq) || seq <= this._highest) {
      return false;
    }
    this._highest = seq;
    return true;
  }
}

/**
 * Batch form: from `items` (any order, possibly with duplicates and values at
 * or below `afterSeq`), return the subset with `seq > afterSeq`, de-duplicated
 * (first occurrence wins) and sorted strictly increasing by `seq`.
 *
 * Used for the backfill read, where the whole set is known at once. First
 * occurrence is kept so a duplicated `seq` carrying a different payload is
 * resolved deterministically.
 */
export function dedupeAndOrder<T extends SeqItem>(items: readonly T[], afterSeq = 0): T[] {
  const floor = Number.isFinite(afterSeq) ? afterSeq : 0;
  const firstBySeq = new Map<number, T>();
  for (const item of items) {
    if (!Number.isFinite(item.seq) || item.seq <= floor) continue;
    if (!firstBySeq.has(item.seq)) firstBySeq.set(item.seq, item);
  }
  return [...firstBySeq.values()].sort((a, b) => a.seq - b.seq);
}
