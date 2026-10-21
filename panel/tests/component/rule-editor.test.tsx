import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

/**
 * S-177 (#322) — rule editor component suite (Layer 2, jsdom), DESIGN.md §5.9.4.
 *  - ordered rules, numbered, with the default rule in its own section and the
 *    first-match note visible;
 *  - move up/down sends the full new order; edges are disabled;
 *  - add/edit/delete/enable; condition rows; agent switch rebinds the params form;
 *  - server validation errors render inline and nothing closes.
 */

const actions = {
  saveRuleAction: vi.fn(),
  deleteRuleAction: vi.fn(),
  toggleRuleAction: vi.fn(),
  reorderRulesAction: vi.fn(),
};
vi.mock("@/app/(panel)/webhooks/actions", () => ({
  saveRuleAction: (...a: unknown[]) => actions.saveRuleAction(...a),
  deleteRuleAction: (...a: unknown[]) => actions.deleteRuleAction(...a),
  toggleRuleAction: (...a: unknown[]) => actions.toggleRuleAction(...a),
  reorderRulesAction: (...a: unknown[]) => actions.reorderRulesAction(...a),
}));
const refresh = vi.fn();
vi.mock("next/navigation", () => ({ useRouter: () => ({ refresh }) }));

import { RuleEditor } from "@/components/webhooks/RuleEditor";
import type { AgentOption, RepositoryOption } from "@/components/schedules/ScheduleDialog";
import type { WebhookRuleRow } from "@/lib/supabase/types";

const EP = "88888888-8888-4888-8888-888888888888";
const SA = "11111111-1111-4111-8111-111111111111";
const DU = "22222222-2222-4222-8222-222222222222";
const REPO = "44444444-4444-4444-8444-444444444444";

const agents: AgentOption[] = [
  {
    id: SA,
    slug: "security-analyst",
    name: "Security Analyst",
    isEnabled: true,
    requiresRepository: true,
    paramsSchema: {
      type: "object",
      required: ["mode"],
      properties: {
        mode: { type: "string", enum: ["audit_only", "fix"], default: "audit_only", title: "mode" },
        pr_number: { type: "integer", title: "pr_number" },
      },
    },
    defaultParams: {},
  },
  {
    id: DU,
    slug: "dependency-update",
    name: "Dependency Update",
    isEnabled: true,
    requiresRepository: true,
    paramsSchema: {
      type: "object",
      properties: { fix_mode: { type: "string", title: "fix_mode" } },
    },
    defaultParams: {},
  },
];
const repositories: RepositoryOption[] = [
  { id: REPO, fullName: "llipe/app", defaultBranch: "main" },
];

function rule(id: string, position: number, over: Partial<WebhookRuleRow> = {}): WebhookRuleRow {
  return {
    id,
    endpoint_id: EP,
    position,
    name: `rule ${id}`,
    event_types: ["issue_comment"],
    conditions: [{ field: "comment.body", op: "contains", value: "/audit" }],
    is_default: false,
    agent_id: SA,
    repo_mode: "payload_field",
    repository_id: null,
    repo_payload_field: "repository.full_name",
    params: { static: { mode: "audit_only" }, from_payload: { pr_number: "issue.number" } },
    consecutive_failures: 0,
    auto_disable_threshold: 3,
    notify_on_success: false,
    is_enabled: true,
    created_at: "2026-10-20T10:00:00Z",
    updated_at: "2026-10-20T10:00:00Z",
    ...over,
  };
}

const A = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa";
const B = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb";
const C = "cccccccc-cccc-4ccc-8ccc-cccccccccccc";
const D = "dddddddd-dddd-4ddd-8ddd-dddddddddddd";

function renderEditor(rules: WebhookRuleRow[]) {
  return render(
    <RuleEditor
      endpoint={{ id: EP, eventAllowlist: ["issue_comment", "pull_request"] }}
      rules={rules}
      agents={agents}
      repositories={repositories}
    />,
  );
}

afterEach(() => {
  for (const f of Object.values(actions)) f.mockReset();
  refresh.mockReset();
});

describe("ordered list", () => {
  it("numbers rules in order, shows the default separately, and states first-match", () => {
    renderEditor([
      rule(B, 1),
      rule(A, 0),
      rule(D, 2, { is_default: true, name: "fallback", event_types: [], conditions: [] }),
    ]);
    expect(screen.getByText(/first matching rule wins/i)).toBeInTheDocument();
    const list = screen.getByRole("list", { name: /rules in match order/i });
    const items = within(list).getAllByRole("listitem");
    expect(items.map((li) => within(li).getByTestId("rule-pos").textContent)).toEqual(["1", "2"]);
    expect(within(items[0]!).getByText(`rule ${A}`)).toBeInTheDocument();
    const def = screen.getByRole("region", { name: /default rule/i });
    expect(within(def).getByText("fallback")).toBeInTheDocument();
  });

  it("summarises events, conditions, agent and repository as text", () => {
    renderEditor([rule(A, 0)]);
    const item = screen.getByRole("listitem");
    expect(item).toHaveTextContent("issue_comment");
    expect(item).toHaveTextContent("comment.body contains /audit");
    expect(item).toHaveTextContent("Security Analyst");
    expect(item).toHaveTextContent("repo from repository.full_name");
  });

  it("shows the failure count once a rule has failed, and auto-disabled rules as disabled", () => {
    renderEditor([
      rule(A, 0, { consecutive_failures: 2 }),
      rule(B, 1, { is_enabled: false, consecutive_failures: 3 }),
    ]);
    const [a, b] = screen.getAllByRole("listitem");
    expect(a).toHaveTextContent("2/3 failed starts");
    expect(b).toHaveTextContent("disabled");
  });

  it("moves a rule down by sending the whole new order (default stays last)", async () => {
    actions.reorderRulesAction.mockResolvedValue({ ok: true });
    renderEditor([rule(A, 0), rule(B, 1), rule(C, 2), rule(D, 3, { is_default: true })]);
    fireEvent.click(screen.getByRole("button", { name: `Move rule rule ${A} down` }));
    await waitFor(() => expect(actions.reorderRulesAction).toHaveBeenCalledWith(EP, [B, A, C, D]));
    await waitFor(() => expect(refresh).toHaveBeenCalled());
  });

  it("disables moving the first rule up and the last rule down", () => {
    renderEditor([rule(A, 0), rule(B, 1)]);
    expect(screen.getByRole("button", { name: `Move rule rule ${A} up` })).toBeDisabled();
    expect(screen.getByRole("button", { name: `Move rule rule ${B} down` })).toBeDisabled();
    expect(screen.getByRole("button", { name: `Move rule rule ${A} down` })).toBeEnabled();
  });

  it("toggles and deletes (after a confirm)", async () => {
    actions.toggleRuleAction.mockResolvedValue({ ok: true });
    actions.deleteRuleAction.mockResolvedValue({ ok: true });
    renderEditor([rule(A, 0)]);
    fireEvent.click(screen.getByRole("button", { name: `Disable rule rule ${A}` }));
    await waitFor(() => expect(actions.toggleRuleAction).toHaveBeenCalledWith(A, false));
    fireEvent.click(screen.getByRole("button", { name: `Delete rule rule ${A}` }));
    const dlg = screen.getByRole("alertdialog", { name: /delete rule/i });
    fireEvent.click(within(dlg).getByRole("button", { name: /delete rule/i }));
    await waitFor(() => expect(actions.deleteRuleAction).toHaveBeenCalledWith(A));
  });

  it("shows an empty state", () => {
    renderEditor([]);
    expect(screen.getByRole("status")).toHaveTextContent(/no rules yet/i);
  });
});

describe("rule dialog", () => {
  function openNew() {
    fireEvent.click(screen.getAllByRole("button", { name: /add rule/i })[0]!);
    return screen.getByRole("dialog", { name: /new rule/i });
  }

  it("creates a rule with conditions, a payload repo and params", async () => {
    actions.saveRuleAction.mockResolvedValue({ ok: true, id: A });
    renderEditor([]);
    const dlg = openNew();
    fireEvent.change(within(dlg).getByLabelText(/^rule name/i), {
      target: { value: "audit on comment" },
    });
    fireEvent.click(within(dlg).getByRole("checkbox", { name: "issue_comment" }));
    fireEvent.click(within(dlg).getByRole("button", { name: /add condition/i }));
    fireEvent.change(within(dlg).getByLabelText(/condition 1 field/i), {
      target: { value: "comment.body" },
    });
    fireEvent.change(within(dlg).getByLabelText(/condition 1 operator/i), {
      target: { value: "contains" },
    });
    fireEvent.change(within(dlg).getByLabelText(/condition 1 value/i), {
      target: { value: "/audit" },
    });
    fireEvent.click(
      within(dlg).getByRole("button", { name: /fill a parameter from the payload/i }),
    );
    fireEvent.change(within(dlg).getByLabelText(/payload parameter 1 name/i), {
      target: { value: "pr_number" },
    });
    fireEvent.change(within(dlg).getByLabelText(/payload parameter 1 path/i), {
      target: { value: "issue.number" },
    });
    fireEvent.click(within(dlg).getByRole("button", { name: /save rule/i }));

    await waitFor(() =>
      expect(actions.saveRuleAction).toHaveBeenCalledWith(
        EP,
        null,
        expect.objectContaining({
          name: "audit on comment",
          eventTypes: ["issue_comment"],
          conditions: [{ field: "comment.body", op: "contains", value: "/audit" }],
          isDefault: false,
          agentId: SA,
          repoMode: "payload_field",
          repoPayloadField: "repository.full_name",
          params: { static: { mode: "audit_only" }, from_payload: { pr_number: "issue.number" } },
          autoDisableThreshold: 3,
          isEnabled: true,
        }),
      ),
    );
    await waitFor(() => expect(screen.queryByRole("dialog", { name: /new rule/i })).toBeNull());
    expect(refresh).toHaveBeenCalled();
  });

  it("splits an `in` value into a list and drops the value for `exists`", async () => {
    actions.saveRuleAction.mockResolvedValue({ ok: true, id: A });
    renderEditor([]);
    const dlg = openNew();
    fireEvent.click(within(dlg).getByRole("checkbox", { name: "pull_request" }));
    fireEvent.click(within(dlg).getByRole("button", { name: /add condition/i }));
    fireEvent.change(within(dlg).getByLabelText(/condition 1 field/i), {
      target: { value: "action" },
    });
    fireEvent.change(within(dlg).getByLabelText(/condition 1 operator/i), {
      target: { value: "in" },
    });
    fireEvent.change(within(dlg).getByLabelText(/condition 1 value/i), {
      target: { value: "opened, reopened" },
    });
    fireEvent.click(within(dlg).getByRole("button", { name: /add condition/i }));
    fireEvent.change(within(dlg).getByLabelText(/condition 2 field/i), {
      target: { value: "pull_request.draft" },
    });
    fireEvent.change(within(dlg).getByLabelText(/condition 2 operator/i), {
      target: { value: "exists" },
    });
    expect(within(dlg).queryByLabelText(/condition 2 value/i)).toBeNull();
    fireEvent.click(within(dlg).getByRole("button", { name: /save rule/i }));
    await waitFor(() =>
      expect(actions.saveRuleAction).toHaveBeenCalledWith(
        EP,
        null,
        expect.objectContaining({
          conditions: [
            { field: "action", op: "in", value: ["opened", "reopened"] },
            { field: "pull_request.draft", op: "exists" },
          ],
        }),
      ),
    );
  });

  it("sends a half-filled payload row so the server can flag it (never drops it silently)", async () => {
    actions.saveRuleAction.mockResolvedValue({ ok: true, id: A });
    renderEditor([]);
    const dlg = openNew();
    fireEvent.click(
      within(dlg).getByRole("button", { name: /fill a parameter from the payload/i }),
    );
    fireEvent.change(within(dlg).getByLabelText(/payload parameter 1 path/i), {
      target: { value: "a..b" },
    });
    fireEvent.click(within(dlg).getByRole("button", { name: /add condition/i }));
    fireEvent.click(within(dlg).getByRole("button", { name: /save rule/i }));
    await waitFor(() =>
      expect(actions.saveRuleAction).toHaveBeenCalledWith(
        EP,
        null,
        expect.objectContaining({
          params: expect.objectContaining({ from_payload: { "": "a..b" } }),
          conditions: [{ field: "", op: "equals", value: "" }],
        }),
      ),
    );
  });

  it("removes a condition row", () => {
    renderEditor([]);
    const dlg = openNew();
    fireEvent.click(within(dlg).getByRole("button", { name: /add condition/i }));
    fireEvent.click(within(dlg).getByRole("button", { name: /remove condition 1/i }));
    expect(within(dlg).queryByLabelText(/condition 1 field/i)).toBeNull();
  });

  it("rebinds the params form when the agent changes", () => {
    renderEditor([]);
    const dlg = openNew();
    expect(within(dlg).getByLabelText(/^mode/)).toBeInTheDocument();
    fireEvent.change(within(dlg).getByLabelText(/^agent/i), { target: { value: DU } });
    expect(within(dlg).queryByLabelText(/^mode/)).toBeNull();
    expect(within(dlg).getByLabelText(/^fix_mode/)).toBeInTheDocument();
  });

  it("switches to a fixed repository", async () => {
    actions.saveRuleAction.mockResolvedValue({ ok: true, id: A });
    renderEditor([]);
    const dlg = openNew();
    fireEvent.click(within(dlg).getByRole("checkbox", { name: "issue_comment" }));
    fireEvent.click(within(dlg).getByRole("radio", { name: /fixed repository/i }));
    fireEvent.change(within(dlg).getByLabelText(/^repository$/i), { target: { value: REPO } });
    fireEvent.click(within(dlg).getByRole("button", { name: /save rule/i }));
    await waitFor(() =>
      expect(actions.saveRuleAction).toHaveBeenCalledWith(
        EP,
        null,
        expect.objectContaining({ repoMode: "fixed", repositoryId: REPO }),
      ),
    );
  });

  it("hides events and conditions for the default rule", () => {
    renderEditor([]);
    const dlg = openNew();
    fireEvent.click(within(dlg).getByRole("switch", { name: /default rule/i }));
    expect(within(dlg).queryByRole("checkbox", { name: "issue_comment" })).toBeNull();
    expect(within(dlg).queryByRole("button", { name: /add condition/i })).toBeNull();
    expect(dlg).toHaveTextContent(/runs only when no other rule matches/i);
  });

  it("shows server validation errors inline and stays open", async () => {
    actions.saveRuleAction.mockResolvedValue({
      ok: false,
      code: "INVALID_INPUT",
      message: "Fix the highlighted fields.",
      fieldErrors: {
        params: "token is not a parameter of this agent",
        conditions: "Condition 1: field is not a valid path",
      },
    });
    renderEditor([]);
    const dlg = openNew();
    fireEvent.click(within(dlg).getByRole("button", { name: /save rule/i }));
    expect(await within(dlg).findByText(/token is not a parameter/i)).toBeInTheDocument();
    expect(within(dlg).getByText(/condition 1: field is not a valid path/i)).toBeInTheDocument();
    expect(refresh).not.toHaveBeenCalled();
  });

  it("opens an existing rule prefilled and saves it in place", async () => {
    actions.saveRuleAction.mockResolvedValue({ ok: true, id: A });
    renderEditor([rule(A, 0)]);
    fireEvent.click(screen.getByRole("button", { name: `Edit rule rule ${A}` }));
    const dlg = screen.getByRole("dialog", { name: /edit rule/i });
    expect(within(dlg).getByLabelText(/^rule name/i)).toHaveValue(`rule ${A}`);
    expect(within(dlg).getByRole("checkbox", { name: "issue_comment" })).toBeChecked();
    expect(within(dlg).getByLabelText(/condition 1 value/i)).toHaveValue("/audit");
    expect(within(dlg).getByLabelText(/payload parameter 1 path/i)).toHaveValue("issue.number");
    fireEvent.click(within(dlg).getByRole("button", { name: /save rule/i }));
    await waitFor(() =>
      expect(actions.saveRuleAction).toHaveBeenCalledWith(EP, A, expect.any(Object)),
    );
  });

  it("closes on Escape", () => {
    renderEditor([]);
    const dlg = openNew();
    fireEvent.keyDown(dlg, { key: "Escape" });
    expect(screen.queryByRole("dialog", { name: /new rule/i })).toBeNull();
  });
});
