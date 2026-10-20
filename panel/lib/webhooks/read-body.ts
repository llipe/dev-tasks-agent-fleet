/**
 * S-169 (#314) — read a request body as raw bytes with a hard limit (D-W3,
 * EC-29). Lives outside `route.ts` because Next.js rejects non-route exports
 * from route files.
 */

/**
 * Read at most `max` bytes. Returns null when the body is (or declares itself)
 * larger than `max`; an absent body reads as zero bytes.
 */
export async function readBodyWithLimit(request: Request, max: number): Promise<Uint8Array | null> {
  const declared = request.headers.get("content-length");
  if (declared !== null && /^\d+$/.test(declared) && Number(declared) > max) {
    return null;
  }
  if (!request.body) return new Uint8Array(0);

  const reader = request.body.getReader();
  const chunks: Uint8Array[] = [];
  let total = 0;
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    total += value.byteLength;
    if (total > max) {
      await reader.cancel().catch(() => undefined);
      return null;
    }
    chunks.push(value);
  }
  const out = new Uint8Array(total);
  let offset = 0;
  for (const c of chunks) {
    out.set(c, offset);
    offset += c.byteLength;
  }
  return out;
}
