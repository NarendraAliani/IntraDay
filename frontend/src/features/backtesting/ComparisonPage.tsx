// frontend/src/features/backtesting/ComparisonPage.tsx
//
// Checkpoint 27 Part 21: multi-strategy/-configuration comparison. Pulls
// PAST backtest results (already run via the Workbench) for a chosen
// strategy and lets the user select two or more to compare side by
// side. Warns rather than silently comparing when instrument/timeframe
// differ between selected results (Part 21: "prevent comparing
// incompatible datasets without warning").
import { useEffect, useState } from "react";

import { ApiNetworkError, ApiRequestError } from "../../common/api/client";
import { ErrorState } from "../../common/components/ErrorState";
import { LoadingState } from "../../common/components/LoadingState";
import {
  asConfigurationView,
  asDataQualityView,
  listBacktestResults,
} from "../../common/api/backtestingApi";
import { listStrategies } from "../../common/api/strategyApi";
import type { BacktestResult } from "../../common/api/backtestingApi";
import type { StrategySummary } from "../../common/api/strategyApi";

type SortMetric = "net_pnl" | "profit_factor" | "return_percent" | "max_drawdown_percent";

function describeError(error: unknown): string {
  if (error instanceof ApiRequestError || error instanceof ApiNetworkError) {
    return error.message;
  }
  return "An unexpected error occurred.";
}

function metricValue(result: BacktestResult, key: SortMetric): number {
  const raw = (result.metrics as Record<string, string | number | null>)[key];
  const parsed = raw === null || raw === undefined ? Number.NEGATIVE_INFINITY : Number(raw);
  return Number.isFinite(parsed) ? parsed : Number.NEGATIVE_INFINITY;
}

export function ComparisonPage(): JSX.Element {
  const [strategies, setStrategies] = useState<StrategySummary[] | null>(null);
  const [selectedStrategyId, setSelectedStrategyId] = useState<string>("");
  const [results, setResults] = useState<BacktestResult[]>([]);
  const [selectedIds, setSelectedIds] = useState<string[]>([]);
  const [sortMetric, setSortMetric] = useState<SortMetric>("net_pnl");
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    listStrategies()
      .then((list) => {
        if (cancelled) return;
        setStrategies(list);
        if (list.length > 0) setSelectedStrategyId(list[0].strategy_id);
      })
      .catch((err) => {
        if (!cancelled) setError(describeError(err));
      });
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    if (!selectedStrategyId) return;
    let cancelled = false;
    setSelectedIds([]);
    listBacktestResults(selectedStrategyId)
      .then((list) => {
        if (!cancelled) setResults(list);
      })
      .catch((err) => {
        if (!cancelled) setError(describeError(err));
      });
    return () => {
      cancelled = true;
    };
  }, [selectedStrategyId]);

  if (error) return <ErrorState message={error} />;
  if (!strategies) return <LoadingState label="Loading strategies…" />;

  const selectedResults = results.filter((r) => selectedIds.includes(r.backtest_id));
  const sorted = [...selectedResults].sort((a, b) => metricValue(b, sortMetric) - metricValue(a, sortMetric));

  const instrumentSet = new Set(selectedResults.map((r) => asConfigurationView(r).instrument_id));
  const timeframeSet = new Set(selectedResults.map((r) => asConfigurationView(r).timeframe));
  const dataQualitySet = new Set(
    selectedResults.map((r) => asDataQualityView(r).data_quality),
  );
  const costModelSet = new Set(
    selectedResults.map(
      (r) => `${asDataQualityView(r).transaction_cost_assumption}|${asDataQualityView(r).slippage_assumption}`,
    ),
  );
  const incompatible =
    instrumentSet.size > 1 ||
    timeframeSet.size > 1 ||
    dataQualitySet.size > 1 ||
    costModelSet.size > 1;

  return (
    <div className="comparison-page">
      <h1>Strategy Comparison</h1>
      <p className="configuration-viewer__subtitle">
        Compare past backtest results by actual metrics - not a profitability guarantee, a
        research ranking only.
      </p>

      <div className="strategy-config-page__field">
        <label htmlFor="comparison-strategy">Strategy</label>
        <select
          id="comparison-strategy"
          value={selectedStrategyId}
          onChange={(e) => setSelectedStrategyId(e.target.value)}
        >
          {strategies.map((s) => (
            <option key={s.strategy_id} value={s.strategy_id}>
              {s.display_name}
            </option>
          ))}
        </select>
      </div>

      <div className="strategy-config-page__field">
        <label htmlFor="comparison-sort">Sort by</label>
        <select
          id="comparison-sort"
          value={sortMetric}
          onChange={(e) => setSortMetric(e.target.value as SortMetric)}
        >
          <option value="net_pnl">Net P&amp;L</option>
          <option value="profit_factor">Profit Factor</option>
          <option value="return_percent">Return %</option>
          <option value="max_drawdown_percent">Max Drawdown %</option>
        </select>
      </div>

      {results.length === 0 ? (
        <p>No saved backtest results for this strategy yet - run one from the Backtesting page.</p>
      ) : (
        <>
          <fieldset>
            <legend>Select results to compare</legend>
            {results.map((r) => (
              <label key={r.backtest_id} className="comparison-page__checkbox">
                <input
                  type="checkbox"
                  checked={selectedIds.includes(r.backtest_id)}
                  onChange={(e) =>
                    setSelectedIds((prev) =>
                      e.target.checked
                        ? [...prev, r.backtest_id]
                        : prev.filter((id) => id !== r.backtest_id),
                    )
                  }
                />
                {r.backtest_id.slice(0, 12)} — {asConfigurationView(r).instrument_id} (
                {asConfigurationView(r).timeframe})
              </label>
            ))}
          </fieldset>

          {incompatible && (
            <div className="callout callout--warn">
              Selected results use different instruments, timeframes, data quality, or cost
              assumptions - comparison numbers are not directly equivalent.
            </div>
          )}

          {sorted.length > 0 && (
            <table>
              <thead>
                <tr>
                  <th>Backtest</th>
                  <th>Net P&amp;L</th>
                  <th>Return %</th>
                  <th>Win Rate</th>
                  <th>Profit Factor</th>
                  <th>Max Drawdown</th>
                  <th>Sharpe</th>
                  <th>Trades</th>
                </tr>
              </thead>
              <tbody>
                {sorted.map((r) => {
                  const m = r.metrics as Record<string, string | number | null>;
                  return (
                    <tr key={r.backtest_id}>
                      <td>{r.backtest_id.slice(0, 12)}</td>
                      <td>{String(m.net_pnl)}</td>
                      <td>{String(m.return_percent)}</td>
                      <td>{String(m.win_rate_percent)}</td>
                      <td>{m.profit_factor === null ? "—" : String(m.profit_factor)}</td>
                      <td>{String(m.max_drawdown_percent)}</td>
                      <td>{m.sharpe_ratio_trade_level === null ? "—" : String(m.sharpe_ratio_trade_level)}</td>
                      <td>{String(m.total_trades)}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          )}
        </>
      )}
    </div>
  );
}
