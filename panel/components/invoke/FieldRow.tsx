"use client";

import type { FieldDescriptor } from "@/lib/schema/form";
import { Input } from "@/components/Input";
import { Toggle } from "@/components/Toggle";
import styles from "./FieldRow.module.css";

/**
 * S-113 (issue 126) — one schema-derived field (task 2.5, DESIGN §5.4).
 *
 * Two-column row: label + type/required on the left, the control on the right
 * (the parent grid is `minmax(0,1fr) 292px`). The control is chosen from the
 * descriptor's `control`:
 *   select   -> native <select> over the enum options
 *   toggle   -> the S-105 Toggle primitive
 *   number   -> Input type=number carrying min/max
 *   text     -> Input type=text
 *   unsupported -> a DISABLED input with a visible note (AC4 — never vanishes)
 *
 * An inline per-field error (from INVALID_PARAMS) renders under the control.
 */
export interface FieldRowProps {
  field: FieldDescriptor;
  value: unknown;
  onChange: (name: string, value: unknown) => void;
  /** Inline error message for this field (INVALID_PARAMS), if any. */
  error?: string;
}

export function FieldRow({ field, value, onChange, error }: FieldRowProps) {
  const controlId = `param-${field.name}`;
  const describedBy = [field.help ? `${controlId}-help` : null, error ? `${controlId}-err` : null]
    .filter(Boolean)
    .join(" ");

  return (
    <div className={styles.row}>
      <div className={styles.labelCol}>
        <label className={styles.label} htmlFor={controlId}>
          {field.label}
          {field.required && (
            <span className={styles.required} aria-hidden="true">
              {" "}
              *
            </span>
          )}
        </label>
        <span className={styles.meta}>
          {field.control === "unsupported" ? "unsupported" : field.control}
          {field.required ? " · required" : ""}
        </span>
        {field.help && (
          <span id={`${controlId}-help`} className={styles.help}>
            {field.help}
          </span>
        )}
      </div>

      <div className={styles.controlCol}>
        {renderControl(field, controlId, value, onChange, describedBy || undefined)}
        {field.control === "unsupported" && field.note && (
          <span className={styles.note} role="note">
            {field.note}
          </span>
        )}
        {error && (
          <span id={`${controlId}-err`} className={styles.error} role="alert">
            {error}
          </span>
        )}
      </div>
    </div>
  );
}

function renderControl(
  field: FieldDescriptor,
  id: string,
  value: unknown,
  onChange: (name: string, value: unknown) => void,
  describedBy: string | undefined,
) {
  switch (field.control) {
    case "select":
      return (
        <select
          id={id}
          className={styles.select}
          value={value === undefined || value === null ? "" : String(value)}
          aria-describedby={describedBy}
          aria-required={field.required}
          onChange={(e) => onChange(field.name, e.target.value)}
        >
          {/* An empty placeholder only when there is no default/value yet. */}
          {(value === undefined || value === null || value === "") && (
            <option value="" disabled>
              Select…
            </option>
          )}
          {(field.options ?? []).map((opt) => {
            const v = String(opt);
            return (
              <option key={v} value={v}>
                {v}
              </option>
            );
          })}
        </select>
      );

    case "toggle":
      return (
        <Toggle
          id={id}
          checked={value === true}
          aria-label={field.label}
          onChange={(next) => onChange(field.name, next)}
        />
      );

    case "number":
      return (
        <Input
          id={id}
          type="number"
          value={value === undefined || value === null ? "" : String(value)}
          min={field.min}
          max={field.max}
          aria-describedby={describedBy}
          aria-required={field.required}
          onChange={(e) => {
            const raw = e.target.value;
            onChange(field.name, raw === "" ? undefined : Number(raw));
          }}
        />
      );

    case "text":
      return (
        <Input
          id={id}
          type="text"
          value={value === undefined || value === null ? "" : String(value)}
          aria-describedby={describedBy}
          aria-required={field.required}
          onChange={(e) => onChange(field.name, e.target.value)}
        />
      );

    case "unsupported":
    default:
      return (
        <Input
          id={id}
          type="text"
          value=""
          disabled
          aria-describedby={describedBy}
          placeholder="unsupported"
        />
      );
  }
}
