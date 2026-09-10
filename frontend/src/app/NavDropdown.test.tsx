// frontend/src/app/NavDropdown.test.tsx
//
// CHECKPOINT-FRONTEND-5 Issue 1: the primary nav's dropdown groups
// previously forced themselves back open on every render whenever the
// active screen lived inside them (`open={containsActive || undefined}`
// driven by the native <details> element) - the operator's own
// "requires an extra click elsewhere to actually dismiss it" report.
// This file proves the fix: selecting an item, clicking outside the
// nav, or pressing Escape all close the dropdown in ONE action, and a
// group can be closed even while it contains the active screen.
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { App } from "./App";
import { AuthProvider } from "../common/auth/AuthContext";
import {
  HEALTH_MARKET_CLOSED,
  READINESS_DEGRADED,
  SESSION_CLOSED,
  WORKER_STOPPED,
} from "../features/dashboard/dashboardFixtures";

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function stubAuthenticatedApp(): void {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.includes("/auth/session/")) {
        return jsonResponse({ is_authenticated: true, username: "operator", capabilities: [] });
      }
      if (url.includes("/market-data/session/")) return jsonResponse(SESSION_CLOSED);
      if (url.includes("/market-data/health/")) return jsonResponse(HEALTH_MARKET_CLOSED);
      if (url.includes("/market-data/worker-status/")) return jsonResponse(WORKER_STOPPED);
      if (url.includes("/system/readiness/")) return jsonResponse(READINESS_DEGRADED);
      return jsonResponse([]);
    }),
  );
}

function renderApp(): void {
  render(
    <AuthProvider>
      <App />
    </AuthProvider>,
  );
}

function researchToggle(): HTMLElement {
  return screen.getByText("Research").closest("summary") as HTMLElement;
}

describe("Primary nav dropdown — CHECKPOINT-FRONTEND-5 Issue 1", () => {
  it("opens on a click and closes again on a second click of the same toggle", async () => {
    stubAuthenticatedApp();
    renderApp();
    await screen.findByRole("navigation", { name: "Primary" });

    const toggle = researchToggle();
    expect(toggle.closest("details")).not.toHaveAttribute("open");

    fireEvent.click(toggle);
    expect(toggle.closest("details")).toHaveAttribute("open");

    fireEvent.click(toggle);
    expect(toggle.closest("details")).not.toHaveAttribute("open");
  });

  it("closes in ONE action when an item inside it is selected — even though the selected screen now lives in that group", async () => {
    stubAuthenticatedApp();
    renderApp();
    await screen.findByRole("navigation", { name: "Primary" });

    fireEvent.click(researchToggle());
    fireEvent.click(screen.getByRole("button", { name: "Screener" }));

    await waitFor(() => {
      expect(screen.getByRole("heading", { name: "Screener" })).toBeInTheDocument();
    });
    // The group now CONTAINS the active screen, but must still be closed -
    // the old `open={containsActive || undefined}` behavior would have
    // forced it back open here.
    expect(researchToggle().closest("details")).not.toHaveAttribute("open");
  });

  it("a group containing the active screen can still be closed by clicking its own toggle", async () => {
    stubAuthenticatedApp();
    renderApp();
    await screen.findByRole("navigation", { name: "Primary" });

    fireEvent.click(researchToggle());
    fireEvent.click(screen.getByRole("button", { name: "Screener" }));
    await screen.findByRole("heading", { name: "Screener" });

    // Reopen it (e.g. to switch to a different item in the same group).
    fireEvent.click(researchToggle());
    expect(researchToggle().closest("details")).toHaveAttribute("open");
    // And close it again - this must work even though Screener (inside
    // this group) is still the active screen.
    fireEvent.click(researchToggle());
    expect(researchToggle().closest("details")).not.toHaveAttribute("open");
  });

  it("closes on an outside click", async () => {
    stubAuthenticatedApp();
    renderApp();
    await screen.findByRole("navigation", { name: "Primary" });

    fireEvent.click(researchToggle());
    expect(researchToggle().closest("details")).toHaveAttribute("open");

    fireEvent.mouseDown(document.body);
    expect(researchToggle().closest("details")).not.toHaveAttribute("open");
  });

  it("closes on Escape (keyboard)", async () => {
    stubAuthenticatedApp();
    renderApp();
    await screen.findByRole("navigation", { name: "Primary" });

    fireEvent.click(researchToggle());
    expect(researchToggle().closest("details")).toHaveAttribute("open");

    fireEvent.keyDown(document, { key: "Escape" });
    expect(researchToggle().closest("details")).not.toHaveAttribute("open");
  });

  it("opening a different group closes the first one", async () => {
    stubAuthenticatedApp();
    renderApp();
    await screen.findByRole("navigation", { name: "Primary" });

    fireEvent.click(researchToggle());
    expect(researchToggle().closest("details")).toHaveAttribute("open");

    const systemSetupToggle = screen.getByText("System Setup").closest("summary") as HTMLElement;
    fireEvent.click(systemSetupToggle);

    expect(researchToggle().closest("details")).not.toHaveAttribute("open");
    expect(systemSetupToggle.closest("details")).toHaveAttribute("open");
  });
});
