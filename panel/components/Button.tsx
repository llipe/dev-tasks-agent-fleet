import type { ButtonHTMLAttributes, ReactNode } from "react";

import styles from "./Button.module.css";

/**
 * Button — /DESIGN.md §3.1. Outlined, never solid-filled (primary is an
 * accent border on transparent). Variants primary/secondary/ghost × sizes
 * sm/md/default, plus a disabled state. Presentational and server-safe: it
 * forwards native button props, so a consumer wires its own onClick in a
 * client component.
 */
export type ButtonVariant = "primary" | "secondary" | "ghost";
export type ButtonSize = "sm" | "md" | "default";

export interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  children: ReactNode;
  variant?: ButtonVariant;
  size?: ButtonSize;
}

export function Button({
  children,
  variant = "secondary",
  size = "default",
  className,
  type,
  ...rest
}: ButtonProps) {
  const classes = [styles.btn, styles[variant], styles[`size_${size}`], className]
    .filter(Boolean)
    .join(" ");
  return (
    // Buttons default to type="button" so they never accidentally submit a form.
    <button type={type ?? "button"} className={classes} {...rest}>
      {children}
    </button>
  );
}
