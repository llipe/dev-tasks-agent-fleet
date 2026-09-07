import styles from "./LiveTailButton.module.css";

/**
 * LiveTailButton — /DESIGN.md §6.6. The pill control that reflects and toggles
 * live-tail follow state:
 *  - **Active** (following): green dot + green text + pulsing animation.
 *  - **Paused** (user scrolled up): transparent background + muted text.
 *
 * `aria-pressed` carries the follow state for assistive tech and for tests.
 * Clicking it resumes following and re-scrolls to the bottom (handled by the
 * parent, which owns the scroll ref).
 */
export interface LiveTailButtonProps {
  following: boolean;
  onResume: () => void;
}

export function LiveTailButton({ following, onResume }: LiveTailButtonProps) {
  return (
    <button
      type="button"
      className={[styles.button, following ? styles.active : styles.paused]
        .filter(Boolean)
        .join(" ")}
      aria-pressed={following}
      aria-label={following ? "Live tail active" : "Live tail paused — resume"}
      onClick={onResume}
    >
      <span className={styles.dot} aria-hidden="true" />
      live tail
    </button>
  );
}
