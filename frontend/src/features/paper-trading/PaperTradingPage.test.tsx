// frontend/src/features/paper-trading/PaperTradingPage.test.tsx
//
// Checkpoint 34/35: real-boundary tests for the Paper Trading page -
// only `global.fetch` is mocked (routed by URL, mirroring
// LiveMarketDataMonitor.test.tsx's own established pattern since this
// page now fetches five endpoints in parallel); the real generated
// contract types and the real component are exercised together.
// Explicitly proves PAPER vs LIVE distinction and that no LIVE control
// exists anywhere.
import { fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { PaperTradingPage } from "./PaperTradingPage";
import { renderWithAuth } from "../../test/testAuth";
import type { components } from "@shared/generated_contracts/api-types";

type KillSwitchStatusResponse = components["schemas"]["KillSwitchStatusResponse"];
type PaperOrderResponse = components["schemas"]["PaperOrderResponse"];
type PaperFundsResponse = components["schemas"]["PaperFundsResponse"];

afterEach(() => {
  vi.unstubAllGlobals();
});

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

const ACTIVE: KillSwitchStatusResponse = { status: "ACTIVE", reason: null, changed_at: null };
const HALTED: KillSwitchStatusResponse = {
  status: "HALTED",
  reason: "manual halt",
  changed_at: "2026-08-14T09:00:00Z",
};

const FUNDS: PaperFundsResponse = {
  available_balance: "1000000.0000",
  utilized_margin: "0.0000",
  updated_at: "2026-08-14T09:00:00Z",
};

const ORDER: PaperOrderResponse = {
  order_id: "ord-1",
  idempotency_key: "idem-1",
  correlation_id: "idem-1",
  instrument_id: "NSE:RELIANCE",
  strategy_id: "orb-v1",
  side: "BUY",
  order_type: "MARKET",
  quantity: "10.0000",
  filled_quantity: "10.0000",
  limit_price: null,
  trigger_price: null,
  status: "FILLED",
  created_at: "2026-08-14T09:00:00Z",
  updated_at: "2026-08-14T09:00:00Z",
  state_history: [],
};

function stubEndpoints(
  killSwitch: KillSwitchStatusResponse,
  orders: PaperOrderResponse[] = [],
): ReturnType<typeof vi.fn> {
  const fetchMock = vi.fn((input: RequestInfo | URL) => {
    const url = String(input);
    if (url.includes("/kill-switch/")) return Promise.resolve(jsonResponse(killSwitch));
    if (url.includes("/paper-trading/orders/")) return Promise.resolve(jsonResponse(orders));
    if (url.includes("/paper-trading/trades/")) return Promise.resolve(jsonResponse([]));
    if (url.includes("/paper-trading/positions/")) return Promise.resolve(jsonResponse([]));
    if (url.includes("/paper-trading/funds/")) return Promise.resolve(jsonResponse(FUNDS));
    return Promise.resolve(jsonResponse({}, 404));
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

const READER_AUTH = {
  state: {
    status: "authenticated" as const,
    username: "reader",
    capabilities: ["configuration.read"],
  },
};

const OPERATOR_AUTH = {
  state: {
    status: "authenticated" as const,
    username: "operator",
    capabilities: ["configuration.read", "configuration.activate"],
  },
};

describe("PaperTradingPage", () => {
  it("shows a PAPER MODE banner and never shows a LIVE control", async () => {
    stubEndpoints(ACTIVE);
    renderWithAuth(<PaperTradingPage />, READER_AUTH);
    await waitFor(() => expect(screen.getByText(/PAPER MODE/)).toBeInTheDocument());
    expect(screen.getByText(/LIVE TRADING — NOT AVAILABLE/)).toBeInTheDocument();
    expect(screen.queryByText("Enable Live Trading")).not.toBeInTheDocument();
  });

  it("shows kill switch status as Active by default", async () => {
    stubEndpoints(ACTIVE);
    renderWithAuth(<PaperTradingPage />, READER_AUTH);
    await waitFor(() => expect(screen.getByTitle("Kill switch not engaged")).toBeInTheDocument());
  });

  it("shows HALTED status and reason when engaged", async () => {
    stubEndpoints(HALTED);
    renderWithAuth(<PaperTradingPage />, READER_AUTH);
    await waitFor(() => expect(screen.getByTitle("Kill switch engaged")).toBeInTheDocument());
    expect(screen.getByText("manual halt")).toBeInTheDocument();
  });

  it("read-only users cannot see engage/reset controls or the order form", async () => {
    stubEndpoints(ACTIVE);
    renderWithAuth(<PaperTradingPage />, READER_AUTH);
    await waitFor(() => expect(screen.getByTitle("Kill switch not engaged")).toBeInTheDocument());
    expect(screen.queryByText("Engage Kill Switch")).not.toBeInTheDocument();
    expect(screen.queryByText("Submit Paper Order")).not.toBeInTheDocument();
    expect(screen.getByText(/read-only access/)).toBeInTheDocument();
  });

  it("operators can engage the kill switch", async () => {
    const fetchMock = stubEndpoints(ACTIVE);
    renderWithAuth(<PaperTradingPage />, OPERATOR_AUTH);
    await waitFor(() => expect(screen.getByTitle("Kill switch not engaged")).toBeInTheDocument());

    fetchMock.mockImplementation((input: RequestInfo | URL) => {
      const url = String(input);
      if (url.includes("/kill-switch/engage/")) return Promise.resolve(jsonResponse(HALTED));
      if (url.includes("/kill-switch/")) return Promise.resolve(jsonResponse(HALTED));
      if (url.includes("/paper-trading/orders/")) return Promise.resolve(jsonResponse([]));
      if (url.includes("/paper-trading/trades/")) return Promise.resolve(jsonResponse([]));
      if (url.includes("/paper-trading/positions/")) return Promise.resolve(jsonResponse([]));
      if (url.includes("/paper-trading/funds/")) return Promise.resolve(jsonResponse(FUNDS));
      return Promise.resolve(jsonResponse({}, 404));
    });

    fireEvent.change(screen.getByLabelText("Reason for halting"), {
      target: { value: "manual halt" },
    });
    fireEvent.click(screen.getByText("Engage Kill Switch"));

    await waitFor(() => expect(screen.getByTitle("Kill switch engaged")).toBeInTheDocument());
  });

  it("never renders a bare, ambiguous trading control", async () => {
    stubEndpoints(ACTIVE);
    renderWithAuth(<PaperTradingPage />, READER_AUTH);
    await waitFor(() => expect(screen.getByTitle("Kill switch not engaged")).toBeInTheDocument());
    for (const forbidden of ["Buy", "Sell", "Place Order"]) {
      expect(screen.queryByText(forbidden)).not.toBeInTheDocument();
    }
  });

  it("shows the order-entry form for operators, labeled unambiguously", async () => {
    stubEndpoints(ACTIVE);
    renderWithAuth(<PaperTradingPage />, OPERATOR_AUTH);
    await waitFor(() =>
      expect(screen.getAllByText("Submit Paper Order").length).toBeGreaterThan(0),
    );
  });

  it("renders submitted paper orders in the monitor table", async () => {
    stubEndpoints(ACTIVE, [ORDER]);
    renderWithAuth(<PaperTradingPage />, READER_AUTH);
    await waitFor(() => expect(screen.getByText("NSE:RELIANCE")).toBeInTheDocument());
    expect(screen.getByText("FILLED")).toBeInTheDocument();
  });

  it("shows available capital from the funds endpoint", async () => {
    stubEndpoints(ACTIVE);
    renderWithAuth(<PaperTradingPage />, READER_AUTH);
    await waitFor(() =>
      expect(screen.getByText("₹1000000.0000")).toBeInTheDocument(),
    );
  });
});
