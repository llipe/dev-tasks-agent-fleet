/**
 * Run panel utility helpers — S-021.
 *
 * Pure functions for:
 * - Session ID truncation (first 8 + "..." + last 5)
 * - Timeline bar geometry (width%, left offset%)
 * - Log line parsing (timestamp + message extraction)
 */

import type { TimelineSpan } from "@/server/runs/span-to-run-mapper.js";

/**
 * Truncate a session_id for display.
 *
 * Rules:
 * - Input: "dep-updater__myorg-myrepo__20250127T100000Z"
 * - Output: "dep-upda...0000Z" (first 8 + "..." + last 5)
 * - If input length <= 16, return as-is (no truncation needed)
 * - Full value available via title attribute and copy payload
 */
export function truncateSessionId(sessionId: string): string {
  if (sessionId.length <= 16) return sessionId;
  const first = sessionId.slice(0, 8);
  const last = sessionId.slice(-5);
  return `${first}...${last}`;
}

/**
 * Bar geometry for a single span in the timeline.
 *
 * Returns CSS-ready percentage values for width and left offset,
 * relative to the root span's duration and start time.
 *
 * Rules:
 * - Root duration = reference (100%)
 * - Child width% = (childDurationMs / rootDurationMs) * 100
 * - Child left offset% = ((childStart - rootStart) / rootDurationMs) * 100
 * - Minimum visible width: 2px equivalent (returned as minWidth flag)
 */
export interface BarGeometry {
  /** Width as a percentage of root duration (0-100) */
  widthPercent: number;
  /** Left offset as a percentage of root duration (0-100) */
  leftPercent: number;
  /** Whether the bar needs a minimum width override (< 1%) */
  needsMinWidth: boolean;
}

export function computeBarGeometry(
  span: TimelineSpan,
  rootStartMs: number,
  rootDurationMs: number,
): BarGeometry {
  if (rootDurationMs <= 0) {
    return { widthPercent: 100, leftPercent: 0, needsMinWidth: false };
  }

  const spanStartMs = parseStartTime(span.startTime);
  const widthPercent = (span.durationMs / rootDurationMs) * 100;
  const leftPercent = ((spanStartMs - rootStartMs) / rootDurationMs) * 100;

  // Clamp values to [0, 100]
  const clampedWidth = Math.max(0, Math.min(100, widthPercent));
  const clampedLeft = Math.max(0, Math.min(100, leftPercent));

  return {
    widthPercent: clampedWidth,
    leftPercent: clampedLeft,
    needsMinWidth: clampedWidth < 1,
  };
}

/**
 * Parse a start time string (ISO or unix nano) into milliseconds since epoch.
 */
export function parseStartTime(startTime: string): number {
  if (!startTime) return 0;

  // Try ISO parse first
  const isoMs = Date.parse(startTime);
  if (!isNaN(isoMs)) return isoMs;

  // Try as nanoseconds (large number string)
  const ns = parseFloat(startTime);
  if (!isNaN(ns) && ns > 1e15) {
    return Math.floor(ns / 1_000_000);
  }

  return 0;
}

/**
 * Parsed log line with timestamp and message.
 */
export interface ParsedLogLine {
  timestamp: string;
  message: string;
  raw: string;
}

/**
 * Parse a raw log line into structured parts.
 *
 * Handles two formats:
 * 1. JSON structured logs: `{"timestamp": "...", "message": "...", ...}`
 * 2. Plain text with ISO timestamp prefix: `2025-01-27T10:00:00.000Z message text`
 *
 * Falls back to raw line as message if parsing fails.
 */
export function parseLogLine(raw: string): ParsedLogLine {
  const trimmed = raw.trim();
  if (!trimmed) {
    return { timestamp: "", message: "", raw };
  }

  // Try JSON parse first
  if (trimmed.startsWith("{")) {
    try {
      const parsed = JSON.parse(trimmed) as Record<string, unknown>;
      const timestamp = String(parsed["timestamp"] ?? parsed["time"] ?? parsed["ts"] ?? "");
      const message = String(parsed["message"] ?? parsed["msg"] ?? parsed["log"] ?? trimmed);
      return { timestamp, message, raw };
    } catch {
      // Fall through to plain text
    }
  }

  // Try ISO timestamp prefix (at least 20 chars like 2025-01-27T10:00:00Z)
  const isoMatch = trimmed.match(/^(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z?)\s+(.*)$/);
  if (isoMatch && isoMatch[1] && isoMatch[2]) {
    return { timestamp: isoMatch[1], message: isoMatch[2], raw };
  }

  // Fallback: entire line is the message
  return { timestamp: "", message: trimmed, raw };
}

/**
 * Process an array of raw log lines into parsed log lines.
 */
export function parseLogLines(lines: string[]): ParsedLogLine[] {
  return lines.map(parseLogLine);
}

/**
 * Compute timeline data from spans: find root, compute geometry for all spans.
 */
export interface TimelineBarData {
  span: TimelineSpan;
  geometry: BarGeometry;
  depth: number;
}

export function computeTimelineLayout(spans: TimelineSpan[]): TimelineBarData[] {
  if (spans.length === 0) return [];

  // Find root span
  const root = spans.find((s) => s.isRoot);
  if (!root) {
    // No explicit root — use first span as reference
    return spans.map((span) => ({
      span,
      geometry: { widthPercent: 100, leftPercent: 0, needsMinWidth: false },
      depth: 0,
    }));
  }

  const rootStartMs = parseStartTime(root.startTime);
  const rootDurationMs = root.durationMs;

  return spans.map((span) => ({
    span,
    geometry: computeBarGeometry(span, rootStartMs, rootDurationMs),
    depth: span.isRoot ? 0 : 1,
  }));
}
