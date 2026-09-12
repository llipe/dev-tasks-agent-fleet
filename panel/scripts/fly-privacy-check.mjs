#!/usr/bin/env node
/**
 * Privacy-check parser for the Fly release gate (Story S-115, SR2 / AC6).
 *
 * The panel's only security boundary in v1 is that the Fly app is NOT publicly
 * reachable (no user auth, D16). This module decides — from the machine-
 * readable output of `fly ips list --json` and `fly status --json` — whether
 * the app exposes any PUBLIC IP or PUBLIC service. If it does, the release must
 * fail.
 *
 * The parsing/decision logic lives here (pure, no I/O) so it is unit-testable
 * from fixtures; `scripts/verify-fly-private.sh` supplies the live `fly` output
 * and acts on the verdict. Keeping the parser separate is what lets the test
 * suite OBSERVE the gate failing on a public-IP fixture (the "gate observed
 * failing" evidence required by AC6).
 *
 * A "public" IP is any allocated IP whose type/address is a global/public v4 or
 * v6 address. Fly's private 6PN addresses are in fdaa::/16 and are reported with
 * type "private"; a shared v4 (`type: "shared_v4"`) is also treated as public
 * exposure because it fronts a public service. The gate is deliberately
 * fail-closed: anything it cannot positively classify as private counts as a
 * public exposure.
 */

/** Lower-cased string, or "" for anything non-stringy. */
function s(v) {
  return typeof v === "string" ? v.toLowerCase() : "";
}

/**
 * Is this IP entry a PUBLIC exposure?
 *
 * Public if:
 *   - type is v4 / v6 / shared_v4 / public / global / anycast, OR
 *   - the address is a routable (non-fdaa::) global address.
 * Private only if type is explicitly "private" or the address is in the Fly
 * 6PN range (fdaa:...). Fail-closed: unknown → public.
 */
export function isPublicIp(entry) {
  if (!entry || typeof entry !== "object") return false; // nothing to expose
  const type = s(entry.Type ?? entry.type);
  const addr = s(entry.Address ?? entry.address);

  // Explicitly private: Fly 6PN.
  if (type === "private") return false;
  if (addr.startsWith("fdaa:")) return false;

  // Explicitly public families Fly reports.
  const PUBLIC_TYPES = new Set(["v4", "v6", "shared_v4", "shared", "public", "global", "anycast"]);
  if (PUBLIC_TYPES.has(type)) return true;

  // If there is an address that is not in a private range, treat as public
  // (fail-closed). Covers unlabeled/unknown types carrying a routable address.
  if (addr.length > 0) return true;

  return false;
}

/** Collect the public IP addresses from `fly ips list --json` output. */
export function findPublicIps(ipsJson) {
  const list = Array.isArray(ipsJson) ? ipsJson : [];
  return list
    .filter((e) => isPublicIp(e))
    .map((e) => String(e.Address ?? e.address ?? "(unknown address)"));
}

/**
 * Does `fly status --json` describe any PUBLIC service? A service is public
 * when it has a port/handler bound for external ingress (http/tls handlers on
 * a service with a non-empty `Ports`). A private-only app has no such services.
 * Fail-closed on unrecognized-but-present service ingress.
 */
export function findPublicServices(statusJson) {
  const services =
    statusJson?.Services ?? statusJson?.services ?? statusJson?.Config?.services ?? [];
  const list = Array.isArray(services) ? services : [];
  const publicOnes = [];
  for (const svc of list) {
    if (!svc || typeof svc !== "object") continue;
    const ports = svc.Ports ?? svc.ports ?? [];
    const portList = Array.isArray(ports) ? ports : [];
    // A service with at least one bound external port/handler is public.
    const hasPublicPort = portList.some((p) => {
      const handlers = p?.Handlers ?? p?.handlers ?? [];
      const hasHandler = Array.isArray(handlers) && handlers.length > 0;
      const port = p?.Port ?? p?.port;
      return hasHandler || typeof port === "number";
    });
    if (hasPublicPort) {
      const proto = s(svc.Protocol ?? svc.protocol) || "?";
      publicOnes.push(`${proto} service with ${portList.length} exposed port(s)`);
    }
  }
  return publicOnes;
}

/**
 * The gate verdict. Returns `{ private: boolean, publicIps, publicServices,
 * reasons }`. `private` is true only when there is NO public IP and NO public
 * service.
 */
export function evaluatePrivacy({ ipsJson, statusJson }) {
  const publicIps = findPublicIps(ipsJson);
  const publicServices = findPublicServices(statusJson);
  const reasons = [];
  if (publicIps.length > 0) {
    reasons.push(`Public IP(s) allocated: ${publicIps.join(", ")}`);
  }
  if (publicServices.length > 0) {
    reasons.push(`Public service(s) exposed: ${publicServices.join("; ")}`);
  }
  return {
    private: reasons.length === 0,
    publicIps,
    publicServices,
    reasons,
  };
}

// --- CLI ------------------------------------------------------------------
// Usage: node fly-privacy-check.mjs <ips.json> <status.json>
// Exits 0 if private-only, 1 if any public exposure is found. The shell wrapper
// (verify-fly-private.sh) captures live `fly` output into these files.
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";

function readJsonOrNull(path) {
  if (!path) return null;
  try {
    return JSON.parse(readFileSync(path, "utf8"));
  } catch {
    return null;
  }
}

function mainCli() {
  const [, , ipsPath, statusPath] = process.argv;
  const verdict = evaluatePrivacy({
    ipsJson: readJsonOrNull(ipsPath),
    statusJson: readJsonOrNull(statusPath),
  });
  if (verdict.private) {
    console.log("[fly-privacy] OK — app is private-only (no public IP, no public service).");
    process.exit(0);
  }
  console.error("[fly-privacy] FAIL — the app is publicly exposed. The release is BLOCKED (SR2).");
  for (const r of verdict.reasons) console.error(`  - ${r}`);
  process.exit(1);
}

if (process.argv[1] && fileURLToPath(import.meta.url) === process.argv[1]) {
  mainCli();
}
