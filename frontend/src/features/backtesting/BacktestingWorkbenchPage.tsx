// frontend/src/features/backtesting/BacktestingWorkbenchPage.tsx
//
// Checkpoint 27: Discover -> Configure -> Backtest -> Review workflow
// (Parts 12-16). ONE page, three internal views (discover/configure/
// results), never "Buy"/"Sell"/"Deploy Live" anywhere (Part 34).
// Reuses the SAME schema-driven parameter renderer
// (`ParameterSchemaFields`) Checkpoint 26's Strategy Configuration
// screen already uses - no duplicated strategy fields (Part 14).
import { Fragment, useEffect, useMemo, useState } from "react";

import { ApiNetworkError, ApiRequestError } from "../../common/api/client";
import { useAuth } from "../../common/auth/AuthContext";
import {
  ParameterSchemaFields,
  defaultValuesFor,
} from "../../common/components/ParameterSchemaFields";
import { DrawdownChart, EquityCurveChart } from "../../common/components/EquityChart";
import { ErrorState } from "../../common/components/ErrorState";
import { InstrumentPickerMulti } from "../../common/components/InstrumentPicker";
import { LoadingState } from "../../common/components/LoadingState";
import {
  asConfigurationView,
  asDataQualityView,
  createHistoricalBacktestRun,
  getCoveragePreview,
  getHistoricalBacktestRunProgress,
  runBacktest,
} from "../../common/api/backtestingApi";
import type {
  CoveragePreviewResponse,
  HistoricalBacktestRunProgress,
} from "../../common/api/backtestingApi";
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

/** Today's calendar date, `YYYY-MM-DD` - the sensible default for
 * every date field on this page (Start/End on both the single- and
 * multi-instrument flows), rather than a stale hardcoded fixture date
 * an operator has to notice and change every time. */
function todayIsoDate(): string {
  return new Date().toISOString().slice(0, 10);
}

/** Converts the raw, all-string form values (`ParameterSchemaFields`
 * always emits strings, even for INTEGER-typed parameters) into the
 * correctly-typed values the strategy-config validator expects - a
 * REAL bug was found and fixed here: the multi-instrument historical
 * run panel used to send `strategy_values` UNPARSED (bare strings like
 * `"9"`), while this exact parsing already existed - but only inline
 * inside the single-instrument `handleRun()` below, never shared - so
 * every historical run failed validation ("parameter 'fast_lookback'
 * is not an int: '9'") despite the single-instrument flow working
 * fine with the identical schema. Now the ONE shared implementation
 * both flows call. */
function parseStrategyValues(
  schema: StrategySchema,
  values: Record<string, string>,
): Record<string, unknown> {
  const parsed: Record<string, unknown> = {};
  for (const parameter of schema.parameters) {
    const raw = values[parameter.parameter_id];
    if (raw === undefined || raw === "") continue;
    parsed[parameter.parameter_id] =
      parameter.parameter_type === "INTEGER" ? Number.parseInt(raw, 10) : raw;
  }
  return parsed;
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

  const [selectedInstrumentIds, setSelectedInstrumentIds] = useState<string[]>(["NSE:FIXTURE01"]);
  const [timeframe, setTimeframe] = useState("5m");
  const [start, setStart] = useState(() => `${todayIsoDate()}T09:15`);
  const [end, setEnd] = useState(() => `${todayIsoDate()}T15:30`);
  const [initialCapital, setInitialCapital] = useState("100000");
  const [positionSizingMode, setPositionSizingMode] = useState<"FIXED_QUANTITY" | "PERCENT_OF_EQUITY">(
    "FIXED_QUANTITY",
  );
  const [positionSizeValue, setPositionSizeValue] = useState("10");
  const [brokeragePercent, setBrokeragePercent] = useState("0.03");
  const [slippagePercent, setSlippagePercent] = useState("0");
  const [costModelName, setCostModelName] = useState<
    "FLAT_PERCENTAGE" | "INDIAN_CASH_EQUITY_INTRADAY"
  >("INDIAN_CASH_EQUITY_INTRADAY");

  const [runState, setRunState] = useState<RunState>({ phase: "ready" });
  const [expandedStrategyId, setExpandedStrategyId] = useState<string | null>(null);
  const [schemaCache, setSchemaCache] = useState<Record<string, StrategySchema>>({});

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

  async function toggleView(strategyId: string): Promise<void> {
    if (expandedStrategyId === strategyId) {
      setExpandedStrategyId(null);
      return;
    }
    setExpandedStrategyId(strategyId);
    if (!schemaCache[strategyId]) {
      try {
        const strategySchema = await getStrategySchema(strategyId);
        setSchemaCache((prev) => ({ ...prev, [strategyId]: strategySchema }));
      } catch (error) {
        setLoadError(describeError(error));
      }
    }
  }

  async function handleRun(): Promise<void> {
    if (!schema || !selectedStrategy) return;
    if (selectedInstrumentIds.length !== 1) return; // gated by the disabled button below too
    setRunState({ phase: "running" });
    try {
      const parsedValues = parseStrategyValues(schema, values);
      const result = await runBacktest({
        instrument_id: selectedInstrumentIds[0],
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
        cost_model_name: costModelName,
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
                  <dt>Maturity</dt>
                  <dd>{strategy.is_active ? "Active for research" : "Registered"}</dd>
                  <dt>Backtest availability</dt>
                  <dd>Available (fixture/historical data)</dd>
                </dl>
                {expandedStrategyId === strategy.strategy_id && schemaCache[strategy.strategy_id] && (
                  <div className="backtest-workbench__card-detail">
                    <p>
                      <strong>Parameters:</strong> {schemaCache[strategy.strategy_id].parameters.length}
                    </p>
                    <ul>
                      {schemaCache[strategy.strategy_id].parameters.map((p) => (
                        <li key={p.parameter_id}>{p.label}</li>
                      ))}
                    </ul>
                  </div>
                )}
                <div className="backtest-workbench__card-actions">
                  <button type="button" onClick={() => void toggleView(strategy.strategy_id)}>
                    {expandedStrategyId === strategy.strategy_id ? "Hide" : "View"}
                  </button>
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
        <Fragment>
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
                <InstrumentPickerMulti
                  idPrefix="bt-instrument"
                  label="Universe (select one, many, or all — Select All)"
                  value={selectedInstrumentIds}
                  onChange={setSelectedInstrumentIds}
                />
                <p className="strategy-config-page__help-text">
                  What stock(s): pick one, many, or all. "Run Backtest" below runs an
                  immediate, single-instrument simulation — it requires exactly ONE stock
                  selected. To backtest 2+ stocks, select them here and use "Prepare Data &amp;
                  Start Backtest" in the Historical Data Readiness panel further down instead.
                  "NSE:FIXTURE01" is this project's deterministic synthetic fixture, always
                  available for testing regardless of live market data.
                </p>
                {selectedInstrumentIds.length !== 1 && (
                  <p className="strategy-config-page__help-text backtest-results__warning">
                    {selectedInstrumentIds.length === 0
                      ? "Select exactly one stock to enable Run Backtest."
                      : `${selectedInstrumentIds.length} stocks selected — Run Backtest needs exactly one. Use the Historical Data Readiness panel below for multiple stocks.`}
                  </p>
                )}
              </div>
              <div className="strategy-config-page__field">
                <label htmlFor="bt-timeframe">Timeframe</label>
                <input id="bt-timeframe" value={timeframe} onChange={(e) => setTimeframe(e.target.value)} />
                <p className="strategy-config-page__help-text">
                  The bar size the strategy evaluates on, e.g. "5m" for 5-minute bars.
                </p>
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
                <p className="strategy-config-page__help-text">
                  What date range: the historical window the simulation covers.
                </p>
              </div>
              <div className="strategy-config-page__field">
                <label htmlFor="bt-capital">Initial Capital</label>
                <input
                  id="bt-capital"
                  type="number"
                  value={initialCapital}
                  onChange={(e) => setInitialCapital(e.target.value)}
                />
                <p className="strategy-config-page__help-text">
                  How much simulated capital the backtest starts with - never real money.
                </p>
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
                <label htmlFor="bt-cost-model">Cost Model</label>
                <select
                  id="bt-cost-model"
                  value={costModelName}
                  onChange={(e) =>
                    setCostModelName(e.target.value as "FLAT_PERCENTAGE" | "INDIAN_CASH_EQUITY_INTRADAY")
                  }
                >
                  <option value="FLAT_PERCENTAGE">Flat Percentage (model assumption)</option>
                  <option value="INDIAN_CASH_EQUITY_INTRADAY">
                    Indian Cash-Equity Intraday (verified NSE schedule)
                  </option>
                </select>
                <p className="strategy-config-page__help-text">
                  {costModelName === "INDIAN_CASH_EQUITY_INTRADAY" ? (
                    <>
                      <strong className="badge badge--ok">VERIFIED COST MODEL</strong> — real NSE
                      STT/exchange charges/SEBI fees/GST/stamp duty. Brokerage itself remains a
                      configurable, representative default (see below).
                    </>
                  ) : (
                    <>
                      <strong className="badge badge--pending">MODEL ASSUMPTION</strong> — a flat
                      percentage cost, not a verified Indian cost schedule.
                    </>
                  )}
                </p>
              </div>
              {costModelName === "FLAT_PERCENTAGE" && (
                <div className="strategy-config-page__field">
                  <label htmlFor="bt-brokerage">Brokerage (%, model assumption)</label>
                  <input
                    id="bt-brokerage"
                    type="number"
                    value={brokeragePercent}
                    onChange={(e) => setBrokeragePercent(e.target.value)}
                  />
                  <p className="strategy-config-page__help-text">
                    ASSUMPTION: a flat percentage cost per trade side - not a verified Indian
                    brokerage/tax schedule.
                  </p>
                </div>
              )}
              <div className="strategy-config-page__field">
                <label htmlFor="bt-slippage">Slippage Model (%, model assumption)</label>
                <input
                  id="bt-slippage"
                  type="number"
                  value={slippagePercent}
                  onChange={(e) => setSlippagePercent(e.target.value)}
                />
                <p className="strategy-config-page__help-text">
                  ASSUMPTION: how much the fill price moves against you on every trade - kept
                  separate from the Cost Model above (statutory/broker costs never include
                  slippage).
                </p>
              </div>
              <p className="strategy-config-page__help-text">
                <strong>What does Run Backtest actually do?</strong> It replays the strategy above,
                bar by bar, against the historical data selected here, and records every simulated
                trade it would have made - it never places a real order.
              </p>
            </fieldset>

            {canRun ? (
              <button
                type="submit"
                disabled={runState.phase === "running" || selectedInstrumentIds.length !== 1}
              >
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

        <HistoricalBacktestRunPanel
          strategyId={selectedStrategy.strategy_id}
          specificationVersion={selectedStrategy.specification_version}
          codeVersion={selectedStrategy.code_version}
          strategyValues={parseStrategyValues(schema, values)}
          selectedInstrumentIds={selectedInstrumentIds}
          defaultTimeframe={timeframe}
          initialCapital={initialCapital}
          positionSizingMode={positionSizingMode}
          positionSizeValue={positionSizeValue}
          brokeragePercent={brokeragePercent}
          slippagePercent={slippagePercent}
          costModelName={costModelName}
          canRun={canRun}
        />
        </Fragment>
      )}
    </div>
  );
}

interface MtmPointRaw {
  timestamp: string;
  total_equity: string;
  drawdown_percent: string;
}

interface ValidationSummaryRaw {
  bar_count: number;
  signal_count: number;
  trade_count: number;
  warmup_bars: number;
  skipped_signals: number;
  rejected_trades: number;
  data_gaps_note: string;
}

/** Data-quality gate level (Part 14): FIXTURE/HISTORICAL is
 * informational, SAMPLE_BAR is a warning (restricted - not suitable for
 * trading-grade claims). Nothing this engine can produce today is
 * BLOCKING (that would apply to corrupted/rejected data, which never
 * reaches a result - the API rejects it before a result exists). */
function dataQualityLevel(quality: string): "informational" | "warning" {
  return quality === "SAMPLE_BAR" ? "warning" : "informational";
}

interface CostModelIdentityRaw {
  name: string;
  version: string;
  effective_from: string;
  is_verified: boolean;
}

interface TradeRawForCosts {
  gross_pnl: string;
  costs: string;
}

// Checkpoint 30 Part 17: a compact, static indicator of the *engine's*
// independent reference-validation status - see
// docs/research/BACKTEST_REFERENCE_VALIDATION.md for the full report.
// This is code-embedded (not fetched from an API) because the
// validation is a property of the engine's source code at a given
// commit, not of any individual backtest run. It intentionally says
// nothing about whether any particular strategy or result is
// profitable, safe, or production-ready - only that the calculation
// engine itself has been cross-checked against an independent
// reference implementation.
const ENGINE_VALIDATION = {
  status: "VERIFIED" as const,
  lastValidated: "2026-08-14",
  reference: "independent reference implementation (tests/validation/reference_engine.py)",
  datasets: "MICRO-EMA-CROSSOVER-V1, EXTENDED-EMA-CROSSOVER-V1",
};

function EngineValidationIndicator(): JSX.Element {
  return (
    <div className="callout callout--info" role="note">
      <span className="badge badge--ok">ENGINE VALIDATION: {ENGINE_VALIDATION.status}</span>{" "}
      Calculation engine cross-checked against an {ENGINE_VALIDATION.reference} on{" "}
      {ENGINE_VALIDATION.datasets} (last validated {ENGINE_VALIDATION.lastValidated}). This
      confirms the engine computes signals, trades, costs, and equity correctly - it does{" "}
      <strong>not</strong> mean this strategy or result is profitable, safe, or production ready.
      See <code>docs/research/BACKTEST_REFERENCE_VALIDATION.md</code> for the full report.
    </div>
  );
}

function BacktestResultsPanel({ result }: { result: BacktestResult }): JSX.Element {
  const m = result.metrics as Record<string, string | number | null>;
  const configuration = asConfigurationView(result);
  const dataQuality = asDataQualityView(result);
  const validation = result.validation as unknown as ValidationSummaryRaw;
  const costModelIdentity = result.cost_model_identity as unknown as CostModelIdentityRaw;
  const trustLevel = String(result.trust_level ?? "POC");
  const level = dataQualityLevel(dataQuality.data_quality);
  const mtmPoints = (result.mark_to_market_curve as unknown as MtmPointRaw[]).map((p) => ({
    timestamp: p.timestamp,
    balance: p.total_equity,
    drawdown_percent: p.drawdown_percent,
  }));
  const tradesForCosts = result.trades as unknown as TradeRawForCosts[];
  const totalGrossPnl = tradesForCosts.reduce((sum, t) => sum + Number(t.gross_pnl), 0);
  const totalCosts = tradesForCosts.reduce((sum, t) => sum + Number(t.costs), 0);

  return (
    <section className="backtest-results" aria-label="Backtest Results">
      <h3>Results</h3>

      <div className="callout callout--warn" role="note">
        <strong>RESULT, not a promise.</strong> Backtest results are historical simulations and
        are not guarantees of future performance. Trust level:{" "}
        <span className="badge badge--pending">{trustLevel}</span> - see the Strategy &amp;
        Backtesting guide for what this level means and does not mean.
      </div>

      <EngineValidationIndicator />

      <div className="backtest-results__cost-model-identity">
        <span
          className={costModelIdentity.is_verified ? "badge badge--ok" : "badge badge--pending"}
        >
          {costModelIdentity.is_verified ? "VERIFIED COST MODEL" : "MODEL ASSUMPTION"}
        </span>{" "}
        {costModelIdentity.name} v{costModelIdentity.version} (effective from{" "}
        {costModelIdentity.effective_from})
      </div>

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
          <span>Gross P&amp;L</span>
          <strong>{formatMoney(String(totalGrossPnl))}</strong>
        </div>
        <div className="backtest-results__kpi backtest-results__kpi--cost">
          <span>Total Costs</span>
          <strong>-{formatMoney(String(totalCosts))}</strong>
        </div>
        <div className="backtest-results__kpi backtest-results__kpi--net">
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
          <span>Max Drawdown (mark-to-market)</span>
          <strong>{formatPercent(String(m.max_drawdown_percent))}</strong>
        </div>
        <div className="backtest-results__kpi">
          <span>Drawdown Duration</span>
          <strong>{String(m.max_drawdown_duration_bars)} bars</strong>
        </div>
        <div className="backtest-results__kpi">
          <span>Sharpe (trade-level, non-annualized)</span>
          <strong>{m.sharpe_ratio_trade_level === null ? "—" : Number(m.sharpe_ratio_trade_level).toFixed(2)}</strong>
        </div>
        <div className="backtest-results__kpi">
          <span>Total Trades</span>
          <strong>{String(m.total_trades)}</strong>
        </div>
      </div>

      <div className="backtest-results__charts">
        <EquityCurveChart points={mtmPoints} />
        <DrawdownChart points={mtmPoints} />
      </div>
      <p className="strategy-config-page__help-text">
        LIMITATION: the equity/drawdown curves above are mark-to-market (valued at each bar's own
        close price while a position is open) - a real, but simplified, view of intrabar risk.
      </p>

      <div className="backtest-results__data-quality">
        <h4>Data Quality &amp; Assumptions</h4>
        <ul>
          <li>
            <strong>Data quality:</strong>{" "}
            <span className={level === "warning" ? "badge badge--pending" : "badge badge--ok"}>
              {dataQuality.data_quality}
            </span>
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
          <li>ASSUMPTION: {dataQuality.transaction_cost_assumption}</li>
          <li>ASSUMPTION: {dataQuality.slippage_assumption}</li>
          <li>LIMITATION: {dataQuality.survivorship_bias_note}</li>
        </ul>
      </div>

      <div className="backtest-results__validation">
        <h4>Research-Quality Validation</h4>
        <p className="strategy-config-page__help-text">
          Diagnostics to explain why two seemingly similar backtests can produce different
          results.
        </p>
        <table>
          <tbody>
            <tr>
              <td>Bars</td>
              <td>{validation.bar_count}</td>
            </tr>
            <tr>
              <td>Signals</td>
              <td>{validation.signal_count}</td>
            </tr>
            <tr>
              <td>Trades</td>
              <td>{validation.trade_count}</td>
            </tr>
            <tr>
              <td>Warm-up bars</td>
              <td>{validation.warmup_bars}</td>
            </tr>
            <tr>
              <td>Skipped signals (same-direction, position already open)</td>
              <td>{validation.skipped_signals}</td>
            </tr>
            <tr>
              <td>Rejected trades (insufficient capital)</td>
              <td>{validation.rejected_trades}</td>
            </tr>
            <tr>
              <td>Data gaps</td>
              <td>{validation.data_gaps_note}</td>
            </tr>
          </tbody>
        </table>
      </div>

      <TradeTable trades={result.trades as never} />
    </section>
  );
}

interface CostBreakdownRow {
  brokerage: string;
  stt: string;
  exchange_transaction_charges: string;
  sebi_charges: string;
  gst: string;
  stamp_duty: string;
  other_statutory_charges: string;
  total: string;
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
  cost_breakdown: CostBreakdownRow;
}

const TRADES_PER_PAGE = 15;

function TradeTable({ trades }: { trades: TradeRow[] }): JSX.Element {
  const [directionFilter, setDirectionFilter] = useState<"ALL" | "BULLISH" | "BEARISH">("ALL");
  const [outcomeFilter, setOutcomeFilter] = useState<"ALL" | "PROFITABLE" | "LOSING">("ALL");
  const [expandedTradeId, setExpandedTradeId] = useState<string | null>(null);
  const [page, setPage] = useState(1);

  const filtered = trades.filter((t) => {
    if (directionFilter !== "ALL" && t.direction !== directionFilter) return false;
    const net = Number.parseFloat(t.net_pnl);
    if (outcomeFilter === "PROFITABLE" && net <= 0) return false;
    if (outcomeFilter === "LOSING" && net >= 0) return false;
    return true;
  });

  const totalPages = Math.max(1, Math.ceil(filtered.length / TRADES_PER_PAGE));
  const currentPage = Math.min(page, totalPages);
  const pageStart = (currentPage - 1) * TRADES_PER_PAGE;
  const pageTrades = filtered.slice(pageStart, pageStart + TRADES_PER_PAGE);

  function updateDirectionFilter(value: "ALL" | "BULLISH" | "BEARISH"): void {
    setDirectionFilter(value);
    setPage(1);
  }

  function updateOutcomeFilter(value: "ALL" | "PROFITABLE" | "LOSING"): void {
    setOutcomeFilter(value);
    setPage(1);
  }

  return (
    <div className="backtest-results__trades">
      <h4>Trade Ledger</h4>
      <div className="backtest-results__filters">
        <label>
          Direction:
          <select
            value={directionFilter}
            onChange={(e) => updateDirectionFilter(e.target.value as never)}
          >
            <option value="ALL">All</option>
            <option value="BULLISH">Long</option>
            <option value="BEARISH">Short</option>
          </select>
        </label>
        <label>
          Outcome:
          <select value={outcomeFilter} onChange={(e) => updateOutcomeFilter(e.target.value as never)}>
            <option value="ALL">All</option>
            <option value="PROFITABLE">Profitable</option>
            <option value="LOSING">Losing</option>
          </select>
        </label>
        <span className="backtest-results__trade-count">
          {filtered.length} trade{filtered.length === 1 ? "" : "s"}
        </span>
      </div>
      {filtered.length === 0 ? (
        <p>No trades match the selected filters.</p>
      ) : (
        <div className="backtest-results__trade-table-wrap">
        <table className="backtest-results__trade-table">
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
              <th>Cost Breakdown</th>
            </tr>
          </thead>
          <tbody>
            {pageTrades.map((trade, index) => (
              <Fragment key={trade.trade_id}>
                <tr className={index % 2 === 0 ? "backtest-results__trade-row--even" : undefined}>
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
                  <td>
                    <button
                      type="button"
                      onClick={() =>
                        setExpandedTradeId((prev) =>
                          prev === trade.trade_id ? null : trade.trade_id,
                        )
                      }
                    >
                      {expandedTradeId === trade.trade_id ? "Hide" : "Details"}
                    </button>
                  </td>
                </tr>
                {expandedTradeId === trade.trade_id && (
                  <tr>
                    <td colSpan={12}>
                      <dl className="backtest-results__cost-breakdown">
                        <dt>Brokerage</dt>
                        <dd>{formatMoney(trade.cost_breakdown.brokerage)}</dd>
                        <dt>STT</dt>
                        <dd>{formatMoney(trade.cost_breakdown.stt)}</dd>
                        <dt>Exchange transaction charges</dt>
                        <dd>{formatMoney(trade.cost_breakdown.exchange_transaction_charges)}</dd>
                        <dt>SEBI charges</dt>
                        <dd>{formatMoney(trade.cost_breakdown.sebi_charges)}</dd>
                        <dt>GST</dt>
                        <dd>{formatMoney(trade.cost_breakdown.gst)}</dd>
                        <dt>Stamp duty</dt>
                        <dd>{formatMoney(trade.cost_breakdown.stamp_duty)}</dd>
                        <dt>Other statutory charges</dt>
                        <dd>{formatMoney(trade.cost_breakdown.other_statutory_charges)}</dd>
                        <dt>
                          <strong>Total</strong>
                        </dt>
                        <dd>
                          <strong>{formatMoney(trade.cost_breakdown.total)}</strong>
                        </dd>
                      </dl>
                    </td>
                  </tr>
                )}
              </Fragment>
            ))}
          </tbody>
        </table>
        </div>
      )}
      {filtered.length > 0 && totalPages > 1 && (
        <div className="backtest-results__pagination">
          <button
            type="button"
            onClick={() => setPage((p) => Math.max(1, p - 1))}
            disabled={currentPage === 1}
          >
            ← Previous
          </button>
          <span>
            Page {currentPage} of {totalPages}
          </span>
          <button
            type="button"
            onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
            disabled={currentPage === totalPages}
          >
            Next →
          </button>
        </div>
      )}
    </div>
  );
}

// --- Checkpoint 63.x: DB-first, multi-instrument historical backtest run,
// with real (never fabricated/timer-driven) progress polling. Separate
// panel from the single-instrument "Run Backtest" flow above -
// deliberately additive rather than replacing it, since the existing
// flow's fixture/single-instrument semantics remain valid for quick
// strategy iteration; THIS panel is for the DB-first multi-instrument
// architecture Checkpoint 63.x introduces. -----------------------------

const TERMINAL_RUN_STATUSES = new Set(["COMPLETED", "PARTIAL", "FAILED", "CANCELLED"]);
const POLL_INTERVAL_MS = 1200;

interface HistoricalBacktestRunPanelProps {
  strategyId: string;
  specificationVersion: string;
  codeVersion: string;
  /** Already parsed/typed (via `parseStrategyValues`) - never the raw,
   * all-string form values `ParameterSchemaFields` emits. */
  strategyValues: Record<string, unknown>;
  /** THE SAME Universe selection as the single-instrument "Backtest
   * Settings" section above - a REAL bug found from a live report: this
   * panel used to have its OWN, entirely separate instrument picker,
   * so an operator who selected stocks above had to select them AGAIN
   * down here for "Prepare Data & Start Backtest" to do anything -
   * confusing enough that it read as "Run Backtest doesn't work" even
   * though both controls were individually correct. One Universe
   * selection, shared by both actions, now. */
  selectedInstrumentIds: string[];
  defaultTimeframe: string;
  initialCapital: string;
  positionSizingMode: "FIXED_QUANTITY" | "PERCENT_OF_EQUITY";
  positionSizeValue: string;
  brokeragePercent: string;
  slippagePercent: string;
  costModelName: "FLAT_PERCENTAGE" | "INDIAN_CASH_EQUITY_INTRADAY";
  canRun: boolean;
}

type HistoricalRunPhase =
  | { phase: "idle" }
  | { phase: "previewing" }
  | { phase: "preview_ready"; preview: CoveragePreviewResponse }
  | { phase: "starting" }
  | { phase: "polling"; progress: HistoricalBacktestRunProgress }
  | { phase: "done"; progress: HistoricalBacktestRunProgress }
  | {
      phase: "error";
      message: string;
      /** Dev-only (DEBUG=True backend) exception detail - see
       * ApiRequestError.debugDetail's own docstring. Never present
       * against a production backend. */
      debugDetail?: ApiRequestError["debugDetail"];
    };

function debugDetailOf(error: unknown): ApiRequestError["debugDetail"] {
  return error instanceof ApiRequestError ? error.debugDetail : undefined;
}

function formatSeconds(value: number | null | undefined): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return "—";
  const total = Math.max(0, Math.round(value));
  const minutes = Math.floor(total / 60)
    .toString()
    .padStart(2, "0");
  const seconds = (total % 60).toString().padStart(2, "0");
  return `${minutes}:${seconds}`;
}

function HistoricalBacktestRunPanel(props: HistoricalBacktestRunPanelProps): JSX.Element {
  const instrumentIds = props.selectedInstrumentIds;
  const [startDate, setStartDate] = useState(todayIsoDate);
  const [endDate, setEndDate] = useState(todayIsoDate);
  const [state, setState] = useState<HistoricalRunPhase>({ phase: "idle" });
  const [runId, setRunId] = useState<string | null>(null);

  useEffect(() => {
    if (state.phase !== "polling" || runId === null) return undefined;
    let cancelled = false;
    const interval = setInterval(async () => {
      try {
        const progress = await getHistoricalBacktestRunProgress(runId);
        if (cancelled) return;
        if (TERMINAL_RUN_STATUSES.has(progress.status)) {
          setState({ phase: "done", progress });
        } else {
          setState({ phase: "polling", progress });
        }
      } catch (error) {
        if (!cancelled) setState({ phase: "error", message: describeError(error), debugDetail: debugDetailOf(error) });
      }
    }, POLL_INTERVAL_MS);
    return () => {
      cancelled = true;
      clearInterval(interval);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [state.phase, runId]);

  async function handlePreview(): Promise<void> {
    setState({ phase: "previewing" });
    try {
      const preview = await getCoveragePreview({
        instrument_ids: instrumentIds,
        timeframe: props.defaultTimeframe,
        start_date: startDate,
        end_date: endDate,
      });
      setState({ phase: "preview_ready", preview });
    } catch (error) {
      setState({ phase: "error", message: describeError(error), debugDetail: debugDetailOf(error) });
    }
  }

  async function handleStart(): Promise<void> {
    setState({ phase: "starting" });
    try {
      const created = await createHistoricalBacktestRun({
        instrument_ids: instrumentIds,
        timeframe: props.defaultTimeframe,
        start_date: startDate,
        end_date: endDate,
        strategy_id: props.strategyId,
        specification_version: props.specificationVersion,
        code_version: props.codeVersion,
        configuration_version: `wb-hist-${Date.now()}`,
        strategy_values: props.strategyValues,
        initial_capital: props.initialCapital,
        position_sizing_mode: props.positionSizingMode,
        position_size_value: props.positionSizeValue,
        brokerage_percent: props.brokeragePercent,
        slippage_percent: props.slippagePercent,
        cost_model_name: props.costModelName,
      });
      setRunId(created.run_id);
      const progress = await getHistoricalBacktestRunProgress(created.run_id);
      setState(
        TERMINAL_RUN_STATUSES.has(progress.status)
          ? { phase: "done", progress }
          : { phase: "polling", progress },
      );
    } catch (error) {
      setState({ phase: "error", message: describeError(error), debugDetail: debugDetailOf(error) });
    }
  }

  const progress = state.phase === "polling" || state.phase === "done" ? state.progress : null;

  return (
    <section className="historical-run" aria-label="DB-First Historical Backtest Run">
      <h2>Historical Data Readiness &amp; Scanner Progress</h2>
      <p className="strategy-config-page__help-text">
        Runs this strategy against a stock universe, sourcing historical bars from the database
        first and only calling the historical data provider for genuinely missing ranges. Signals
        only ever come from bars already persisted in the database — never directly from the
        provider. Uses the SAME Universe selected in Backtest Settings above.
      </p>

      {instrumentIds.length === 0 && (
        <p className="strategy-config-page__help-text backtest-results__warning">
          No stocks selected yet — pick one, many, or all in the Universe field under Backtest
          Settings above.
        </p>
      )}

      <div className="historical-run__config">
        <div className="strategy-config-page__field">
          <label htmlFor="hist-start-date">Start Date</label>
          <input
            id="hist-start-date"
            type="date"
            value={startDate}
            onChange={(e) => setStartDate(e.target.value)}
          />
        </div>
        <div className="strategy-config-page__field">
          <label htmlFor="hist-end-date">End Date</label>
          <input
            id="hist-end-date"
            type="date"
            value={endDate}
            onChange={(e) => setEndDate(e.target.value)}
          />
        </div>
      </div>

      <div className="historical-run__actions">
        <button
          type="button"
          onClick={() => void handlePreview()}
          disabled={instrumentIds.length === 0 || state.phase === "previewing"}
        >
          {state.phase === "previewing" ? "Checking…" : "Check Data Readiness"}
        </button>
        {props.canRun && (
          <button
            type="button"
            onClick={() => void handleStart()}
            disabled={
              instrumentIds.length === 0 || state.phase === "starting" || state.phase === "polling"
            }
          >
            Prepare Data &amp; Start Backtest
          </button>
        )}
      </div>

      {state.phase === "preview_ready" && (
        <table className="historical-run__readiness-table">
          <caption>Historical Data Readiness</caption>
          <thead>
            <tr>
              <th scope="col">Instrument</th>
              <th scope="col">Coverage</th>
              <th scope="col">Status</th>
            </tr>
          </thead>
          <tbody>
            {state.preview.instruments.map((entry) => (
              <tr key={entry.instrument_id}>
                <td>{entry.instrument_id}</td>
                <td>{entry.coverage_percent.toFixed(1)}%</td>
                <td>
                  {entry.is_complete ? (
                    <span className="badge badge--ok">READY</span>
                  ) : (
                    <span className="badge badge--pending">FETCH REQUIRED</span>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      {state.phase === "error" && (
        <>
          <ErrorState message={state.message} />
          {state.debugDetail && (
            <details className="historical-run__debug-detail">
              <summary>
                Developer detail (only shown because the backend is running with DEBUG on - never
                appears against a production backend): {state.debugDetail.exception_type}
              </summary>
              <p>{state.debugDetail.exception_message}</p>
              <pre>{state.debugDetail.traceback}</pre>
            </details>
          )}
        </>
      )}

      {progress && (
        <div className="historical-run__progress" aria-label="Scanner Progress">
          <div
            className="historical-run__progress-bar"
            role="progressbar"
            aria-valuenow={progress.progress_percent}
            aria-valuemin={0}
            aria-valuemax={100}
          >
            <div
              className={`historical-run__progress-bar-fill historical-run__progress-bar-fill--${Math.round(progress.progress_percent / 10) * 10}`}
            />
          </div>
          <p>
            <strong>{progress.progress_percent.toFixed(1)}%</strong> — {progress.phase}
          </p>
          <p className="strategy-config-page__help-text">{progress.message || "—"}</p>

          <dl className="historical-run__stats">
            <dt>Current Instrument</dt>
            <dd>{progress.current_instrument || "—"}</dd>
            <dt>Current Strategy</dt>
            <dd>{progress.current_strategy || "—"}</dd>
            <dt>Instruments</dt>
            <dd>
              {progress.completed_instruments} / {progress.total_instruments}
            </dd>
            <dt>Bars Scanned</dt>
            <dd>{progress.scanned_bars.toLocaleString()}</dd>
            <dt>Signals</dt>
            <dd>{progress.signals_generated}</dd>
            <dt>Database Cache Hits</dt>
            <dd>{progress.cache_hits.toLocaleString()}</dd>
            <dt>API-Fetched Bars</dt>
            <dd>{progress.cache_misses.toLocaleString()}</dd>
            <dt>API Requests</dt>
            <dd>{progress.api_requests}</dd>
            <dt>Elapsed</dt>
            <dd>{formatSeconds(progress.elapsed_seconds)}</dd>
            <dt>ETA</dt>
            <dd>{formatSeconds(progress.eta_seconds)}</dd>
            <dt>Scan Source</dt>
            <dd>
              <strong className="badge badge--ok">DATABASE ONLY</strong>
            </dd>
          </dl>

          {(() => {
            const failures = progress.failed_instruments as Array<{
              instrument_id: string;
              reason: string;
            }>;
            return (
              failures.length > 0 && (
                <div role="alert" className="historical-run__failures">
                  <strong>Incomplete data — the following instruments were skipped:</strong>
                  <ul>
                    {failures.map((failure) => (
                      <li key={failure.instrument_id}>
                        {failure.instrument_id}: {failure.reason}
                      </li>
                    ))}
                  </ul>
                </div>
              )
            );
          })()}

          {state.phase === "done" && (
            <p>
              <strong
                className={`badge ${progress.status === "COMPLETED" ? "badge--ok" : "badge--pending"}`}
              >
                {progress.status}
              </strong>
            </p>
          )}
        </div>
      )}
    </section>
  );
}
