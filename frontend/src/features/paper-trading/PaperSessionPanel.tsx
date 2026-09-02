// frontend/src/features/paper-trading/PaperSessionPanel.tsx
//
// Checkpoint 64.68 §9/§10: the Paper Trading SESSION surface, rendered
// inside the EXISTING `PaperTradingPage` rather than as a new page -
// §9's "Create/reuse a Paper Trading page" and "do NOT redesign the
// entire application". Uses the project's existing frontend stack
// (React 18 + Vite + plain CSS classes from `app/styles.css`) and its
// existing conventions (`apiGet`/`apiPost` wrappers, generated contract
// types, `LoadingState`/`ErrorState`, `useAuth` capability gating).
//
// LIVE SAFETY (§10), enforced here and re-asserted by the backend's own
// `mode: "PAPER_REPLAY"` field:
//   - Every control says "Paper Trading" explicitly: "Start Paper
//     Trading", "Stop Paper Trading". There is no bare "Trade" button.
//   - There is no live-broker control of any kind on this panel.
//   - A prominent banner states this is a deterministic REPLAY, and
//     that these are simulated fills, not real executions.
import { useCallback, useEffect, useState } from "react";

import { ApiNetworkError, ApiRequestError } from "../../common/api/client";
import {
  configurePaperSession,
  getPaperSession,
  pausePaperSession,
  resetPaperSession,
  resumePaperSession,
  startPaperSession,
  stepPaperSession,
  stopPaperSession,
} from "../../common/api/paperSessionApi";
import type { PaperSessionResponse } from "../../common/api/paperSessionApi";
import { useAuth } from "../../common/auth/AuthContext";
import { ErrorState } from "../../common/components/ErrorState";
import { LoadingState } from "../../common/components/LoadingState";
import { badgeIconName } from "../../common/components/statusIcon";
import { Icon } from "../../common/icons/Icon";

const TIMEFRAMES = ["1m", "3m", "5m", "15m", "30m"] as const;
type SelectableTimeframe = (typeof TIMEFRAMES)[number];

function asTimeframe(value: string): SelectableTimeframe {
  return (TIMEFRAMES as readonly string[]).includes(value)
    ? (value as SelectableTimeframe)
    : "5m";
}

function describeError(error: unknown): string {
  if (error instanceof ApiRequestError || error instanceof ApiNetworkError) {
    return error.message;
  }
  return "An unexpected error occurred.";
}

const STATUS_BADGE: Record<string, string> = {
  RUNNING: "badge--active",
  PAUSED: "badge--pending",
  STOPPED: "badge--historical",
  COMPLETED: "badge--info",
  FAILED: "badge--danger",
};

function money(value: string | number | undefined): string {
  if (value === undefined || value === null) return "—";
  return `₹${Number(value).toLocaleString("en-IN", { maximumFractionDigits: 2 })}`;
}

function pnlClass(value: string | number | undefined): string {
  return Number(value ?? 0) < 0 ? "paper-trading__pnl--negative" : "paper-trading__pnl--positive";
}

type LoadState =
  | { phase: "loading" }
  | { phase: "error"; message: string }
  | { phase: "ready"; session: PaperSessionResponse };

export function PaperSessionPanel(): JSX.Element {
  const { state: authState } = useAuth();
  const canOperate =
    authState.status === "authenticated" &&
    authState.capabilities.includes("configuration.activate");

  const [state, setState] = useState<LoadState>({ phase: "loading" });
  const [busy, setBusy] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [form, setForm] = useState({
    strategyId: "",
    instrumentIds: "NSE:RELIANCE",
    timeframe: "5m" as SelectableTimeframe,
    startingCapital: "1000000",
    quantity: "10",
    playbackSpeed: "5",
  });

  const load = useCallback(async (): Promise<void> => {
    try {
      const session = await getPaperSession();
      setState({ phase: "ready", session });
      setForm((current) => ({
        ...current,
        strategyId:
          current.strategyId || session.strategy_id || session.available_strategy_ids[0] || "",
        instrumentIds:
          session.instrument_ids.length > 0
            ? session.instrument_ids.join(", ")
            : current.instrumentIds,
        timeframe: asTimeframe(session.timeframe || current.timeframe),
      }));
    } catch (error) {
      setState({ phase: "error", message: describeError(error) });
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  async function run(action: () => Promise<PaperSessionResponse>): Promise<void> {
    setBusy(true);
    setActionError(null);
    setNotice(null);
    try {
      const session = await action();
      setState({ phase: "ready", session });
      setNotice(session.message || null);
    } catch (error) {
      setActionError(describeError(error));
    } finally {
      setBusy(false);
    }
  }

  function handleConfigure(): void {
    void run(() =>
      configurePaperSession({
        strategy_id: form.strategyId,
        instrument_ids: form.instrumentIds
          .split(",")
          .map((value) => value.trim())
          .filter((value) => value.length > 0),
        timeframe: form.timeframe,
        starting_capital: form.startingCapital,
        quantity: form.quantity,
        playback_speed: Number(form.playbackSpeed),
      }),
    );
  }

  if (state.phase === "loading") {
    return <LoadingState label="Loading paper trading session…" />;
  }
  if (state.phase === "error") {
    return <ErrorState message={state.message} />;
  }

  const session = state.session;
  const account = session.account;
  const status = session.status;
  const running = status === "RUNNING";
  const paused = status === "PAUSED";
  const stoppable = running || paused;

  return (
    <section className="capability-status-section" aria-labelledby="paper-session-heading">
      <h2 id="paper-session-heading">Paper Trading Session (Deterministic Replay)</h2>

      <div className="callout callout--warn" role="note">
        <strong>
          <Icon name="paper-trading" /> PAPER TRADING — NOT LIVE TRADING.
        </strong>{" "}
        This session replays deterministic,
        pre-generated market data through the paper broker. Every fill, position and P&amp;L figure
        below is <strong>simulated</strong>. No real broker connection, no real market data and no
        real order is involved anywhere on this screen, and{" "}
        <strong>LIVE TRADING — NOT AVAILABLE</strong>. Results here do not demonstrate real-market
        performance.
      </div>

      <div className="paper-trading__kpis">
        <div className="paper-trading__kpi">
          <span>Status</span>
          <strong>
            <span className={`badge ${STATUS_BADGE[status] ?? "badge--info"}`}>
              <Icon name={badgeIconName(STATUS_BADGE[status])} /> {status}
            </span>
          </strong>
        </div>
        <div className="paper-trading__kpi">
          <span>Strategy</span>
          <strong>{session.strategy_id || "—"}</strong>
        </div>
        <div className="paper-trading__kpi">
          <span>Timeframe</span>
          <strong>{session.timeframe}</strong>
        </div>
        <div className="paper-trading__kpi">
          <span>Symbol Universe</span>
          <strong>{session.instrument_ids.join(", ") || "—"}</strong>
        </div>
        <div className="paper-trading__kpi">
          <span>Replay Progress</span>
          <strong>
            {session.replay_cursor} / {session.replay_total_steps}
          </strong>
        </div>
        <div className="paper-trading__kpi">
          <span>Replay Date (simulated)</span>
          <strong>{session.replay_date}</strong>
        </div>
      </div>

      <h3>Replay Session Account (Simulated)</h3>
      <p className="signal-monitor__hint">
        Tracks only this replay session&apos;s simulated fills — not the standing Live Paper
        Trading account used elsewhere in the app.
      </p>
      <div className="paper-trading__kpis">
        <div className="paper-trading__kpi">
          <span>Starting Capital (Paper)</span>
          <strong>{money(account.starting_capital)}</strong>
        </div>
        <div className="paper-trading__kpi">
          <span>Available Capital (Paper)</span>
          <strong>{money(account.available_capital)}</strong>
        </div>
        <div className="paper-trading__kpi">
          <span>Equity (Paper)</span>
          <strong>{money(account.equity)}</strong>
        </div>
        <div className="paper-trading__kpi">
          <span>Realized P&amp;L (Paper)</span>
          <strong className={pnlClass(account.realized_pnl)}>{money(account.realized_pnl)}</strong>
        </div>
        <div className="paper-trading__kpi">
          <span>Unrealized P&amp;L (Paper)</span>
          <strong className={pnlClass(account.unrealized_pnl)}>
            {money(account.unrealized_pnl)}
          </strong>
        </div>
        <div className="paper-trading__kpi">
          <span>Total P&amp;L (Paper)</span>
          <strong className={pnlClass(account.total_pnl)}>{money(account.total_pnl)}</strong>
        </div>
        <div className="paper-trading__kpi">
          <span>Drawdown (Paper)</span>
          <strong>{money(account.drawdown)}</strong>
        </div>
      </div>

      {!canOperate && (
        <p className="settings-card__readonly-note">You have read-only access to this screen.</p>
      )}

      {canOperate && (
        <>
          <h3>Session Setup</h3>
          <div className="form-grid">
            <label>
              Strategy
              <select
                value={form.strategyId}
                onChange={(e) => setForm((f) => ({ ...f, strategyId: e.target.value }))}
                disabled={stoppable}
              >
                {session.available_strategy_ids.map((id) => (
                  <option key={id} value={id}>
                    {id}
                  </option>
                ))}
              </select>
            </label>
            <label>
              Symbols (comma-separated)
              <input
                type="text"
                value={form.instrumentIds}
                disabled={stoppable}
                onChange={(e) => setForm((f) => ({ ...f, instrumentIds: e.target.value }))}
              />
            </label>
            <label>
              Timeframe
              <select
                value={form.timeframe}
                disabled={stoppable}
                onChange={(e) => setForm((f) => ({ ...f, timeframe: asTimeframe(e.target.value) }))}
              >
                {TIMEFRAMES.map((tf) => (
                  <option key={tf} value={tf}>
                    {tf}
                  </option>
                ))}
              </select>
            </label>
            <label>
              Starting Capital (Paper)
              <input
                type="number"
                value={form.startingCapital}
                disabled={stoppable}
                onChange={(e) => setForm((f) => ({ ...f, startingCapital: e.target.value }))}
              />
            </label>
            <label>
              Quantity per Signal
              <input
                type="number"
                value={form.quantity}
                disabled={stoppable}
                onChange={(e) => setForm((f) => ({ ...f, quantity: e.target.value }))}
              />
            </label>
            <label>
              Playback Speed (bars per step)
              <input
                type="number"
                min="1"
                value={form.playbackSpeed}
                disabled={stoppable}
                onChange={(e) => setForm((f) => ({ ...f, playbackSpeed: e.target.value }))}
              />
            </label>
          </div>
          <button type="button" disabled={busy || stoppable} onClick={handleConfigure}>
            Apply Paper Session Setup
          </button>

          <h3>Paper Trading Controls</h3>
          <div className="form-row">
            <button
              type="button"
              disabled={busy || !session.exists || running || paused}
              onClick={() => void run(startPaperSession)}
            >
              Start Paper Trading
            </button>
            <button
              type="button"
              disabled={busy || !running}
              onClick={() => void run(pausePaperSession)}
            >
              Pause Paper Trading
            </button>
            <button
              type="button"
              disabled={busy || !paused}
              onClick={() => void run(resumePaperSession)}
            >
              Resume Paper Trading
            </button>
            <button
              type="button"
              disabled={busy || !stoppable}
              onClick={() => void run(stopPaperSession)}
            >
              Stop Paper Trading
            </button>
            <button
              type="button"
              disabled={busy || stoppable || !session.exists}
              onClick={() => void run(resetPaperSession)}
            >
              Reset Paper Session
            </button>
            <button
              type="button"
              disabled={busy || !running}
              onClick={() => void run(stepPaperSession)}
            >
              Step Replay Forward
            </button>
          </div>
          <p className="capability-status__description">
            Reset is only available while the paper session is stopped — it rewinds the replay and
            discards the simulated results, so it is deliberately refused while a session is
            running or paused.
          </p>
          {notice && <p role="status">{notice}</p>}
          {actionError && (
            <p role="alert" className="dialog__error">
              {actionError}
            </p>
          )}
        </>
      )}

      <h3>Open Paper Positions</h3>
      {session.open_positions.length === 0 ? (
        <p className="market-data-monitor__empty">No open paper positions.</p>
      ) : (
        <div className="table-scroll">
          <table className="market-data-monitor__table">
            <thead>
              <tr>
                <th scope="col">Instrument</th>
                <th scope="col">Direction</th>
                <th scope="col">Qty</th>
                <th scope="col">Avg Entry</th>
                <th scope="col">Unrealized P&amp;L</th>
              </tr>
            </thead>
            <tbody>
              {session.open_positions.map((position) => (
                <tr key={position.position_id}>
                  <td>{position.instrument_id}</td>
                  <td>{position.direction}</td>
                  <td>{position.quantity}</td>
                  <td>{money(position.average_entry_price)}</td>
                  <td className={pnlClass(position.unrealized_pnl)}>
                    {money(position.unrealized_pnl)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <h3>Closed Paper Trades</h3>
      {session.closed_trades.length === 0 ? (
        <p className="market-data-monitor__empty">No closed paper trades yet.</p>
      ) : (
        <div className="table-scroll">
          <table className="market-data-monitor__table">
            <thead>
              <tr>
                <th scope="col">Instrument</th>
                <th scope="col">Direction</th>
                <th scope="col">Entry</th>
                <th scope="col">Exit</th>
                <th scope="col">Qty</th>
                <th scope="col">Net P&amp;L</th>
              </tr>
            </thead>
            <tbody>
              {session.closed_trades.map((trade) => (
                <tr key={trade.trade_id}>
                  <td>{trade.instrument_id}</td>
                  <td>{trade.direction}</td>
                  <td>{money(trade.entry_price)}</td>
                  <td>{money(trade.exit_price)}</td>
                  <td>{trade.quantity}</td>
                  <td className={pnlClass(trade.realized_net_pnl ?? trade.realized_pnl)}>
                    {money(trade.realized_net_pnl ?? trade.realized_pnl)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <h3>Recent Paper Signals</h3>
      {session.recent_signals.length === 0 ? (
        <p className="market-data-monitor__empty">No paper signals yet.</p>
      ) : (
        <div className="table-scroll">
          <table className="market-data-monitor__table">
            <thead>
              <tr>
                <th scope="col">Step</th>
                <th scope="col">Bar Time</th>
                <th scope="col">Direction</th>
                <th scope="col">Risk Gate</th>
                <th scope="col">Paper Order</th>
              </tr>
            </thead>
            <tbody>
              {session.recent_signals.map((signal) => (
                <tr key={`${signal.step}-${signal.signal_id ?? "none"}`}>
                  <td>{signal.step}</td>
                  <td>{new Date(signal.bar_timestamp).toLocaleString("en-IN")}</td>
                  <td>{signal.direction ?? signal.skipped_reason ?? "—"}</td>
                  <td>
                    {signal.risk_outcome ? (
                      <span
                        className={`badge ${
                          signal.risk_outcome === "REJECTED" ? "badge--danger" : "badge--active"
                        }`}
                      >
                        {signal.risk_outcome}
                        {signal.risk_reason_code ? ` (${signal.risk_reason_code})` : ""}
                      </span>
                    ) : (
                      "—"
                    )}
                  </td>
                  <td>{signal.order_status ?? "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}
