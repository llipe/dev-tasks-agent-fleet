import type { InputHTMLAttributes } from "react";

import styles from "./Input.module.css";

/**
 * Input — /DESIGN.md §3.2. Surface background, divider border that shifts to
 * accent on focus, accent caret. Two sizes (sm/default). Presentational and
 * server-safe; forwards all native input props. Callers MUST associate a
 * <label> (accessibility rule) — this primitive intentionally does not render
 * its own label so it composes into field rows.
 */
export type InputSize = "sm" | "default";

export interface InputProps extends Omit<InputHTMLAttributes<HTMLInputElement>, "size"> {
  inputSize?: InputSize;
}

export function Input({ inputSize = "default", className, type, ...rest }: InputProps) {
  const classes = [styles.input, inputSize === "sm" && styles.sm, className]
    .filter(Boolean)
    .join(" ");
  return <input type={type ?? "text"} className={classes} {...rest} />;
}
