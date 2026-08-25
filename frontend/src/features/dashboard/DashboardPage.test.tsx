// frontend/src/features/dashboard/DashboardPage.test.tsx
//
// Checkpoint 64.80-F Phases 18/19: targeted component tests for the
// Application Dashboard. Only the network boundary (`global.fetch`) is
// mocked - the REAL component tree, the REAL centralized API client, and
// the REAL generated contract types are exercised.
//
// The safety-critical assertions here are the negative ones: no
// live-trading control and no Gainz activation control may EVER appear
// on this screen. Those tests exist so that can never silently regress.
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { DashboardPage } from "./DashboardPage";
import {
  HEALTH_MARKET_CLOSED,
  READINESS_DEGRADED,
  READINESS_READY_NO_REASONS,
  SESSION_CLOSED,
  SESSION_OPEN,
  WORKER_RUNNING,
  WORKER_STOPPED,
} from "./dashboardFixtures";

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

interface RouteOverrides {
  session?: unknown;
  health?: unknown;
  worker?: unknown;
  readiness?: unknown;
}

/** Routes each dashboard request by URL so the four panels can be given
 * independent fixtures (including independent failures). */
function stubApi(overrides: RouteOverrides = {}): void {
  const routes: Array<[string, unknown]> = [
    ["/market-data/session/", overrides.session ?? SESSION_CLOSED],
    ["/market-data/health/", overrides.health ?? HEALTH_MARKET_CLOSED],
    ["/market-data/worker-status/", overrides.worker ?? WORKER_STOPPED],
    ["/system/readiness/", overrides.readiness ?? READINESS_DEGRADED],
  ];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      for (const [fragment, body] of routes) {
        if (url.includes(fragment)) {
          if (body === "FAIL") {
            return jsonResponse({ error_code: "server_error", message: "Backend unavailable." }, 500);
          }
          return jsonResponse(body);
        }
      }
      return jsonResponse({ error_code: "not_found", message: "Not found." }, 404);
    }),
  );
}

const NAV = {
  onOpenMarketData: vi.fn(),
  onOpenArchive: vi.fn(),
  onOpenPaperTrading: vi.fn(),
  onOpenBacktesting: vi.fn(),
};

function renderDashboard(): typeof NAV {
  const handlers = {
    onOpenMarketData: vi.fn(),
    onOpenArchive: vi.fn(),
    onOpenPaperTrading: vi.fn(),
    onOpenBacktesting: vi.fn(),
  };
  render(<DashboardPage {...handlers} />);
  return handlers;
}

describe("DashboardPage — rendering and market/system state", () => {
  it("renders the dashboard heading once the status APIs resolve", async () => {
    stubApi();
    renderDashboard();
    // Settle on a ready-state-only element first: the loading branch
    // renders the same <h1>, so querying the heading immediately would
    // match the node that the ready re-render then replaces.
    await screen.findByRole("heading", { name: "Market Status", level: 2 });
    expect(
      screen.getByRole("heading", { name: "Application Dashboard", level: 1 }),
    ).toBeInTheDocument();
  });

  it("renders NSE MARKET CLOSED with the real trading date when the session API says CLOSED", async () => {
    stubApi();
    renderDashboard();
    expect(await screen.findByText("NSE MARKET CLOSED")).toBeInTheDocument();
    // The trading date appears in both the Market Status panel and the
    // Today's Market Data card - both read the SAME session response.
    expect(screen.getAllByText("2026-08-25").length).toBeGreaterThan(0);
    expect(screen.queryByText("NSE MARKET OPEN")).not.toBeInTheDocument();
  });

  it("renders NSE MARKET OPEN when the session API says OPEN (state is never hard-coded to closed)", async () => {
    stubApi({ session: SESSION_OPEN, worker: WORKER_RUNNING });
    renderDashboard();
    expect(await screen.findByText("NSE MARKET OPEN")).toBeInTheDocument();
  });

  it("renders the worker as STOPPED, using the backend's own WorkerRuntimeStatus vocabulary", async () => {
    stubApi();
    renderDashboard();
    await screen.findByRole("heading", { name: "Worker Status", level: 2 });
    expect(screen.getAllByText("STOPPED").length).toBeGreaterThan(0);
    expect(
      screen.getByText(/market-data worker is not running/i),
    ).toBeInTheDocument();
  });

  it("shows NO INGESTION for today's market data while the worker is stopped", async () => {
    stubApi();
    renderDashboard();
    expect(await screen.findByText("NO INGESTION")).toBeInTheDocument();
  });

  it("shows INGESTING for today's market data while the worker is running", async () => {
    stubApi({ session: SESSION_OPEN, worker: WORKER_RUNNING });
    renderDashboard();
    expect(await screen.findByText("INGESTING")).toBeInTheDocument();
  });
});

describe("DashboardPage — archive, reconciliation, research and Gainz honesty", () => {
  it("renders the archive/reconciliation card as NOT AVAILABLE rather than fabricating bar counts", async () => {
    stubApi();
    renderDashboard();
    await screen.findByRole("heading", { name: /Archive & Reconciliation/i, level: 2 });
    expect(screen.getAllByText("NOT AVAILABLE").length).toBeGreaterThan(0);
    expect(
      screen.getAllByText(/no archive HTTP API/i).length,
    ).toBeGreaterThan(0);
  });

  it("never renders a numeric expected/actual/missing bar count while the archive API is missing", async () => {
    stubApi();
    renderDashboard();
    await screen.findByRole("heading", { name: /Today's Market Data/i, level: 2 });
    const expectedBars = screen.getByText("Expected / actual / missing bars");
    expect(expectedBars.nextElementSibling?.textContent).toMatch(/Not available/i);
  });

  it("renders Research Readiness as NOT READY with the recorded pending criteria", async () => {
    stubApi();
    renderDashboard();
    expect(await screen.findByText("NOT READY")).toBeInTheDocument();
    expect(screen.getByText(/Full NSE session validation — Pending/i)).toBeInTheDocument();
    expect(screen.getByText(/Independent candle authority — Pending/i)).toBeInTheDocument();
    expect(screen.getByText(/Reconciliation evidence — Pending/i)).toBeInTheDocument();
  });

  it("renders Gainz as DISABLED", async () => {
    stubApi();
    renderDashboard();
    await screen.findByRole("heading", { name: "Gainz", level: 2 });
    expect(screen.getByText("DISABLED")).toBeInTheDocument();
  });

  it("renders the reconciliation state as NOT RECONCILED/unavailable via the readiness reasons, never as reconciled", async () => {
    stubApi();
    renderDashboard();
    expect(
      await screen.findByText(/No archive reconciliation evidence recorded./i),
    ).toBeInTheDocument();
    expect(screen.queryByText(/reconciled successfully/i)).not.toBeInTheDocument();
  });
});

describe("DashboardPage — safety: no live trading and no Gainz activation controls", () => {
  it("exposes no live-trading control anywhere on the dashboard", async () => {
    stubApi();
    renderDashboard();
    await screen.findByRole("heading", { name: "Application Dashboard", level: 1 });
    const buttonLabels = screen.getAllByRole("button").map((b) => b.textContent ?? "");
    for (const label of buttonLabels) {
      expect(label).not.toMatch(/\b(go live|live trading|place order|submit order|buy|sell|execute|deploy)\b/i);
    }
  });

  it("exposes no Gainz enable/activate control", async () => {
    stubApi();
    renderDashboard();
    await screen.findByRole("heading", { name: "Gainz", level: 2 });
    const buttonLabels = screen.getAllByRole("button").map((b) => b.textContent ?? "");
    for (const label of buttonLabels) {
      expect(label).not.toMatch(/gainz/i);
      expect(label).not.toMatch(/\b(enable|activate|start)\b/i);
    }
  });

  it("labels Paper Trading unmistakably as not live trading", async () => {
    stubApi();
    renderDashboard();
    expect(
      await screen.findByText(/PAPER TRADING — NOT LIVE TRADING/i),
    ).toBeInTheDocument();
  });
});

describe("DashboardPage — navigation", () => {
  it("navigates to Paper Trading via a specifically-labelled action", async () => {
    stubApi();
    const handlers = renderDashboard();
    const button = await screen.findByRole("button", { name: "Open Paper Trading" });
    fireEvent.click(button);
    expect(handlers.onOpenPaperTrading).toHaveBeenCalledTimes(1);
  });

  it("navigates to the Archive via a specifically-labelled action", async () => {
    stubApi();
    const handlers = renderDashboard();
    fireEvent.click(await screen.findByRole("button", { name: "View Archive" }));
    expect(handlers.onOpenArchive).toHaveBeenCalledTimes(1);
  });

  it("navigates to Market Data and to Research & Backtesting", async () => {
    stubApi();
    const handlers = renderDashboard();
    fireEvent.click(await screen.findByRole("button", { name: "View Market Data" }));
    fireEvent.click(
      screen.getByRole("button", { name: /Open Research & Backtesting/i }),
    );
    expect(handlers.onOpenMarketData).toHaveBeenCalledTimes(1);
    expect(handlers.onOpenBacktesting).toHaveBeenCalledTimes(1);
  });
});

describe("DashboardPage — loading, empty and error states", () => {
  it("renders a loading state while the status APIs are in flight", () => {
    vi.stubGlobal("fetch", vi.fn(() => new Promise<Response>(() => {})));
    renderDashboard();
    expect(screen.getByRole("status")).toHaveTextContent("Loading application status…");
  });

  it("renders a page-level error with a retry action when every status API fails", async () => {
    stubApi({ session: "FAIL", health: "FAIL", worker: "FAIL", readiness: "FAIL" });
    renderDashboard();
    expect(await screen.findByRole("alert")).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Retry loading application status" }),
    ).toBeInTheDocument();
  });

  it("degrades a single failing panel to Not Available without blanking the dashboard", async () => {
    stubApi({ worker: "FAIL" });
    renderDashboard();
    // The market panel still renders from its own (successful) API...
    expect(await screen.findByText("NSE MARKET CLOSED")).toBeInTheDocument();
    // ...while the worker panel honestly reports it could not be read.
    expect(
      screen.getByText("The worker runtime status API could not be read."),
    ).toBeInTheDocument();
  });

  it("renders an empty state when a successful API returns an empty collection", async () => {
    stubApi({ readiness: READINESS_READY_NO_REASONS });
    renderDashboard();
    expect(
      await screen.findByText("The backend reports no outstanding readiness reasons."),
    ).toBeInTheDocument();
  });

  it("re-fetches when the refresh action is used", async () => {
    stubApi();
    renderDashboard();
    const refresh = await screen.findByRole("button", {
      name: "Refresh application status",
    });
    const callsBefore = (global.fetch as unknown as { mock: { calls: unknown[] } }).mock.calls
      .length;
    fireEvent.click(refresh);
    await waitFor(() => {
      expect(
        (global.fetch as unknown as { mock: { calls: unknown[] } }).mock.calls.length,
      ).toBeGreaterThan(callsBefore);
    });
  });
});

describe("DashboardPage — accessibility", () => {
  it("uses a single level-1 heading and level-2 section headings", async () => {
    stubApi();
    renderDashboard();
    await screen.findByRole("heading", { name: "Application Dashboard", level: 1 });
    expect(screen.getAllByRole("heading", { level: 1 })).toHaveLength(1);
    expect(screen.getAllByRole("heading", { level: 2 }).length).toBeGreaterThan(4);
  });

  it("gives every primary action a specific, non-vague accessible name", async () => {
    stubApi();
    renderDashboard();
    await screen.findByRole("heading", { name: "Application Dashboard", level: 1 });
    for (const button of screen.getAllByRole("button")) {
      const name = (button.textContent ?? "").trim();
      expect(name.length).toBeGreaterThan(3);
      expect(name).not.toMatch(/^(click here|here|more|go|ok)$/i);
    }
  });

  it("communicates status with text, not color alone", async () => {
    stubApi();
    renderDashboard();
    // The badge carries the literal status word as text content.
    const badge = await screen.findByText("NSE MARKET CLOSED");
    expect(badge.textContent).toContain("NSE MARKET CLOSED");
  });
});
