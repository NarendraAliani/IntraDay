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
import { Pagination, paginate } from "../../common/components/Pagination";
import {
  asConfigurationView,
  asDataQualityView,
  listBacktestResults,
} from "../../common/api/backtestingApi";
import { listStrategies } from "../../common/api/strategyApi";
import type { BacktestResult } from "../../common/api/backtestingApi";
import type { StrategySummary } from "../../common/api/strategyApi";

type SortMetric = "net_pnl" | "profit_factor" | "return_percent" | "max_drawdown_percent";

// Checkpoint FRONTEND-DATA-TABLES: sorting the RAW results list before
// selection - distinct from `SortMetric` above, which only orders the
// already-selected comparison table. `strategy_id`/`configuration_
// version` come from `configuration` (see `to_json_dict()` in
// research/backtesting/serialization.py) - already-available data, no
// new backend field.
type ListSort = "generated_at_desc" | "generated_at_asc" | "instrument_id" | "timeframe";

const RESULTS_PER_PAGE = 20;

interface BacktestConfigurationFull {
  instrument_id: string;
  timeframe: string;
  strategy_id: string;
  configuration_version: string;
  start: string;
  end: string;
}

function fullConfiguration(result: BacktestResult): BacktestConfigurationFull {
  return result.configuration as unknown as BacktestConfigurationFull;
}

// CHECKPOINT-FRONTEND-9: no `timeZone` option here rendered the
// VIEWER'S browser-local time for this backtest's own real
// `generated_at` moment, not IST - fixed to match the same
// `Asia/Kolkata` convention every other timestamp in this project
// uses.
function formatGeneratedAt(isoTimestamp: string): string {
  const parsed = new Date(isoTimestamp);
  if (Number.isNaN(parsed.getTime())) return isoTimestamp;
  return parsed.toLocaleString("en-IN", {
    dateStyle: "medium",
    timeStyle: "short",
    timeZone: "Asia/Kolkata",
  });
}

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
  const [listSort, setListSort] = useState<ListSort>("generated_at_desc");
  const [listPage, setListPage] = useState(1);
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
    setListPage(1);
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

  const sortedList = [...results].sort((a, b) => {
    switch (listSort) {
      case "generated_at_desc":
        return b.generated_at.localeCompare(a.generated_at);
      case "generated_at_asc":
        return a.generated_at.localeCompare(b.generated_at);
      case "instrument_id":
        return fullConfiguration(a).instrument_id.localeCompare(fullConfiguration(b).instrument_id);
      case "timeframe":
        return fullConfiguration(a).timeframe.localeCompare(fullConfiguration(b).timeframe);
      default:
        return 0;
    }
  });
  const { pageItems: pageResults, totalPages: listTotalPages, currentPage: listCurrentPage } =
    paginate(sortedList, listPage, RESULTS_PER_PAGE);

  const instrumentSet = new Set(selectedResults.map((r) => asConfigurationView(r).instrument_id));
  const timeframeSet = new Set(selectedResults.map((r) => asConfigurationView(r).timeframe));
  const dataQualitySet = new Set(
    selectedResults.map((r) => asDataQualityView(r).data_quality),
  );
  const costModelSet = new Set(
    selectedResults.map((r) => {
      const identity = r.cost_model_identity as unknown as {
        name: string;
        version: string;
        effective_from: string;
      };
      return `${identity.name}:${identity.version}:${identity.effective_from}`;
    }),
  );
  const slippageAssumptionSet = new Set(
    selectedResults.map((r) => asDataQualityView(r).slippage_assumption),
  );
  const incompatible =
    instrumentSet.size > 1 ||
    timeframeSet.size > 1 ||
    dataQualitySet.size > 1 ||
    costModelSet.size > 1 ||
    slippageAssumptionSet.size > 1;

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
        <label htmlFor="comparison-sort">Sort comparison table by</label>
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
            <legend>Select results to compare ({results.length} saved for this strategy)</legend>
            <div className="comparison-page__list-controls">
              <label>
                Sort list by
                <select
                  value={listSort}
                  onChange={(e) => {
                    setListSort(e.target.value as ListSort);
                    setListPage(1);
                  }}
                >
                  <option value="generated_at_desc">Newest first</option>
                  <option value="generated_at_asc">Oldest first</option>
                  <option value="instrument_id">Instrument</option>
                  <option value="timeframe">Timeframe</option>
                </select>
              </label>
            </div>
            {pageResults.map((r) => {
              const config = fullConfiguration(r);
              return (
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
                  <span className="comparison-page__result-primary">
                    {config.instrument_id} · {config.timeframe} · {formatGeneratedAt(r.generated_at)}
                  </span>{" "}
                  <span
                    className="comparison-page__result-secondary"
                    title={`Backtest ID: ${r.backtest_id}`}
                  >
                    ({r.backtest_id.slice(0, 12)}
                    {config.configuration_version ? `, config v${config.configuration_version}` : ""})
                  </span>
                </label>
              );
            })}
            <Pagination
              page={listCurrentPage}
              totalPages={listTotalPages}
              onChange={setListPage}
              totalItems={results.length}
              itemLabel="result"
            />
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
