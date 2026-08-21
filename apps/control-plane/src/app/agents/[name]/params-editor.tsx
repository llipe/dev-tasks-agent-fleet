"use client";

/**
 * ParamsEditor — S-022, sub-task 22.5.
 *
 * Client-side JSON validation before enabling Save.
 * Shows inline error naming the failing key.
 * Uses paramsSchemaFor from @fleet/shared for validation.
 */

import { useState, useCallback, useTransition } from "react";
import { paramsSchemaFor } from "@fleet/shared";
import { setSubjectParams } from "@/server/actions/scope.js";

interface ParamsEditorProps {
  subjectId: string;
  agentName: string;
}

export function ParamsEditor({ subjectId, agentName }: ParamsEditorProps) {
  const [isOpen, setIsOpen] = useState(false);
  const [jsonInput, setJsonInput] = useState("");
  const [validationError, setValidationError] = useState<string | null>(null);
  const [submitError, setSubmitError] = useState<string | null>(null);
  const [success, setSuccess] = useState(false);
  const [isPending, startTransition] = useTransition();

  const handleOpen = useCallback(() => {
    setIsOpen(true);
    setJsonInput("");
    setValidationError(null);
    setSubmitError(null);
    setSuccess(false);
  }, []);

  const handleClose = useCallback(() => {
    setIsOpen(false);
  }, []);

  const validate = useCallback(
    (input: string): Record<string, unknown> | null => {
      // 1. Parse JSON
      let parsed: unknown;
      try {
        parsed = JSON.parse(input);
      } catch {
        setValidationError("Invalid JSON syntax");
        return null;
      }

      if (typeof parsed !== "object" || parsed === null || Array.isArray(parsed)) {
        setValidationError("Params must be a JSON object");
        return null;
      }

      // 2. Validate against agent schema
      const schema = paramsSchemaFor(agentName);
      const result = schema.safeParse(parsed);

      if (!result.success) {
        const issue = result.error.issues[0];
        const key = issue?.path?.join(".") || "unknown";
        setValidationError(`Key "${key}": ${issue?.message ?? "validation failed"}`);
        return null;
      }

      setValidationError(null);
      return parsed as Record<string, unknown>;
    },
    [agentName],
  );

  const handleInputChange = useCallback(
    (value: string) => {
      setJsonInput(value);
      setSuccess(false);
      setSubmitError(null);

      if (value.trim() === "") {
        setValidationError(null);
        return;
      }

      validate(value);
    },
    [validate],
  );

  const handleSave = useCallback(() => {
    const params = validate(jsonInput);
    if (!params) return;

    setSubmitError(null);
    startTransition(async () => {
      const result = await setSubjectParams({
        subjectId,
        agentName,
        params,
      });

      if (result.ok) {
        setSuccess(true);
        setTimeout(() => setIsOpen(false), 1000);
      } else {
        setSubmitError(`Failed to update "${subjectId}": ${result.error.message}`);
      }
    });
  }, [jsonInput, validate, subjectId, agentName]);

  const isValid = jsonInput.trim() !== "" && validationError === null;

  if (!isOpen) {
    return (
      <button
        type="button"
        onClick={handleOpen}
        className="text-xs text-brand-secondary underline hover:text-brand-primary"
      >
        Edit
      </button>
    );
  }

  return (
    <div className="flex flex-col gap-2 min-w-[200px]">
      <textarea
        aria-label={`Edit params for ${subjectId}`}
        className="w-full rounded border border-surface-border bg-surface-bg p-2 font-mono text-xs text-text-primary focus:border-brand-secondary focus:outline-none"
        rows={4}
        value={jsonInput}
        onChange={(e) => handleInputChange(e.target.value)}
        placeholder='{"allow_fixes": true, "max_fix_attempts": 3}'
      />
      {validationError && (
        <span role="alert" className="text-xs text-status-failed-fg">
          {validationError}
        </span>
      )}
      {submitError && (
        <span role="alert" className="text-xs text-status-failed-fg">
          {submitError}
        </span>
      )}
      {success && <span className="text-xs text-status-success-fg">Params saved.</span>}
      <div className="flex gap-2">
        <button
          type="button"
          onClick={handleSave}
          disabled={!isValid || isPending}
          className="rounded bg-brand-secondary px-3 py-1 text-xs font-medium text-white transition-colors hover:bg-brand-primary disabled:opacity-50"
        >
          {isPending ? "Saving…" : "Save"}
        </button>
        <button
          type="button"
          onClick={handleClose}
          className="rounded border border-surface-border px-3 py-1 text-xs font-medium text-text-secondary hover:bg-surface-hover"
        >
          Cancel
        </button>
      </div>
    </div>
  );
}
