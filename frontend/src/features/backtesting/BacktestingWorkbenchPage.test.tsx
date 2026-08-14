// frontend/src/features/backtesting/BacktestingWorkbenchPage.test.tsx
//
// Checkpoint 27 Part 30/31: real-boundary tests for the Backtesting
// Workbench - only `global.fetch` is mocked; the real generated
// contract types, the real backtestingApi.ts/strategyApi.ts client
// functions, and the real component are exercised together.
import { fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { BacktestingWorkbenchPage } from "./BacktestingWorkbenchPage";
import { renderWithAuth } from "../../test/testAuth";
import type { components } from "@shared/generated_contracts/api-types";

type FieldDefinition = components["schemas"]["FieldDefinition"];
type StrategySummary = components["schemas"]["StrategySummary"];
type StrategySchema = components["schemas"]["StrategySchema"];

afterEach(() => {
  vi.unstubAllGlobals();
});

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

const FIELDS: FieldDefinition[] = [];

const STRATEGIES: StrategySummary[] = [
  {
    strategy_id: "ema_crossover",
    display_name: "EMA Crossover",
    specification_version: "v1",
    code_version: "v1",
    is_active: false,
  },
];

const SCHEMA: StrategySchema = {
  strategy_id: "ema_crossover",
  parameters: [
    {
      parameter_id: "fast_lookback",
      label: "Fast EMA Lookback",
      parameter_type: "INTEGER",
      required: true,
      default: 3,
      minimum: "1",
      maximum: "200",
      allowed_values: [],
      field_category: null,
      depends_on: [],
      help_text: "",
    },
    {
      parameter_id: "slow_lookback",
      label: "Slow EMA Lookback",
      parameter_type: "INTEGER",
      required: true,
      default: 6,
      minimum: "2",
      maximum: "400",
      allowed_values: [],
      field_category: null,
      depends_on: [],
      help_text: "",
    },
  ],
};

const BACKTEST_RESULT = {
  backtest_id: "abc123",
  generated_at: "2026-08-14T06:00:00Z",
  configuration: {
    instrument_id: "NSE:FIXTURE01",
    timeframe: "5m",
    initial_capital: "100000",
  },
  trades: [
    {
      trade_id: "ema_crossover-1",
      strategy_id: "ema_crossover",
      direction: "BULLISH",
      entry_timestamp: "2026-01-02T04:00:00Z",
      exit_timestamp: "2026-01-02T04:10:00Z",
      entry_price: "100.00",
      exit_price: "102.00",
      quantity: "10",
      gross_pnl: "20.00",
      costs: "0.00",
      net_pnl: "20.00",
      reason: "signal_reversal",
    },
  ],
  equity_curve: [
    { timestamp: "2026-01-02T04:00:00Z", balance: "100000", cumulative_pnl: "0", drawdown: "0", drawdown_percent: "0" },
    { timestamp: "2026-01-02T04:10:00Z", balance: "100020", cumulative_pnl: "20", drawdown: "0", drawdown_percent: "0" },
  ],
  metrics: {
    total_trades: 1,
    winning_trades: 1,
    losing_trades: 0,
    win_rate_percent: "100",
    gross_profit: "20",
    gross_loss: "0",
    net_pnl: "20",
    profit_factor: null,
    max_drawdown: "0",
    max_drawdown_percent: "0",
    average_trade: "20",
    average_winner: "20",
    average_loser: null,
    sharpe_ratio_trade_level: null,
    sortino_ratio_trade_level: null,
    final_capital: "100020",
    return_percent: "0.02",
  },
  data_quality: {
    data_source: "fixture",
    data_quality: "FIXTURE_OR_HISTORICAL",
    bar_count: 8,
    missing_bar_note: "none",
    transaction_cost_assumption: "flat pct",
    slippage_assumption: "flat pct",
    survivorship_bias_note: "n/a",
  },
};

function stubFetch(routes: Record<string, unknown>): void {
  const sortedRoutes = Object.entries(routes).sort((a, b) => b[0].length - a[0].length);
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = typeof input === "string" ? input : input.toString();
      for (const [path, body] of sortedRoutes) {
        if (url.includes(path)) {
          return jsonResponse(typeof body === "function" ? (body as () => unknown)() : body);
        }
      }
      void init;
      return jsonResponse({ error_code: "not_found", message: "no route" }, 404);
    }),
  );
}

describe("BacktestingWorkbenchPage", () => {
  it("shows the strategy library (Discover) with View/Configure/Backtest actions", async () => {
    stubFetch({
      "/strategy-engine/fields/": FIELDS,
      "/strategy-engine/strategies/": STRATEGIES,
    });
    renderWithAuth(<BacktestingWorkbenchPage />);

    await waitFor(() => expect(screen.getByText("EMA Crossover")).toBeInTheDocument());
    expect(screen.getByRole("button", { name: "Configure" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Backtest" })).toBeInTheDocument();
  });

  it("never renders live-trading controls anywhere on the page", async () => {
    stubFetch({
      "/strategy-engine/fields/": FIELDS,
      "/strategy-engine/strategies/": STRATEGIES,
    });
    renderWithAuth(<BacktestingWorkbenchPage />);
    await waitFor(() => expect(screen.getByText("EMA Crossover")).toBeInTheDocument());

    const bodyText = document.body.textContent ?? "";
    for (const forbidden of ["Buy", "Sell", "Deploy Live", "Place Order"]) {
      expect(bodyText).not.toContain(forbidden);
    }
  });

  it("configures using the SAME schema-driven parameter renderer (reuse, not duplication)", async () => {
    stubFetch({
      "/strategy-engine/fields/": FIELDS,
      "/strategy-engine/strategies/": STRATEGIES,
      "/strategy-engine/strategies/ema_crossover/schema/": SCHEMA,
    });
    renderWithAuth(<BacktestingWorkbenchPage />);
    await waitFor(() => expect(screen.getByText("EMA Crossover")).toBeInTheDocument());

    fireEvent.click(screen.getByRole("button", { name: "Configure" }));

    await waitFor(() => expect(screen.getByLabelText(/Fast EMA Lookback/)).toBeInTheDocument());
    expect(screen.getByLabelText(/Slow EMA Lookback/)).toBeInTheDocument();
    expect(screen.getByLabelText("Instrument")).toBeInTheDocument();
  });

  it("runs a backtest and renders KPIs, charts, data-quality disclosure, and the trade ledger", async () => {
    stubFetch({
      "/strategy-engine/fields/": FIELDS,
      "/strategy-engine/strategies/": STRATEGIES,
      "/strategy-engine/strategies/ema_crossover/schema/": SCHEMA,
      "/backtesting/run/": BACKTEST_RESULT,
    });
    renderWithAuth(<BacktestingWorkbenchPage />);
    await waitFor(() => expect(screen.getByText("EMA Crossover")).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: "Configure" }));
    await waitFor(() => expect(screen.getByLabelText(/Fast EMA Lookback/)).toBeInTheDocument());

    fireEvent.click(screen.getByRole("button", { name: "Run Backtest" }));

    await waitFor(() => expect(screen.getByText("Results")).toBeInTheDocument());
    expect(screen.getAllByText("Net P&L").length).toBeGreaterThan(0);
    expect(screen.getByText("Equity Curve")).toBeInTheDocument();
    expect(screen.getByText("Drawdown Curve (%)")).toBeInTheDocument();
    expect(screen.getByText("Data Quality & Assumptions")).toBeInTheDocument();
    expect(screen.getByText("ema_crossover-1")).toBeInTheDocument();
  });

  it("shows a failed state when the run request errors", async () => {
    stubFetch({
      "/strategy-engine/fields/": FIELDS,
      "/strategy-engine/strategies/": STRATEGIES,
      "/strategy-engine/strategies/ema_crossover/schema/": SCHEMA,
    });
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL) => {
        const url = typeof input === "string" ? input : input.toString();
        if (url.includes("/strategy-engine/fields/")) return jsonResponse(FIELDS);
        if (url.includes("/strategy-engine/strategies/ema_crossover/schema/")) return jsonResponse(SCHEMA);
        if (url.endsWith("/strategy-engine/strategies/")) return jsonResponse(STRATEGIES);
        if (url.includes("/backtesting/run/")) {
          return jsonResponse({ error_code: "invalid_configuration", message: "bad config" }, 400);
        }
        return jsonResponse({ error_code: "not_found", message: "no route" }, 404);
      }),
    );
    renderWithAuth(<BacktestingWorkbenchPage />);
    await waitFor(() => expect(screen.getByText("EMA Crossover")).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: "Configure" }));
    await waitFor(() => expect(screen.getByLabelText(/Fast EMA Lookback/)).toBeInTheDocument());

    fireEvent.click(screen.getByRole("button", { name: "Run Backtest" }));

    await waitFor(() => expect(screen.getByText("bad config")).toBeInTheDocument());
  });

  it("hides Run Backtest for users without configuration.activate", async () => {
    stubFetch({
      "/strategy-engine/fields/": FIELDS,
      "/strategy-engine/strategies/": STRATEGIES,
      "/strategy-engine/strategies/ema_crossover/schema/": SCHEMA,
    });
    renderWithAuth(<BacktestingWorkbenchPage />, {
      state: { status: "authenticated", username: "reader", capabilities: ["configuration.read"] },
    });
    await waitFor(() => expect(screen.getByText("EMA Crossover")).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: "Configure" }));
    await waitFor(() => expect(screen.getByLabelText(/Fast EMA Lookback/)).toBeInTheDocument());

    expect(screen.queryByRole("button", { name: "Run Backtest" })).not.toBeInTheDocument();
    expect(screen.getByText(/configuration-operator role/)).toBeInTheDocument();
  });
});
