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
      cost_breakdown: {
        brokerage: "0.00",
        stt: "0.00",
        exchange_transaction_charges: "0.00",
        sebi_charges: "0.00",
        gst: "0.00",
        stamp_duty: "0.00",
        other_statutory_charges: "0.00",
        total: "0.00",
      },
    },
  ],
  equity_curve: [
    { timestamp: "2026-01-02T04:00:00Z", balance: "100000", cumulative_pnl: "0", drawdown: "0", drawdown_percent: "0" },
    { timestamp: "2026-01-02T04:10:00Z", balance: "100020", cumulative_pnl: "20", drawdown: "0", drawdown_percent: "0" },
  ],
  mark_to_market_curve: [
    { timestamp: "2026-01-02T04:00:00Z", realized_pnl: "0", unrealized_pnl: "0", total_equity: "100000", peak_equity: "100000", drawdown: "0", drawdown_percent: "0" },
    { timestamp: "2026-01-02T04:10:00Z", realized_pnl: "20", unrealized_pnl: "0", total_equity: "100020", peak_equity: "100020", drawdown: "0", drawdown_percent: "0" },
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
    max_drawdown_duration_bars: 0,
    average_trade: "20",
    average_winner: "20",
    average_loser: null,
    sharpe_ratio_trade_level: null,
    sortino_ratio_trade_level: null,
    final_capital: "100020",
    return_percent: "0.02",
  },
  validation: {
    bar_count: 8,
    signal_count: 3,
    trade_count: 1,
    warmup_bars: 5,
    skipped_signals: 0,
    rejected_trades: 0,
    data_gaps_note: "not computed",
  },
  trust_level: "POC",
  data_quality: {
    data_source: "fixture",
    data_quality: "FIXTURE_OR_HISTORICAL",
    bar_count: 8,
    missing_bar_note: "none",
    transaction_cost_assumption: "flat pct",
    slippage_assumption: "flat pct",
    survivorship_bias_note: "n/a",
  },
  cost_model_identity: {
    name: "FLAT_PERCENTAGE",
    version: "v1",
    effective_from: "2026-01-01",
    is_verified: false,
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

  it("shows the POC trust level and a not-a-guarantee disclaimer on results", async () => {
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
    expect(screen.getByText("POC")).toBeInTheDocument();
    expect(screen.getByText(/not guarantees of future performance/)).toBeInTheDocument();
    expect(screen.getByText("Research-Quality Validation")).toBeInTheDocument();
  });

  it("warns when data quality is SAMPLE_BAR", async () => {
    const sampleBarResult = {
      ...BACKTEST_RESULT,
      data_quality: { ...BACKTEST_RESULT.data_quality, data_quality: "SAMPLE_BAR" },
    };
    stubFetch({
      "/strategy-engine/fields/": FIELDS,
      "/strategy-engine/strategies/": STRATEGIES,
      "/strategy-engine/strategies/ema_crossover/schema/": SCHEMA,
      "/backtesting/run/": sampleBarResult,
    });
    renderWithAuth(<BacktestingWorkbenchPage />);
    await waitFor(() => expect(screen.getByText("EMA Crossover")).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: "Configure" }));
    await waitFor(() => expect(screen.getByLabelText(/Fast EMA Lookback/)).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: "Run Backtest" }));

    await waitFor(() =>
      expect(screen.getByText(/NOT SUITABLE FOR TRADING-GRADE/)).toBeInTheDocument(),
    );
  });

  it("View expands strategy details showing parameter count", async () => {
    stubFetch({
      "/strategy-engine/fields/": FIELDS,
      "/strategy-engine/strategies/": STRATEGIES,
      "/strategy-engine/strategies/ema_crossover/schema/": SCHEMA,
    });
    renderWithAuth(<BacktestingWorkbenchPage />);
    await waitFor(() => expect(screen.getByText("EMA Crossover")).toBeInTheDocument());

    const viewButtons = screen.getAllByRole("button", { name: "View" });
    fireEvent.click(viewButtons[0]);

    await waitFor(() =>
      expect(screen.getByText("Parameters:", { exact: false })).toBeInTheDocument(),
    );
    expect(screen.getByText("Fast EMA Lookback")).toBeInTheDocument();
  });

  it("lets the user choose the verified Indian cost model and shows the VERIFIED badge in results", async () => {
    const indianResult = {
      ...BACKTEST_RESULT,
      cost_model_identity: {
        name: "INDIAN_CASH_EQUITY_INTRADAY",
        version: "v1",
        effective_from: "2026-08-14",
        is_verified: true,
      },
    };
    stubFetch({
      "/strategy-engine/fields/": FIELDS,
      "/strategy-engine/strategies/": STRATEGIES,
      "/strategy-engine/strategies/ema_crossover/schema/": SCHEMA,
      "/backtesting/run/": indianResult,
    });
    renderWithAuth(<BacktestingWorkbenchPage />);
    await waitFor(() => expect(screen.getByText("EMA Crossover")).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: "Configure" }));
    await waitFor(() => expect(screen.getByLabelText(/Fast EMA Lookback/)).toBeInTheDocument());

    fireEvent.change(screen.getByLabelText("Cost Model"), {
      target: { value: "INDIAN_CASH_EQUITY_INTRADAY" },
    });
    expect(screen.getByText("VERIFIED COST MODEL")).toBeInTheDocument();
    // the Flat-Percentage-only brokerage field must disappear once the
    // verified model is selected (it does not use that assumption).
    expect(screen.queryByLabelText(/Brokerage \(%/)).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Run Backtest" }));
    await waitFor(() => expect(screen.getAllByText("VERIFIED COST MODEL").length).toBeGreaterThan(0));
    expect(screen.getByText(/INDIAN_CASH_EQUITY_INTRADAY/)).toBeInTheDocument();
  });

  it("shows an expandable per-trade cost breakdown", async () => {
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

    await waitFor(() => expect(screen.getByText("ema_crossover-1")).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: "Details" }));
    expect(screen.getByText("Brokerage")).toBeInTheDocument();
    expect(screen.getByText("STT")).toBeInTheDocument();
    expect(screen.getByText("GST")).toBeInTheDocument();
  });

  it("shows the DB-first historical run panel with a real data-readiness preview", async () => {
    stubFetch({
      "/strategy-engine/fields/": FIELDS,
      "/strategy-engine/strategies/": STRATEGIES,
      "/strategy-engine/strategies/ema_crossover/schema/": SCHEMA,
      "/market-data/quotes/": [
        {
          symbol: "RELIANCE",
          exchange: "NSE",
          last_price: "1234.56",
          source_timestamp: "2026-08-14T06:00:00Z",
          freshness_age_seconds: 5,
          is_stale: false,
        },
      ],
      "/backtesting/coverage-preview/": {
        instruments: [
          {
            instrument_id: "NSE:RELIANCE",
            coverage_percent: 0,
            expected_bar_count: 75,
            cached_bar_count: 0,
            is_complete: false,
            missing_range_count: 1,
          },
        ],
        overall_coverage_percent: 0,
      },
    });
    renderWithAuth(<BacktestingWorkbenchPage />);
    await waitFor(() => expect(screen.getByText("EMA Crossover")).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: "Configure" }));
    await waitFor(() => expect(screen.getByLabelText(/Fast EMA Lookback/)).toBeInTheDocument());
    await waitFor(() =>
      expect(screen.getAllByText("NSE:RELIANCE").length).toBeGreaterThan(0),
    );
    fireEvent.click(screen.getAllByRole("checkbox", { name: "NSE:RELIANCE" })[0]);

    fireEvent.click(screen.getByRole("button", { name: "Check Data Readiness" }));

    await waitFor(() => expect(screen.getByText("FETCH REQUIRED")).toBeInTheDocument());
  });

  it("polls real backend progress after starting a historical run - never a fake timer-driven bar", async () => {
    let pollCount = 0;
    function progressPayload(): unknown {
      pollCount += 1;
      const complete = pollCount >= 2;
      return {
        run_id: "run-1",
        status: complete ? "COMPLETED" : "RUNNING",
        phase: complete ? "COMPLETED" : "SCANNING",
        progress_percent: complete ? 100 : 50,
        current_instrument: "NSE:RELIANCE",
        current_strategy: "ema_crossover",
        message: complete ? "Backtest run completed" : "Scanning NSE:RELIANCE",
        total_instruments: 1,
        completed_instruments: complete ? 1 : 0,
        total_bars: 75,
        scanned_bars: complete ? 75 : 30,
        signals_generated: 2,
        cache_hits: 0,
        cache_misses: 75,
        api_requests: 1,
        failed_instruments: [],
        result_backtest_ids: complete ? { "NSE:RELIANCE": "abc123" } : {},
        error_message: "",
        created_at: "2026-08-17T06:00:00Z",
        started_at: "2026-08-17T06:00:00Z",
        completed_at: complete ? "2026-08-17T06:01:00Z" : null,
        elapsed_seconds: 12,
        eta_seconds: complete ? null : 5,
      };
    }
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
        const url = typeof input === "string" ? input : input.toString();
        const method = init?.method ?? "GET";
        if (url.includes("/strategy-engine/fields/")) return jsonResponse(FIELDS);
        if (url.includes("/strategy-engine/strategies/ema_crossover/schema/")) return jsonResponse(SCHEMA);
        if (url.endsWith("/strategy-engine/strategies/")) return jsonResponse(STRATEGIES);
        if (url.includes("/market-data/quotes/")) {
          return jsonResponse([
            {
              symbol: "RELIANCE",
              exchange: "NSE",
              last_price: "1234.56",
              source_timestamp: "2026-08-14T06:00:00Z",
              freshness_age_seconds: 5,
              is_stale: false,
            },
          ]);
        }
        if (url.includes("/progress/")) return jsonResponse(progressPayload());
        if (method === "POST" && url.endsWith("/backtesting/historical-runs/")) {
          return jsonResponse({ run_id: "run-1" });
        }
        return jsonResponse({ error_code: "not_found", message: "no route" }, 404);
      }),
    );
    renderWithAuth(<BacktestingWorkbenchPage />);
    await waitFor(() => expect(screen.getByText("EMA Crossover")).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: "Configure" }));
    await waitFor(() => expect(screen.getByLabelText(/Fast EMA Lookback/)).toBeInTheDocument());
    await waitFor(() =>
      expect(screen.getAllByText("NSE:RELIANCE").length).toBeGreaterThan(0),
    );
    fireEvent.click(screen.getAllByRole("checkbox", { name: "NSE:RELIANCE" })[0]);

    fireEvent.click(screen.getByRole("button", { name: "Prepare Data & Start Backtest" }));

    await waitFor(() => expect(screen.getByText("DATABASE ONLY")).toBeInTheDocument());
    await waitFor(() => expect(screen.getByText("COMPLETED")).toBeInTheDocument(), { timeout: 5000 });
    expect(screen.getByText("2")).toBeInTheDocument(); // signals_generated rendered from real backend state
  });
});
