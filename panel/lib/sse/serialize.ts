/**
 * SSE frame serializer (Story S-110, AC3) — pure and newline-safe.
 *
 * The relay emits exactly four event types over `text/event-stream`:
 *  - `event`     — one `run_events` row (a new log line)
 *  - `run`       — the run row changed (`{ status, outcome, finished_at, ... }`)
 *  - `heartbeat` — `{}` every 15s, so an intermediary does not idle the
 *                  connection out
 *  - `closed`    — `{ reason }` when the run reaches a terminal state; the
 *                  client stops reconnecting on this
 *
 * SSE frame grammar: one or more `field: value` lines, terminated by a blank
 * line. A payload is JSON-encoded; `JSON.stringify` escapes control characters
 * (including `\n` and `\r`) so the encoded value can never contain a raw
 * newline that would forge the blank-line frame terminator (EC-11, EC-14).
 * `parseFrames` is the inverse, used as the round-trip oracle in tests and by
 * any server-side consumer that needs to read its own output back.
 */

export type SseEventName = "event" | "run" | "heartbeat" | "closed";

export interface SseFrame {
  event: SseEventName;
  data: unknown;
}

/**
 * Serialize one SSE frame. The payload is JSON on a single `data:` line; if a
 * caller ever passes a value whose JSON somehow contains a newline (it cannot
 * via `JSON.stringify`, but the split is defensive), each physical line is
 * emitted as its own `data:` line, which the SSE spec concatenates with `\n`.
 */
export function serializeFrame(event: SseEventName, data: unknown): string {
  const json = JSON.stringify(data ?? null);
  const dataLines = json.split("\n").map((line) => `data: ${line}`);
  return `event: ${event}\n${dataLines.join("\n")}\n\n`;
}

/**
 * Parse a wire string of concatenated SSE frames back into structured frames.
 * Frames are separated by a blank line; `data:` lines are concatenated with
 * `\n` (SSE spec) before JSON-parsing. Unknown event names are ignored.
 */
export function parseFrames(wire: string): SseFrame[] {
  const frames: SseFrame[] = [];
  // Normalize CRLF, then split on the blank-line frame terminator.
  const blocks = wire.replace(/\r\n/g, "\n").split("\n\n");
  for (const block of blocks) {
    if (block.trim() === "") continue;
    let event: string | null = null;
    const dataLines: string[] = [];
    for (const line of block.split("\n")) {
      if (line.startsWith("event: ")) {
        event = line.slice("event: ".length);
      } else if (line.startsWith("data: ")) {
        dataLines.push(line.slice("data: ".length));
      }
    }
    if (event === null) continue;
    if (event !== "event" && event !== "run" && event !== "heartbeat" && event !== "closed") {
      continue;
    }
    const raw = dataLines.join("\n");
    frames.push({ event, data: raw === "" ? null : JSON.parse(raw) });
  }
  return frames;
}
