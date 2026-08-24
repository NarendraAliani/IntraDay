// frontend/src/features/paper-trading/PaperSessionPanel.test.tsx
//
// Checkpoint 64.68 §9/§10: real-boundary tests for the Paper Trading
// session panel - only `global.fetch` is mocked; the real component and
// the real generated contract types are exercised together, matching
// `LivePaperOperationsConsole.test.tsx`'s established pattern.
//
// The LIVE-SAFETY tests here are the frontend half of the §10 proof
// (the backend half is `mode: "PAPER_REPLAY"`, asserted in
// `tests/unit/infrastructure/api/test_checkpoint_64_68_paper_session_api.py`).
import { fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { PaperSessionPanel } from "./PaperSessionPanel";
import { renderWithAuth } from "../../test/testAuth";
import type { components } from "@shared/generated_contracts/api-types";

type PaperSessionResponse = components["schemas"]["PaperSessionResponse"];

afterEach(() => {
  vi.unstubAllGlobals();
});

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

const ACCOUNT: PaperSessionResponse["account"] = {
  starting_capital: "1000000.0000",
  available_capital: "988000.0000",
  utilized_margin: "0.0000",
  realized_pnl: "-1250.5000",
  unrealized_pnl: "3400.0000",
  total_pnl: "2149.5000",
  equity: "1002149.5000",
  peak_equity: "1004000.0000",
  drawdown: "1850.5000",
};

const STOPPED_SESSION: PaperSessionResponse = {
  mode: "PAPER_REPLAY",
  exists: true,
  accepted: true,
  message: "",
  session_id: "default",
  status: "STOPPED",
  strategy_id: "ema_crossover",
  timeframe: "5m",
  instrument_ids: ["NSE:RELIANCE"],
  replay_date: "2026-01-05",
  replay_cursor: 0,
  replay_total_steps: 74,
  playback_speed: 5,
  quantity: "10.0000",
  available_strategy_ids: ["ema_crossover", "sma_trend_filter", "atr_volatility_breakout"],
  account: ACCOUNT,
  open_positions: [],
  closed_trades: [],
  recent_signals: [],
};

const RUNNING_SESSION: PaperSessionResponse = {
  ...STOPPED_SESSION,
  status: "RUNNING",
  message: "Paper session STOPPED -> RUNNING.",
  replay_cursor: 5,
  open_positions: [
    {
      position_id: "replay-000006",
      instrument_id: "NSE:RELIANCE",
      direction: "BUY",
      quantity: "10.0000",
      average_entry_price: "1088.2200",
      unrealized_pnl: "3400.0000",
      realized_net_pnl: "0.0000",
      status: "OPEN",
    },
  ],
  closed_trades: [
    {
      trade_id: "replay-000013",
      instrument_id: "NSE:RELIANCE",
      direction: "BUY",
      entry_price: "1088.2200",
      exit_price: "1077.5000",
      quantity: "10.0000",
      realized_pnl: "-107.2000",
      realized_net_pnl: "-125.0500",
      closed_at: "2026-01-05T09:45:00Z",
    },
  ],
  recent_signals: [
    {
      step: 4,
      bar_timestamp: "2026-01-05T09:45:00Z",
      instrument_id: "NSE:RELIANCE",
      strategy_id: "ema_crossover",
      direction: "BULLISH",
      signal_id: "abc123",
      skipped_reason: null,
      risk_outcome: "APPROVED",
      risk_reason_code: null,
      order_status: "FILLED",
    },
    {
      step: 3,
      bar_timestamp: "2026-01-05T09:40:00Z",
      instrument_id: "NSE:RELIANCE",
      strategy_id: "ema_crossover",
      direction: "BEARISH",
      signal_id: "def456",
      skipped_reason: null,
      risk_outcome: "REJECTED",
      risk_reason_code: "MAX_TOTAL_EXPOSURE_EXCEEDED",
      order_status: null,
    },
  ],
};

function withCapabilities(capabilities: string[]) {
  return {
    state: {
      status: "authenticated" as const,
      username: "operator",
      capabilities,
    },
  };
}

function stubFetch(sequence: PaperSessionResponse[]): ReturnType<typeof vi.fn> {
  let index = 0;
  const fetchMock = vi.fn(() => {
    const body = sequence[Math.min(index, sequence.length - 1)];
    index += 1;
    return Promise.resolve(jsonResponse(body));
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

describe("PaperSessionPanel", () => {
  it("renders the session status, strategy, timeframe, universe and paper account", async () => {
    stubFetch([STOPPED_SESSION]);
    renderWithAuth(<PaperSessionPanel />, withCapabilities(["configuration.activate"]));

    await waitFor(() => expect(screen.getByText("STOPPED")).toBeInTheDocument());
    // The KPI strip (not the <option> lists) - hence getAllByText.
    expect(screen.getAllByText("ema_crossover").length).toBeGreaterThan(0);
    expect(screen.getAllByText("5m").length).toBeGreaterThan(0);
    expect(screen.getAllByText("NSE:RELIANCE").length).toBeGreaterThan(0);
    expect(screen.getByText("0 / 74")).toBeInTheDocument();

    // Every §9-required account figure is on screen.
    expect(screen.getAllByText("Starting Capital (Paper)").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Available Capital (Paper)").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Equity (Paper)").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Realized P&L (Paper)").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Unrealized P&L (Paper)").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Total P&L (Paper)").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Drawdown (Paper)").length).toBeGreaterThan(0);
  });

  it("labels every control unambiguously as PAPER trading and exposes no live control", async () => {
    stubFetch([STOPPED_SESSION]);
    renderWithAuth(<PaperSessionPanel />, withCapabilities(["configuration.activate"]));

    await waitFor(() =>
      expect(screen.getByRole("button", { name: "Start Paper Trading" })).toBeInTheDocument(),
    );
    expect(screen.getByRole("button", { name: "Stop Paper Trading" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Pause Paper Trading" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Resume Paper Trading" })).toBeInTheDocument();

    // §10: no ambiguous bare "Trade" button, and no live-broker control.
    for (const button of screen.getAllByRole("button")) {
      const label = button.textContent ?? "";
      expect(label).not.toMatch(/^\s*Trade\s*$/);
      expect(label.toLowerCase()).not.toMatch(/\blive\b/);
      expect(label.toLowerCase()).not.toMatch(/place order|submit order|go live/);
    }

    const banner = screen.getByRole("note");
    expect(banner.textContent).toContain("PAPER TRADING — NOT LIVE TRADING");
    expect(banner.textContent).toContain("LIVE TRADING — NOT AVAILABLE");
    expect(banner.textContent).toContain("simulated");
  });

  it("starts paper trading and reflects the RUNNING session returned by the backend", async () => {
    const fetchMock = stubFetch([STOPPED_SESSION, RUNNING_SESSION]);
    renderWithAuth(<PaperSessionPanel />, withCapabilities(["configuration.activate"]));

    await waitFor(() =>
      expect(screen.getByRole("button", { name: "Start Paper Trading" })).toBeEnabled(),
    );
    fireEvent.click(screen.getByRole("button", { name: "Start Paper Trading" }));

    await waitFor(() => expect(screen.getByText("RUNNING")).toBeInTheDocument());
    const startCall = fetchMock.mock.calls.find(
      (call) => String(call[0]).endsWith("/paper-trading/session/start/"),
    );
    expect(startCall).toBeDefined();
    expect(screen.getByText("5 / 74")).toBeInTheDocument();
  });

  it("shows open positions, closed trades and the risk-gate outcome of each signal", async () => {
    stubFetch([RUNNING_SESSION]);
    renderWithAuth(<PaperSessionPanel />, withCapabilities(["configuration.activate"]));

    await waitFor(() => expect(screen.getByText("Open Paper Positions")).toBeInTheDocument());
    expect(screen.getByText("Closed Paper Trades")).toBeInTheDocument();
    expect(screen.getByText("Recent Paper Signals")).toBeInTheDocument();
    expect(screen.getByText("BULLISH")).toBeInTheDocument();
    expect(screen.getByText("APPROVED")).toBeInTheDocument();
    expect(screen.getByText("REJECTED (MAX_TOTAL_EXPOSURE_EXCEEDED)")).toBeInTheDocument();
    expect(screen.getByText("FILLED")).toBeInTheDocument();
  });

  it("disables reset while the session is running, matching the documented semantics", async () => {
    stubFetch([RUNNING_SESSION]);
    renderWithAuth(<PaperSessionPanel />, withCapabilities(["configuration.activate"]));

    await waitFor(() =>
      expect(screen.getByRole("button", { name: "Reset Paper Session" })).toBeDisabled(),
    );
    expect(screen.getByRole("button", { name: "Start Paper Trading" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Stop Paper Trading" })).toBeEnabled();
  });

  it("hides every control from a user without the operator capability", async () => {
    stubFetch([STOPPED_SESSION]);
    renderWithAuth(<PaperSessionPanel />, withCapabilities(["configuration.read"]));

    await waitFor(() =>
      expect(screen.getByText("You have read-only access to this screen.")).toBeInTheDocument(),
    );
    expect(screen.queryByRole("button", { name: "Start Paper Trading" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Stop Paper Trading" })).toBeNull();
  });

  it("only offers strategies the backend registry actually reports", async () => {
    stubFetch([STOPPED_SESSION]);
    renderWithAuth(<PaperSessionPanel />, withCapabilities(["configuration.activate"]));

    await waitFor(() => expect(screen.getByLabelText(/Strategy/)).toBeInTheDocument());
    const options = Array.from(
      screen.getByLabelText(/Strategy/).querySelectorAll("option"),
    ).map((option) => option.textContent);
    expect(options).toEqual([
      "ema_crossover",
      "sma_trend_filter",
      "atr_volatility_breakout",
    ]);
    // Gainz is NOT productized and must never appear as a selectable
    // paper-trading strategy.
    expect(options.join(" ")).not.toContain("gainz");
  });
});
