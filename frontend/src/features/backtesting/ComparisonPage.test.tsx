// frontend/src/features/backtesting/ComparisonPage.test.tsx
import { fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ComparisonPage } from "./ComparisonPage";
import { renderWithAuth } from "../../test/testAuth";

afterEach(() => {
  vi.unstubAllGlobals();
});

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

const STRATEGIES = [
  {
    strategy_id: "ema_crossover",
    display_name: "EMA Crossover",
    specification_version: "v1",
    code_version: "v1",
    is_active: false,
  },
];

function result(id: string, netPnl: string, instrument = "NSE:FIXTURE01", timeframe = "5m") {
  return {
    backtest_id: id,
    generated_at: "2026-08-14T06:00:00Z",
    configuration: { instrument_id: instrument, timeframe, initial_capital: "100000" },
    trades: [],
    equity_curve: [],
    metrics: {
      total_trades: 3,
      winning_trades: 2,
      losing_trades: 1,
      win_rate_percent: "66.67",
      gross_profit: "100",
      gross_loss: "-40",
      net_pnl: netPnl,
      profit_factor: "2.5",
      max_drawdown: "10",
      max_drawdown_percent: "1",
      average_trade: "20",
      average_winner: "50",
      average_loser: "-40",
      sharpe_ratio_trade_level: "1.2",
      sortino_ratio_trade_level: "1.5",
      final_capital: "100060",
      return_percent: "0.06",
    },
    data_quality: {
      data_source: "fixture",
      data_quality: "FIXTURE_OR_HISTORICAL",
      bar_count: 20,
      missing_bar_note: "none",
      transaction_cost_assumption: "flat pct",
      slippage_assumption: "flat pct",
      survivorship_bias_note: "n/a",
    },
  };
}

describe("ComparisonPage", () => {
  it("lists past results for a strategy and compares selected ones", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL) => {
        const url = typeof input === "string" ? input : input.toString();
        if (url.endsWith("/strategy-engine/strategies/")) return jsonResponse(STRATEGIES);
        if (url.includes("/backtesting/strategies/ema_crossover/results/")) {
          return jsonResponse([result("bt-aaaaaaaaaaaa", "60"), result("bt-bbbbbbbbbbbb", "10")]);
        }
        return jsonResponse({ error_code: "not_found", message: "no route" }, 404);
      }),
    );
    renderWithAuth(<ComparisonPage />);

    await waitFor(() => expect(screen.getByText(/bt-aaaaaaaaa/)).toBeInTheDocument());

    const checkboxes = screen.getAllByRole("checkbox");
    fireEvent.click(checkboxes[0]);
    fireEvent.click(checkboxes[1]);

    await waitFor(() => expect(screen.getByText("60")).toBeInTheDocument());
  });

  it("warns when comparing results from different instruments", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL) => {
        const url = typeof input === "string" ? input : input.toString();
        if (url.endsWith("/strategy-engine/strategies/")) return jsonResponse(STRATEGIES);
        if (url.includes("/backtesting/strategies/ema_crossover/results/")) {
          return jsonResponse([
            result("bt-cccccccccccc", "60", "NSE:FIXTURE01"),
            result("bt-dddddddddddd", "10", "NSE:TESTCO"),
          ]);
        }
        return jsonResponse({ error_code: "not_found", message: "no route" }, 404);
      }),
    );
    renderWithAuth(<ComparisonPage />);
    await waitFor(() => expect(screen.getByText(/bt-ccccccccc/)).toBeInTheDocument());

    const checkboxes = screen.getAllByRole("checkbox");
    fireEvent.click(checkboxes[0]);
    fireEvent.click(checkboxes[1]);

    await waitFor(() =>
      expect(screen.getByText(/different instruments\/timeframes/)).toBeInTheDocument(),
    );
  });
});
