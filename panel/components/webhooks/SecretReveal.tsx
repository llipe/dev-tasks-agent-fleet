"use client";

import { useEffect, useId, useRef, useState } from "react";

import { Button } from "@/components/Button";
import { CopyIcon } from "@/components/icons";

import styles from "./Webhooks.module.css";

/**
 * S-176 (issue 321) — the show-once signing-secret dialog (DESIGN.md §5.9.2). The
 * secret exists only in the parent's state for as long as this dialog is open.
 * Dismissing drops it, and nothing can fetch it again: rotate to get a new one.
 * Only an explicit button closes it. There is no Escape or backdrop close, so
 * the secret can't be lost by accident.
 */
export interface SecretRevealProps {
  endpointName: string;
  secret: string;
  url: string;
  rotated: boolean;
  onDone: () => void;
}

export function SecretReveal({ endpointName, secret, url, rotated, onDone }: SecretRevealProps) {
  const uid = useId();
  const [copied, setCopied] = useState<"secret" | "url" | null>(null);
  const secretRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    secretRef.current?.focus();
    secretRef.current?.select();
  }, []);

  async function copy(which: "secret" | "url") {
    try {
      await navigator.clipboard.writeText(which === "secret" ? secret : url);
      setCopied(which);
    } catch {
      setCopied(null);
    }
  }

  return (
    <div className={styles.overlay}>
      <div
        className={`${styles.dialog} ${styles.small}`}
        role="dialog"
        aria-modal="true"
        aria-label="Copy the signing secret"
      >
        <header className={styles.header}>
          <h2 className={styles.title}>{rotated ? "New signing secret" : "Endpoint created"}</h2>
        </header>
        <div className={styles.bodyPad}>
          <p className={styles.warn}>
            Copy the secret now. It won&apos;t be shown again. To get a new one later, rotate it.
          </p>
          <p className={styles.dialogBody}>
            {rotated ? (
              <>
                Paste it into the sender&apos;s webhook <strong>Secret</strong> for{" "}
                <strong>{endpointName}</strong> right away. Deliveries signed with the old secret
                now return 401.
              </>
            ) : (
              <>
                In GitHub: Settings → Webhooks → Add webhook. Use the payload URL and secret below,
                content type <strong>application/json</strong>.
              </>
            )}
          </p>

          <div className={styles.field}>
            <label className={styles.label} htmlFor={`${uid}-secret`}>
              Signing secret
            </label>
            <div className={styles.secretRow}>
              <input
                ref={secretRef}
                id={`${uid}-secret`}
                className={`${styles.input} ${styles.secretInput}`}
                value={secret}
                readOnly
                autoComplete="off"
                spellCheck={false}
              />
              <Button
                variant="secondary"
                size="sm"
                onClick={() => copy("secret")}
                aria-label="Copy secret"
              >
                <CopyIcon size={14} aria-hidden="true" /> Copy
              </Button>
            </div>
          </div>

          <div className={styles.field}>
            <label className={styles.label} htmlFor={`${uid}-url`}>
              Payload URL
            </label>
            <div className={styles.secretRow}>
              <input
                id={`${uid}-url`}
                className={`${styles.input} ${styles.secretInput}`}
                value={url}
                readOnly
                spellCheck={false}
              />
              <Button
                variant="secondary"
                size="sm"
                onClick={() => copy("url")}
                aria-label="Copy URL"
              >
                <CopyIcon size={14} aria-hidden="true" /> Copy
              </Button>
            </div>
          </div>
          <span className={styles.copied} aria-live="polite">
            {copied === "secret" ? "Secret copied" : copied === "url" ? "URL copied" : ""}
          </span>
        </div>
        <div className={styles.footer}>
          <Button variant="primary" onClick={onDone}>
            I&apos;ve stored it
          </Button>
        </div>
      </div>
    </div>
  );
}
