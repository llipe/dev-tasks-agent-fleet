import { describe, expect, it } from "vitest";

import {
  evaluatePrivacy,
  findPublicIps,
  findPublicServices,
  isPublicIp,
} from "@/scripts/fly-privacy-check.mjs";

/**
 * Privacy-check parser (Story S-115, SR2 / AC6).
 *
 * The panel's only v1 security boundary is that the Fly app is not publicly
 * reachable (no user auth, D16). This suite is the "gate observed failing"
 * evidence at unit level: a fixture with a public IP or a public service MUST
 * make the parser report a NON-private verdict (which the release script turns
 * into a non-zero exit), and a private-only allocation MUST pass.
 *
 * Fixtures mirror the shape of `fly ips list --json` and `fly status --json`.
 */

// A public IPv4 allocation (fly ips allocate-v4).
const IPS_PUBLIC_V4 = [
  { Address: "168.220.90.10", Type: "v4", Region: "iad" },
  { Address: "fdaa:0:1234::2", Type: "private", Region: "global" },
];

// A shared public v4 (fronts a public service).
const IPS_SHARED_V4 = [{ Address: "66.241.125.1", Type: "shared_v4", Region: "global" }];

// A public IPv6 allocation.
const IPS_PUBLIC_V6 = [{ Address: "2a09:8280:1::abcd", Type: "v6", Region: "iad" }];

// Private-only: just the Fly 6PN address.
const IPS_PRIVATE_ONLY = [{ Address: "fdaa:0:1234::3", Type: "private", Region: "global" }];

// No IPs allocated at all — also private-only.
const IPS_NONE: unknown[] = [];

// A public HTTP service (has bound ports with handlers).
const STATUS_PUBLIC_SERVICE = {
  Services: [
    {
      Protocol: "tcp",
      Ports: [
        { Port: 443, Handlers: ["tls", "http"] },
        { Port: 80, Handlers: ["http"] },
      ],
    },
  ],
};

// No public services (private-only app).
const STATUS_NO_SERVICE = { Services: [] };

describe("isPublicIp", () => {
  it("classifies a public v4 as public", () => {
    expect(isPublicIp({ Address: "168.220.90.10", Type: "v4" })).toBe(true);
  });

  it("classifies a public v6 as public", () => {
    expect(isPublicIp({ Address: "2a09:8280:1::1", Type: "v6" })).toBe(true);
  });

  it("classifies a shared_v4 as public exposure", () => {
    expect(isPublicIp({ Address: "66.241.125.1", Type: "shared_v4" })).toBe(true);
  });

  it("classifies an explicit private (6PN) IP as NOT public", () => {
    expect(isPublicIp({ Address: "fdaa:0:1234::2", Type: "private" })).toBe(false);
  });

  it("classifies an fdaa:: address as private even if the type label is missing", () => {
    expect(isPublicIp({ Address: "fdaa:0:9999::7" })).toBe(false);
  });

  it("is fail-closed: an unknown type carrying a routable address counts as public", () => {
    expect(isPublicIp({ Address: "203.0.113.9", Type: "mystery" })).toBe(true);
  });

  it("treats a malformed/empty entry as no exposure", () => {
    expect(isPublicIp(null)).toBe(false);
    expect(isPublicIp({})).toBe(false);
  });
});

describe("findPublicIps", () => {
  it("finds the public v4 and ignores the 6PN address", () => {
    expect(findPublicIps(IPS_PUBLIC_V4)).toEqual(["168.220.90.10"]);
  });

  it("returns empty for a private-only allocation", () => {
    expect(findPublicIps(IPS_PRIVATE_ONLY)).toEqual([]);
  });

  it("returns empty when no IPs are allocated", () => {
    expect(findPublicIps(IPS_NONE)).toEqual([]);
  });

  it("tolerates a non-array input (fail-safe to empty)", () => {
    expect(findPublicIps(null)).toEqual([]);
    expect(findPublicIps(undefined)).toEqual([]);
  });
});

describe("findPublicServices", () => {
  it("detects a public HTTP/TLS service", () => {
    expect(findPublicServices(STATUS_PUBLIC_SERVICE).length).toBe(1);
  });

  it("returns empty when there are no services", () => {
    expect(findPublicServices(STATUS_NO_SERVICE)).toEqual([]);
  });

  it("returns empty for missing/garbage status", () => {
    expect(findPublicServices(null)).toEqual([]);
    expect(findPublicServices({})).toEqual([]);
  });
});

describe("evaluatePrivacy — the release-gate verdict", () => {
  it("FAILS the release when a public v4 IP is allocated (gate observed failing)", () => {
    const v = evaluatePrivacy({ ipsJson: IPS_PUBLIC_V4, statusJson: STATUS_NO_SERVICE });
    expect(v.private).toBe(false);
    expect(v.publicIps).toEqual(["168.220.90.10"]);
    expect(v.reasons.join(" ")).toMatch(/Public IP/i);
  });

  it("FAILS the release when a shared public v4 is allocated", () => {
    const v = evaluatePrivacy({ ipsJson: IPS_SHARED_V4, statusJson: STATUS_NO_SERVICE });
    expect(v.private).toBe(false);
  });

  it("FAILS the release when a public v6 IP is allocated", () => {
    const v = evaluatePrivacy({ ipsJson: IPS_PUBLIC_V6, statusJson: STATUS_NO_SERVICE });
    expect(v.private).toBe(false);
  });

  it("FAILS the release when a public service is exposed even with no public IP", () => {
    const v = evaluatePrivacy({ ipsJson: IPS_PRIVATE_ONLY, statusJson: STATUS_PUBLIC_SERVICE });
    expect(v.private).toBe(false);
    expect(v.reasons.join(" ")).toMatch(/Public service/i);
  });

  it("PASSES for a private-only allocation with no public service", () => {
    const v = evaluatePrivacy({ ipsJson: IPS_PRIVATE_ONLY, statusJson: STATUS_NO_SERVICE });
    expect(v.private).toBe(true);
    expect(v.reasons).toEqual([]);
  });

  it("PASSES when no IPs and no services exist at all", () => {
    const v = evaluatePrivacy({ ipsJson: IPS_NONE, statusJson: STATUS_NO_SERVICE });
    expect(v.private).toBe(true);
  });

  it("reports BOTH reasons when a public IP and a public service coexist", () => {
    const v = evaluatePrivacy({ ipsJson: IPS_PUBLIC_V4, statusJson: STATUS_PUBLIC_SERVICE });
    expect(v.private).toBe(false);
    expect(v.reasons.length).toBe(2);
  });
});
