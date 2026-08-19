/**
 * Session ID builder.
 *
 * Produces a deterministic, URL-safe identifier for a scheduled agent run.
 * Guarantees a minimum length of 33 characters.
 */

import { createHash } from "node:crypto";

const MIN_LENGTH = 33;

/**
 * Build a deterministic session ID for a scheduled run.
 *
 * Format: `<agent>-<repo-slug>-<timestamp>[-<hash-pad>]`
 * - repo slug: owner/repo → owner-repo
 * - timestamp: YYYYMMDD-HHmmss (UTC)
 * - If the base is shorter than 33 chars, a hash suffix is appended to meet the floor.
 *
 * @param agent - Agent name (e.g., "dep-updater")
 * @param repo - Repository in owner/repo format
 * @param scheduledAt - The scheduled timestamp for this occurrence
 * @returns A string of at least 33 characters, deterministic for the same inputs
 */
export function buildSessionId(agent: string, repo: string, scheduledAt: Date): string {
  const repoSlug = repo.replace(/\//g, "-");
  const ts = formatTimestamp(scheduledAt);

  const base = `${agent}-${repoSlug}-${ts}`;

  if (base.length >= MIN_LENGTH) {
    return base;
  }

  // Pad with a deterministic hash suffix to reach the minimum length
  const hashInput = `${agent}/${repo}/${scheduledAt.toISOString()}`;
  const hash = createHash("sha256").update(hashInput).digest("hex");
  const padNeeded = MIN_LENGTH - base.length;
  // prepend a separator hyphen
  return `${base}-${hash.slice(0, padNeeded - 1)}`;
}

function formatTimestamp(date: Date): string {
  const y = date.getUTCFullYear();
  const m = String(date.getUTCMonth() + 1).padStart(2, "0");
  const d = String(date.getUTCDate()).padStart(2, "0");
  const h = String(date.getUTCHours()).padStart(2, "0");
  const min = String(date.getUTCMinutes()).padStart(2, "0");
  const s = String(date.getUTCSeconds()).padStart(2, "0");
  return `${y}${m}${d}-${h}${min}${s}`;
}
