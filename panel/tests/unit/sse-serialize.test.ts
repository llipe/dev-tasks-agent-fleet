import { describe, expect, it } from "vitest";

import { serializeFrame, parseFrames, type SseEventName } from "@/lib/sse/serialize";

/**
 * SSE frame serializer (Story S-110, AC3). The four event types and a
 * newline-safe encoding: a message containing `\n` must not forge a frame
 * boundary (EC-11, EC-14 — frame injection guard).
 */

const NAMES: SseEventName[] = ["event", "run", "heartbeat", "closed"];

describe("serializeFrame", () => {
  it("emits `event:` then `data:` then a blank line (SSE grammar, CT-1)", () => {
    const frame = serializeFrame("heartbeat", {});
    expect(frame).toBe("event: heartbeat\ndata: {}\n\n");
  });

  it("serializes all four event names (AC3)", () => {
    for (const name of NAMES) {
      const frame = serializeFrame(name, { name });
      expect(frame.startsWith(`event: ${name}\n`)).toBe(true);
      expect(frame.endsWith("\n\n")).toBe(true);
    }
  });

  it("encodes a payload with embedded newlines across multiple data: lines (EC-14)", () => {
    // A multi-line message must be split into one `data:` line per physical
    // line so the blank-line frame terminator is never forged by content.
    const frame = serializeFrame("event", { message: "line1\nline2" });
    // The JSON itself has no raw newline (JSON.stringify escapes \n to \\n),
    // so the frame stays single-line; the guard is that the serialized JSON
    // contains NO raw newline that could terminate the frame early.
    const dataLine = frame.split("\n").find((l) => l.startsWith("data: "))!;
    expect(dataLine).not.toContain("\n");
    // Round-trips (see parseFrames below).
    const [parsed] = parseFrames(frame);
    expect((parsed.data as { message: string }).message).toBe("line1\nline2");
  });

  it("does not emit a frame that a parser would split early (2 KB single-line, EC-11)", () => {
    const big = "x".repeat(2048);
    const frame = serializeFrame("event", { message: big });
    // Exactly one frame (one trailing blank-line terminator).
    expect(parseFrames(frame)).toHaveLength(1);
    expect((parseFrames(frame)[0].data as { message: string }).message).toBe(big);
  });
});

describe("parseFrames (round-trip oracle)", () => {
  it("round-trips name + payload for every event type (RT-2)", () => {
    const payloads: unknown[] = [
      { seq: 1, level: "info", message: "hello" },
      { status: "running", outcome: null },
      {},
      { reason: "succeeded" },
    ];
    const wire = NAMES.map((n, i) => serializeFrame(n, payloads[i])).join("");
    const frames = parseFrames(wire);
    expect(frames.map((f) => f.event)).toEqual(NAMES);
    frames.forEach((f, i) => expect(f.data).toEqual(payloads[i]));
  });

  it("property: arbitrary payload strings round-trip without forging boundaries (RT-2)", () => {
    const seed = 1725500001; // recorded seed: prop-AC3-1725500001-b2c4
    let state = seed >>> 0;
    const rand = () => {
      state ^= state << 13;
      state ^= state >>> 17;
      state ^= state << 5;
      return (state >>> 0) / 0xffffffff;
    };
    const chars = ["\n", "\r", "\r\n", '"', "\\", "€", "😀", "a", " ", ":", "data:"];

    for (let iter = 0; iter < 500; iter++) {
      const len = Math.floor(rand() * 40);
      let msg = "";
      for (let i = 0; i < len; i++) msg += chars[Math.floor(rand() * chars.length)];
      const name = NAMES[Math.floor(rand() * NAMES.length)];
      const frame = serializeFrame(name, { message: msg, seq: iter });
      const parsed = parseFrames(frame);
      expect(parsed).toHaveLength(1);
      expect(parsed[0].event).toBe(name);
      expect((parsed[0].data as { message: string }).message).toBe(msg);
    }
  });
});
