"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";

import type { AgentSummary } from "@/lib/domain/dashboard";
import { formatRelative, formatRunCount } from "@/lib/format";
import { StatusDot } from "@/components/StatusDot";

import { outcomeLabel } from "./summary-view";
import styles from "./Ledger.module.css";

/**
 * Dashboard variant 1c — ledger (`/DESIGN.md` §5.1, keyboard-first). Maximum
 * density, one line per agent. Client component because it owns keyboard
 * selection.
 *
 * Keyboard affordances (task 2.13, AC-107.7) — these SHIP; "or render them
 * absent" is withdrawn:
 *  - `Up`/`Down` move the selection using a **roving tabindex** (exactly one
 *    row is focusable at a time), clamped at both ends (no wrap).
 *  - `Enter` on the selected row activates the SAME target as its Invoke action
 *    (task 2.11 governs both), so the keyboard path never reaches a route the
 *    mouse path deliberately does not. When no invoke route exists yet, Enter
 *    is inert rather than navigating somewhere wrong.
 *
 * The hint row renders the shortcuts (§6.5); the hint/behavior coupling guard
 * (task 2.13a) asserts a rendered hint always has a working key behind it.
 */
export interface LedgerProps {
  agents: AgentSummary[];
  nowMs: number;
  invokeHref: (slug: string) => string | null;
  /** Focus the header filter input (bound to `/`, provided by the parent). */
  onFocusFilter?: () => void;
}

export function Ledger({ agents, nowMs, invokeHref, onFocusFilter }: LedgerProps) {
  const router = useRouter();
  const [selected, setSelected] = useState(0);
  const rowRefs = useRef<(HTMLDivElement | null)[]>([]);

  // Keep the selection in range as the filtered list shrinks/grows.
  useEffect(() => {
    setSelected((s) => Math.min(s, Math.max(0, agents.length - 1)));
  }, [agents.length]);

  const activate = useCallback(
    (index: number) => {
      const agent = agents[index];
      if (!agent) return;
      const href = invokeHref(agent.slug);
      // Enter reaches the same target as the mouse Invoke action; when the
      // route does not exist yet, do nothing (never navigate somewhere wrong).
      if (href != null) router.push(href);
    },
    [agents, invokeHref, router],
  );

  const onKeyDown = useCallback(
    (event: React.KeyboardEvent<HTMLDivElement>) => {
      if (event.key === "ArrowDown") {
        event.preventDefault();
        setSelected((s) => {
          const next = Math.min(s + 1, agents.length - 1); // clamp, no wrap
          rowRefs.current[next]?.focus();
          return next;
        });
      } else if (event.key === "ArrowUp") {
        event.preventDefault();
        setSelected((s) => {
          const next = Math.max(s - 1, 0); // clamp, no wrap
          rowRefs.current[next]?.focus();
          return next;
        });
      } else if (event.key === "Enter") {
        event.preventDefault();
        activate(selected);
      } else if (event.key === "/") {
        // `/` focuses the filter (superset of §6.5). The parent's global
        // handler also binds it; guarding here avoids inserting a slash when a
        // row (not a text field) has focus.
        event.preventDefault();
        onFocusFilter?.();
      }
    },
    [agents.length, selected, activate, onFocusFilter],
  );

  return (
    <div
      className={styles.ledger}
      role="listbox"
      aria-label="Agents ledger"
      aria-activedescendant={agents[selected] ? `ledger-row-${agents[selected].id}` : undefined}
    >
      {agents.map((agent, index) => {
        const isSelected = index === selected;
        return (
          <div
            key={agent.id}
            id={`ledger-row-${agent.id}`}
            ref={(el) => {
              rowRefs.current[index] = el;
            }}
            role="option"
            aria-selected={isSelected}
            // Roving tabindex: only the selected row is in the tab order.
            tabIndex={isSelected ? 0 : -1}
            className={`${styles.row} ${isSelected ? styles.selected : ""}`}
            onKeyDown={onKeyDown}
            onFocus={() => setSelected(index)}
            onClick={() => setSelected(index)}
          >
            <StatusDot status={agent.lastRun?.effectiveStatus ?? "queued"} size={6} decorative />
            <span className={styles.name}>{agent.name}</span>
            <span className={styles.slug}>{agent.slug}</span>
            <span className={styles.runs}>{formatRunCount(agent.runCount)}</span>
            <span className={styles.outcome}>
              {agent.lastRun != null ? outcomeLabel(agent.lastRun.outcome) : "—"}
            </span>
            <span className={styles.time}>
              {agent.lastRun?.atMs != null ? formatRelative(agent.lastRun.atMs, nowMs) : "—"}
            </span>
          </div>
        );
      })}
      <p className={styles.hints} aria-hidden="true">
        <span>
          <kbd>↑</kbd>
          <kbd>↓</kbd> navigate
        </span>
        <span>
          <kbd>Enter</kbd> invoke
        </span>
        <span>
          <kbd>/</kbd> filter
        </span>
      </p>
    </div>
  );
}
