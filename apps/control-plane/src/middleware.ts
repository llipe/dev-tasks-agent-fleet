import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";
import { verifyToken } from "./lib/auth/verify-token";

const CF_ACCESS_TEAM_NAME = process.env["CF_ACCESS_TEAM_NAME"] ?? "";
const CF_ACCESS_AUD = process.env["CF_ACCESS_AUD"] ?? "";

const CF_ACCESS_CERTS_URL = `https://${CF_ACCESS_TEAM_NAME}.cloudflareaccess.com/cdn-cgi/access/certs`;
const CF_ACCESS_ISSUER = `https://${CF_ACCESS_TEAM_NAME}.cloudflareaccess.com`;

export async function middleware(request: NextRequest): Promise<NextResponse> {
  const token = request.headers.get("Cf-Access-Jwt-Assertion") ?? "";

  const result = await verifyToken(token, {
    certsUrl: CF_ACCESS_CERTS_URL,
    issuer: CF_ACCESS_ISSUER,
    audience: CF_ACCESS_AUD,
  });

  if (!result.ok) {
    return NextResponse.json({ error: "unauthorized", reason: result.reason }, { status: 401 });
  }

  const response = NextResponse.next();
  if (result.email) {
    response.headers.set("x-cf-email", result.email);
  }
  return response;
}

export const config = {
  matcher: [
    /*
     * Match all request paths except:
     * - /healthz (health check, no auth)
     * - /_next/static (static files)
     * - /_next/image (image optimization)
     * - /favicon.ico (browser icon)
     */
    "/((?!healthz|_next/static|_next/image|favicon\\.ico).*)",
  ],
};
