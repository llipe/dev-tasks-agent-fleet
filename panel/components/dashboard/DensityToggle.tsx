"use client";

import type { Density } from "@/lib/ui/density-state";
import styles from "./DensityToggle.module.css";

/**
 * Density variant selector (task 2.9 / AC-107.2, AC-107.3). A segmented
 * control over the three §5.1 variants. Presentation swap only — selecting a
 * variant changes which component renders the SAME already-loaded data; it
 * **never navigates** (no router call, no `<Link>`, no `searchParams` write)
 * and therefore cannot refetch. Persistence to `localStorage` is handled by the
 * parent (`DashboardClient`) so this stays a controlled presentational control.
 */
const OPTIONS: { value: Density; label: string }[] = [
  { value: "dense", label: "Rows" },
  { value: "cards", label: "Cards" },
  { value: "ledger", label: "Ledger" },
];

export interface DensityToggleProps {
  value: Density;
  onChange: (value: Density) => void;
}

export function DensityToggle({ value, onChange }: DensityToggleProps) {
  return (
    <div className={styles.group} role="group" aria-label="Density">
      {OPTIONS.map((opt) => {
        const active = opt.value === value;
        return (
          <button
            key={opt.value}
            type="button"
            className={`${styles.option} ${active ? styles.active : ""}`}
            aria-pressed={active}
            onClick={() => onChange(opt.value)}
          >
            {opt.label}
          </button>
        );
      })}
    </div>
  );
}
