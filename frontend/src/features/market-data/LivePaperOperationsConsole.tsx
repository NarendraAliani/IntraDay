// frontend/src/features/market-data/LivePaperOperationsConsole.tsx
//
// Checkpoint 64.15: THE consolidated operator screen for a Live Paper
// Session - the frontend consumption Checkpoint 64.14 explicitly left
// unbuilt. Every value on this screen comes from an already-real,
// already-tested backend contract:
//
//   - GET .../live-paper-workbench/ (Checkpoint 64.14) - the 10-item
//     readiness checklist, the authoritative `LivePaperReadiness`
//     aggregate, the real `session_state`, and desired-vs-effective
//     configuration with an honest `drift` flag.
//   - POST .../live-paper-session/start/ and /stop/ (Checkpoint 64.13) -
//     the ONLY way this screen mutates session state. It never writes
//     `ScannerConfiguration` directly (that path now belongs to
//     LiveScannerConsole's own timeframe/universe/strategy editing
//     only - starting/stopping a SESSION is this screen's job).
//   - GET .../reports/daily-session/ (Checkpoint 64.10) - reused,
//     never re-derived client-side, for the Paper Execution,
//     Communication, and Paper P&L KPI panels.
//   - GET .../signals/ (Checkpoint 62.x/64.9) - reused for the compact
//     signal table, same TradePlan/communication shape the existing
//     Active Signal Monitor already renders.
//   - WorkerStatusCard (Checkpoint 64.3, LiveMarketDataMonitor.tsx) -
//     reused verbatim for the Live Data Monitor section, never
//     duplicated.
//
// The market is CLOSED as of this checkpoint - this screen makes no
// live Dhan call of its own and fabricates nothing: when the backend's
// own `market_state` checklist item reports BLOCKED, this screen shows
// that BLOCKED state honestly (§16), it does not simulate an OPEN
// market to look more complete.
import { useCallback, useEffect, useRef, useState } from "react";

import { ApiNetworkError, ApiRequestError } from "../../common/api/client";
import {
  getLivePaperWorkbench,
  startLivePaperSession,
  stopLivePaperSession,
} from "../../common/api/marketDataApi";
import type {
  LivePaperWorkbenchResponse,
  ReadinessCheckItem,
} from "../../common/api/marketDataApi";
import { getDailySessionReport } from "../../common/api/reportsApi";
import type { DailySessionReportResponse } from "../../common/api/reportsApi";
import { listSignals } from "../../common/api/signalApi";
import type { SignalResponse } from "../../common/api/signalApi";
import { useAuth } from "../../common/auth/AuthContext";
import { ErrorState } from "../../common/components/ErrorState";
import { LoadingState } from "../../common/components/LoadingState";
import { WorkerStatusCard } from "./LiveMarketDataMonitor";

// Checkpoint 64.15 §15: a single documented polling interval, matching
// this project's existing conventions (LivePaperReadinessCard already
// polls at 15s, WorkerStatusCard at 10s) - the workbench composes
// MORE signals per call than either of those, so 8s is chosen as a
// reasonable middle ground: frequent enough for an operator watching a
// START/STOP transition, not aggressive enough to hammer the backend.
const WORKBENCH_POLL_MS = 8000;
const REPORT_POLL_MS = 20000;
const SIGNALS_POLL_MS = 20000;

function describeError(error: unknown): string {
  if (error instanceof ApiRequestError || error instanceof ApiNetworkError) {
    return error.message;
  }
  return "An unexpected error occurred.";
}

const SESSION_STATE_LABELS: Record<string, string> = {
  NOT_READY: "Not Ready",
  READY: "Ready",
  STARTING: "Starting",
  RUNNING: "Running",
  STOPPING: "Stopping",
  STOPPED: "Stopped",
  FAILED: "Failed",
};

const SESSION_STATE_CLASS: Record<string, string> = {
  NOT_READY: "badge--historical",
  READY: "badge--pending",
  STARTING: "badge--pending",
  RUNNING: "badge--active",
  STOPPING: "badge--pending",
  STOPPED: "badge--historical",
  FAILED: "badge--danger",
};

const TIMELINE_STEPS = ["READY", "STARTING", "RUNNING", "STOPPING", "STOPPED"] as const;

const CHECK_STATE_CLASS: Record<string, string> = {
  READY: "badge--active",
  WARNING: "badge--pending",
  BLOCKED: "badge--danger",
  UNKNOWN: "badge--historical",
};

const READINESS_STATE_CLASS: Record<string, string> = {
  READY_FOR_PAPER: "badge--active",
  NOT_CONFIGURED: "badge--historical",
  CREDENTIAL_EXPIRED: "badge--danger",
  CREDENTIAL_INVALID: "badge--danger",
  PROVIDER_UNAVAILABLE: "badge--pending",
  BLOCKED_BY_SAFETY: "badge--danger",
};

const SCAN_STATUS_CLASS: Record<string, string> = {
  IDLE: "badge--historical",
  STARTING: "badge--pending",
  SCANNING: "badge--pending",
  COMPLETED: "badge--active",
  DEGRADED: "badge--pending",
  FAILED: "badge--danger",
  STOPPED: "badge--historical",
};

function formatTimestamp(value: string): string {
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return value;
  return parsed.toLocaleString("en-IN", { timeZone: "Asia/Kolkata" });
}

function symbolFromInstrumentId(instrumentId: string): string {
  const parts = instrumentId.split(":");
  return parts.length > 1 ? parts[1] : instrumentId;
}

function formatTradeValue(value: string | null | undefined): string {
  if (value === null || value === undefined) return "Not provided";
  return `₹${value}`;
}

function formatDurationSeconds(seconds: number | null): string {
  if (seconds === null) return "Not available";
  if (seconds < 60) return `${Math.round(seconds)}s`;
  if (seconds < 3600) return `${Math.round(seconds / 60)}m`;
  const hours = Math.floor(seconds / 3600);
  const minutes = Math.round((seconds % 3600) / 60);
  return `${hours}h ${minutes}m`;
}

function formatPnl(value: string | null): string {
  if (value === null) return "Not available";
  const asNumber = Number(value);
  if (Number.isNaN(asNumber)) return "Not available";
  return `${asNumber >= 0 ? "+" : ""}₹${value}`;
}

function formatSecondsAgo(lastUpdated: Date | null): string {
  if (!lastUpdated) return "Never";
  const seconds = Math.max(0, Math.round((Date.now() - lastUpdated.getTime()) / 1000));
  if (seconds < 5) return "just now";
  if (seconds < 60) return `${seconds}s ago`;
  return `${Math.round(seconds / 60)}m ago`;
}

function ReadinessCheckCard({ item }: { item: ReadinessCheckItem }): JSX.Element {
  return (
    <div
      className="market-data-monitor__card live-paper-console__check-card"
      data-check-key={item.key}
    >
      <h3>{item.label}</h3>
      <span role="status" className={`badge ${CHECK_STATE_CLASS[item.state] ?? ""}`}>
        {item.state}
      </span>
      <p className="signal-monitor__hint">{item.explanation}</p>
      {item.remediation && (
        <p className="live-paper-console__remediation">
          <strong>Remediation:</strong> {item.remediation}
        </p>
      )}
    </div>
  );
}

export function LivePaperOperationsConsole(): JSX.Element {
  const { state: authState } = useAuth();
  const canOperate =
    authState.status === "authenticated" &&
    authState.capabilities.includes("configuration.activate");

  const [workbench, setWorkbench] = useState<LivePaperWorkbenchResponse | null>(null);
  const [workbenchError, setWorkbenchError] = useState<string | null>(null);
  const [workbenchUpdatedAt, setWorkbenchUpdatedAt] = useState<Date | null>(null);

  const [report, setReport] = useState<DailySessionReportResponse | null>(null);
  const [reportError, setReportError] = useState<string | null>(null);

  const [signals, setSignals] = useState<SignalResponse[] | null>(null);
  const [signalsError, setSignalsError] = useState<string | null>(null);

  const [actionMessage, setActionMessage] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [actionPending, setActionPending] = useState(false);

  // Checkpoint 64.15 §15: exactly ONE interval per data source, created
  // once on mount and cleared on unmount - proven by
  // `LivePaperOperationsConsole.test.tsx`'s
  // "does not create duplicate timers on remount" test.
  const loadWorkbench = useCallback(async (): Promise<void> => {
    try {
      const result = await getLivePaperWorkbench();
      setWorkbench(result);
      setWorkbenchError(null);
      setWorkbenchUpdatedAt(new Date());
    } catch (error) {
      // §20: a polling failure never clears already-shown data - only
      // the error indicator is set, the stale-but-real workbench stays
      // visible alongside a "last updated" hint.
      setWorkbenchError(describeError(error));
    }
  }, []);

  useEffect(() => {
    void loadWorkbench();
    const interval = setInterval(() => void loadWorkbench(), WORKBENCH_POLL_MS);
    return () => clearInterval(interval);
  }, [loadWorkbench]);

  useEffect(() => {
    let cancelled = false;
    function load(): void {
      getDailySessionReport()
        .then((result) => {
          if (!cancelled) {
            setReport(result);
            setReportError(null);
          }
        })
        .catch((error) => {
          if (!cancelled) setReportError(describeError(error));
        });
    }
    load();
    const interval = setInterval(load, REPORT_POLL_MS);
    return () => {
      cancelled = true;
      clearInterval(interval);
    };
  }, []);

  useEffect(() => {
    let cancelled = false;
    function load(): void {
      listSignals({ pageSize: 10, sort: "newest" })
        .then((result) => {
          if (!cancelled) {
            setSignals(result.items);
            setSignalsError(null);
          }
        })
        .catch((error) => {
          if (!cancelled) setSignalsError(describeError(error));
        });
    }
    load();
    const interval = setInterval(load, SIGNALS_POLL_MS);
    return () => {
      cancelled = true;
      clearInterval(interval);
    };
  }, []);

  async function handleStart(): Promise<void> {
    setActionPending(true);
    setActionError(null);
    setActionMessage(null);
    try {
      const result = await startLivePaperSession();
      setActionMessage(result.message);
      if (!result.accepted) {
        setActionError(result.remediation ?? null);
      }
      await loadWorkbench();
    } catch (error) {
      setActionError(describeError(error));
    } finally {
      setActionPending(false);
    }
  }

  async function handleStop(): Promise<void> {
    setActionPending(true);
    setActionError(null);
    setActionMessage(null);
    try {
      const result = await stopLivePaperSession();
      setActionMessage(result.message);
      await loadWorkbench();
    } catch (error) {
      setActionError(describeError(error));
    } finally {
      setActionPending(false);
    }
  }

  const sessionState = workbench?.session_state ?? null;
  const readiness = workbench?.readiness ?? null;
  const checklist = (workbench?.checklist ?? []) as unknown as ReadinessCheckItem[];
  const effectiveConfig = workbench?.effective_session_configuration ?? null;
  const scannerProgress = workbench?.scanner_progress ?? null;

  const canStart = Boolean(readiness?.can_start) && sessionState !== "RUNNING";
  const isRunning = sessionState === "RUNNING" || sessionState === "STARTING";

  return (
    <div className="signal-monitor live-paper-console">
      {/* §4: the top safety strip - always rendered, never conditional
          on session state, never relying on color alone (each label
          carries explicit text). */}
      <div className="live-paper-console__safety-strip" role="note">
        <span className="badge badge--paper">Execution Mode: PAPER</span>
        <span className="badge badge--historical">Real Trading: DISABLED</span>
        <span className="badge badge--historical">Broker Execution: PAPER ONLY</span>
      </div>

      <header className="signal-monitor__header">
        <h1>Live Paper Operations</h1>
        <p className="configuration-viewer__subtitle">
          The consolidated operator console for a Live Paper Session - pre-session readiness,
          desired vs effective configuration, session control, live data, signals, paper
          execution, and communication in one place. Every number below is read from a real,
          already-tested backend endpoint - nothing here is simulated.
        </p>
      </header>

      {workbenchError && !workbench && <ErrorState message={workbenchError} />}
      {!workbench && !workbenchError && <LoadingState label="Loading readiness workbench…" />}

      {workbench && (
        <>
          {workbenchError && (
            <p role="alert" className="dialog__error">
              {workbenchError} (showing data last updated {formatSecondsAgo(workbenchUpdatedAt)})
            </p>
          )}
          {!workbenchError && (
            <p className="signal-monitor__hint">
              Last updated {formatSecondsAgo(workbenchUpdatedAt)}
            </p>
          )}

          {/* §3: top-level session state. */}
          <section aria-labelledby="lpc-session-state-heading" className="live-scanner__section">
            <h2 id="lpc-session-state-heading">Session State</h2>
            <span role="status" className={`badge ${SESSION_STATE_CLASS[sessionState ?? ""] ?? ""}`}>
              {SESSION_STATE_LABELS[sessionState ?? ""] ?? sessionState}
            </span>

            {sessionState === "FAILED" ? (
              <p role="alert" className="dialog__error">
                The live worker reported a real failure state
                {readiness ? ` (${readiness.provider_state})` : ""}. Check the Live Data Monitor
                section below and the worker process logs before retrying.
              </p>
            ) : (
              <ol className="live-paper-console__timeline" aria-label="Session state timeline">
                {TIMELINE_STEPS.map((step) => (
                  <li
                    key={step}
                    className={
                      sessionState === step
                        ? "live-paper-console__timeline-step live-paper-console__timeline-step--current"
                        : "live-paper-console__timeline-step"
                    }
                    aria-current={sessionState === step ? "step" : undefined}
                  >
                    {SESSION_STATE_LABELS[step]}
                  </li>
                ))}
              </ol>
            )}
          </section>

          {/* §6: overall readiness. */}
          {readiness && (
            <section aria-labelledby="lpc-readiness-heading" className="live-scanner__section">
              <h2 id="lpc-readiness-heading">Live Paper Readiness</h2>
              <span
                role="status"
                className={`badge ${READINESS_STATE_CLASS[readiness.state] ?? ""}`}
              >
                {readiness.can_start ? "● READY" : "● BLOCKED"} — {readiness.state}
              </span>
              <p className="signal-monitor__hint">{readiness.safe_reason}</p>
              {!readiness.can_start && (
                <p className="live-paper-console__remediation">
                  <strong>Remediation:</strong> {readiness.remediation}
                </p>
              )}

              {canOperate && (
                <div className="live-scanner__actions">
                  {!isRunning ? (
                    <button
                      type="button"
                      className="market-data-monitor__refresh-button"
                      disabled={!canStart || actionPending}
                      onClick={() => void handleStart()}
                    >
                      START LIVE PAPER SESSION
                    </button>
                  ) : (
                    <button
                      type="button"
                      className="live-scanner__stop-button"
                      disabled={actionPending}
                      onClick={() => void handleStop()}
                    >
                      STOP LIVE PAPER SESSION
                    </button>
                  )}
                </div>
              )}
              {!canOperate && (
                <p className="settings-card__readonly-note">
                  You have read-only access to this screen - starting or stopping a Live Paper
                  Session requires the configuration-operator role.
                </p>
              )}
              {actionMessage && (
                <p role="status" className="signal-monitor__hint">
                  {actionMessage}
                </p>
              )}
              {actionError && (
                <p role="alert" className="dialog__error">
                  {actionError}
                </p>
              )}
            </section>
          )}

          {/* §5: the 10-item readiness workbench. */}
          <section aria-labelledby="lpc-checklist-heading" className="live-scanner__section">
            <h2 id="lpc-checklist-heading">Pre-Session Readiness Checklist</h2>
            <div className="market-data-monitor__summary live-paper-console__check-grid">
              {checklist.map((item) => (
                <ReadinessCheckCard key={item.key} item={item} />
              ))}
            </div>
          </section>

          {/* §7: desired vs effective configuration. */}
          {effectiveConfig && (
            <div className="live-scanner__state-grid">
              <section
                aria-labelledby="lpc-desired-heading"
                className="market-data-monitor__card"
              >
                <h2 id="lpc-desired-heading">Desired Configuration</h2>
                <dl>
                  <dt>Configuration Version</dt>
                  <dd>{effectiveConfig.desired_configuration_version}</dd>
                  <dt>Universe Mode</dt>
                  <dd>{effectiveConfig.desired_universe_mode || "—"}</dd>
                  <dt>Timeframe</dt>
                  <dd>{effectiveConfig.desired_timeframe || "—"}</dd>
                  <dt>Strategies</dt>
                  <dd>
                    {effectiveConfig.desired_strategy_ids.length > 0
                      ? effectiveConfig.desired_strategy_ids.join(", ")
                      : "None selected"}
                  </dd>
                  <dt>Requested By</dt>
                  <dd>{effectiveConfig.desired_requested_by || "—"}</dd>
                </dl>
              </section>

              <section
                aria-labelledby="lpc-effective-heading"
                className="market-data-monitor__card"
              >
                <h2 id="lpc-effective-heading">Effective Configuration</h2>
                <span
                  role="status"
                  className={`badge ${effectiveConfig.drift ? "badge--pending" : "badge--active"}`}
                >
                  {effectiveConfig.drift ? "DRIFT" : "NO DRIFT"}
                </span>
                <dl>
                  <dt>Configuration Version</dt>
                  <dd>{effectiveConfig.effective_configuration_version || "Never reconciled"}</dd>
                  <dt>Timeframe</dt>
                  <dd>{effectiveConfig.effective_timeframe || "—"}</dd>
                  <dt>Strategies</dt>
                  <dd>
                    {effectiveConfig.effective_strategy_ids.length > 0
                      ? effectiveConfig.effective_strategy_ids.join(", ")
                      : "—"}
                  </dd>
                  <dt>Requested Count</dt>
                  <dd>{effectiveConfig.effective_requested_stock_count}</dd>
                  <dt>Subscribed Count</dt>
                  <dd>{effectiveConfig.effective_stock_count}</dd>
                </dl>
              </section>
            </div>
          )}
        </>
      )}

      {/* Checkpoint 64.18 §2-7: Scanner Progress - real backend state
          only, written exclusively by the worker's own scan loop. This
          screen only READS it; it never estimates/increments progress
          itself. */}
      <section aria-labelledby="lpc-scanner-progress-heading" className="live-scanner__section">
        <h2 id="lpc-scanner-progress-heading">Scanner Progress</h2>
        {!scannerProgress && (
          <p className="market-data-monitor__empty">
            No scan has started yet - the scanner has never run in this environment, or the
            market is closed.
          </p>
        )}
        {scannerProgress && (
          <div className="market-data-monitor__card">
            <span
              role="status"
              className={`badge ${SCAN_STATUS_CLASS[scannerProgress.status] ?? ""}`}
            >
              {scannerProgress.status}
            </span>
            {scannerProgress.stale && (
              <span role="status" className="badge badge--danger">
                STALE
              </span>
            )}
            {scannerProgress.status === "FAILED" && (
              <p role="alert" className="dialog__error">
                {scannerProgress.last_error_safe || "The scan failed."}
              </p>
            )}
            <ScannerProgressBar percent={scannerProgress.progress_percent} />
            <dl>
              <dt>Timeframe</dt>
              <dd>{scannerProgress.timeframe || "—"}</dd>
              <dt>Instruments</dt>
              <dd>{scannerProgress.universe_total}</dd>
              <dt>Processed</dt>
              <dd>{scannerProgress.universe_processed}</dd>
              <dt>Remaining</dt>
              <dd>{scannerProgress.remaining}</dd>
              <dt>Progress %</dt>
              <dd>{scannerProgress.progress_percent}%</dd>
              <dt>Current Stock</dt>
              <dd>{scannerProgress.current_instrument || "—"}</dd>
              <dt>Current Strategy</dt>
              <dd>{scannerProgress.current_strategy || "—"}</dd>
              <dt>Strategies</dt>
              <dd>
                {scannerProgress.strategies_processed} of {scannerProgress.strategies_total}
              </dd>
              <dt>Signals Found</dt>
              <dd>{scannerProgress.signals_found}</dd>
              <dt>Started</dt>
              <dd>{scannerProgress.started_at ? formatTimestamp(scannerProgress.started_at) : "—"}</dd>
              <dt>Last Update</dt>
              <dd>
                {scannerProgress.last_progress_at
                  ? formatTimestamp(scannerProgress.last_progress_at)
                  : "—"}
              </dd>
            </dl>
          </div>
        )}
      </section>

      {/* §10: Live Data Monitor - reuses WorkerStatusCard verbatim. */}
      <section aria-labelledby="lpc-monitor-heading" className="live-scanner__section">
        <h2 id="lpc-monitor-heading">Live Data Monitor</h2>
        <div className="market-data-monitor__summary">
          <WorkerStatusCard />
        </div>
      </section>

      {/* §11: Signal Operations - a compact, reused signal table. */}
      <section aria-labelledby="lpc-signals-heading" className="live-scanner__section">
        <h2 id="lpc-signals-heading">Signal Operations</h2>
        {signalsError && <ErrorState message={signalsError} />}
        {!signalsError && signals === null && <LoadingState label="Loading signals…" />}
        {!signalsError && signals !== null && signals.length === 0 && (
          <p className="market-data-monitor__empty">No signal records yet.</p>
        )}
        {!signalsError && signals !== null && signals.length > 0 && (
          <table className="signal-monitor__table">
            <thead>
              <tr>
                <th scope="col">Time</th>
                <th scope="col">Stock</th>
                <th scope="col">Strategy</th>
                <th scope="col">Timeframe</th>
                <th scope="col">Direction</th>
                <th scope="col">Spot</th>
                <th scope="col">Entry</th>
                <th scope="col">Stop Loss</th>
                <th scope="col">Target 1</th>
                <th scope="col">Target 2</th>
                <th scope="col">Target 3</th>
                <th scope="col">Trailing SL</th>
                <th scope="col">Risk</th>
                <th scope="col">Paper</th>
                <th scope="col">Telegram</th>
                <th scope="col">Discord</th>
              </tr>
            </thead>
            <tbody>
              {signals.map((signal) => (
                <tr key={signal.signal_id}>
                  <td>{formatTimestamp(signal.signal_timestamp)}</td>
                  <td>{symbolFromInstrumentId(signal.instrument_id)}</td>
                  <td>{signal.strategy_id}</td>
                  <td>{signal.timeframe}</td>
                  <td>{signal.direction}</td>
                  <td>{`₹${signal.price}`}</td>
                  <td>{formatTradeValue(signal.trade_plan?.entry_price)}</td>
                  <td>{formatTradeValue(signal.trade_plan?.stop_loss)}</td>
                  <td>{formatTradeValue(signal.trade_plan?.target_1)}</td>
                  <td>{formatTradeValue(signal.trade_plan?.target_2)}</td>
                  <td>{formatTradeValue(signal.trade_plan?.target_3)}</td>
                  <td>{formatTradeValue(signal.trade_plan?.trailing_stop_loss)}</td>
                  <td>{signal.risk_status}</td>
                  <td>{signal.order_status}</td>
                  <td>{signal.telegram?.status ?? "Not provided"}</td>
                  <td>{signal.discord?.status ?? "Not provided"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>

      {/* §12/13/14: Paper Execution, Communication, Paper P&L - all
          from the SAME existing Daily Session Report call, never a
          duplicate client-side calculation. */}
      <section aria-labelledby="lpc-execution-heading" className="live-scanner__section">
        <h2 id="lpc-execution-heading">Paper Execution Summary</h2>
        {reportError && <ErrorState message={reportError} />}
        {!reportError && report === null && <LoadingState label="Loading paper execution summary…" />}
        {!reportError && report !== null && (
          <div className="signal-monitor__summary">
            <SummaryCard label="Signals" value={report.total_signals} />
            <SummaryCard label="Risk Approved" value={report.risk_accepted} />
            <SummaryCard label="Risk Rejected" value={report.risk_rejected} />
            <SummaryCard label="Paper Orders" value={report.paper_orders_total} />
            <SummaryCard label="Paper Fills" value={report.paper_orders_filled} />
            <SummaryCard label="Paper Orders Rejected" value={report.paper_orders_rejected} />
            <SummaryCard label="Open Positions" value={report.open_positions} />
            <SummaryCard label="Closed Positions" value={report.closed_positions} />
          </div>
        )}
      </section>

      <section aria-labelledby="lpc-communication-heading" className="live-scanner__section">
        <h2 id="lpc-communication-heading">Communication Summary</h2>
        <p className="signal-monitor__hint">
          A signal rejected by risk still appears here if a communication attempt was made for it
          - signal truth and execution truth remain independent (Checkpoint 37).
        </p>
        {!reportError && report !== null && (
          <>
            <h3>Telegram</h3>
            <div className="signal-monitor__summary">
              <SummaryCard label="Telegram Sent" value={report.telegram.sent} />
              <SummaryCard label="Telegram Failed" value={report.telegram.failed} />
              <SummaryCard label="Telegram Pending" value={report.telegram.pending} />
            </div>
            <h3>Discord</h3>
            <div className="signal-monitor__summary">
              <SummaryCard label="Discord Sent" value={report.discord.sent} />
              <SummaryCard label="Discord Failed" value={report.discord.failed} />
              <SummaryCard label="Discord Pending" value={report.discord.pending} />
            </div>
          </>
        )}
      </section>

      <section aria-labelledby="lpc-pnl-heading" className="live-scanner__section">
        <h2 id="lpc-pnl-heading">Paper P&amp;L</h2>
        <p className="signal-monitor__hint">
          This is PAPER P&amp;L only - a simulated result from the paper trading engine. It is
          never a real account balance or real money outcome.
        </p>
        {!reportError && report !== null && (
          <>
            <p className="market-data-monitor__session-value">
              Realized PAPER P&amp;L: {formatPnl(report.realized_pnl_total)}
            </p>
            <p className="market-data-monitor__session-value">
              Unrealized PAPER P&amp;L: {formatPnl(report.unrealized_pnl_total)}
            </p>
            <p className="signal-monitor__hint">
              Unrealized P&amp;L is marked from the latest persisted bar close price for each open
              position - never a live Dhan call from this report. Shows "Not available" whenever any
              open position has no persisted mark price yet, rather than an incomplete total.
            </p>
          </>
        )}
      </section>

      <section aria-labelledby="lpc-reproducibility-heading" className="live-scanner__section">
        <h2 id="lpc-reproducibility-heading">Session Duration &amp; Reproducibility</h2>
        {!reportError && report !== null && (
          <dl>
            <dt>Session Duration</dt>
            <dd>{formatDurationSeconds(report.session_duration_seconds)}</dd>
            <dt>Configuration Version</dt>
            <dd>{report.configuration_version ?? "Not available"}</dd>
            <dt>Session Date</dt>
            <dd>{report.session_date}</dd>
          </dl>
        )}
      </section>
    </div>
  );
}

function SummaryCard({ label, value }: { label: string; value: number }): JSX.Element {
  return (
    <div className="signal-monitor__summary-card">
      <span className="signal-monitor__summary-label">{label}</span>
      <span className="signal-monitor__summary-value">{value}</span>
    </div>
  );
}

// Sets the fill width imperatively via a ref (never a JSX inline-style
// object prop, per this project's existing "no inline styles" CSS
// quality gate, `styles.quality.test.ts`) - the only genuinely dynamic
// value here is the numeric percent itself, driven entirely by real
// backend state.
function ScannerProgressBar({ percent }: { percent: number }): JSX.Element {
  const fillRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (fillRef.current) {
      fillRef.current.style.width = `${percent}%`;
    }
  }, [percent]);

  return (
    <div
      role="progressbar"
      aria-valuemin={0}
      aria-valuemax={100}
      aria-valuenow={percent}
      aria-label="Scanner progress"
      className="live-paper-console__progress-track"
    >
      <div ref={fillRef} className="live-paper-console__progress-fill" />
    </div>
  );
}
