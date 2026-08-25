import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render } from "@testing-library/react";
import { RelativeTime } from "../relative-time";

function getTimeElement(container: HTMLElement): HTMLTimeElement {
  const el = container.querySelector("time");
  expect(el).not.toBeNull();
  return el as HTMLTimeElement;
}

describe("RelativeTime", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    // Set "now" to 2024-06-15T12:00:00Z
    vi.setSystemTime(new Date("2024-06-15T12:00:00Z"));
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("renders as a <time> element", () => {
    const { container } = render(<RelativeTime dateTime="2024-06-15T11:58:00Z" />);
    const timeEl = getTimeElement(container);
    expect(timeEl.tagName).toBe("TIME");
  });

  it("has dateTime attribute with ISO string", () => {
    const { container } = render(<RelativeTime dateTime="2024-06-15T11:58:00Z" />);
    const timeEl = getTimeElement(container);
    expect(timeEl.getAttribute("datetime")).toBe("2024-06-15T11:58:00Z");
  });

  it("has title attribute with absolute UTC ISO string", () => {
    const { container } = render(<RelativeTime dateTime="2024-06-15T11:58:00Z" />);
    const timeEl = getTimeElement(container);
    expect(timeEl.getAttribute("title")).toContain("2024-06-15");
    expect(timeEl.getAttribute("title")).toContain("UTC");
  });

  it("shows '2 min ago' for 2 minutes in the past", () => {
    const { container } = render(<RelativeTime dateTime="2024-06-15T11:58:00Z" />);
    const timeEl = getTimeElement(container);
    expect(timeEl.textContent).toBe("2 min ago");
  });

  it("shows relative text for hours", () => {
    const { container } = render(<RelativeTime dateTime="2024-06-15T09:00:00Z" />);
    const timeEl = getTimeElement(container);
    expect(timeEl.textContent).toBe("3 hours ago");
  });

  it("shows relative text for days", () => {
    const { container } = render(<RelativeTime dateTime="2024-06-13T12:00:00Z" />);
    const timeEl = getTimeElement(container);
    expect(timeEl.textContent).toBe("2 days ago");
  });

  it("shows 'just now' for very recent times (< 1 min)", () => {
    const { container } = render(<RelativeTime dateTime="2024-06-15T11:59:45Z" />);
    const timeEl = getTimeElement(container);
    expect(timeEl.textContent).toBe("just now");
  });

  it("shows relative text for 1 minute", () => {
    const { container } = render(<RelativeTime dateTime="2024-06-15T11:59:00Z" />);
    const timeEl = getTimeElement(container);
    expect(timeEl.textContent).toBe("1 min ago");
  });

  it("shows relative text for 1 hour", () => {
    const { container } = render(<RelativeTime dateTime="2024-06-15T11:00:00Z" />);
    const timeEl = getTimeElement(container);
    expect(timeEl.textContent).toBe("1 hour ago");
  });

  it("shows relative text for 1 day", () => {
    const { container } = render(<RelativeTime dateTime="2024-06-14T12:00:00Z" />);
    const timeEl = getTimeElement(container);
    expect(timeEl.textContent).toBe("1 day ago");
  });

  it("does not contain any hardcoded color or inline style", () => {
    const { container } = render(<RelativeTime dateTime="2024-06-15T11:58:00Z" />);
    const timeEl = getTimeElement(container);
    expect(timeEl.getAttribute("style")).toBeNull();
  });
});
