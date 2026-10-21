import { describe, expect, it } from "vitest";
import { requestOrigin } from "@/lib/webhooks/request-origin";

// Layer 1 — S-176: the payload-URL origin shown on /webhooks (display only).

const h = (m: Record<string, string>) => ({ get: (k: string) => m[k] ?? null });

describe("requestOrigin", () => {
  it("uses the forwarded host and proto (Fly)", () => {
    expect(
      requestOrigin(
        h({
          "x-forwarded-host": "dt-agent-fleet-panel.fly.dev",
          "x-forwarded-proto": "https",
          host: "internal:8080",
        }),
      ),
    ).toBe("https://dt-agent-fleet-panel.fly.dev");
  });

  it("falls back to Host, https by default and http for localhost", () => {
    expect(requestOrigin(h({ host: "panel.example" }))).toBe("https://panel.example");
    expect(requestOrigin(h({ host: "localhost:3000" }))).toBe("http://localhost:3000");
  });

  it("takes the first value of a comma-separated forwarded header", () => {
    expect(
      requestOrigin(
        h({ "x-forwarded-host": "a.example, b.example", "x-forwarded-proto": "https, http" }),
      ),
    ).toBe("https://a.example");
  });

  it.each(["evil.example/path", "a b", "<script>", "user@host", ""])(
    "returns '' for an unusable host %j",
    (host) => {
      expect(requestOrigin(h({ host }))).toBe("");
    },
  );

  it("ignores an unknown forwarded proto", () => {
    expect(requestOrigin(h({ host: "panel.example", "x-forwarded-proto": "javascript" }))).toBe(
      "https://panel.example",
    );
  });
});
