// frontend/src/features/market-data/LiveMarketDataMonitor.test.tsx
//
// Checkpoint 23: real-boundary tests for the Live Market Data Monitor -
// only `global.fetch` is mocked; the real generated contract types, the
// real marketDataApi.ts client functions, and the real component are
// exercised together (matching DhanSettingsCard.test.tsx's established
// philosophy). Explicitly asserts NO trading control (Buy/Sell/Order/
// Quantity/Stop Loss/Target/Position/P&L/Execute/Trade) is ever
// rendered, per Checkpoint 23 §12.
import { fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { LiveMarketDataMonitor } from "./LiveMarketDataMonitor";
import { renderWithAuth } from "../../test/testAuth";
import type { components } from "@shared/generated_contracts/api-types";

type SessionResponse = components["schemas"]["SessionResponse"];
type MarketDataHealthResponse = components["schemas"]["MarketDataHealthResponse"];
type QuoteResponse = components["schemas"]["QuoteResponse"];

afterEach(() => {
  vi.unstubAllGlobals();
});

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

const SESSION: SessionResponse = {
  session_date: "2026-08-14",
  exchange: "NSE",
  market_open: "2026-08-14T03:45:00Z",
  market_close: "2026-08-14T10:00:00Z",
  square_off_deadline: "2026-08-14T09:50:00Z",
  status: "OPEN",
};

const HEALTH_DISCONNECTED: MarketDataHealthResponse = {
  state: "DISCONNECTED",
  last_success_at: null,
  last_failure_at: null,
  last_error_safe: "",
  freshness_age_seconds: null,
  consecutive_failures: 0,
  reconnect_count: 0,
  subscription_active: false,
};

const HEALTH_CONNECTED: MarketDataHealthResponse = {
  state: "CONNECTED_FRESH",
  last_success_at: "2026-08-14T06:00:00Z",
  last_failure_at: null,
  last_error_safe: "",
  freshness_age_seconds: 5,
  consecutive_failures: 0,
  reconnect_count: 0,
  subscription_active: false,
};

const RELIANCE_QUOTE: QuoteResponse = {
  symbol: "RELIANCE",
  exchange: "NSE",
  last_price: "1234.5600",
  source_timestamp: "2026-08-14T06:00:00Z",
  freshness_age_seconds: 5,
  is_stale: false,
};

function stubEndpoints(
  session: SessionResponse,
  health: MarketDataHealthResponse,
  quotes: QuoteResponse[],
): ReturnType<typeof vi.fn> {
  const fetchMock = vi.fn((input: RequestInfo | URL) => {
    const url = String(input);
    if (url.includes("/session/")) return Promise.resolve(jsonResponse(session));
    if (url.includes("/health/")) return Promise.resolve(jsonResponse(health));
    if (url.includes("/quotes/")) return Promise.resolve(jsonResponse(quotes));
    return Promise.resolve(jsonResponse(health));
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

describe("LiveMarketDataMonitor", () => {
  it("shows a loading state before the responses resolve", () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(() => new Promise<Response>(() => {})),
    );

    renderWithAuth(<LiveMarketDataMonitor />);

    expect(screen.getByRole("status")).toHaveTextContent(/loading/i);
  });

  it("renders session status, health, and an empty instrument table before any refresh", async () => {
    stubEndpoints(SESSION, HEALTH_DISCONNECTED, []);

    renderWithAuth(<LiveMarketDataMonitor />);

    await waitFor(() => expect(screen.getByText("Market Open")).toBeInTheDocument());
    expect(screen.getByText(/disconnected/i)).toBeInTheDocument();
    expect(screen.getByText(/no quotes observed yet/i)).toBeInTheDocument();
  });

  it("renders observed quotes in the instrument table", async () => {
    stubEndpoints(SESSION, HEALTH_CONNECTED, [RELIANCE_QUOTE]);

    renderWithAuth(<LiveMarketDataMonitor />);

    await waitFor(() => expect(screen.getByText("RELIANCE")).toBeInTheDocument());
    expect(screen.getByText("₹1234.5600")).toBeInTheDocument();
    expect(screen.getByText("● Fresh")).toBeInTheDocument();
  });

  it("hides the Refresh button for a reader without operator capability", async () => {
    stubEndpoints(SESSION, HEALTH_DISCONNECTED, []);

    renderWithAuth(<LiveMarketDataMonitor />, {
      state: { status: "authenticated", username: "reader", capabilities: ["configuration.read"] },
    });

    await waitFor(() => expect(screen.getByText(/read-only access/i)).toBeInTheDocument());
    expect(screen.queryByRole("button", { name: /refresh quotes/i })).not.toBeInTheDocument();
  });

  it("shows the Refresh button for an operator and triggers a refresh on click", async () => {
    const fetchMock = stubEndpoints(SESSION, HEALTH_DISCONNECTED, []);
    fetchMock.mockImplementation((input: RequestInfo | URL) => {
      const url = String(input);
      if (url.includes("/refresh/")) return Promise.resolve(jsonResponse(HEALTH_CONNECTED));
      if (url.includes("/session/")) return Promise.resolve(jsonResponse(SESSION));
      if (url.includes("/health/")) return Promise.resolve(jsonResponse(HEALTH_CONNECTED));
      if (url.includes("/quotes/")) return Promise.resolve(jsonResponse([RELIANCE_QUOTE]));
      return Promise.resolve(jsonResponse(HEALTH_CONNECTED));
    });

    renderWithAuth(<LiveMarketDataMonitor />);

    await waitFor(() => expect(screen.getByRole("button", { name: /refresh quotes/i })).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: /refresh quotes/i }));

    await waitFor(() => expect(screen.getByText(/^● Connected$/)).toBeInTheDocument());
    const refreshCalled = fetchMock.mock.calls.some((call) => String(call[0]).includes("/refresh/"));
    expect(refreshCalled).toBe(true);
  });

  it("renders a safe error message when loading fails, never raw backend internals", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(() =>
        Promise.resolve(
          jsonResponse({ error_code: "internal_error", message: "Unable to load market data." }, 500),
        ),
      ),
    );

    renderWithAuth(<LiveMarketDataMonitor />);

    await waitFor(() => expect(screen.getByRole("alert")).toBeInTheDocument());
    expect(screen.getByRole("alert")).toHaveTextContent("Unable to load market data.");
  });

  it("never renders any trading control or field (Checkpoint 23 §12)", async () => {
    stubEndpoints(SESSION, HEALTH_CONNECTED, [RELIANCE_QUOTE]);

    const { container } = renderWithAuth(<LiveMarketDataMonitor />);

    await waitFor(() => expect(screen.getByText("RELIANCE")).toBeInTheDocument());

    const forbiddenPatterns = [
      /\bbuy\b/i,
      /\bsell\b/i,
      /\border\b/i,
      /quantity/i,
      /stop loss/i,
      /\btarget\b/i,
      /\bposition\b/i,
      /p&l/i,
      /\bexecute\b/i,
      /\btrade\b/i,
    ];
    const text = container.textContent ?? "";
    for (const pattern of forbiddenPatterns) {
      expect(text).not.toMatch(pattern);
    }
  });
});
