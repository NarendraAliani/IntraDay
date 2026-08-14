// frontend/src/features/backtesting/BacktestingWorkbenchPage.tsx
//
// Checkpoint 27: Discover -> Configure -> Backtest -> Review workflow
// (Parts 12-16). ONE page, three internal views (discover/configure/
// results), never "Buy"/"Sell"/"Deploy Live" anywhere (Part 34).
// Reuses the SAME schema-driven parameter renderer
// (`ParameterSchemaFields`) Checkpoint 26's Strategy Configuration
// screen already uses - no duplicated strategy fields (Part 14).
import { useEffect, useMemo, useState } from "react";

import { ApiNetworkError, ApiRequestError } from "../../common/api/client";
import { useAuth } from "../../common/auth/AuthContext";
import {
  ParameterSchemaFields,
  defaultValuesFor,
} from "../../common/components/ParameterSchemaFields";
import { DrawdownChart, EquityCurveChart } from "../../common/components/EquityChart";
import { ErrorState } from "../../common/components/ErrorState";
import { LoadingState } from "../../common/components/LoadingState";
import { asConfigurationView, asDataQualityView, runBacktest } from "../../common/api/backtestingApi";
import {
  getFieldRegistry,
  getStrategySchema,
  listStrategies,
} from "../../common/api/strategyApi";
import type { BacktestResult } from "../../common/api/backtestingApi";
import type { FieldDefinition, StrategySchema, StrategySummary } from "../../common/api/strategyApi";

type View = "discover" | "configure";
type RunState =
  | { phase: "ready" }
  | { phase: "running" }
  | { phase: "completed"; result: BacktestResult }
  | { phase: "failed"; message: string };

function describeError(error: unknown): string {
  if (error instanceof ApiRequestError || error instanceof ApiNetworkError) {
    return error.message;
  }
  return "An unexpected error occurred.";
}

function formatMoney(value: string | null | undefined): string {
  if (value === null || value === undefined) return "—";
  const parsed = Number.parseFloat(value);
  return Number.isFinite(parsed) ? `₹${parsed.toFixed(2)}` : "—";
}

function formatPercent(value: string | null | undefined): string {
  if (value === null || value === undefined) return "—";
  const parsed = Number.parseFloat(value);
  return Number.isFinite(parsed) ? `${parsed.toFixed(2)}%` : "—";
}

export function BacktestingWorkbenchPage(): JSX.Element {
  const { state: authState } = useAuth();
  const canRun =
    authState.status === "authenticated" &&
    authState.capabilities.includes("configuration.activate");

  const [view, setView] = useState<View>("discover");
  const [strategies, setStrategies] = useState<StrategySummary[] | null>(null);
  const [fields, setFields] = useState<FieldDefinition[]>([]);
  const [loadError, setLoadError] = useState<string | null>(null);

  const [selectedStrategyId, setSelectedStrategyId] = useState<string | null>(null);
  const [schema, setSchema] = useState<StrategySchema | null>(null);
  const [values, setValues] = useState<Record<string, string>>({});

  const [instrumentId, setInstrumentId] = useState("NSE:FIXTURE01");
  const [timeframe, setTimeframe] = useState("5m");
  const [start, setStart] = useState("2026-01-02T03:00");
  const [end, setEnd] = useState("2026-01-02T06:00");
  const [initialCapital, setInitialCapital] = useState("100000");
  const [positionSizingMode, setPositionSizingMode] = useState<"FIXED_QUANTITY" | "PERCENT_OF_EQUITY">(
    "FIXED_QUANTITY",
  );
  const [positionSizeValue, setPositionSizeValue] = useState("10");
  const [brokeragePercent, setBrokeragePercent] = useState("0");
  const [slippagePercent, setSlippagePercent] = useState("0");

  const [runState, setRunState] = useState<RunState>({ phase: "ready" });

  useEffect(() => {
    let cancelled = false;
    async function load(): Promise<void> {
      try {
        const [strategyList, fieldList] = await Promise.all([listStrategies(), getFieldRegistry()]);
        if (cancelled) return;
        setStrategies(strategyList);
        setFields(fieldList);
      } catch (error) {
        if (cancelled) return;
        setLoadError(describeError(error));
      }
    }
    void load();
    return () => {
      cancelled = true;
    };
  }, []);

  const selectedStrategy = useMemo(
    () => strategies?.find((s) => s.strategy_id === selectedStrategyId),
    [strategies, selectedStrategyId],
  );

  async function openConfigure(strategyId: string): Promise<void> {
    setSelectedStrategyId(strategyId);
    setRunState({ phase: "ready" });
    setView("configure");
    try {
      const strategySchema = await getStrategySchema(strategyId);
      setSchema(strategySchema);
      setValues(defaultValuesFor(strategySchema.parameters));
    } catch (error) {
      setLoadError(describeError(error));
    }
  }

  async function handleRun(): Promise<void> {
    if (!schema || !selectedStrategy) return;
    setRunState({ phase: "running" });
    try {
      const parsedValues: Record<string, unknown> = {};
      for (const parameter of schema.parameters) {
        const raw = values[parameter.parameter_id];
        if (raw === undefined || raw === "") continue;
        parsedValues[parameter.parameter_id] =
          parameter.parameter_type === "INTEGER" ? Number.parseInt(raw, 10) : raw;
      }
      const result = await runBacktest({
        instrument_id: instrumentId,
        timeframe,
        start: new Date(start).toISOString(),
        end: new Date(end).toISOString(),
        strategy_id: selectedStrategy.strategy_id,
        specification_version: selectedStrategy.specification_version,
        code_version: selectedStrategy.code_version,
        configuration_version: `workbench-${Date.now()}`,
        strategy_values: parsedValues,
        initial_capital: initialCapital,
        position_sizing_mode: positionSizingMode,
        position_size_value: positionSizeValue,
        brokerage_percent: brokeragePercent,
        slippage_percent: slippagePercent,
      });
      setRunState({ phase: "completed", result });
    } catch (error) {
      setRunState({ phase: "failed", message: describeError(error) });
    }
  }

  if (loadError) return <ErrorState message={loadError} />;
  if (!strategies) return <LoadingState label="Loading strategy library…" />;

  return (
    <div className="backtest-workbench">
      <h1>Strategy Backtesting</h1>
      <p className="configuration-viewer__subtitle">
        Discover a strategy, configure it, and run a backtest against fixture/historical bars.
        Results here are research/backtest output only - they never place an order and never
        authorize live trading.
      </p>

      {view === "discover" && (
        <section className="backtest-workbench__library" aria-label="Strategy Library">
          <div className="backtest-workbench__cards">
            {strategies.map((strategy) => (
              <article className="backtest-workbench__card" key={strategy.strategy_id}>
                <h2>{strategy.display_name}</h2>
                <dl>
                  <dt>Version</dt>
                  <dd>
                    {strategy.specification_version} / {strategy.code_version}
                  </dd>
                  <dt>Status</dt>
                  <dd>{strategy.is_active ? "Active for research" : "Registered"}</dd>
                </dl>
                <div className="backtest-workbench__card-actions">
                  <button type="button" onClick={() => void openConfigure(strategy.strategy_id)}>
                    Configure
                  </button>
                  <button type="button" onClick={() => void openConfigure(strategy.strategy_id)}>
                    Backtest
                  </button>
                </div>
              </article>
            ))}
          </div>
        </section>
      )}

      {view === "configure" && schema && selectedStrategy && (
        <section className="backtest-workbench__configure" aria-label="Configure Backtest">
          <button type="button" onClick={() => setView("discover")}>
            ← Back to Discover
          </button>
          <h2>{selectedStrategy.display_name}</h2>

          <form
            onSubmit={(e) => {
              e.preventDefault();
              void handleRun();
            }}
          >
            <fieldset>
              <legend>Strategy Parameters</legend>
              <ParameterSchemaFields
                parameters={schema.parameters}
                values={values}
                onChange={(id, next) => setValues((prev) => ({ ...prev, [id]: next }))}
                fields={fields}
              />
            </fieldset>

            <fieldset>
              <legend>Backtest Settings</legend>
              <div className="strategy-config-page__field">
                <label htmlFor="bt-instrument">Instrument</label>
                <input
                  id="bt-instrument"
                  value={instrumentId}
                  onChange={(e) => setInstrumentId(e.target.value)}
                />
              </div>
              <div className="strategy-config-page__field">
                <label htmlFor="bt-timeframe">Timeframe</label>
                <input id="bt-timeframe" value={timeframe} onChange={(e) => setTimeframe(e.target.value)} />
              </div>
              <div className="strategy-config-page__field">
                <label htmlFor="bt-start">Start</label>
                <input
                  id="bt-start"
                  type="datetime-local"
                  value={start}
                  onChange={(e) => setStart(e.target.value)}
                />
              </div>
              <div className="strategy-config-page__field">
                <label htmlFor="bt-end">End</label>
                <input
                  id="bt-end"
                  type="datetime-local"
                  value={end}
                  onChange={(e) => setEnd(e.target.value)}
                />
              </div>
              <div className="strategy-config-page__field">
                <label htmlFor="bt-capital">Initial Capital</label>
                <input
                  id="bt-capital"
                  type="number"
                  value={initialCapital}
                  onChange={(e) => setInitialCapital(e.target.value)}
                />
              </div>
              <div className="strategy-config-page__field">
                <label htmlFor="bt-sizing-mode">Position Size Model</label>
                <select
                  id="bt-sizing-mode"
                  value={positionSizingMode}
                  onChange={(e) =>
                    setPositionSizingMode(e.target.value as "FIXED_QUANTITY" | "PERCENT_OF_EQUITY")
                  }
                >
                  <option value="FIXED_QUANTITY">Fixed Quantity</option>
                  <option value="PERCENT_OF_EQUITY">Percent of Equity</option>
                </select>
              </div>
              <div className="strategy-config-page__field">
                <label htmlFor="bt-sizing-value">
                  {positionSizingMode === "FIXED_QUANTITY" ? "Quantity" : "Fraction of Equity"}
                </label>
                <input
                  id="bt-sizing-value"
                  type="number"
                  value={positionSizeValue}
                  onChange={(e) => setPositionSizeValue(e.target.value)}
                />
              </div>
              <div className="strategy-config-page__field">
                <label htmlFor="bt-brokerage">Brokerage (%, model assumption)</label>
                <input
                  id="bt-brokerage"
                  type="number"
                  value={brokeragePercent}
                  onChange={(e) => setBrokeragePercent(e.target.value)}
                />
              </div>
              <div className="strategy-config-page__field">
                <label htmlFor="bt-slippage">Slippage (%, model assumption)</label>
                <input
                  id="bt-slippage"
                  type="number"
                  value={slippagePercent}
                  onChange={(e) => setSlippagePercent(e.target.value)}
                />
              </div>
            </fieldset>

            {canRun ? (
              <button type="submit" disabled={runState.phase === "running"}>
                {runState.phase === "running" ? "Running…" : "Run Backtest"}
              </button>
            ) : (
              <p className="strategy-config-page__help-text">
                Running a backtest requires the configuration-operator role.
              </p>
            )}
          </form>

          {runState.phase === "failed" && <ErrorState message={runState.message} />}

          {runState.phase === "completed" && <BacktestResultsPanel result={runState.result} />}
        </section>
      )}
    </div>
  );
}

function BacktestResultsPanel({ result }: { result: BacktestResult }): JSX.Element {
  const m = result.metrics as Record<string, string | number | null>;
  const configuration = asConfigurationView(result);
  const dataQuality = asDataQualityView(result);
  return (
    <section className="backtest-results" aria-label="Backtest Results">
      <h3>Results</h3>

      <div className="backtest-results__kpis">
        <div className="backtest-results__kpi">
          <span>Initial Capital</span>
          <strong>{formatMoney(configuration.initial_capital)}</strong>
        </div>
        <div className="backtest-results__kpi">
          <span>Final Capital</span>
          <strong>{formatMoney(String(m.final_capital))}</strong>
        </div>
        <div className="backtest-results__kpi">
          <span>Net P&amp;L</span>
          <strong>{formatMoney(String(m.net_pnl))}</strong>
        </div>
        <div className="backtest-results__kpi">
          <span>Return %</span>
          <strong>{formatPercent(String(m.return_percent))}</strong>
        </div>
        <div className="backtest-results__kpi">
          <span>Win Rate</span>
          <strong>{formatPercent(String(m.win_rate_percent))}</strong>
        </div>
        <div className="backtest-results__kpi">
          <span>Profit Factor</span>
          <strong>{m.profit_factor === null ? "—" : Number(m.profit_factor).toFixed(2)}</strong>
        </div>
        <div className="backtest-results__kpi">
          <span>Max Drawdown</span>
          <strong>{formatPercent(String(m.max_drawdown_percent))}</strong>
        </div>
        <div className="backtest-results__kpi">
          <span>Sharpe (trade-level)</span>
          <strong>{m.sharpe_ratio_trade_level === null ? "—" : Number(m.sharpe_ratio_trade_level).toFixed(2)}</strong>
        </div>
        <div className="backtest-results__kpi">
          <span>Total Trades</span>
          <strong>{String(m.total_trades)}</strong>
        </div>
      </div>

      <div className="backtest-results__charts">
        <EquityCurveChart points={result.equity_curve as never} />
        <DrawdownChart points={result.equity_curve as never} />
      </div>

      <div className="backtest-results__data-quality">
        <h4>Data Quality &amp; Assumptions</h4>
        <ul>
          <li>
            <strong>Data quality:</strong> {dataQuality.data_quality}
            {dataQuality.data_quality === "SAMPLE_BAR" && (
              <strong className="backtest-results__warning">
                {" "}
                — NOT SUITABLE FOR TRADING-GRADE PERFORMANCE CLAIMS
              </strong>
            )}
          </li>
          <li>
            <strong>Bar count:</strong> {dataQuality.bar_count}
          </li>
          <li>{dataQuality.transaction_cost_assumption}</li>
          <li>{dataQuality.slippage_assumption}</li>
          <li>{dataQuality.survivorship_bias_note}</li>
        </ul>
      </div>

      <TradeTable trades={result.trades as never} />
    </section>
  );
}

interface TradeRow {
  trade_id: string;
  direction: string;
  entry_timestamp: string;
  exit_timestamp: string;
  entry_price: string;
  exit_price: string;
  quantity: string;
  gross_pnl: string;
  costs: string;
  net_pnl: string;
  reason: string;
}

function TradeTable({ trades }: { trades: TradeRow[] }): JSX.Element {
  const [directionFilter, setDirectionFilter] = useState<"ALL" | "BULLISH" | "BEARISH">("ALL");
  const [outcomeFilter, setOutcomeFilter] = useState<"ALL" | "PROFITABLE" | "LOSING">("ALL");

  const filtered = trades.filter((t) => {
    if (directionFilter !== "ALL" && t.direction !== directionFilter) return false;
    const net = Number.parseFloat(t.net_pnl);
    if (outcomeFilter === "PROFITABLE" && net <= 0) return false;
    if (outcomeFilter === "LOSING" && net >= 0) return false;
    return true;
  });

  return (
    <div className="backtest-results__trades">
      <h4>Trade Ledger</h4>
      <div className="backtest-results__filters">
        <label>
          Direction:
          <select value={directionFilter} onChange={(e) => setDirectionFilter(e.target.value as never)}>
            <option value="ALL">All</option>
            <option value="BULLISH">Long</option>
            <option value="BEARISH">Short</option>
          </select>
        </label>
        <label>
          Outcome:
          <select value={outcomeFilter} onChange={(e) => setOutcomeFilter(e.target.value as never)}>
            <option value="ALL">All</option>
            <option value="PROFITABLE">Profitable</option>
            <option value="LOSING">Losing</option>
          </select>
        </label>
      </div>
      {filtered.length === 0 ? (
        <p>No trades match the selected filters.</p>
      ) : (
        <table>
          <thead>
            <tr>
              <th>Trade #</th>
              <th>Entry</th>
              <th>Exit</th>
              <th>Direction</th>
              <th>Qty</th>
              <th>Entry Price</th>
              <th>Exit Price</th>
              <th>Gross P&amp;L</th>
              <th>Costs</th>
              <th>Net P&amp;L</th>
              <th>Reason</th>
            </tr>
          </thead>
          <tbody>
            {filtered.map((trade) => (
              <tr key={trade.trade_id}>
                <td>{trade.trade_id}</td>
                <td>{new Date(trade.entry_timestamp).toLocaleString()}</td>
                <td>{new Date(trade.exit_timestamp).toLocaleString()}</td>
                <td>{trade.direction === "BULLISH" ? "Long" : "Short"}</td>
                <td>{trade.quantity}</td>
                <td>{formatMoney(trade.entry_price)}</td>
                <td>{formatMoney(trade.exit_price)}</td>
                <td>{formatMoney(trade.gross_pnl)}</td>
                <td>{formatMoney(trade.costs)}</td>
                <td>{formatMoney(trade.net_pnl)}</td>
                <td>{trade.reason}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}
