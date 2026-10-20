import { describe, expect, it } from "vitest";
import { readBodyWithLimit } from "@/lib/webhooks/read-body";

// Layer 1 — S-169 (#314): the byte-limited raw body read (EC-29, D-W3).

function streamOf(chunks: Uint8Array[]): ReadableStream<Uint8Array> {
  return new ReadableStream({
    start(controller) {
      for (const c of chunks) controller.enqueue(c);
      controller.close();
    },
  });
}

function req(body: BodyInit | null, headers: Record<string, string> = {}): Request {
  return new Request("http://x/api/webhooks/t", {
    method: "POST",
    body,
    headers,
    // Required by undici for a streaming body.
    ...(body instanceof ReadableStream ? { duplex: "half" } : {}),
  } as RequestInit);
}

describe("readBodyWithLimit", () => {
  it("returns the exact bytes, including non-UTF-8", async () => {
    const bytes = new Uint8Array([0x7b, 0xff, 0x00, 0x7d]);
    expect(await readBodyWithLimit(req(bytes), 10)).toEqual(bytes);
  });

  it("accepts a body of exactly the cap and rejects cap + 1", async () => {
    expect((await readBodyWithLimit(req(new Uint8Array(8)), 8))?.byteLength).toBe(8);
    expect(await readBodyWithLimit(req(new Uint8Array(9)), 8)).toBeNull();
  });

  it("refuses up front when Content-Length declares more than the cap", async () => {
    const r = req(streamOf([new Uint8Array(1)]), { "content-length": "999999999" });
    expect(await readBodyWithLimit(r, 8)).toBeNull();
  });

  it("enforces the cap on a streamed body with no Content-Length", async () => {
    const r = req(streamOf([new Uint8Array(5), new Uint8Array(5)]));
    expect(r.headers.get("content-length")).toBeNull();
    expect(await readBodyWithLimit(r, 8)).toBeNull();
  });

  it("enforces the cap even when Content-Length understates the body", async () => {
    const r = req(streamOf([new Uint8Array(5), new Uint8Array(5)]), { "content-length": "4" });
    expect(await readBodyWithLimit(r, 8)).toBeNull();
  });

  it("joins multiple chunks in order", async () => {
    const r = req(streamOf([new Uint8Array([1, 2]), new Uint8Array([3])]));
    expect(await readBodyWithLimit(r, 8)).toEqual(new Uint8Array([1, 2, 3]));
  });

  it("reads an absent body as zero bytes", async () => {
    expect((await readBodyWithLimit(req(null), 8))?.byteLength).toBe(0);
  });
});
