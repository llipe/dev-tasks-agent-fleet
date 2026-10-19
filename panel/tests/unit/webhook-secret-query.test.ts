import { describe, expect, it, vi } from "vitest";
import type { SupabaseClient } from "@supabase/supabase-js";
import { getEndpointSecret } from "@/lib/supabase/queries";
import { DatabaseError } from "@/lib/supabase/errors";

// Layer 1 — S-166 (#310) task 2.4: the panel's only read path for an endpoint
// signing secret. It calls the service_role-only RPC (never a table select) and
// fails closed: no secret, an unexpected shape, or an error never yields a value
// the inbound route could verify against.

function clientReturning(result: { data: unknown; error: unknown }): {
  client: SupabaseClient;
  rpc: ReturnType<typeof vi.fn>;
} {
  const rpc = vi.fn().mockResolvedValue(result);
  return { client: { rpc } as unknown as SupabaseClient, rpc };
}

describe("getEndpointSecret", () => {
  it("calls the webhook_endpoint_secret RPC with the endpoint id", async () => {
    const { client, rpc } = clientReturning({ data: "s3cret", error: null });
    await expect(getEndpointSecret(client, "ep-1")).resolves.toBe("s3cret");
    expect(rpc).toHaveBeenCalledWith("webhook_endpoint_secret", { p_endpoint_id: "ep-1" });
  });

  it.each([
    ["null", null],
    ["an empty string", ""],
    ["a non-string", { secret: "x" }],
  ])("returns null when the RPC yields %s (route fails closed)", async (_label, data) => {
    const { client } = clientReturning({ data, error: null });
    await expect(getEndpointSecret(client, "ep-1")).resolves.toBeNull();
  });

  it("throws a client-safe DatabaseError on an RPC error", async () => {
    const { client } = clientReturning({
      data: null,
      error: { code: "42501", message: "permission denied for function webhook_endpoint_secret" },
    });
    const err = await getEndpointSecret(client, "ep-1").catch((e: unknown) => e);
    expect(err).toBeInstanceOf(DatabaseError);
    expect((err as Error).message).not.toMatch(/permission denied/);
  });
});
