"use client";

/**
 * AddRepoForm — S-022, sub-task 22.7.
 *
 * Single input for repo name (e.g., "owner/repo").
 * Validates format client-side before submitting.
 * Calls addSubjectToAgent server action.
 */

import { useState, useCallback, useTransition } from "react";
import { addSubjectToAgent } from "@/server/actions/scope.js";

interface AddRepoFormProps {
  agentName: string;
}

/** Validate repo format: must be "owner/repo" style */
function validateRepoName(name: string): string | null {
  const trimmed = name.trim();
  if (trimmed === "") return "Repository name is required";

  // Accept owner/repo format, URLs, or SSH remotes
  // Minimal check: must contain at least one "/"
  if (!trimmed.includes("/")) {
    return 'Repository must be in "owner/repo" format';
  }

  return null;
}

export function AddRepoForm({ agentName }: AddRepoFormProps) {
  const [isOpen, setIsOpen] = useState(false);
  const [repoName, setRepoName] = useState("");
  const [validationError, setValidationError] = useState<string | null>(null);
  const [submitError, setSubmitError] = useState<string | null>(null);
  const [success, setSuccess] = useState(false);
  const [isPending, startTransition] = useTransition();

  const handleOpen = useCallback(() => {
    setIsOpen(true);
    setRepoName("");
    setValidationError(null);
    setSubmitError(null);
    setSuccess(false);
  }, []);

  const handleClose = useCallback(() => {
    setIsOpen(false);
  }, []);

  const handleInputChange = useCallback((value: string) => {
    setRepoName(value);
    setSuccess(false);
    setSubmitError(null);
    if (value.trim() !== "") {
      setValidationError(validateRepoName(value));
    } else {
      setValidationError(null);
    }
  }, []);

  const handleSubmit = useCallback(() => {
    const error = validateRepoName(repoName);
    if (error) {
      setValidationError(error);
      return;
    }

    setSubmitError(null);
    startTransition(async () => {
      const result = await addSubjectToAgent({
        subjectId: repoName.trim(),
        agentName,
        enabled: true,
      });

      if (result.ok) {
        setSuccess(true);
        setRepoName("");
        setTimeout(() => setIsOpen(false), 1500);
      } else {
        setSubmitError(result.error.message);
      }
    });
  }, [repoName, agentName]);

  if (!isOpen) {
    return (
      <button
        type="button"
        onClick={handleOpen}
        className="rounded bg-brand-secondary px-3 py-1.5 text-sm font-medium text-white transition-colors hover:bg-brand-primary"
      >
        Add Repo
      </button>
    );
  }

  const isValid = repoName.trim() !== "" && validationError === null;

  return (
    <div className="flex items-start gap-2">
      <div className="flex flex-col gap-1">
        <input
          type="text"
          aria-label="Repository name"
          className="rounded border border-surface-border bg-surface-bg px-3 py-1.5 text-sm text-text-primary placeholder-text-muted focus:border-brand-secondary focus:outline-none"
          value={repoName}
          onChange={(e) => handleInputChange(e.target.value)}
          placeholder="owner/repo"
          onKeyDown={(e) => {
            if (e.key === "Enter" && isValid && !isPending) {
              handleSubmit();
            }
          }}
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
        {success && <span className="text-xs text-status-success-fg">Repository added.</span>}
      </div>
      <button
        type="button"
        onClick={handleSubmit}
        disabled={!isValid || isPending}
        className="rounded bg-brand-secondary px-3 py-1.5 text-sm font-medium text-white transition-colors hover:bg-brand-primary disabled:opacity-50"
      >
        {isPending ? "Adding…" : "Add"}
      </button>
      <button
        type="button"
        onClick={handleClose}
        className="rounded border border-surface-border px-3 py-1.5 text-sm font-medium text-text-secondary hover:bg-surface-hover"
      >
        Cancel
      </button>
    </div>
  );
}
