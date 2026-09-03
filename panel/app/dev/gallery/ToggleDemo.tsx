"use client";

import { useState } from "react";

import { Toggle } from "@/components/Toggle";

/**
 * Client wrapper so the dev gallery can show the Toggle actually toggling.
 * The gallery page itself stays a Server Component; only this interactive
 * island is client-side.
 */
export function ToggleDemo() {
  const [on, setOn] = useState(false);
  const [verbose, setVerbose] = useState(true);
  return (
    <div style={{ display: "flex", gap: "16px", alignItems: "center" }}>
      <Toggle checked={on} onChange={setOn} aria-label="off by default" />
      <Toggle checked={verbose} onChange={setVerbose} aria-label="on by default" />
      <Toggle checked={false} onChange={() => {}} disabled aria-label="disabled" />
    </div>
  );
}
