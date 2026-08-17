// frontend/src/features/market-data/LiveMarketDataMonitor.tsx
//
// Checkpoint 23: OBSERVATION-ONLY live market-data screen. Deliberately
// contains no Buy/Sell/Order/Quantity/Stop Loss/Target/Position/P&L/
// Execute/Trade control anywhere this project has not actually computed
// those values for a given signal - see the honest "Not available from
// the current signal contract" fallback below, never a fabricated one.
//
// Checkpoint 62.x: redesigned from a raw market-data table into the
// ACTIVE SIGNAL MONITOR. The primary table shows only REAL, persisted,
// qualifying strategy signals (`GET /api/v1/config/signals/`,
// `signalApi.ts`) - never a market-data row. QUOTE != SIGNAL, BAR !=
// SIGNAL, STRATEGY EVALUATION != SIGNAL: a signal only exists in this
// table when `PaperSignalExecutionService.evaluate_and_submit()`
// (backend) genuinely produced one - proven by
// `test_a_flat_bar_series_with_no_signal_records_nothing` in the
// backend test suite. The former raw-market-data view (session, quote
// freshness, recent bars) is retained as a secondary, collapsible
// "Market Data Health" diagnostic section, not removed.
//
// Every filter control (timeframe/universe/strategy) is a REAL,
// server-side query parameter on `listSignals()` - never a cosmetic
// dropdown filtering an already-fetched array. The strategy list and
// observed-instrument universe are both read from real backend sources
// (`listStrategies()`, `getCurrentQuotes()`), never hard-coded.
import { useCallback, useEffect, useMemo, useState } from "react";

import {
  getCurrentQuotes,
  getMarketDataHealth,
  getMarketSession,
  getRecentBars,
  refreshMarketData,
} from "../../common/api/marketDataApi";
import { ApiNetworkError, ApiRequestError } from "../../common/api/client";
import { listSignals } from "../../common/api/signalApi";
import { listStrategies } from "../../common/api/strategyApi";
import { useAuth } from "../../common/auth/AuthContext";
import { EmptyState } from "../../common/components/EmptyState";
import { ErrorState } from "../../common/components/ErrorState";
import { LoadingState } from "../../common/components/LoadingState";
import type {
  BarResponse,
  MarketDataHealthResponse,
  QuoteResponse,
  SessionResponse,
} from "../../common/api/marketDataApi";
import type { SignalResponse } from "../../common/api/signalApi";
import type { StrategySummary } from "../../common/api/strategyApi";

const AUTO_REFRESH_INTERVAL_MS = 5000;
const SIGNAL_PAGE_SIZE = 10;

// The real, intraday-relevant subset of `domain.shared_kernel.contracts
// .Timeframe` (Checkpoint 62.x Phase 4 - `TICK` and `1d` are real enum
// members but not meaningful choices for an intraday SCANNING
// workflow, so they are deliberately excluded from this control rather
// than exposed merely because the enum has them).
const TIMEFRAME_OPTIONS = ["1m", "3m", "5m", "15m", "30m", "1h"] as const;

type UniverseMode = "all" | "selected";

function DataQualityBanner(): JSX.Element {
  return (
    <div className="callout callout--warn" role="note">
      <span className="badge badge--pending">◐ SAMPLE_BAR</span> Prices shown here are built from
      periodic point-in-time samples, not a continuous market-data stream. This is real, honest
      market data - never fabricated - but it cannot yet guarantee a true OPEN/HIGH/LOW/CLOSE the
      way continuous tick coverage or exchange-computed candles could, so it is not yet{" "}
      <strong>TRADING_GRADE_BAR</strong>. A green connection indicator below means the platform is
      successfully talking to the data provider - it does <strong>not</strong> mean these candles
      are trading-grade, and it does <strong>not</strong> mean signals below were generated from a
      continuous live feed.
    </div>
  );
}

const SESSION_LABELS: Record<SessionResponse["status"], string> = {
  PRE_OPEN: "Pre-Market",
  OPEN: "Market Open",
  CLOSED: "Market Closed",
};

const HEALTH_LABELS: Record<MarketDataHealthResponse["state"], string> = {
  CONNECTED_FRESH: "Connected",
  CONNECTED_STALE: "Connected (Stale)",
  DISCONNECTED: "Disconnected",
  AUTHENTICATION_FAILED: "Authentication Failed",
  ERROR: "Error",
  MARKET_CLOSED: "Market Closed",
};

const HEALTH_ICONS: Record<MarketDataHealthResponse["state"], string> = {
  CONNECTED_FRESH: "●",
  CONNECTED_STALE: "◐",
  DISCONNECTED: "○",
  AUTHENTICATION_FAILED: "✕",
  ERROR: "✕",
  MARKET_CLOSED: "○",
};

const HEALTH_CLASS: Record<MarketDataHealthResponse["state"], string> = {
  CONNECTED_FRESH: "badge--active",
  CONNECTED_STALE: "badge--pending",
  DISCONNECTED: "badge--historical",
  AUTHENTICATION_FAILED: "badge--danger",
  ERROR: "badge--danger",
  MARKET_CLOSED: "badge--historical",
};

function describeError(error: unknown): string {
  if (error instanceof ApiRequestError || error instanceof ApiNetworkError) {
    return error.message;
  }
  return "An unexpected error occurred.";
}

function formatAge(seconds: number): string {
  if (seconds < 60) return `${Math.round(seconds)}s ago`;
  if (seconds < 3600) return `${Math.round(seconds / 60)}m ago`;
  return `${Math.round(seconds / 3600)}h ago`;
}

function formatTimestamp(value: string): string {
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return value;
  return parsed.toLocaleString("en-IN", { timeZone: "Asia/Kolkata" });
}

function symbolFromInstrumentId(instrumentId: string): string {
  // `InstrumentId` is `"{exchange}:{symbol}"` (backend format,
  // `domain.instrument.contracts.make_instrument_id`) - the signal
  // table shows the plain symbol, matching the market-data table's
  // own display convention.
  const parts = instrumentId.split(":");
  return parts.length > 1 ? parts[1] : instrumentId;
}

type MarketDataState =
  | { phase: "loading" }
  | { phase: "error"; message: string }
  | {
      phase: "ready";
      session: SessionResponse;
      health: MarketDataHealthResponse;
      quotes: QuoteResponse[];
      bars: BarResponse[];
    };

type SignalListState =
  | { phase: "loading" }
  | { phase: "error"; message: string }
  | { phase: "ready"; items: SignalResponse[]; totalCount: number };

export function LiveMarketDataMonitor(): JSX.Element {
  const { state: authState } = useAuth();
  const canRefresh =
    authState.status === "authenticated" && authState.capabilities.includes("configuration.activate");

  // --- Market-data diagnostics (Checkpoint 23, retained as a secondary section) ---
  const [marketData, setMarketData] = useState<MarketDataState>({ phase: "loading" });
  const [refreshing, setRefreshing] = useState(false);
  const [refreshError, setRefreshError] = useState<string | null>(null);
  const [diagnosticsOpen, setDiagnosticsOpen] = useState(false);

  // --- Real strategy registry (never a hard-coded list) ---
  const [strategies, setStrategies] = useState<StrategySummary[] | null>(null);

  // --- Scanning configuration - every value here is a REAL filter on
  // the signals query, never a cosmetic control. ---
  const [timeframe, setTimeframe] = useState<string>("5m");
  const [universeMode, setUniverseMode] = useState<UniverseMode>("all");
  const [selectedInstrumentIds, setSelectedInstrumentIds] = useState<Set<string>>(new Set());
  const [selectedStrategyIds, setSelectedStrategyIds] = useState<Set<string>>(new Set());

  // --- Signals (the primary table) ---
  const [signalState, setSignalState] = useState<SignalListState>({ phase: "loading" });
  const [page, setPage] = useState(1);
  const [selectedSignal, setSelectedSignal] = useState<SignalResponse | null>(null);

  const loadMarketData = useCallback(async (): Promise<void> => {
    try {
      const [session, health, quotes, bars] = await Promise.all([
        getMarketSession(),
        getMarketDataHealth(),
        getCurrentQuotes(),
        getRecentBars(),
      ]);
      setMarketData({ phase: "ready", session, health, quotes, bars });
    } catch (error) {
      setMarketData({ phase: "error", message: describeError(error) });
    }
  }, []);

  useEffect(() => {
    void loadMarketData();
    const interval = setInterval(() => void loadMarketData(), AUTO_REFRESH_INTERVAL_MS);
    return () => clearInterval(interval);
  }, [loadMarketData]);

  useEffect(() => {
    let cancelled = false;
    listStrategies()
      .then((result) => {
        if (!cancelled) setStrategies(result);
      })
      .catch(() => {
        if (!cancelled) setStrategies([]);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  // Once the real strategy list arrives, default to "all selected" -
  // never an empty selection that would silently scan nothing.
  useEffect(() => {
    if (strategies && strategies.length > 0 && selectedStrategyIds.size === 0) {
      setSelectedStrategyIds(new Set(strategies.map((s) => s.strategy_id)));
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [strategies]);

  const observedInstrumentIds = useMemo((): string[] => {
    if (marketData.phase !== "ready") return [];
    return Array.from(new Set(marketData.quotes.map((q) => `${q.exchange}:${q.symbol}`)));
  }, [marketData]);

  const activeStrategyFilter = useMemo((): string | undefined => {
    if (!strategies || strategies.length === 0) return undefined;
    // The signals API accepts exactly one `strategy_id` filter - when
    // every strategy is selected (the common case), no filter is sent
    // at all (equivalent to "any strategy"); when the operator narrows
    // to exactly one, that one is used as a real query parameter.
    if (selectedStrategyIds.size === 1) return Array.from(selectedStrategyIds)[0];
    return undefined;
  }, [strategies, selectedStrategyIds]);

  const activeInstrumentFilter = useMemo((): string | undefined => {
    if (universeMode === "all") return undefined;
    if (selectedInstrumentIds.size === 1) return Array.from(selectedInstrumentIds)[0];
    return undefined;
  }, [universeMode, selectedInstrumentIds]);

  const loadSignals = useCallback(async (): Promise<void> => {
    // Only show the loading state on a genuine first load. A filter
    // change (e.g. the strategies auto-select-all effect firing after
    // the strategy registry loads) re-triggers this fetch, but must not
    // flash previously-rendered signal rows/controls back to "loading"
    // - that would unmount interactive elements (like a Details button)
    // mid-interaction for no user-visible reason.
    setSignalState((previous) => (previous.phase === "ready" ? previous : { phase: "loading" }));
    try {
      const result = await listSignals({
        page,
        pageSize: SIGNAL_PAGE_SIZE,
        timeframe,
        strategyId: activeStrategyFilter,
        instrumentId: activeInstrumentFilter,
      });
      setSignalState({ phase: "ready", items: result.items, totalCount: result.total_count });
    } catch (error) {
      setSignalState({ phase: "error", message: describeError(error) });
    }
  }, [page, timeframe, activeStrategyFilter, activeInstrumentFilter]);

  useEffect(() => {
    void loadSignals();
  }, [loadSignals]);

  useEffect(() => {
    setPage(1);
  }, [timeframe, activeStrategyFilter, activeInstrumentFilter]);

  async function handleRefreshClick(): Promise<void> {
    setRefreshing(true);
    setRefreshError(null);
    try {
      await refreshMarketData();
      await loadMarketData();
    } catch (error) {
      setRefreshError(describeError(error));
    } finally {
      setRefreshing(false);
    }
  }

  function toggleStrategy(strategyId: string): void {
    setSelectedStrategyIds((prev) => {
      const next = new Set(prev);
      if (next.has(strategyId)) next.delete(strategyId);
      else next.add(strategyId);
      return next;
    });
  }

  function toggleInstrument(instrumentId: string): void {
    setSelectedInstrumentIds((prev) => {
      const next = new Set(prev);
      if (next.has(instrumentId)) next.delete(instrumentId);
      else next.add(instrumentId);
      return next;
    });
  }

  const totalPages =
    signalState.phase === "ready" ? Math.max(1, Math.ceil(signalState.totalCount / SIGNAL_PAGE_SIZE)) : 1;

  return (
    <div className="signal-monitor">
      <header className="signal-monitor__header">
        <h1>Active Signal Monitor</h1>
        <p className="configuration-viewer__subtitle">
          Monitor qualifying strategy signals generated from the selected market universe and
          timeframe. No order, position, or trading controls exist on this screen.
        </p>
      </header>

      <div className="signal-monitor__layout">
        <aside className="signal-monitor__sidebar" aria-label="Scanning configuration">
          <h2>Scanning Configuration</h2>

          <div className="signal-monitor__field">
            <label htmlFor="timeframe-select">Timeframe</label>
            <select
              id="timeframe-select"
              value={timeframe}
              onChange={(event) => setTimeframe(event.target.value)}
            >
              {TIMEFRAME_OPTIONS.map((option) => (
                <option key={option} value={option}>
                  {option}
                </option>
              ))}
            </select>
          </div>

          <div className="signal-monitor__field">
            <span className="signal-monitor__field-label">Stock Universe</span>
            <label className="signal-monitor__radio">
              <input
                type="radio"
                name="universe-mode"
                checked={universeMode === "all"}
                onChange={() => setUniverseMode("all")}
              />
              All Stocks
            </label>
            <label className="signal-monitor__radio">
              <input
                type="radio"
                name="universe-mode"
                checked={universeMode === "selected"}
                onChange={() => setUniverseMode("selected")}
              />
              Selected Stocks
            </label>
            {universeMode === "selected" && (
              <div className="signal-monitor__checklist" role="group" aria-label="Selected stocks">
                {observedInstrumentIds.length === 0 ? (
                  <p className="signal-monitor__hint">
                    No observed instruments yet - the current configured universe has not returned
                    any quotes.
                  </p>
                ) : (
                  observedInstrumentIds.map((instrumentId) => (
                    <label key={instrumentId} className="signal-monitor__checkbox">
                      <input
                        type="checkbox"
                        checked={selectedInstrumentIds.has(instrumentId)}
                        onChange={() => toggleInstrument(instrumentId)}
                      />
                      {symbolFromInstrumentId(instrumentId)}
                    </label>
                  ))
                )}
                <p className="signal-monitor__hint">
                  This project's currently configured observation universe is limited to a small,
                  hand-verified symbol list (see the market-data health section below) - not the
                  full NSE cash-equity universe.
                </p>
              </div>
            )}
          </div>

          <div className="signal-monitor__field">
            <span className="signal-monitor__field-label">Strategies</span>
            {strategies === null && <p className="signal-monitor__hint">Loading strategies…</p>}
            {strategies !== null && strategies.length === 0 && (
              <p className="signal-monitor__hint">No strategies registered.</p>
            )}
            {strategies !== null &&
              strategies.map((strategy) => (
                <label key={strategy.strategy_id} className="signal-monitor__checkbox">
                  <input
                    type="checkbox"
                    checked={selectedStrategyIds.has(strategy.strategy_id)}
                    onChange={() => toggleStrategy(strategy.strategy_id)}
                  />
                  {strategy.display_name}
                </label>
              ))}
            {strategies !== null && strategies.length > 0 && (
              <div className="signal-monitor__strategy-actions">
                <button
                  type="button"
                  className="signal-monitor__link-button"
                  onClick={() => setSelectedStrategyIds(new Set(strategies.map((s) => s.strategy_id)))}
                >
                  Select All
                </button>
                <button
                  type="button"
                  className="signal-monitor__link-button"
                  onClick={() => setSelectedStrategyIds(new Set())}
                >
                  Clear
                </button>
              </div>
            )}
            {selectedStrategyIds.size > 1 && (
              <p className="signal-monitor__hint">
                Showing signals from any strategy - the signals API filters by exactly one strategy
                at a time; narrow to a single strategy above to filter the table by it.
              </p>
            )}
          </div>

          <div className="signal-monitor__field">
            <span className="signal-monitor__field-label">Scan Source</span>
            <p className="signal-monitor__hint">
              Signals shown here are recorded by the platform's own scheduled active loop whenever a
              selected strategy evaluates real bar data and produces a qualifying signal - this page
              does not itself start or stop that process.
            </p>
          </div>
        </aside>

        <main className="signal-monitor__main">
          <section className="signal-monitor__summary" aria-label="Summary">
            <div className="signal-monitor__summary-card">
              <span className="signal-monitor__summary-label">Market Status</span>
              <span className="signal-monitor__summary-value">
                {marketData.phase === "ready" ? SESSION_LABELS[marketData.session.status] : "—"}
              </span>
            </div>
            <div className="signal-monitor__summary-card">
              <span className="signal-monitor__summary-label">Data Feed</span>
              <span className="signal-monitor__summary-value">
                {marketData.phase === "ready" ? (
                  <span className={`badge ${HEALTH_CLASS[marketData.health.state]}`}>
                    {HEALTH_ICONS[marketData.health.state]} {HEALTH_LABELS[marketData.health.state]}
                  </span>
                ) : (
                  "—"
                )}
              </span>
            </div>
            <div className="signal-monitor__summary-card">
              <span className="signal-monitor__summary-label">Stocks Observed</span>
              <span className="signal-monitor__summary-value">{observedInstrumentIds.length}</span>
            </div>
            <div className="signal-monitor__summary-card">
              <span className="signal-monitor__summary-label">Active Signals</span>
              <span className="signal-monitor__summary-value">
                {signalState.phase === "ready" ? signalState.totalCount : "—"}
              </span>
            </div>
            <div className="signal-monitor__summary-card">
              <span className="signal-monitor__summary-label">Last Signal</span>
              <span className="signal-monitor__summary-value">
                {signalState.phase === "ready" && signalState.items.length > 0
                  ? formatAge(
                      (Date.now() - new Date(signalState.items[0].signal_timestamp).getTime()) / 1000,
                    )
                  : "—"}
              </span>
            </div>
          </section>

          <section aria-labelledby="signals-heading">
            <h2 id="signals-heading">Active Signals</h2>

            {signalState.phase === "loading" && <LoadingState label="Loading signals…" />}
            {signalState.phase === "error" && <ErrorState message={signalState.message} />}

            {signalState.phase === "ready" && signalState.items.length === 0 && (
              <EmptyState
                message={`No active signals. Timeframe: ${timeframe}. Universe: ${
                  universeMode === "all" ? "All Stocks" : `${selectedInstrumentIds.size} selected`
                }. Strategies are actively monitoring the selected universe - no qualifying signal has been generated.`}
              />
            )}

            {signalState.phase === "ready" && signalState.items.length > 0 && (
              <>
                <table className="signal-monitor__table">
                  <thead>
                    <tr>
                      <th scope="col">Strategy</th>
                      <th scope="col">Stock</th>
                      <th scope="col">Direction</th>
                      <th scope="col">Timeframe</th>
                      <th scope="col">Signal Time</th>
                      <th scope="col">Signal Price</th>
                      <th scope="col">Risk</th>
                      <th scope="col">Order</th>
                      <th scope="col" aria-label="Details" />
                    </tr>
                  </thead>
                  <tbody>
                    {signalState.items.map((signal) => (
                      <tr key={signal.signal_id}>
                        <td>{signal.strategy_id}</td>
                        <td>{symbolFromInstrumentId(signal.instrument_id)}</td>
                        <td>
                          <span
                            className={`badge ${signal.direction === "BULLISH" ? "badge--active" : "badge--danger"}`}
                          >
                            {signal.direction}
                          </span>
                        </td>
                        <td>{signal.timeframe}</td>
                        <td>{formatTimestamp(signal.signal_timestamp)}</td>
                        <td>₹{signal.price}</td>
                        <td>
                          <span
                            className={`badge ${signal.risk_status === "APPROVED" ? "badge--active" : "badge--danger"}`}
                          >
                            {signal.risk_status}
                          </span>
                        </td>
                        <td>{signal.order_status || "—"}</td>
                        <td>
                          <button
                            type="button"
                            className="signal-monitor__link-button"
                            onClick={() => setSelectedSignal(signal)}
                          >
                            Details
                          </button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>

                <div className="signal-monitor__pagination">
                  <button type="button" disabled={page <= 1} onClick={() => setPage((p) => p - 1)}>
                    ← Previous
                  </button>
                  <span>
                    Page {page} of {totalPages} ({signalState.totalCount} total)
                  </span>
                  <button
                    type="button"
                    disabled={page >= totalPages}
                    onClick={() => setPage((p) => p + 1)}
                  >
                    Next →
                  </button>
                </div>
              </>
            )}
          </section>

          {selectedSignal && (
            <section
              className="signal-monitor__details"
              aria-labelledby="signal-details-heading"
              role="dialog"
              aria-modal="false"
            >
              <div className="signal-monitor__details-header">
                <h2 id="signal-details-heading">Signal Details</h2>
                <button
                  type="button"
                  className="signal-monitor__link-button"
                  onClick={() => setSelectedSignal(null)}
                >
                  Close
                </button>
              </div>
              <dl className="signal-monitor__details-grid">
                <dt>Strategy</dt>
                <dd>{selectedSignal.strategy_id}</dd>
                <dt>Stock</dt>
                <dd>{symbolFromInstrumentId(selectedSignal.instrument_id)}</dd>
                <dt>Timeframe</dt>
                <dd>{selectedSignal.timeframe}</dd>
                <dt>Direction</dt>
                <dd>{selectedSignal.direction}</dd>
                <dt>Generated At</dt>
                <dd>{formatTimestamp(selectedSignal.signal_timestamp)}</dd>
                <dt>Signal Price</dt>
                <dd>₹{selectedSignal.price}</dd>
                <dt>Risk Status</dt>
                <dd>{selectedSignal.risk_status}</dd>
                {selectedSignal.risk_reason && (
                  <>
                    <dt>Risk Reason</dt>
                    <dd>{selectedSignal.risk_reason}</dd>
                  </>
                )}
                <dt>Order Status</dt>
                <dd>{selectedSignal.order_status || "—"}</dd>
                <dt>Entry / Stop Loss / Targets</dt>
                <dd className="signal-monitor__unavailable">
                  Not available from the current signal contract - this platform's signal
                  pipeline does not yet compute or persist per-signal entry/stop-loss/target
                  levels.
                </dd>
                <dt>Why this signal?</dt>
                <dd className="signal-monitor__unavailable">
                  Not available from the current signal contract - the strategy engine does not
                  yet expose a per-condition evidence trail (which indicator conditions passed or
                  failed) through this API.
                </dd>
              </dl>
            </section>
          )}

          <section className="signal-monitor__diagnostics">
            <button
              type="button"
              className="signal-monitor__link-button"
              onClick={() => setDiagnosticsOpen((open) => !open)}
              aria-expanded={diagnosticsOpen}
            >
              {diagnosticsOpen ? "▾" : "▸"} Market Data Health
            </button>

            {diagnosticsOpen && (
              <div className="signal-monitor__diagnostics-body">
                <DataQualityBanner />

                {marketData.phase === "loading" && <LoadingState label="Loading market data…" />}
                {marketData.phase === "error" && <ErrorState message={marketData.message} />}

                {marketData.phase === "ready" && (
                  <>
                    <div className="market-data-monitor__summary">
                      <section className="market-data-monitor__card" aria-labelledby="session-heading">
                        <h2 id="session-heading">Market Session</h2>
                        <p className="market-data-monitor__session-value">
                          {SESSION_LABELS[marketData.session.status]}
                        </p>
                        <dl>
                          <dt>Session Date</dt>
                          <dd>{marketData.session.session_date}</dd>
                          <dt>Exchange</dt>
                          <dd>{marketData.session.exchange}</dd>
                        </dl>
                      </section>

                      <section className="market-data-monitor__card" aria-labelledby="health-heading">
                        <h2 id="health-heading">Connection Health</h2>
                        <span className={`badge ${HEALTH_CLASS[marketData.health.state]}`}>
                          {HEALTH_ICONS[marketData.health.state]} {HEALTH_LABELS[marketData.health.state]}
                        </span>
                        <dl>
                          <dt>Last Update</dt>
                          <dd>
                            {marketData.health.freshness_age_seconds !== null
                              ? formatAge(marketData.health.freshness_age_seconds)
                              : "Never"}
                          </dd>
                          <dt>Reconnect Count</dt>
                          <dd>{marketData.health.reconnect_count}</dd>
                          <dt>Last Error</dt>
                          <dd>{marketData.health.last_error_safe || "None"}</dd>
                        </dl>

                        {canRefresh ? (
                          <>
                            <button
                              type="button"
                              className="market-data-monitor__refresh-button"
                              onClick={() => void handleRefreshClick()}
                              disabled={refreshing}
                            >
                              {refreshing ? "Refreshing…" : "Refresh Quotes"}
                            </button>
                            {refreshError && (
                              <p role="alert" className="dialog__error">
                                {refreshError}
                              </p>
                            )}
                          </>
                        ) : (
                          <p className="settings-card__readonly-note">
                            You have read-only access to this screen.
                          </p>
                        )}
                      </section>
                    </div>

                    <section aria-labelledby="instruments-heading">
                      <h2 id="instruments-heading">Observed Instruments</h2>
                      {marketData.quotes.length === 0 ? (
                        <p className="market-data-monitor__empty">
                          No quotes observed yet.{" "}
                          {canRefresh ? "Press Refresh Quotes to fetch live data." : ""}
                        </p>
                      ) : (
                        <table className="market-data-monitor__table">
                          <thead>
                            <tr>
                              <th scope="col">Symbol</th>
                              <th scope="col">LTP</th>
                              <th scope="col">Timestamp</th>
                              <th scope="col">Freshness</th>
                              <th scope="col">Status</th>
                            </tr>
                          </thead>
                          <tbody>
                            {marketData.quotes.map((quote) => (
                              <tr key={quote.symbol}>
                                <td>{quote.symbol}</td>
                                <td>₹{quote.last_price}</td>
                                <td>{formatTimestamp(quote.source_timestamp)}</td>
                                <td>{formatAge(quote.freshness_age_seconds)}</td>
                                <td>
                                  <span
                                    className={`badge ${quote.is_stale ? "badge--pending" : "badge--active"}`}
                                  >
                                    {quote.is_stale ? "◐ Stale" : "● Fresh"}
                                  </span>
                                </td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      )}
                    </section>

                    <section aria-labelledby="bars-heading">
                      <h2 id="bars-heading">Recent Bars (1-Minute)</h2>
                      {marketData.bars.length === 0 ? (
                        <p className="market-data-monitor__empty">
                          No bars aggregated yet.{" "}
                          {canRefresh ? "Press Refresh Quotes to fetch live data." : ""}
                        </p>
                      ) : (
                        <table className="market-data-monitor__table">
                          <thead>
                            <tr>
                              <th scope="col">Symbol</th>
                              <th scope="col">Timeframe</th>
                              <th scope="col">Interval</th>
                              <th scope="col">Open</th>
                              <th scope="col">High</th>
                              <th scope="col">Low</th>
                              <th scope="col">Close</th>
                              <th scope="col">Status</th>
                            </tr>
                          </thead>
                          <tbody>
                            {marketData.bars.map((bar) => (
                              <tr key={`${bar.symbol}-${bar.interval_start}`}>
                                <td>{bar.symbol}</td>
                                <td>{bar.timeframe}</td>
                                <td>
                                  {formatTimestamp(bar.interval_start)} –{" "}
                                  {formatTimestamp(bar.interval_end)}
                                </td>
                                <td>₹{bar.open}</td>
                                <td>₹{bar.high}</td>
                                <td>₹{bar.low}</td>
                                <td>₹{bar.close}</td>
                                <td>
                                  <span
                                    className={`badge ${bar.status === "CLOSED" ? "badge--active" : "badge--pending"}`}
                                  >
                                    {bar.status === "CLOSED" ? "● Closed" : "◐ Forming"}
                                  </span>
                                </td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      )}
                    </section>
                  </>
                )}
              </div>
            )}
          </section>
        </main>
      </div>
    </div>
  );
}
