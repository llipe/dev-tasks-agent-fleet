# Fidelity Report — S-168 (#313) webhook signature verifier (verifier, Audit Mode)

**Verdict: High fidelity.** All 4 acceptance criteria met. Highest drift impact: **Minor** (two intended deviations from the spec text; both carry over to S-169).

## AC → evidence

| AC | Evidence | Result |
| --- | --- | --- |
| `verifyHmacSignature(rawBody, presented, secret)` recomputes `sha256=` + hex HMAC-SHA256 and compares in constant time | GitHub's published reference vector verifies; `timingSafeEqual` on two 32-byte buffers. A mutant that skips the compare fails 6 tests | Pass |
| Format guard: `sha256=` + valid lowercase hex of the right length | Rejected as `header_malformed`: uppercase hex, `sha1=`, bare hex, base64, ±1 char, a non-hex char, leading/trailing whitespace, comma-joined values (EC-1). A loose-format mutant fails 3 tests | Pass |
| Fails closed on empty secret, missing header, mismatch or wrong length; never throws; never logs secrets | `secret_not_configured`, `header_missing`, `signature_mismatch`; hostile input types never throw; reasons are fixed `[a-z_]` tokens with no secret or digest material | Pass |
| `deliveryDedupKey` returns the header value, or a body hash when the header is absent | Header value, case-insensitive name, body-hash fallback for an absent/empty/over-length header; 200-char cap respected at the boundary (197 accepted, 198 falls back) | Pass |

Test-plan items covered: CT-1 (malformed variants), EC-1, EC-3, EC-4, RT-1 (seed 309001, 2000 iterations; any single-bit flip in the body or digest rejects).

## Drift

| # | Finding | Type | Impact |
| --- | --- | --- | --- |
| 1 | **Raw bytes, not text.** D-W3 and spec §6.1 say to read the body with `request.text()`. That decodes UTF-8 and turns invalid bytes into U+FFFD, so the HMAC would cover different bytes from the ones the sender signed. The verifier takes a `Uint8Array`, and **S-169 must read the body with `request.arrayBuffer()`** (a test proves a non-UTF-8 body verifies). Spec write-back routed to product-engineer. | Intended | Minor |
| 2 | **Namespaced dedup keys.** Keys are `id:<header>` or `body:<sha256>`, so a presented header can never collide with another delivery's body-hash key (tested). The usable header length is therefore 197 characters. | Intended | Minor |

## Gates

- L1 `webhook-signature.test.ts`: 37/37. It was red before the module existed (import failure). Mutation checks: loose format (3 failing), no compare (6 failing), no namespace (4 failing).
- `make validate-js`: pass (1664 tests, lint, format, typecheck, audit).
- `make validate-py`: audit fails on #355 (pre-existing, no Python touched).
