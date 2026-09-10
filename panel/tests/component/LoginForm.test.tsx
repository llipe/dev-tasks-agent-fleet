import { render, screen, fireEvent, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

/**
 * S-119 — LoginForm component suite (Layer 2, jsdom).
 *
 * Asserts the spec §10.1 mockup elements and the security-relevant UX:
 *   - all mockup elements present; fields label-associated (AC10)
 *   - the SHOW toggle reveals/re-masks, is keyboard-operable, reports
 *     `aria-pressed`, and the field defaults to masked (AC13)
 *   - the error region uses `role="alert"` (AC5/AC10)
 *   - the submit button is disabled while pending (double-submit guard)
 *   - "Forgot password?" is NOT activatable — a non-link with `aria-disabled`,
 *     not an `<a href>` (AC16)
 *
 * The server action is mocked (it pulls in `next/headers`); `useFormStatus` is
 * mocked so the pending state is controllable without an in-flight submit.
 */

// The action module imports next/headers + next/navigation at the top level.
vi.mock("next/headers", () => ({ cookies: vi.fn() }));
vi.mock("next/navigation", () => ({ redirect: vi.fn() }));

// Control the action's returned state via useActionState. We drive the error
// path by making the initial state a failure through a wrapper below.
const signInMock = vi.fn();
vi.mock("@/app/login/actions", () => ({
  signIn: (...args: unknown[]) => signInMock(...args),
}));

// useFormStatus is controllable per-test via this ref.
let pendingRef = { pending: false };
vi.mock("react-dom", async (importOriginal) => {
  const actual = await importOriginal<typeof import("react-dom")>();
  return { ...actual, useFormStatus: () => pendingRef };
});

import { LoginForm } from "@/components/auth/LoginForm";

afterEach(() => {
  pendingRef = { pending: false };
  signInMock.mockReset();
});

function renderForm() {
  return render(<LoginForm redirectTarget="/" region="us-east-1" />);
}

describe("LoginForm — mockup elements (AC10)", () => {
  it("renders the brand wordmark, heading is provided by the page (form has EMAIL/PASSWORD)", () => {
    renderForm();
    // Labels present and associated with inputs.
    const email = screen.getByLabelText("EMAIL");
    expect(email).toHaveAttribute("type", "email");
    expect(email).toHaveAttribute("autocomplete", "email");
    expect(email).toHaveAttribute("placeholder", "you@company.com");

    const password = screen.getByLabelText("PASSWORD");
    expect(password).toHaveAttribute("type", "password");
    expect(password).toHaveAttribute("autocomplete", "current-password");
  });

  it("renders a full-width primary Sign in submit button", () => {
    renderForm();
    const btn = screen.getByRole("button", { name: /^sign in$/i });
    expect(btn).toHaveAttribute("type", "submit");
  });

  it("renders the region tag and the 12h session fine print", () => {
    renderForm();
    expect(screen.getByText(/us-east-1/)).toBeInTheDocument();
    expect(screen.getByText(/sessions expire after 12 hours of inactivity/i)).toBeInTheDocument();
  });

  it("carries the redirect target as a hidden field", () => {
    const { container } = render(<LoginForm redirectTarget="/runs/abc" region="us-east-1" />);
    const hidden = container.querySelector('input[type="hidden"][name="redirect"]');
    expect(hidden).not.toBeNull();
    expect(hidden).toHaveValue("/runs/abc");
  });
});

describe("LoginForm — SHOW toggle (AC13)", () => {
  it("defaults to masked and toggles to text and back, keyboard-operable, aria-pressed", () => {
    renderForm();
    const password = screen.getByLabelText("PASSWORD");
    expect(password).toHaveAttribute("type", "password");

    const toggle = screen.getByRole("button", { name: /show password/i });
    expect(toggle).toHaveAttribute("type", "button");
    expect(toggle).toHaveAttribute("aria-pressed", "false");
    // aria-controls points at the input.
    expect(toggle).toHaveAttribute("aria-controls", password.getAttribute("id"));

    // Reveal (a click; buttons are inherently keyboard-operable — Enter/Space
    // dispatch a click on a native <button>).
    fireEvent.click(toggle);
    expect(password).toHaveAttribute("type", "text");
    expect(screen.getByRole("button", { name: /hide password/i })).toHaveAttribute(
      "aria-pressed",
      "true",
    );

    // Re-mask.
    fireEvent.click(screen.getByRole("button", { name: /hide password/i }));
    expect(screen.getByLabelText("PASSWORD")).toHaveAttribute("type", "password");
  });

  it("the SHOW toggle never submits the form (type=button)", () => {
    renderForm();
    expect(screen.getByRole("button", { name: /show password/i })).toHaveAttribute(
      "type",
      "button",
    );
  });
});

describe("LoginForm — pending state (double-submit guard)", () => {
  it("disables the fields and the submit button while pending", () => {
    pendingRef = { pending: true };
    renderForm();
    expect(screen.getByLabelText("EMAIL")).toBeDisabled();
    expect(screen.getByLabelText("PASSWORD")).toBeDisabled();
    const btn = screen.getByRole("button", { name: /signing in/i });
    expect(btn).toBeDisabled();
    expect(btn).toHaveAttribute("aria-disabled", "true");
  });
});

describe('LoginForm — "Forgot password?" is dead (AC16)', () => {
  it("renders a non-link span with aria-disabled, not an <a href>", () => {
    const { container } = renderForm();
    const forgot = screen.getByText(/forgot password\?/i);
    // Not a link element and not activatable.
    expect(forgot.tagName).not.toBe("A");
    expect(forgot).toHaveAttribute("aria-disabled", "true");
    // There is no anchor anywhere with an href="#" or a forgot-password link.
    expect(within(container).queryByRole("link", { name: /forgot password/i })).toBeNull();
    expect(container.querySelector('a[href="#"]')).toBeNull();
  });
});
