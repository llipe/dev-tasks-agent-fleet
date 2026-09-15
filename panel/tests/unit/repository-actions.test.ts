import { describe, expect, it, vi } from "vitest";

/**
 * S-147 (#207) — Add-repository action decision logic (Layer 1, spec §6/§8.4).
 *
 * Tests the PURE core `resolveAddRepository`, which takes injected
 * `getInstallation`/`insert` functions so no live Supabase or Next request
 * context is needed — the same shape as `resolveSignIn` (`app/login/actions.ts`).
 *
 * Load-bearing assertions:
 *   - a malformed `full_name` is rejected with `INVALID_REPOSITORY_FORMAT`
 *     BEFORE either dependency is called (client-side-shaped validation is
 *     re-run server-side, never trusted from the client alone).
 *   - `defaultBranch` defaults to `"main"` when absent/blank.
 *   - `insert` throwing `RepositoryAlreadyExistsError`-shaped (`code:
 *     "REPOSITORY_ALREADY_EXISTS"`) maps to a friendly, non-raw error.
 *   - any other thrown error maps to a generic `DATABASE_ERROR`, never
 *     leaking the raw Postgres detail.
 *   - `getInstallation` failing (config/DB error) also maps to `DATABASE_ERROR`
 *     without ever calling `insert`.
 *   - success returns `{ ok: true, repository }`.
 */

import { resolveAddRepository, type AddRepositoryDeps } from "@/app/(panel)/repositories/actions";
import { REPOSITORY_ALREADY_EXISTS } from "@/lib/supabase/queries";
import { INVALID_REPOSITORY_FORMAT } from "@/lib/domain/repository-input";
import type { RepositoryRow } from "@/lib/supabase/types";

function fakeRepository(overrides: Partial<RepositoryRow> = {}): RepositoryRow {
  return {
    id: "repo-1",
    installation_id: "inst-1",
    github_repo_id: null,
    full_name: "acme/widgets",
    default_branch: "main",
    is_enabled: true,
    metadata: {},
    archived_at: null,
    created_at: "2026-01-01T00:00:00.000Z",
    updated_at: "2026-01-01T00:00:00.000Z",
    ...overrides,
  };
}

function deps(overrides: Partial<AddRepositoryDeps> = {}): AddRepositoryDeps {
  return {
    getInstallation: vi.fn(async () => ({ id: "inst-1" })),
    insert: vi.fn(async (row) => fakeRepository({ full_name: row.fullName })),
    ...overrides,
  };
}

describe("resolveAddRepository — client-shaped validation re-run server-side", () => {
  it("rejects an empty full_name with INVALID_REPOSITORY_FORMAT, never calling a dependency", async () => {
    const d = deps();
    const r = await resolveAddRepository({ fullName: "", defaultBranch: undefined }, d);
    expect(r.ok).toBe(false);
    if (!r.ok) expect(r.code).toBe(INVALID_REPOSITORY_FORMAT);
    expect(d.getInstallation).not.toHaveBeenCalled();
    expect(d.insert).not.toHaveBeenCalled();
  });

  it("rejects a malformed full_name (no slash)", async () => {
    const d = deps();
    const r = await resolveAddRepository({ fullName: "noslash", defaultBranch: undefined }, d);
    expect(r.ok).toBe(false);
    if (!r.ok) expect(r.code).toBe(INVALID_REPOSITORY_FORMAT);
    expect(d.insert).not.toHaveBeenCalled();
  });

  it("rejects a non-string fullName field", async () => {
    const d = deps();
    const r = await resolveAddRepository({ fullName: undefined, defaultBranch: undefined }, d);
    expect(r.ok).toBe(false);
    if (!r.ok) expect(r.code).toBe(INVALID_REPOSITORY_FORMAT);
  });

  it("surfaces a fieldErrors.fullName hint on rejection", async () => {
    const d = deps();
    const r = await resolveAddRepository({ fullName: "bad", defaultBranch: undefined }, d);
    expect(r.ok).toBe(false);
    if (!r.ok) expect(r.fieldErrors?.fullName).toBeTruthy();
  });
});

describe("resolveAddRepository — defaultBranch defaulting", () => {
  it("defaults defaultBranch to 'main' when absent", async () => {
    const insert = vi.fn(async (row: { defaultBranch: string }) =>
      fakeRepository({ default_branch: row.defaultBranch }),
    );
    const d = deps({ insert });
    await resolveAddRepository({ fullName: "acme/widgets", defaultBranch: undefined }, d);
    expect(insert).toHaveBeenCalledWith(expect.objectContaining({ defaultBranch: "main" }));
  });

  it("defaults defaultBranch to 'main' when blank/whitespace", async () => {
    const insert = vi.fn(async (row: { defaultBranch: string }) =>
      fakeRepository({ default_branch: row.defaultBranch }),
    );
    const d = deps({ insert });
    await resolveAddRepository({ fullName: "acme/widgets", defaultBranch: "   " }, d);
    expect(insert).toHaveBeenCalledWith(expect.objectContaining({ defaultBranch: "main" }));
  });

  it("honors an explicit trimmed defaultBranch", async () => {
    const insert = vi.fn(async (row: { defaultBranch: string }) =>
      fakeRepository({ default_branch: row.defaultBranch }),
    );
    const d = deps({ insert });
    await resolveAddRepository({ fullName: "acme/widgets", defaultBranch: "  develop  " }, d);
    expect(insert).toHaveBeenCalledWith(expect.objectContaining({ defaultBranch: "develop" }));
  });
});

describe("resolveAddRepository — success", () => {
  it("returns { ok: true, repository } with the installation id resolved from getInstallation", async () => {
    const insert = vi.fn(async (row: { installationId: string; fullName: string }) =>
      fakeRepository({ installation_id: row.installationId, full_name: row.fullName }),
    );
    const d = deps({ getInstallation: vi.fn(async () => ({ id: "inst-xyz" })), insert });
    const r = await resolveAddRepository({ fullName: "acme/widgets", defaultBranch: undefined }, d);
    expect(r.ok).toBe(true);
    if (r.ok) {
      expect(r.repository.installation_id).toBe("inst-xyz");
      expect(r.repository.full_name).toBe("acme/widgets");
    }
    expect(insert).toHaveBeenCalledWith(
      expect.objectContaining({ installationId: "inst-xyz", fullName: "acme/widgets" }),
    );
  });
});

describe("resolveAddRepository — duplicate rejection (REPOSITORY_ALREADY_EXISTS)", () => {
  it("maps an insert error carrying code REPOSITORY_ALREADY_EXISTS to a friendly, non-raw message", async () => {
    const err = Object.assign(new Error("raw postgres detail — must not leak"), {
      code: REPOSITORY_ALREADY_EXISTS,
    });
    const d = deps({
      insert: vi.fn(async () => {
        throw err;
      }),
    });
    const r = await resolveAddRepository({ fullName: "acme/widgets", defaultBranch: undefined }, d);
    expect(r.ok).toBe(false);
    if (!r.ok) {
      expect(r.code).toBe(REPOSITORY_ALREADY_EXISTS);
      expect(r.message).not.toContain("raw postgres detail");
    }
  });
});

describe("resolveAddRepository — generic failures never leak raw Postgres detail", () => {
  it("maps any other insert error to DATABASE_ERROR", async () => {
    const d = deps({
      insert: vi.fn(async () => {
        throw new Error("connection reset by peer — internal detail");
      }),
    });
    const r = await resolveAddRepository({ fullName: "acme/widgets", defaultBranch: undefined }, d);
    expect(r.ok).toBe(false);
    if (!r.ok) {
      expect(r.code).toBe("DATABASE_ERROR");
      expect(r.message).not.toContain("connection reset");
    }
  });

  it("maps a getInstallation failure to DATABASE_ERROR without calling insert", async () => {
    const insert = vi.fn(async () => fakeRepository());
    const d = deps({
      getInstallation: vi.fn(async () => {
        throw new Error("no installation seeded");
      }),
      insert,
    });
    const r = await resolveAddRepository({ fullName: "acme/widgets", defaultBranch: undefined }, d);
    expect(r.ok).toBe(false);
    if (!r.ok) expect(r.code).toBe("DATABASE_ERROR");
    expect(insert).not.toHaveBeenCalled();
  });
});
