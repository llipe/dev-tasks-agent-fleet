"use client";

import { useState } from "react";
import { Button } from "@/components/Button";
import styles from "./SchemaPreview.module.css";

/**
 * S-113 (issue 126) — the schema preview toggle (task 2.10, DESIGN §5.4).
 *
 * Shows the raw `params_schema` JSON on demand, so an operator can see exactly
 * what the form was generated from. Collapsed by default.
 */
export interface SchemaPreviewProps {
  schema: unknown;
}

export function SchemaPreview({ schema }: SchemaPreviewProps) {
  const [open, setOpen] = useState(false);
  return (
    <div className={styles.wrap}>
      <Button variant="ghost" size="sm" aria-expanded={open} onClick={() => setOpen((v) => !v)}>
        {open ? "Hide schema" : "Show schema"}
      </Button>
      {open && (
        <pre className={styles.pre} data-testid="schema-preview">
          {JSON.stringify(schema, null, 2)}
        </pre>
      )}
    </div>
  );
}
