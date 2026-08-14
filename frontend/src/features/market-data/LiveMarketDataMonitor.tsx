// frontend/src/features/market-data/LiveMarketDataMonitor.tsx
//
// Checkpoint 23: OBSERVATION-ONLY live market-data screen. Deliberately
// contains no Buy/Sell/Order/Quantity/Stop Loss/Target/Position/P&L/
// Execute/Trade control or field anywhere (Checkpoint 23 §12's explicit
// exclusion list) - this screen can only ever display what the backend
// itself exposes, and the backend has no such concept to expose.
//
// Auto-refreshes the READ endpoints (session/health/quotes) every 5
// seconds on a client-side timer - this never triggers a live Dhan
// call itself (matching the read-vs-refresh separation the backend
// enforces: GET session/health/quotes never call Dhan, only POST
// refresh/ does). A live Dhan fetch only happens when the operator
// explicitly clicks "Refresh Quotes."
import { useCallback, useEffect, useState } from "react";

import {
  getCurrentQuotes,
  getMarketDataHealth,
  getMarketSession,
  getRecentBars,
  refreshMarketData,
} from "../../common/api/marketDataApi";
import { ApiNetworkError, ApiRequestError } from "../../common/api/client";
import { useAuth } from "../../common/auth/AuthContext";
import { ErrorState } from "../../common/components/ErrorState";
import { LoadingState } from "../../common/components/LoadingState";
import type {
  BarResponse,
  MarketDataHealthResponse,
  QuoteResponse,
  SessionResponse,
} from "../../common/api/marketDataApi";

const AUTO_REFRESH_INTERVAL_MS = 5000;

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

type LoadState =
  | { phase: "loading" }
  | { phase: "error"; message: string }
  | {
      phase: "ready";
      session: SessionResponse;
      health: MarketDataHealthResponse;
      quotes: QuoteResponse[];
      bars: BarResponse[];
    };

export function LiveMarketDataMonitor(): JSX.Element {
  const { state: authState } = useAuth();
  const canRefresh =
    authState.status === "authenticated" && authState.capabilities.includes("configuration.activate");

  const [state, setState] = useState<LoadState>({ phase: "loading" });
  const [refreshing, setRefreshing] = useState(false);
  const [refreshError, setRefreshError] = useState<string | null>(null);

  const loadAll = useCallback(async (): Promise<void> => {
    try {
      const [session, health, quotes, bars] = await Promise.all([
        getMarketSession(),
        getMarketDataHealth(),
        getCurrentQuotes(),
        getRecentBars(),
      ]);
      setState({ phase: "ready", session, health, quotes, bars });
    } catch (error) {
      setState({ phase: "error", message: describeError(error) });
    }
  }, []);

  useEffect(() => {
    void loadAll();
    const interval = setInterval(() => void loadAll(), AUTO_REFRESH_INTERVAL_MS);
    return () => clearInterval(interval);
  }, [loadAll]);

  async function handleRefreshClick(): Promise<void> {
    setRefreshing(true);
    setRefreshError(null);
    try {
      await refreshMarketData();
      await loadAll();
    } catch (error) {
      setRefreshError(describeError(error));
    } finally {
      setRefreshing(false);
    }
  }

  return (
    <div className="market-data-monitor">
      <h1>Live Market Data Monitor</h1>
      <p className="configuration-viewer__subtitle">
        Read-only observation of live NSE cash-equity prices. No orders, positions, or trading
        controls exist on this screen.
      </p>

      {state.phase === "loading" && <LoadingState label="Loading market data…" />}
      {state.phase === "error" && <ErrorState message={state.message} />}

      {state.phase === "ready" && (
        <>
          <div className="market-data-monitor__summary">
            <section className="market-data-monitor__card" aria-labelledby="session-heading">
              <h2 id="session-heading">Market Session</h2>
              <p className="market-data-monitor__session-value">
                {SESSION_LABELS[state.session.status]}
              </p>
              <dl>
                <dt>Session Date</dt>
                <dd>{state.session.session_date}</dd>
                <dt>Exchange</dt>
                <dd>{state.session.exchange}</dd>
              </dl>
            </section>

            <section className="market-data-monitor__card" aria-labelledby="health-heading">
              <h2 id="health-heading">Connection Health</h2>
              <span className={`badge ${HEALTH_CLASS[state.health.state]}`}>
                {HEALTH_ICONS[state.health.state]} {HEALTH_LABELS[state.health.state]}
              </span>
              <dl>
                <dt>Last Update</dt>
                <dd>
                  {state.health.freshness_age_seconds !== null
                    ? formatAge(state.health.freshness_age_seconds)
                    : "Never"}
                </dd>
                <dt>Reconnect Count</dt>
                <dd>{state.health.reconnect_count}</dd>
                <dt>Last Error</dt>
                <dd>{state.health.last_error_safe || "None"}</dd>
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
            {state.quotes.length === 0 ? (
              <p className="market-data-monitor__empty">
                No quotes observed yet. {canRefresh ? "Press Refresh Quotes to fetch live data." : ""}
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
                  {state.quotes.map((quote) => (
                    <tr key={quote.symbol}>
                      <td>{quote.symbol}</td>
                      <td>₹{quote.last_price}</td>
                      <td>{formatTimestamp(quote.source_timestamp)}</td>
                      <td>{formatAge(quote.freshness_age_seconds)}</td>
                      <td>
                        <span className={`badge ${quote.is_stale ? "badge--pending" : "badge--active"}`}>
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
            {state.bars.length === 0 ? (
              <p className="market-data-monitor__empty">
                No bars aggregated yet. {canRefresh ? "Press Refresh Quotes to fetch live data." : ""}
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
                    <th scope="col">Volume</th>
                    <th scope="col">Status</th>
                    <th scope="col">Source Timestamp</th>
                  </tr>
                </thead>
                <tbody>
                  {state.bars.map((bar) => (
                    <tr key={`${bar.symbol}-${bar.interval_start}`}>
                      <td>{bar.symbol}</td>
                      <td>{bar.timeframe}</td>
                      <td>
                        {formatTimestamp(bar.interval_start)} – {formatTimestamp(bar.interval_end)}
                      </td>
                      <td>₹{bar.open}</td>
                      <td>₹{bar.high}</td>
                      <td>₹{bar.low}</td>
                      <td>₹{bar.close}</td>
                      <td>—</td>
                      <td>
                        <span
                          className={`badge ${bar.status === "CLOSED" ? "badge--active" : "badge--pending"}`}
                        >
                          {bar.status === "CLOSED" ? "● Closed" : "◐ Forming"}
                        </span>
                      </td>
                      <td>{formatTimestamp(bar.interval_end)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </section>
        </>
      )}
    </div>
  );
}
