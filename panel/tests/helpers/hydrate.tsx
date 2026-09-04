import { act } from "react";
import { hydrateRoot } from "react-dom/client";
import { renderToString } from "react-dom/server";
import type { ReactElement } from "react";

/**
 * Hydration test instrument (test-plan G3).
 *
 * RTL's `render()` does a client-only render — it never hydrates — so no
 * ordinary component test can observe a server/client hydration mismatch. This
 * helper reproduces the real sequence: render the element to a string on the
 * "server", put that HTML in the DOM, then `hydrateRoot` the same element onto
 * it. React reports any mismatch through `onRecoverableError`, which we
 * collect — asserting `recoverable` is empty is a genuine, falsifiable check
 * that the server and client renders agreed.
 *
 * Returns the container plus the collected recoverable errors and a cleanup
 * function. The caller reads the post-hydration DOM off `container`.
 */
export async function renderHydrated(element: ReactElement): Promise<{
  container: HTMLDivElement;
  recoverable: unknown[];
  cleanup: () => void;
}> {
  const container = document.createElement("div");
  // Server pass.
  container.innerHTML = renderToString(element);
  document.body.appendChild(container);

  const recoverable: unknown[] = [];
  let root: ReturnType<typeof hydrateRoot>;
  await act(async () => {
    root = hydrateRoot(container, element, {
      onRecoverableError: (error) => {
        recoverable.push(error);
      },
    });
  });

  return {
    container,
    recoverable,
    cleanup: () => {
      act(() => {
        root.unmount();
      });
      container.remove();
    },
  };
}
