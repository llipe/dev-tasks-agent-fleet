/**
 * Auto-scroll threshold predicate (Story S-110, AC6 / DESIGN §6.6) — pure.
 *
 * The live-tail log follows new lines only while the user is near the bottom.
 * DESIGN §6.6: "Auto-scrolls log when user is within 24px of bottom". Kept as a
 * pure function of the three scroll measurements so the exact 24px boundary is
 * a single asserted truth (EC-15) rather than a value buried in an effect.
 *
 * "within 24px" is inclusive: at exactly 24px the log follows; at 25px it
 * pauses.
 */

/** DESIGN §6.6 — follow when the distance from the bottom is at most this. */
export const AUTOSCROLL_THRESHOLD_PX = 24;

/** The three scroll measurements a scroll container exposes. */
export interface ScrollMetrics {
  scrollHeight: number;
  scrollTop: number;
  clientHeight: number;
}

/** Pixels between the current viewport bottom and the content bottom. */
export function distanceFromBottom(m: ScrollMetrics): number {
  return m.scrollHeight - m.scrollTop - m.clientHeight;
}

/** True when the log should auto-scroll to follow a newly appended line. */
export function shouldAutoScroll(m: ScrollMetrics): boolean {
  return distanceFromBottom(m) <= AUTOSCROLL_THRESHOLD_PX;
}
