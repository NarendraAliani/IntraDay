// frontend/src/features/paper-trading/PaperTradingPage.tsx
//
// Checkpoint 34/35: the real "Paper Trading" operational surface. NOT
// a cosmetic dashboard - kill switch, order submission, and the order/
// trade/position/funds monitor are all wired to the real, tested
// backend. Every capability the backend does NOT yet expose (live
// market-data-driven pricing, scheduled EOD expiry trigger,
// reconciliation report) uses the shared `CapabilityStatus` component
// - never bespoke "Coming Soon" markup.
//
// Part 13/17's explicit requirement: PAPER MODE must never be visually
// confusable with LIVE. Every label on this page says "Paper" where a
// layman could otherwise read it as a real action ("Submit Paper
// Order," never bare "Submit Order").
import { useCallback, useEffect, useState } from "react";

import {
  engageKillSwitch,
  getKillSwitchStatus,
  resetKillSwitch,
} from "../../common/api/killSwitchApi";
import type { KillSwitchStatusResponse } from "../../common/api/killSwitchApi";
import { ApiNetworkError, ApiRequestError } from "../../common/api/client";
import { InstrumentPickerSingle } from "../../common/components/InstrumentPicker";
import { Icon } from "../../common/icons/Icon";
import {
  getPaperFunds,
  getPaperOrders,
  getPaperPositions,
  getPaperTrades,
  submitPaperOrder,
} from "../../common/api/paperTradingApi";
import type {
  PaperFundsResponse,
  PaperOrderResponse,
  PaperPositionResponse,
  PaperTradeResponse,
} from "../../common/api/paperTradingApi";
import { useAuth } from "../../common/auth/AuthContext";
import { CapabilityStatus } from "../../common/components/CapabilityStatus";
import { ErrorState } from "../../common/components/ErrorState";
import { badgeIconName } from "../../common/components/statusIcon";
import { PaperSessionPanel } from "./PaperSessionPanel";
import { LoadingState } from "../../common/components/LoadingState";

const ORDER_TYPES = ["MARKET", "LIMIT", "SL", "SL-M"] as const;
const SIDES = ["BUY", "SELL"] as const;

type LoadState =
  | { phase: "loading" }
  | { phase: "error"; message: string }
  | {
      phase: "ready";
      killSwitch: KillSwitchStatusResponse;
      orders: PaperOrderResponse[];
      trades: PaperTradeResponse[];
      positions: PaperPositionResponse[];
      funds: PaperFundsResponse;
    };

function describeError(error: unknown): string {
  if (error instanceof ApiRequestError || error instanceof ApiNetworkError) {
    return error.message;
  }
  return "An unexpected error occurred.";
}

const STATUS_BADGE_CLASS: Record<string, string> = {
  FILLED: "badge--active",
  CANCELLED: "badge--historical",
  REJECTED: "badge--danger",
  EXPIRED: "badge--historical",
  ERROR: "badge--danger",
  PENDING: "badge--pending",
  PARTIALLY_FILLED: "badge--pending",
};

function statusBadgeClass(status: string): string {
  return STATUS_BADGE_CLASS[status] ?? "badge--info";
}

export function PaperTradingPage(): JSX.Element {
  const { state: authState } = useAuth();
  const canOperate =
    authState.status === "authenticated" &&
    authState.capabilities.includes("configuration.activate");

  const [state, setState] = useState<LoadState>({ phase: "loading" });
  const [reason, setReason] = useState("");
  const [actionError, setActionError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const [orderForm, setOrderForm] = useState({
    instrumentId: "NSE:RELIANCE",
    side: "BUY" as (typeof SIDES)[number],
    quantity: "10",
    orderType: "MARKET" as (typeof ORDER_TYPES)[number],
    limitPrice: "",
    triggerPrice: "",
    strategyId: "manual-paper",
  });
  const [submitResult, setSubmitResult] = useState<string | null>(null);
  const [submitError, setSubmitError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  const load = useCallback(async (): Promise<void> => {
    try {
      const [killSwitch, orders, trades, positions, funds] = await Promise.all([
        getKillSwitchStatus(),
        getPaperOrders(),
        getPaperTrades(),
        getPaperPositions(),
        getPaperFunds(),
      ]);
      setState({ phase: "ready", killSwitch, orders, trades, positions, funds });
    } catch (error) {
      setState({ phase: "error", message: describeError(error) });
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  async function handleEngage(): Promise<void> {
    setBusy(true);
    setActionError(null);
    try {
      await engageKillSwitch(reason);
      setReason("");
      await load();
    } catch (error) {
      setActionError(describeError(error));
    } finally {
      setBusy(false);
    }
  }

  async function handleReset(): Promise<void> {
    setBusy(true);
    setActionError(null);
    try {
      await resetKillSwitch();
      await load();
    } catch (error) {
      setActionError(describeError(error));
    } finally {
      setBusy(false);
    }
  }

  async function handleSubmitOrder(): Promise<void> {
    setSubmitting(true);
    setSubmitError(null);
    setSubmitResult(null);
    try {
      const result = await submitPaperOrder({
        instrument_id: orderForm.instrumentId,
        side: orderForm.side,
        quantity: orderForm.quantity,
        order_type: orderForm.orderType,
        strategy_id: orderForm.strategyId,
        limit_price: orderForm.limitPrice || undefined,
        trigger_price: orderForm.triggerPrice || undefined,
      });
      setSubmitResult(
        result.risk_outcome === "REJECTED"
          ? `Rejected by risk engine: ${result.risk_reason_code ?? "unknown"} — ${result.risk_explanation}`
          : `Approved — paper order status: ${result.order_status ?? "unknown"}`,
      );
      await load();
    } catch (error) {
      setSubmitError(describeError(error));
    } finally {
      setSubmitting(false);
    }
  }

  const needsLimitPrice = orderForm.orderType === "LIMIT" || orderForm.orderType === "SL";
  const needsTriggerPrice = orderForm.orderType === "SL" || orderForm.orderType === "SL-M";

  return (
    <div className="paper-trading-page">
      <h1>Paper Trading</h1>
      <div className="callout callout--warn" role="note">
        <strong>
          <Icon name="paper-trading" /> PAPER MODE — simulated trading only.
        </strong>{" "}
        No fill shown anywhere on this
        page is a real broker execution. This platform has never placed a real order, and{" "}
        <strong>LIVE TRADING — NOT AVAILABLE</strong> — there is no control anywhere in this
        application that enables it.
      </div>

      {/* Checkpoint 64.68: the deterministic-replay Paper Trading
          SESSION - start/pause/resume/stop/reset, paper account, open
          positions, closed trades and recent signals. Rendered on the
          EXISTING Paper Trading page rather than as a new page. */}
      <PaperSessionPanel />

      {state.phase === "loading" && <LoadingState label="Loading paper trading status…" />}
      {state.phase === "error" && <ErrorState message={state.message} />}

      {state.phase === "ready" && (
        <>
          <section className="capability-status-section" aria-labelledby="kill-switch-heading">
            <h2 id="kill-switch-heading">Kill Switch</h2>
            <p>
              Status:{" "}
              {/* Checkpoint 64.80-F2 Phase 8/11: the marker is now an SVG
                  from the single icon system instead of a Unicode glyph.
                  The status WORDS (HALTED / Active) and the badge classes
                  are unchanged - this is a rendering change only, and the
                  `title` gives this safety-critical badge a stable,
                  non-glyph handle for tests and hover text. */}
              <span
                className={`badge ${state.killSwitch.status === "HALTED" ? "badge--danger" : "badge--active"}`}
                title={
                  state.killSwitch.status === "HALTED"
                    ? "Kill switch engaged"
                    : "Kill switch not engaged"
                }
              >
                {state.killSwitch.status === "HALTED" ? (
                  <>
                    <Icon name="error" /> HALTED
                  </>
                ) : (
                  <>
                    <Icon name="success" /> Active
                  </>
                )}
              </span>
            </p>
            {state.killSwitch.status === "HALTED" && state.killSwitch.reason && (
              <p>
                <strong>Reason:</strong> {state.killSwitch.reason}
              </p>
            )}
            <p className="capability-status__description">
              While halted, the risk engine rejects every new paper order before it ever reaches
              the paper broker.
            </p>

            {canOperate ? (
              <>
                {state.killSwitch.status === "ACTIVE" ? (
                  <div className="form-row">
                    <label htmlFor="kill-switch-reason">Reason for halting</label>
                    <input
                      id="kill-switch-reason"
                      type="text"
                      value={reason}
                      onChange={(event) => setReason(event.target.value)}
                      placeholder="e.g. unexpected repeated losses"
                    />
                    <button
                      type="button"
                      disabled={busy || reason.trim() === ""}
                      onClick={() => void handleEngage()}
                    >
                      {busy ? "Engaging…" : "Engage Kill Switch"}
                    </button>
                  </div>
                ) : (
                  <button type="button" disabled={busy} onClick={() => void handleReset()}>
                    {busy ? "Resetting…" : "Reset Kill Switch"}
                  </button>
                )}
                {actionError && (
                  <p role="alert" className="dialog__error">
                    {actionError}
                  </p>
                )}
              </>
            ) : (
              <p className="settings-card__readonly-note">
                You have read-only access to this screen.
              </p>
            )}
          </section>

          <section className="capability-status-section" aria-labelledby="funds-heading">
            <h2 id="funds-heading">Live Paper Trading Account</h2>
            <p className="signal-monitor__hint">
              Tracks all manually submitted paper orders on this platform — a standing account,
              distinct from any single replay session&apos;s simulated account. Still paper only:
              no order here ever reaches a real exchange.
            </p>
            <div className="paper-trading__kpis">
              <div className="paper-trading__kpi">
                <span>Available Capital (Paper)</span>
                <strong>₹{state.funds.available_balance}</strong>
              </div>
              <div className="paper-trading__kpi">
                <span>Utilized Margin (Paper)</span>
                <strong>₹{state.funds.utilized_margin}</strong>
              </div>
              <div className="paper-trading__kpi">
                <span>Open Positions</span>
                <strong>{state.positions.filter((p) => p.status === "OPEN").length}</strong>
              </div>
            </div>
          </section>

          {canOperate && (
            <section
              className="capability-status-section"
              aria-labelledby="order-entry-heading"
            >
              <h2 id="order-entry-heading">Submit Paper Order</h2>
              <p className="capability-status__description">
                This submits a simulated order only. There is no live order button anywhere in
                this application.
              </p>
              <div className="form-grid">
                <InstrumentPickerSingle
                  id="paper-order-instrument"
                  label="Instrument"
                  value={orderForm.instrumentId}
                  onChange={(instrumentId) => setOrderForm((f) => ({ ...f, instrumentId }))}
                />
                <label>
                  Side
                  <select
                    value={orderForm.side}
                    onChange={(e) =>
                      setOrderForm((f) => ({ ...f, side: e.target.value as typeof f.side }))
                    }
                  >
                    {SIDES.map((side) => (
                      <option key={side} value={side}>
                        {side}
                      </option>
                    ))}
                  </select>
                </label>
                <label>
                  Quantity
                  <input
                    type="number"
                    min="1"
                    value={orderForm.quantity}
                    onChange={(e) => setOrderForm((f) => ({ ...f, quantity: e.target.value }))}
                  />
                </label>
                <label>
                  Order Type
                  <select
                    value={orderForm.orderType}
                    onChange={(e) =>
                      setOrderForm((f) => ({
                        ...f,
                        orderType: e.target.value as typeof f.orderType,
                      }))
                    }
                  >
                    {ORDER_TYPES.map((type) => (
                      <option key={type} value={type}>
                        {type}
                      </option>
                    ))}
                  </select>
                </label>
                {needsLimitPrice && (
                  <label>
                    Limit Price
                    <input
                      type="number"
                      step="0.01"
                      value={orderForm.limitPrice}
                      onChange={(e) =>
                        setOrderForm((f) => ({ ...f, limitPrice: e.target.value }))
                      }
                    />
                  </label>
                )}
                {needsTriggerPrice && (
                  <label>
                    Trigger Price
                    <input
                      type="number"
                      step="0.01"
                      value={orderForm.triggerPrice}
                      onChange={(e) =>
                        setOrderForm((f) => ({ ...f, triggerPrice: e.target.value }))
                      }
                    />
                  </label>
                )}
                <label>
                  Strategy
                  <input
                    type="text"
                    value={orderForm.strategyId}
                    onChange={(e) =>
                      setOrderForm((f) => ({ ...f, strategyId: e.target.value }))
                    }
                  />
                </label>
              </div>
              <button type="button" disabled={submitting} onClick={() => void handleSubmitOrder()}>
                {submitting ? "Submitting Paper Order…" : "Submit Paper Order"}
              </button>
              {submitResult && <p role="status">{submitResult}</p>}
              {submitError && (
                <p role="alert" className="dialog__error">
                  {submitError}
                </p>
              )}
            </section>
          )}

          <section className="capability-status-section" aria-labelledby="orders-heading">
            <h2 id="orders-heading">Paper Orders</h2>
            {state.orders.length === 0 ? (
              <p className="market-data-monitor__empty">No paper orders submitted yet.</p>
            ) : (
              <div className="table-scroll">
                <table className="market-data-monitor__table">
                  <thead>
                    <tr>
                      <th scope="col">Instrument</th>
                      <th scope="col">Side</th>
                      <th scope="col">Type</th>
                      <th scope="col">Qty</th>
                      <th scope="col">Filled</th>
                      <th scope="col">Status</th>
                      <th scope="col">Created</th>
                    </tr>
                  </thead>
                  <tbody>
                    {state.orders.map((order) => (
                      <tr key={order.order_id}>
                        <td>{order.instrument_id}</td>
                        <td>{order.side}</td>
                        <td>{order.order_type}</td>
                        <td>{order.quantity}</td>
                        <td>{order.filled_quantity}</td>
                        <td>
                          <span className={`badge ${statusBadgeClass(order.status)}`}>
                            <Icon name={badgeIconName(statusBadgeClass(order.status))} />{" "}
                            {order.status}
                          </span>
                        </td>
                        <td>{new Date(order.created_at).toLocaleString("en-IN")}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </section>

          <section className="capability-status-section" aria-labelledby="positions-heading">
            <h2 id="positions-heading">Paper Positions</h2>
            {state.positions.length === 0 ? (
              <p className="market-data-monitor__empty">No paper positions yet.</p>
            ) : (
              <div className="table-scroll">
                <table className="market-data-monitor__table">
                  <thead>
                    <tr>
                      <th scope="col">Instrument</th>
                      <th scope="col">Direction</th>
                      <th scope="col">Qty</th>
                      <th scope="col">Avg Entry</th>
                      <th scope="col">Realized P&amp;L</th>
                      <th scope="col">Status</th>
                    </tr>
                  </thead>
                  <tbody>
                    {state.positions.map((position) => (
                      <tr key={position.position_id}>
                        <td>{position.instrument_id}</td>
                        <td>{position.direction}</td>
                        <td>{position.quantity}</td>
                        <td>₹{position.average_entry_price}</td>
                        <td
                          className={
                            Number(position.realized_pnl) < 0
                              ? "paper-trading__pnl--negative"
                              : "paper-trading__pnl--positive"
                          }
                        >
                          ₹{position.realized_pnl}
                        </td>
                        <td>
                          <span
                            className={`badge ${position.status === "OPEN" ? "badge--active" : "badge--historical"}`}
                          >
                            {position.status}
                          </span>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </section>

          <section className="capability-status-section" aria-labelledby="trades-heading">
            <h2 id="trades-heading">Paper Trades</h2>
            {state.trades.length === 0 ? (
              <p className="market-data-monitor__empty">No completed paper trades yet.</p>
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
                      <th scope="col">Realized P&amp;L</th>
                      <th scope="col">Closed</th>
                    </tr>
                  </thead>
                  <tbody>
                    {state.trades.map((trade) => (
                      <tr key={trade.trade_id}>
                        <td>{trade.instrument_id}</td>
                        <td>{trade.direction}</td>
                        <td>₹{trade.entry_price}</td>
                        <td>₹{trade.exit_price}</td>
                        <td>{trade.quantity}</td>
                        <td
                          className={
                            Number(trade.realized_pnl) < 0
                              ? "paper-trading__pnl--negative"
                              : "paper-trading__pnl--positive"
                          }
                        >
                          ₹{trade.realized_pnl}
                        </td>
                        <td>{new Date(trade.closed_at).toLocaleString("en-IN")}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </section>
        </>
      )}

      <section className="capability-status-section" aria-labelledby="paper-lifecycle-heading">
        <h2 id="paper-lifecycle-heading">Paper Trading Lifecycle</h2>
        <div className="capability-status-grid">
          <CapabilityStatus
            title="Risk Gating"
            description="Every paper order is evaluated against max daily loss, max position size, max total exposure, max concurrent positions, duplicate-order, stale-data, session, and strategy-activation checks before it reaches the paper broker."
            status="AVAILABLE"
            documentationLink="docs/architecture/RISK_ENGINE_ARCHITECTURE.md"
          />
          <CapabilityStatus
            title="Order Execution Simulation"
            description="Market/limit/stop-loss/stop-loss-market order types, partial fills, slippage, and cost-model-based fees, all backend-tested and now persisted."
            status="AVAILABLE"
            documentationLink="docs/architecture/PAPER_TRADING_ARCHITECTURE.md"
          />
          <CapabilityStatus
            title="Order Submission (UI)"
            description="Submitting a paper order from this screen."
            status="AVAILABLE"
          />
          <CapabilityStatus
            title="Order / Trade / Position Monitor"
            description="Real, persisted view of paper orders, trades, and positions."
            status="AVAILABLE"
          />
          <CapabilityStatus
            title="Live Market-Data-Driven Pricing"
            description="Feeding real observed live quotes/bars into the paper broker's price feed automatically."
            status="PARTIAL"
            blocker="Prices are currently supplied by whatever fed the paper broker at submission time (a Dhan-verified reference price where available) - not yet a continuous, automatic live-quote subscription."
            documentationLink="docs/architecture/PAPER_TRADING_ARCHITECTURE.md"
          />
          <CapabilityStatus
            title="Scheduled End-of-Session Expiry"
            description="Automatically expiring resting orders at the market-session boundary."
            status="PARTIAL"
            blocker="The expiry function itself is implemented and tested; no scheduler (Celery beat) triggers it automatically yet - see the Checkpoint 32 runtime-architecture decision."
            documentationLink="docs/architecture/RUNTIME_ARCHITECTURE_DECISION.md"
          />
          <CapabilityStatus
            title="Reconciliation Report"
            description="Comparing local ledger state against the paper broker's own reported state."
            status="NOT_YET_IMPLEMENTED"
            blocker="The reconciliation engine exists and is tested, but no scheduled job or UI trigger runs it against this runtime's live state yet."
            documentationLink="docs/architecture/RISK_ENGINE_ARCHITECTURE.md"
          />
          <CapabilityStatus
            title="Live Trading"
            description="Real broker order placement."
            status="NOT_YET_IMPLEMENTED"
            blocker="This platform has never placed a real order, by design. LIVE TRADING — NOT AVAILABLE anywhere in this codebase."
          />
        </div>
      </section>
    </div>
  );
}
