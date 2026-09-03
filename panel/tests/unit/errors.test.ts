import { describe, expect, it } from "vitest";
import { DatabaseError, DATABASE_ERROR, unwrap } from "@/lib/supabase/errors";

// Layer 1 unit coverage for the DATABASE_ERROR shape (S-104 / issue #117,
// EC-9, spec §13). The contract: any PostgREST failure surfaces as a
// DatabaseError (500, stable code), the Postgres error code + raw detail are
// captured for the SERVER LOG ONLY (logDetail / pgCode), and the client-safe
// `message` names only the operation — never the Postgres detail. On an app
// with no auth in front of it (D16), leaking schema/privilege detail to a
// client is the risk this guards.

describe("DatabaseError shape (EC-9)", () => {
  it("carries the stable code and 500 status", () => {
    const e = new DatabaseError("getAgentBySlug");
    expect(e.code).toBe(DATABASE_ERROR);
    expect(e.status).toBe(500);
    expect(e).toBeInstanceOf(Error);
    expect(e.name).toBe("DatabaseError");
  });

  it("client-safe message names the operation but not the Postgres detail", () => {
    const e = new DatabaseError("getRunById", {
      code: "42501",
      message: "permission denied for table runs",
      details: "role anon lacks SELECT",
    });
    // message is what a client could see — must not contain the pg specifics.
    expect(e.message).toContain("getRunById");
    expect(e.message).not.toContain("42501");
    expect(e.message).not.toContain("permission denied");
    expect(e.message).not.toContain("anon");
  });

  it("captures the Postgres code and full detail for the server log only", () => {
    const e = new DatabaseError("getRunEvents", {
      code: "42501",
      message: "permission denied for table run_events",
      details: "insufficient privilege",
    });
    expect(e.pgCode).toBe("42501");
    // logDetail is the server-log field; it MAY contain the pg specifics.
    expect(e.logDetail).toContain("operation=getRunEvents");
    expect(e.logDetail).toContain("pgCode=42501");
    expect(e.logDetail).toContain("permission denied for table run_events");
    expect(e.logDetail).toContain("insufficient privilege");
  });

  it("handles an undefined cause without throwing", () => {
    const e = new DatabaseError("getEnabledAgents");
    expect(e.pgCode).toBeUndefined();
    expect(e.logDetail).toBe("operation=getEnabledAgents");
  });

  it("handles a non-shaped cause (e.g. a plain string) gracefully", () => {
    // The cause is typed `unknown`; a value without code/message/details fields
    // must not crash logDetail assembly.
    const e = new DatabaseError("getRunSteps", "some network blip");
    expect(e.pgCode).toBeUndefined();
    expect(e.logDetail).toBe("operation=getRunSteps");
  });
});

describe("unwrap (EC-9)", () => {
  it("returns data when there is no error", () => {
    expect(unwrap("op", { data: [{ id: 1 }], error: null })).toEqual([{ id: 1 }]);
  });

  it("throws DatabaseError when the result carries an error", () => {
    expect(() =>
      unwrap("getEnabledAgents", { data: null, error: { code: "42501", message: "denied" } }),
    ).toThrow(DatabaseError);
  });

  it("the thrown error carries the operation and pg code for the log, not the response", () => {
    try {
      unwrap("getAgentBySlug", {
        data: null,
        error: { code: "08006", message: "connection failed" },
      });
      expect.unreachable("should have thrown");
    } catch (err) {
      const e = err as DatabaseError;
      expect(e.code).toBe(DATABASE_ERROR);
      expect(e.pgCode).toBe("08006");
      expect(e.message).not.toContain("08006");
      expect(e.logDetail).toContain("pgCode=08006");
    }
  });
});
