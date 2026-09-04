"use client";

import { forwardRef } from "react";

import { Input } from "@/components/Input";
import styles from "./AgentFilter.module.css";

/**
 * Dashboard header filter (task 2.12a / AC-107.8). Client-side over the
 * already-loaded list, matching name + slug case-insensitively (the predicate
 * lives in `lib/domain/dashboard.ts`). **Transient — never persisted**: a
 * remembered filter would silently hide agents on the next load. It never
 * navigates and never refetches.
 *
 * `/` focuses this input (bound globally by the parent); `Escape` clears a
 * non-empty value, then blurs when already empty. The ref is forwarded so the
 * parent can focus it in response to `/`.
 */
export interface AgentFilterProps {
  value: string;
  onChange: (value: string) => void;
}

export const AgentFilter = forwardRef<HTMLInputElement, AgentFilterProps>(function AgentFilter(
  { value, onChange },
  ref,
) {
  return (
    <div className={styles.wrap}>
      <label htmlFor="agent-filter" className={styles.srOnly}>
        Filter agents by name or slug
      </label>
      <Input
        id="agent-filter"
        ref={ref}
        inputSize="sm"
        type="search"
        placeholder="Filter agents…"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Escape") {
            if (value !== "") {
              e.preventDefault();
              onChange("");
            } else {
              (e.target as HTMLInputElement).blur();
            }
          }
        }}
        autoComplete="off"
        spellCheck={false}
      />
    </div>
  );
});
