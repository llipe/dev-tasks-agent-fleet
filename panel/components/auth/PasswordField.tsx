"use client";

import { useId, useState } from "react";

import { Input } from "../Input";
import { KLabel } from "../KLabel";
import styles from "./PasswordField.module.css";

/**
 * Password field with a SHOW/HIDE reveal toggle (Story S-119, spec §10.1, FR13).
 *
 * The password defaults to **masked** (`type="password"`). A text toggle button,
 * right-aligned on the label row, reveals and re-masks it. The toggle:
 *   - is a real `<button type="button">` — keyboard-operable and never submits
 *     the form (AC13);
 *   - reports its state with `aria-pressed` (pressed = revealed);
 *   - controls the input via `aria-controls` for assistive tech.
 *
 * Client component: it owns the transient `revealed` state. The password value
 * itself is uncontrolled — the field forwards straight to the form submission,
 * so React never holds the plaintext in state (it is read from `FormData` in the
 * server action). `autoComplete="current-password"` per §10.1.
 */
export interface PasswordFieldProps {
  /** The form field name (submitted to the action). */
  name: string;
  /** Visible label text (e.g. "PASSWORD"). */
  label: string;
  /** Disabled while the form is pending (prevents edits mid-submit). */
  disabled?: boolean;
}

export function PasswordField({ name, label, disabled }: PasswordFieldProps) {
  const [revealed, setRevealed] = useState(false);
  const inputId = useId();

  return (
    <div className={styles.field}>
      <div className={styles.labelRow}>
        <KLabel>
          <label htmlFor={inputId}>{label}</label>
        </KLabel>
        <button
          type="button"
          className={styles.toggle}
          aria-pressed={revealed}
          aria-controls={inputId}
          aria-label={revealed ? "Hide password" : "Show password"}
          onClick={() => setRevealed((v) => !v)}
          disabled={disabled}
        >
          {revealed ? "HIDE" : "SHOW"}
        </button>
      </div>
      <Input
        id={inputId}
        name={name}
        type={revealed ? "text" : "password"}
        autoComplete="current-password"
        required
        disabled={disabled}
      />
    </div>
  );
}
