import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

/**
 * S-176 (#321) — /webhooks component suite (Layer 2, jsdom), DESIGN.md §5.9.
 *  - list: status pill, name + source, events (+N), rule count, copyable URL;
 *  - empty state with the create CTA;
 *  - create / edit form, including generic-only header fields and inline errors;
 *  - secret shown once after create or rotate, gone after dismiss, never in the list;
 *  - every control is a real, labelled button or input (keyboard reachable).
 */

const actions = {
  createEndpointAction: vi.fn(),
  updateEndpointAction: vi.fn(),
  rotateSecretAction: vi.fn(),
  deleteEndpointAction: vi.fn(),
  toggleEndpointAction: vi.fn(),
};
vi.mock("@/app/(panel)/webhooks/actions", () => ({
  createEndpointAction: (...a: unknown[]) => actions.createEndpointAction(...a),
  updateEndpointAction: (...a: unknown[]) => actions.updateEndpointAction(...a),
  rotateSecretAction: (...a: unknown[]) => actions.rotateSecretAction(...a),
  deleteEndpointAction: (...a: unknown[]) => actions.deleteEndpointAction(...a),
  toggleEndpointAction: (...a: unknown[]) => actions.toggleEndpointAction(...a),
}));
const refresh = vi.fn();
vi.mock("next/navigation", () => ({ useRouter: () => ({ refresh }) }));

import { WebhooksClient } from "@/components/webhooks/WebhooksClient";
import type { WebhookEndpointListRow } from "@/lib/supabase/queries";

const BASE = "https://panel.example";
const SECRET = "a".repeat(64);

function row(over: Partial<WebhookEndpointListRow> = {}): WebhookEndpointListRow {
  return {
    id: "3f9b1c2e-8a4d-4c6b-9e1f-2a3b4c5d6e7f",
    name: "GitHub org",
    url_token: "tok_" + "x".repeat(40),
    source: "github",
    signature_header: "x-hub-signature-256",
    delivery_id_header: "x-github-delivery",
    event_allowlist: ["issue_comment", "pull_request", "push", "issues"],
    ignore_bot_author: true,
    is_enabled: true,
    created_at: "2026-10-20T10:00:00Z",
    updated_at: "2026-10-20T10:00:00Z",
    rule_count: 2,
    ...over,
  };
}

let writeText: ReturnType<typeof vi.fn>;
beforeEach(() => {
  writeText = vi.fn(async () => {});
  Object.assign(navigator, { clipboard: { writeText } });
});
afterEach(() => {
  for (const f of Object.values(actions)) f.mockReset();
  refresh.mockReset();
});

describe("list", () => {
  it("renders status, name + source, events with overflow, rule count and the URL", () => {
    render(
      <WebhooksClient
        rows={[
          row(),
          row({
            id: "b".repeat(8) + "-0000-4000-8000-000000000000",
            name: "Generic",
            source: "generic",
            is_enabled: false,
            event_allowlist: ["deploy"],
            rule_count: 0,
          }),
        ]}
        baseUrl={BASE}
      />,
    );
    const table = screen.getByRole("table", { name: /webhook endpoints/i });
    const rows = within(table).getAllByRole("row").slice(1);
    expect(rows).toHaveLength(2);

    const first = within(rows[0]!);
    expect(first.getByText("enabled")).toBeInTheDocument();
    expect(first.getByRole("link", { name: "GitHub org" })).toHaveAttribute(
      "href",
      `/webhooks/${row().id}`,
    );
    expect(first.getByText("github")).toBeInTheDocument();
    expect(first.getByText("issue_comment")).toBeInTheDocument();
    expect(first.getByText("+1")).toBeInTheDocument(); // 4 events, 3 shown
    expect(first.getByText("2 rules")).toBeInTheDocument();
    expect(first.getByText(`${BASE}/api/webhooks/${row().url_token}`)).toBeInTheDocument();

    const second = within(rows[1]!);
    expect(second.getByText("disabled")).toBeInTheDocument();
    expect(second.getByText("0 rules")).toBeInTheDocument();
  });

  it("copies the URL with a labelled button", async () => {
    render(<WebhooksClient rows={[row()]} baseUrl={BASE} />);
    fireEvent.click(screen.getByRole("button", { name: /copy url for github org/i }));
    await waitFor(() =>
      expect(writeText).toHaveBeenCalledWith(`${BASE}/api/webhooks/${row().url_token}`),
    );
    expect(await screen.findByText(/copied/i)).toBeInTheDocument();
  });

  it("shows an empty state with a create button", () => {
    render(<WebhooksClient rows={[]} baseUrl={BASE} />);
    expect(screen.getByRole("status")).toHaveTextContent(/no webhook endpoints yet/i);
    expect(screen.getAllByRole("button", { name: /new endpoint/i }).length).toBeGreaterThan(0);
  });

  it("toggles enabled and refreshes", async () => {
    actions.toggleEndpointAction.mockResolvedValue({ ok: true });
    render(<WebhooksClient rows={[row()]} baseUrl={BASE} />);
    fireEvent.click(screen.getByRole("button", { name: /disable github org/i }));
    await waitFor(() => expect(actions.toggleEndpointAction).toHaveBeenCalledWith(row().id, false));
    await waitFor(() => expect(refresh).toHaveBeenCalled());
  });

  it("deletes only after a confirm that says rules and deliveries go too", async () => {
    actions.deleteEndpointAction.mockResolvedValue({ ok: true });
    render(<WebhooksClient rows={[row()]} baseUrl={BASE} />);
    fireEvent.click(screen.getByRole("button", { name: /delete github org/i }));
    const dlg = screen.getByRole("alertdialog", { name: /delete endpoint/i });
    expect(dlg).toHaveTextContent(/2 rules/);
    expect(dlg).toHaveTextContent(/delivery log/i);
    expect(dlg).toHaveTextContent(/runs .* are kept/i);
    expect(actions.deleteEndpointAction).not.toHaveBeenCalled();
    fireEvent.click(within(dlg).getByRole("button", { name: /delete endpoint/i }));
    await waitFor(() => expect(actions.deleteEndpointAction).toHaveBeenCalledWith(row().id));
  });
});

describe("create + show-once secret", () => {
  it("creates, then shows the secret and URL once; dismissing removes the secret from the page", async () => {
    actions.createEndpointAction.mockResolvedValue({
      ok: true,
      id: row().id,
      urlToken: "newtoken_" + "y".repeat(40),
      secret: SECRET,
    });
    render(<WebhooksClient rows={[]} baseUrl={BASE} />);
    fireEvent.click(screen.getAllByRole("button", { name: /new endpoint/i })[0]!);
    const form = screen.getByRole("dialog", { name: /new endpoint/i });
    fireEvent.change(within(form).getByLabelText(/^name/i), { target: { value: "GH" } });
    fireEvent.click(within(form).getByRole("checkbox", { name: "issue_comment" }));
    fireEvent.click(within(form).getByRole("button", { name: /create endpoint/i }));

    await waitFor(() =>
      expect(actions.createEndpointAction).toHaveBeenCalledWith(
        expect.objectContaining({
          name: "GH",
          source: "github",
          eventAllowlist: ["issue_comment"],
          ignoreBotAuthor: true,
        }),
      ),
    );
    const reveal = await screen.findByRole("dialog", { name: /copy the signing secret/i });
    expect(within(reveal).getByLabelText(/signing secret/i)).toHaveValue(SECRET);
    expect(within(reveal).getByLabelText(/payload url/i)).toHaveValue(
      `${BASE}/api/webhooks/newtoken_${"y".repeat(40)}`,
    );
    expect(reveal).toHaveTextContent(/won.t be shown again/i);

    fireEvent.click(within(reveal).getByRole("button", { name: /copy secret/i }));
    await waitFor(() => expect(writeText).toHaveBeenCalledWith(SECRET));

    fireEvent.click(within(reveal).getByRole("button", { name: /i.ve stored it/i }));
    expect(screen.queryByRole("dialog", { name: /copy the signing secret/i })).toBeNull();
    expect(document.body.innerHTML).not.toContain(SECRET);
    expect(refresh).toHaveBeenCalled();
  });

  it("shows server field errors inline and keeps the form open", async () => {
    actions.createEndpointAction.mockResolvedValue({
      ok: false,
      code: "INVALID_INPUT",
      message: "Fix the highlighted fields.",
      fieldErrors: { eventAllowlist: "Choose at least one event. Others are ignored." },
    });
    render(<WebhooksClient rows={[]} baseUrl={BASE} />);
    fireEvent.click(screen.getAllByRole("button", { name: /new endpoint/i })[0]!);
    const form = screen.getByRole("dialog", { name: /new endpoint/i });
    fireEvent.change(within(form).getByLabelText(/^name/i), { target: { value: "GH" } });
    fireEvent.click(within(form).getByRole("button", { name: /create endpoint/i }));
    expect(await within(form).findByText(/choose at least one event/i)).toBeInTheDocument();
    expect(screen.queryByRole("dialog", { name: /copy the signing secret/i })).toBeNull();
  });

  it("shows the header fields only for a generic sender", () => {
    render(<WebhooksClient rows={[]} baseUrl={BASE} />);
    fireEvent.click(screen.getAllByRole("button", { name: /new endpoint/i })[0]!);
    const form = screen.getByRole("dialog", { name: /new endpoint/i });
    expect(within(form).queryByLabelText(/signature header/i)).toBeNull();
    fireEvent.click(within(form).getByRole("radio", { name: /generic/i }));
    expect(within(form).getByLabelText(/signature header/i)).toHaveValue("x-signature-256");
    expect(within(form).getByLabelText(/delivery id header/i)).toBeInTheDocument();
  });

  it("adds custom event names from the free-text field", async () => {
    actions.createEndpointAction.mockResolvedValue({
      ok: true,
      id: row().id,
      urlToken: "t".repeat(43),
      secret: SECRET,
    });
    render(<WebhooksClient rows={[]} baseUrl={BASE} />);
    fireEvent.click(screen.getAllByRole("button", { name: /new endpoint/i })[0]!);
    const form = screen.getByRole("dialog", { name: /new endpoint/i });
    fireEvent.change(within(form).getByLabelText(/^name/i), { target: { value: "GH" } });
    fireEvent.change(within(form).getByLabelText(/other events/i), {
      target: { value: "deployment, deployment_status" },
    });
    fireEvent.click(within(form).getByRole("button", { name: /create endpoint/i }));
    await waitFor(() =>
      expect(actions.createEndpointAction).toHaveBeenCalledWith(
        expect.objectContaining({ eventAllowlist: ["deployment", "deployment_status"] }),
      ),
    );
  });

  it("closes the form on Escape", () => {
    render(<WebhooksClient rows={[]} baseUrl={BASE} />);
    fireEvent.click(screen.getAllByRole("button", { name: /new endpoint/i })[0]!);
    const form = screen.getByRole("dialog", { name: /new endpoint/i });
    fireEvent.keyDown(form, { key: "Escape" });
    expect(screen.queryByRole("dialog", { name: /new endpoint/i })).toBeNull();
  });
});

describe("edit + rotate", () => {
  it("edits settings with the source fixed, and sends the enabled flag", async () => {
    actions.updateEndpointAction.mockResolvedValue({ ok: true });
    render(<WebhooksClient rows={[row()]} baseUrl={BASE} />);
    fireEvent.click(screen.getByRole("button", { name: /edit github org/i }));
    const form = screen.getByRole("dialog", { name: /edit endpoint/i });
    expect(within(form).queryByRole("radio", { name: /generic/i })).toBeNull();
    expect(within(form).getByRole("checkbox", { name: "issue_comment" })).toBeChecked();
    fireEvent.change(within(form).getByLabelText(/^name/i), { target: { value: "Renamed" } });
    fireEvent.click(within(form).getByRole("button", { name: /^save$/i }));
    await waitFor(() =>
      expect(actions.updateEndpointAction).toHaveBeenCalledWith(
        row().id,
        expect.objectContaining({ name: "Renamed", isEnabled: true, source: "github" }),
      ),
    );
    await waitFor(() =>
      expect(screen.queryByRole("dialog", { name: /edit endpoint/i })).toBeNull(),
    );
  });

  it("rotates only after a confirm, then shows the new secret once", async () => {
    actions.rotateSecretAction.mockResolvedValue({ ok: true, secret: SECRET });
    render(<WebhooksClient rows={[row()]} baseUrl={BASE} />);
    fireEvent.click(screen.getByRole("button", { name: /rotate secret for github org/i }));
    const confirm = screen.getByRole("alertdialog", { name: /rotate secret/i });
    expect(confirm).toHaveTextContent(/old secret stops working/i);
    await act(async () => {
      fireEvent.click(within(confirm).getByRole("button", { name: /rotate secret/i }));
    });
    expect(actions.rotateSecretAction).toHaveBeenCalledWith(row().id);
    const reveal = await screen.findByRole("dialog", { name: /copy the signing secret/i });
    expect(within(reveal).getByLabelText(/signing secret/i)).toHaveValue(SECRET);
  });

  it("reports a failed rotate without showing any secret", async () => {
    actions.rotateSecretAction.mockResolvedValue({
      ok: false,
      code: "DATABASE_ERROR",
      message: "Could not rotate the secret. The old secret is still active.",
    });
    render(<WebhooksClient rows={[row()]} baseUrl={BASE} />);
    fireEvent.click(screen.getByRole("button", { name: /rotate secret for github org/i }));
    await act(async () => {
      fireEvent.click(
        within(screen.getByRole("alertdialog")).getByRole("button", { name: /rotate secret/i }),
      );
    });
    expect(await screen.findByRole("alert")).toHaveTextContent(/old secret is still active/i);
    expect(screen.queryByRole("dialog", { name: /copy the signing secret/i })).toBeNull();
  });
});
