// frontend/src/app/AppDashboardNavigation.test.tsx
//
// Checkpoint 64.80-F Phase 19: route/navigation tests through the REAL
// App shell and the REAL AuthProvider - proving the Dashboard is the
// landing screen and that the dashboard's own entry points actually
// reach the EXISTING Paper Trading page and the Archive shell (rather
// than a duplicated copy of them).
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

/** An authenticated session plus the four dashboard status endpoints.
 * Anything else resolves to an empty list/object so unrelated pages
 * mount without exploding - this file asserts navigation, not those
 * pages' own content (they have their own test files). */
function stubAuthenticatedApp(): void {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.includes("/auth/session/")) {
        // The real `CurrentUserResponse` shape AuthContext consumes.
        return jsonResponse({
          is_authenticated: true,
          username: "operator",
          capabilities: [],
        });
      }
      if (url.includes("/market-data/session/")) return jsonResponse(SESSION_CLOSED);
      if (url.includes("/market-data/health/")) return jsonResponse(HEALTH_MARKET_CLOSED);
      if (url.includes("/market-data/worker-status/")) return jsonResponse(WORKER_STOPPED);
      if (url.includes("/system/readiness/")) return jsonResponse(READINESS_DEGRADED);
      // The existing Paper Trading page's own dependencies - stubbed
      // only so it MOUNTS; its content is asserted by its own test file.
      if (url.includes("/kill-switch/")) {
        return jsonResponse({ status: "ACTIVE", reason: null, changed_at: null });
      }
      if (url.includes("/paper-trading/session/")) {
        return jsonResponse({
          mode: "REPLAY",
          exists: false,
          accepted: true,
          message: "",
          session_id: "",
          status: "NOT_CONFIGURED",
          strategy_id: "",
          timeframe: "ONE_MINUTE",
          instrument_ids: [],
          replay_date: "2026-08-25",
          replay_cursor: 0,
          replay_total_steps: 0,
          playback_speed: 1,
          quantity: "0",
          available_strategy_ids: [],
          account: {
            starting_balance: "100000.00",
            available_balance: "100000.00",
            utilized_margin: "0.00",
            realized_pnl: "0.00",
            unrealized_pnl: "0.00",
          },
          open_positions: [],
          closed_trades: [],
          recent_signals: [],
        });
      }
      if (url.includes("/paper-trading/funds/")) {
        return jsonResponse({
          available_balance: "100000.00",
          utilized_margin: "0.00",
          updated_at: "2026-08-25T10:00:00Z",
        });
      }
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

describe("App navigation — Checkpoint 64.80-F", () => {
  it("lands on the Application Dashboard for an authenticated user", async () => {
    stubAuthenticatedApp();
    renderApp();
    expect(
      await screen.findByRole("heading", { name: "Application Dashboard", level: 1 }),
    ).toBeInTheDocument();
  });

  it("exposes Dashboard, Market Data, Market Data Archive, Paper Trading and Backtesting in primary navigation", async () => {
    stubAuthenticatedApp();
    renderApp();
    const nav = await screen.findByRole("navigation", { name: "Primary" });
    for (const label of [
      "Dashboard",
      "Market Data",
      "Market Data Archive",
      "Paper Trading",
      "Backtesting",
    ]) {
      expect(
        screen.getByRole("button", { name: label }),
      ).toBeInTheDocument();
      expect(nav).toContainElement(screen.getByRole("button", { name: label }));
    }
  });

  it("reaches the EXISTING Paper Trading page from the dashboard's own entry point", async () => {
    stubAuthenticatedApp();
    renderApp();
    fireEvent.click(await screen.findByRole("button", { name: "Open Paper Trading" }));
    await waitFor(() => {
      expect(
        screen.queryByRole("heading", { name: "Application Dashboard", level: 1 }),
      ).not.toBeInTheDocument();
    });
    // Navigation landed on the EXISTING Paper Trading screen - proven by
    // the primary nav's own active marker, which does not depend on that
    // page's data loading successfully.
    expect(screen.getByRole("button", { name: "Paper Trading" })).toHaveAttribute(
      "aria-current",
      "page",
    );
  });

  it("reaches the Market Data Archive from the dashboard's own entry point", async () => {
    stubAuthenticatedApp();
    renderApp();
    fireEvent.click(await screen.findByRole("button", { name: "View Archive" }));
    expect(
      await screen.findByRole("heading", { name: "Market Data Archive", level: 1 }),
    ).toBeInTheDocument();
  });

  it("marks the active navigation entry with aria-current for assistive technology", async () => {
    stubAuthenticatedApp();
    renderApp();
    const dashboardNav = await screen.findByRole("button", { name: "Dashboard" });
    expect(dashboardNav).toHaveAttribute("aria-current", "page");
  });
});
