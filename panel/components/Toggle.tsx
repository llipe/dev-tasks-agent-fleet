"use client";

import type { CSSProperties } from "react";

import styles from "./Toggle.module.css";

/**
 * Toggle switch — /DESIGN.md §3.10 (Invoke form boolean control). Interactive,
 * so it is a client component. Implemented as a real
 * `role="switch"` button for accessibility: keyboard-operable (Space/Enter via
 * native button activation), announces its on/off state via `aria-checked`,
 * and is labelled by `aria-label` or an external label via `aria-labelledby`.
 */
export interface ToggleProps {
  checked: boolean;
  onChange: (next: boolean) => void;
  disabled?: boolean;
  id?: string;
  "aria-label"?: string;
  "aria-labelledby"?: string;
  className?: string;
}

export function Toggle({
  checked,
  onChange,
  disabled = false,
  id,
  className,
  ...aria
}: ToggleProps) {
  const classes = [styles.track, checked && styles.on, className].filter(Boolean).join(" ");
  return (
    <button
      type="button"
      role="switch"
      id={id}
      aria-checked={checked}
      aria-label={aria["aria-label"]}
      aria-labelledby={aria["aria-labelledby"]}
      disabled={disabled}
      className={classes}
      onClick={() => onChange(!checked)}
    >
      <span className={styles.knob} style={{ "--knob": checked ? 1 : 0 } as CSSProperties} />
    </button>
  );
}
