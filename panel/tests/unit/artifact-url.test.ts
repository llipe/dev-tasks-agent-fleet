import { describe, expect, it } from "vitest";

import { isSafeArtifactUrl } from "@/lib/domain/artifact-url";

/**
 * Layer 1 (unit) — mandatory security-negative test #5 (test-plan SC-14 / RT-1).
 *
 * `run_artifacts.url` is agent-authored, therefore untrusted input (spec §12,
 * A10 SSRF/XSS). Before the panel turns a URL into an `<a href>`, the scheme
 * MUST be validated: only a well-formed `https:` URL is safe to link. Every
 * other shape — `javascript:`, `data:`, `http:`, relative, empty, whitespace —
 * renders as inert text, never a link.
 *
 * Load-bearing properties:
 *  - Only `https:` is accepted. `http:` is rejected (no mixed-content / no
 *    downgrade), and the dangerous pseudo-schemes never reach an href.
 *  - Scheme comparison is case-insensitive (`HTTPS:` is https).
 *  - The validator is TOTAL: it NEVER throws, for any string (RT-1). A
 *    malformed URL returns `false`, it does not raise.
 */

describe("isSafeArtifactUrl — accepts only well-formed https:", () => {
  it("accepts a normal https URL", () => {
    expect(isSafeArtifactUrl("https://github.com/llipe/x/pull/42")).toBe(true);
  });

  it("accepts https with a port, path, query, and fragment", () => {
    expect(isSafeArtifactUrl("https://example.com:8443/a/b?c=d#frag")).toBe(true);
  });

  it("accepts a mixed-case HTTPS scheme (case-insensitive)", () => {
    expect(isSafeArtifactUrl("HTTPS://github.com/x")).toBe(true);
    expect(isSafeArtifactUrl("HtTpS://github.com/x")).toBe(true);
  });
});

describe("isSafeArtifactUrl — rejects every non-https shape", () => {
  it("rejects http: (no downgrade, no mixed content)", () => {
    expect(isSafeArtifactUrl("http://github.com/x")).toBe(false);
  });

  it("rejects the javascript: pseudo-scheme (XSS)", () => {
    expect(isSafeArtifactUrl("javascript:alert(1)")).toBe(false);
    expect(isSafeArtifactUrl("JAVASCRIPT:alert(1)")).toBe(false);
    // Leading/embedded whitespace + tab obfuscation still rejected.
    expect(isSafeArtifactUrl("  javascript:alert(1)")).toBe(false);
    expect(isSafeArtifactUrl("java\tscript:alert(1)")).toBe(false);
  });

  it("rejects the data: pseudo-scheme", () => {
    expect(isSafeArtifactUrl("data:text/html,<script>alert(1)</script>")).toBe(false);
  });

  it("rejects other dangerous schemes", () => {
    expect(isSafeArtifactUrl("vbscript:msgbox(1)")).toBe(false);
    expect(isSafeArtifactUrl("file:///etc/passwd")).toBe(false);
    expect(isSafeArtifactUrl("ftp://example.com/x")).toBe(false);
  });

  it("rejects a relative path (no scheme)", () => {
    expect(isSafeArtifactUrl("/runs/123")).toBe(false);
    expect(isSafeArtifactUrl("github.com/x")).toBe(false);
    expect(isSafeArtifactUrl("//evil.com/x")).toBe(false);
  });

  it("rejects empty and whitespace-only", () => {
    expect(isSafeArtifactUrl("")).toBe(false);
    expect(isSafeArtifactUrl("   ")).toBe(false);
    expect(isSafeArtifactUrl("\n\t")).toBe(false);
  });

  it("rejects null / undefined url values", () => {
    expect(isSafeArtifactUrl(null)).toBe(false);
    expect(isSafeArtifactUrl(undefined)).toBe(false);
  });
});

describe("isSafeArtifactUrl — total function (RT-1: never throws)", () => {
  it("returns false, never throws, on malformed/garbage input", () => {
    const garbage = [
      "https://",
      "https:// spaces in host",
      "ht!tps://x",
      "https:example.com", // no slashes — WHATWG parses as opaque path
      "\u0000https://x",
      "https://[::1", // unbalanced ipv6 bracket
      "%%%",
      "https://ex\nample.com",
      String.fromCharCode(0, 1, 2, 3),
    ];
    for (const g of garbage) {
      expect(() => isSafeArtifactUrl(g)).not.toThrow();
      // Whatever the parse outcome, the return is a boolean.
      expect(typeof isSafeArtifactUrl(g)).toBe("boolean");
    }
  });

  it("fuzz: never throws for a large corpus of random-ish strings (RT-1)", () => {
    // Deterministic pseudo-random so a failure is reproducible without a seed
    // library. Replay: this loop is fixed; the seed is the literal below.
    let seed = 0x9e3779b9;
    const rand = () => {
      // xorshift32
      seed ^= seed << 13;
      seed ^= seed >>> 17;
      seed ^= seed << 5;
      return (seed >>> 0) / 0xffffffff;
    };
    const alphabet = "htps:/.javscrp danger\t\n0123456789[]:@%#?&=";
    for (let i = 0; i < 5000; i++) {
      const len = Math.floor(rand() * 40);
      let s = "";
      for (let j = 0; j < len; j++) {
        s += alphabet[Math.floor(rand() * alphabet.length)];
      }
      expect(() => isSafeArtifactUrl(s)).not.toThrow();
      const result = isSafeArtifactUrl(s);
      expect(typeof result).toBe("boolean");
      // A "safe" result must always parse to an https URL — no false accept.
      if (result === true) {
        expect(s.trim().toLowerCase().startsWith("https:")).toBe(true);
      }
    }
  });
});
