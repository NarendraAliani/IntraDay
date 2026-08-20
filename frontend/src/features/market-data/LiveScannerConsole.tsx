// frontend/src/features/market-data/LiveScannerConsole.tsx
//
// Checkpoint 64.5: the actual operator-facing "LIVE SCANNER" control
// console - the highest-priority product gap named in this checkpoint's
// brief. The Checkpoint 64.4 backend (desired/effective ScannerConfiguration
// + WorkerRuntimeStatus reconciliation) was complete and tested but had NO
// UI - an operator could only drive it with curl. This screen closes that
// gap by wiring every control to the REAL, already-tested API
// (scannerConfigApi.ts) - no duplicate backend endpoints, no invented
// numbers.
//
// Reuses, never duplicates:
//   - WorkerStatusCard / TIMEFRAME_OPTIONS from LiveMarketDataMonitor.tsx
//     (the truthful health evaluator from Checkpoint 64.3)
//   - InstrumentPickerMulti (Checkpoint 63.x) for SELECTED-mode universe
//   - listStrategies() (Checkpoint 26 strategy registry)
//   - listWatchlists() (Checkpoint 27 research watchlists)
//   - The existing Active Signal Monitor screen for the signal table
//     itself (not rebuilt here - see the "View Signals" link below).
//
// HONESTY RULES ENFORCED THROUGHOUT THIS FILE (§17 of the brief):
//   - Every number shown comes from a real API response field.
//   - Fields the backend does not yet provide (current stock, current
//     strategy, bars processed, signals today) are shown as an explicit
//     "Not provided by the current backend" string, never a fabricated
//     0/placeholder.
//   - START/STOP map to the single `enabled` boolean the backend
//     actually has (§8 Option B) - the UI does not pretend PAUSE/RESUME
//     are distinct states from STOP/START when they are not.
import { useCallback, useEffect, useRef, useState } from "react";

import { listWatchlists } from "../../common/api/backtestingApi";
import { ApiNetworkError, ApiRequestError } from "../../common/api/client";
import {
  getLivePaperReadiness,
  startLivePaperSession,
  stopLivePaperSession,
} from "../../common/api/marketDataApi";
import type { LivePaperReadinessResponse } from "../../common/api/marketDataApi";
import {
  getScannerConfiguration,
  updateScannerConfiguration,
} from "../../common/api/scannerConfigApi";
import type { ScannerConfigurationResponse } from "../../common/api/scannerConfigApi";
import { listStrategies } from "../../common/api/strategyApi";
import type { StrategySummary } from "../../common/api/strategyApi";
import { useAuth } from "../../common/auth/AuthContext";
import { InstrumentPickerMulti } from "../../common/components/InstrumentPicker";
import { TIMEFRAME_OPTIONS, WorkerStatusCard } from "./LiveMarketDataMonitor";

type UniverseMode = "ALL_CONFIGURED" | "SELECTED" | "WATCHLIST";

type ApplyPhase = "idle" | "validating" | "saving" | "applying" | "effective" | "failed";

const POLL_INTERVAL_MS = 2000;
const POLL_TIMEOUT_MS = 30000;

function describeError(error: unknown): string {
  if (error instanceof ApiRequestError || error instanceof ApiNetworkError) {
    return error.message;
  }
  return "An unexpected error occurred.";
}

function formatTimestamp(value: string | null): string {
  if (!value) return "Never";
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return value;
  return parsed.toLocaleString("en-IN", { timeZone: "Asia/Kolkata" });
}

const STATUS_LABELS: Record<string, string> = {
  EFFECTIVE: "Effective",
  APPLYING: "Applying",
  DEGRADED: "Degraded",
  STOPPED: "Stopped",
};

const STATUS_CLASS: Record<string, string> = {
  EFFECTIVE: "badge--active",
  APPLYING: "badge--pending",
  DEGRADED: "badge--danger",
  STOPPED: "badge--historical",
};

function statusNotification(config: ScannerConfigurationResponse): string {
  switch (config.status) {
    case "EFFECTIVE":
      return `Scanner is now running with configuration v${config.effective.configuration_version}.`;
    case "APPLYING":
      return "Waiting for live worker to apply configuration…";
    case "DEGRADED":
      return "Configuration partially applied.";
    case "STOPPED":
      return "Scanner is stopped.";
    default:
      return "";
  }
}

export function LiveScannerConsole(): JSX.Element {
  const { state: authState } = useAuth();
  const canOperate =
    authState.status === "authenticated" &&
    authState.capabilities.includes("configuration.activate");

  const [config, setConfig] = useState<ScannerConfigurationResponse | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);

  const [strategies, setStrategies] = useState<StrategySummary[] | null>(null);
  const [watchlistNames, setWatchlistNames] = useState<string[] | null>(null);

  // --- Draft form state (what the operator is currently editing) ---
  const [timeframe, setTimeframe] = useState<string>("5m");
  const [universeMode, setUniverseMode] = useState<UniverseMode>("ALL_CONFIGURED");
  const [selectedInstrumentIds, setSelectedInstrumentIds] = useState<string[]>([]);
  const [selectedWatchlistName, setSelectedWatchlistName] = useState<string>("");
  const [selectedStrategyIds, setSelectedStrategyIds] = useState<Set<string>>(new Set());

  const [applyPhase, setApplyPhase] = useState<ApplyPhase>("idle");
  // Checkpoint 64.13: the Pre-Session Readiness gate - re-fetched
  // independently of the scanner-config polling above; START stays
  // disabled unless the backend's own current readiness says
  // `can_start`. The backend independently re-checks this on every
  // start request too - this frontend check is a UX convenience, NEVER
  // the actual enforcement (see startLivePaperSession()).
  const [readiness, setReadiness] = useState<LivePaperReadinessResponse | null>(null);
  const [sessionMessage, setSessionMessage] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    function load(): void {
      getLivePaperReadiness()
        .then((result) => {
          if (!cancelled) setReadiness(result);
        })
        .catch(() => {
          /* readiness is advisory on this screen - WorkerStatusCard already surfaces errors */
        });
    }
    load();
    const interval = setInterval(load, 15000);
    return () => {
      cancelled = true;
      clearInterval(interval);
    };
  }, []);
  const [applyError, setApplyError] = useState<string | null>(null);
  const pollTimer = useRef<ReturnType<typeof setInterval> | null>(null);
  const pollDeadline = useRef<number>(0);

  const loadConfig = useCallback(async (): Promise<ScannerConfigurationResponse | null> => {
    try {
      const result = await getScannerConfiguration();
      setConfig(result);
      setLoadError(null);
      return result;
    } catch (error) {
      setLoadError(describeError(error));
      return null;
    }
  }, []);

  // Initial load - seed the draft form from the current DESIRED state so
  // an operator opening this screen sees what is actually configured,
  // not a blank/default form.
  useEffect(() => {
    void loadConfig().then((result) => {
      if (!result) return;
      setTimeframe(result.desired.timeframe);
      if (result.desired.universe_mode) {
        setUniverseMode(result.desired.universe_mode as UniverseMode);
      }
      setSelectedStrategyIds(new Set(result.desired.strategy_ids));
    });
  }, [loadConfig]);

  useEffect(() => {
    let cancelled = false;
    listStrategies()
      .then((result) => {
        if (!cancelled) setStrategies(result);
      })
      .catch(() => {
        if (!cancelled) setStrategies([]);
      });
    listWatchlists()
      .then((result) => {
        if (!cancelled) setWatchlistNames(result.map((w) => w.name));
      })
      .catch(() => {
        if (!cancelled) setWatchlistNames([]);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    return () => {
      if (pollTimer.current) clearInterval(pollTimer.current);
    };
  }, []);

  function stopPolling(): void {
    if (pollTimer.current) {
      clearInterval(pollTimer.current);
      pollTimer.current = null;
    }
  }

  // §9 of the brief: the POST only proves the desired configuration was
  // accepted - it does NOT prove the worker applied it. This polls the
  // real status API (the same one WorkerStatusCard and the desired/
  // effective panels below read) until effective_version == desired_
  // version, or a DEGRADED/timeout terminal state is reached.
  function beginPollingForEffective(desiredVersion: number): void {
    stopPolling();
    pollDeadline.current = Date.now() + POLL_TIMEOUT_MS;
    setApplyPhase("applying");
    pollTimer.current = setInterval(() => {
      void loadConfig().then((result) => {
        if (!result) return;
        if (result.effective.configuration_version === desiredVersion) {
          stopPolling();
          setApplyPhase(result.status === "DEGRADED" ? "failed" : "effective");
          if (result.status === "DEGRADED") {
            setApplyError(
              `Configuration partially applied: ${result.effective.universe_subscribed_count} of ` +
                `${result.effective.universe_requested_count} instruments subscribed.`,
            );
          }
          return;
        }
        if (Date.now() > pollDeadline.current) {
          stopPolling();
          setApplyPhase("failed");
          setApplyError(
            "Worker could not apply the requested configuration within the expected time - " +
              "check that the live worker process is running.",
          );
        }
      });
    }, POLL_INTERVAL_MS);
  }

  async function handleApply(enabled: boolean): Promise<void> {
    setApplyError(null);
    setApplyPhase("validating");
    await new Promise((resolve) => setTimeout(resolve, 150)); // let the "Validating…" state paint
    setApplyPhase("saving");
    try {
      const result = await updateScannerConfiguration({
        enabled,
        timeframe,
        universe_mode: universeMode,
        selected_instrument_ids: universeMode === "SELECTED" ? selectedInstrumentIds : [],
        selected_watchlist_name: universeMode === "WATCHLIST" ? selectedWatchlistName : "",
        selected_strategy_ids: Array.from(selectedStrategyIds),
      });
      setConfig(result);
      beginPollingForEffective(result.desired.configuration_version);
    } catch (error) {
      setApplyPhase("failed");
      setApplyError(describeError(error));
    }
  }

  // Checkpoint 64.13 §6/§7: explicit, human-triggered START - first
  // saves the operator's current draft selections as the desired
  // configuration (still disabled), THEN calls the real, backend-
  // enforced start gate. The backend re-checks readiness itself on
  // this call - a stale/cached frontend `can_start` is never trusted.
  async function handleStart(): Promise<void> {
    setApplyError(null);
    setSessionMessage(null);
    setApplyPhase("validating");
    try {
      const saved = await updateScannerConfiguration({
        enabled: false,
        timeframe,
        universe_mode: universeMode,
        selected_instrument_ids: universeMode === "SELECTED" ? selectedInstrumentIds : [],
        selected_watchlist_name: universeMode === "WATCHLIST" ? selectedWatchlistName : "",
        selected_strategy_ids: Array.from(selectedStrategyIds),
      });
      setConfig(saved);
      setApplyPhase("saving");
      const result = await startLivePaperSession();
      setSessionMessage(result.message);
      if (!result.accepted && !result.enabled) {
        setApplyPhase("failed");
        setApplyError(result.remediation ?? result.message);
        return;
      }
      const refreshed = await getScannerConfiguration();
      setConfig(refreshed);
      beginPollingForEffective(refreshed.desired.configuration_version);
    } catch (error) {
      setApplyPhase("failed");
      setApplyError(describeError(error));
    }
  }

  async function handleStop(): Promise<void> {
    setApplyError(null);
    setSessionMessage(null);
    try {
      const result = await stopLivePaperSession();
      setSessionMessage(result.message);
      const refreshed = await getScannerConfiguration();
      setConfig(refreshed);
    } catch (error) {
      setApplyError(describeError(error));
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

  const applyLabel: Record<ApplyPhase, string> = {
    idle: "",
    validating: "Validating…",
    saving: "Saving…",
    applying: "Applying…",
    effective: "Applied",
    failed: "Failed",
  };

  return (
    <div className="signal-monitor live-scanner">
      <header className="signal-monitor__header">
        <h1>Live Scanner</h1>
        <p className="configuration-viewer__subtitle">
          Configure and control the live market-data scanner without restarting the worker
          process. Every value on this page is read from or written to the real runtime
          control-plane API - nothing here is simulated.
        </p>
      </header>

      {loadError && <ErrorBanner message={loadError} />}

      <section aria-labelledby="live-scanner-health-heading" className="live-scanner__section">
        <h2 id="live-scanner-health-heading">System Health</h2>
        <div className="market-data-monitor__summary">
          <WorkerStatusCard />
        </div>
      </section>

      <section aria-labelledby="live-scanner-control-heading" className="live-scanner__section">
        <h2 id="live-scanner-control-heading">Scanner Control</h2>

        {!canOperate && (
          <p className="settings-card__readonly-note">
            You have read-only access to this screen - configuration changes require the
            configuration-operator role.
          </p>
        )}

        <div className="live-scanner__control-grid">
          <div className="signal-monitor__field">
            <label htmlFor="live-scanner-timeframe">Timeframe</label>
            <select
              id="live-scanner-timeframe"
              value={timeframe}
              disabled={!canOperate}
              onChange={(event) => setTimeframe(event.target.value)}
            >
              {TIMEFRAME_OPTIONS.map((option) => (
                <option key={option} value={option}>
                  {option}
                </option>
              ))}
            </select>
          </div>

          <fieldset className="signal-monitor__field live-scanner__fieldset">
            <legend className="signal-monitor__field-label">Universe</legend>
            <p className="signal-monitor__hint">
              Pending reconnect: unlike timeframe/strategy, a universe change is applied only the
              next time the worker reconnects to Dhan (researched - Dhan's documented WebSocket
              protocol offers no verified per-instrument unsubscribe distinct from a full
              disconnect, see docs/architecture/DHAN_MARKET_DATA_CAPABILITY_RESEARCH.md), so this
              can take longer than other changes to reach "Effective".
            </p>
            <label className="signal-monitor__radio">
              <input
                type="radio"
                name="live-scanner-universe-mode"
                checked={universeMode === "ALL_CONFIGURED"}
                disabled={!canOperate}
                onChange={() => setUniverseMode("ALL_CONFIGURED")}
              />
              All Configured
            </label>
            <label className="signal-monitor__radio">
              <input
                type="radio"
                name="live-scanner-universe-mode"
                checked={universeMode === "SELECTED"}
                disabled={!canOperate}
                onChange={() => setUniverseMode("SELECTED")}
              />
              Selected Stocks
            </label>
            <label className="signal-monitor__radio">
              <input
                type="radio"
                name="live-scanner-universe-mode"
                checked={universeMode === "WATCHLIST"}
                disabled={!canOperate}
                onChange={() => setUniverseMode("WATCHLIST")}
              />
              Watchlist
            </label>

            {universeMode === "SELECTED" && (
              <InstrumentPickerMulti
                idPrefix="live-scanner-universe"
                label={`Selected Stocks (${selectedInstrumentIds.length} selected)`}
                value={selectedInstrumentIds}
                onChange={setSelectedInstrumentIds}
              />
            )}

            {universeMode === "WATCHLIST" && (
              <div className="signal-monitor__field">
                <label htmlFor="live-scanner-watchlist">Watchlist</label>
                {watchlistNames === null && (
                  <p className="signal-monitor__hint">Loading watchlists…</p>
                )}
                {watchlistNames !== null && watchlistNames.length === 0 && (
                  <p className="signal-monitor__hint">
                    No watchlists saved yet - create one on the Watchlists screen first.
                  </p>
                )}
                {watchlistNames !== null && watchlistNames.length > 0 && (
                  <select
                    id="live-scanner-watchlist"
                    value={selectedWatchlistName}
                    disabled={!canOperate}
                    onChange={(event) => setSelectedWatchlistName(event.target.value)}
                  >
                    <option value="">Select a watchlist…</option>
                    {watchlistNames.map((name) => (
                      <option key={name} value={name}>
                        {name}
                      </option>
                    ))}
                  </select>
                )}
              </div>
            )}
          </fieldset>

          <fieldset className="signal-monitor__field live-scanner__fieldset">
            <legend className="signal-monitor__field-label">Strategies</legend>
            {strategies === null && <p className="signal-monitor__hint">Loading strategies…</p>}
            {strategies !== null && strategies.length === 0 && (
              <p className="signal-monitor__hint">No strategies registered.</p>
            )}
            {strategies !== null &&
              strategies.map((strategy) => (
                <label key={strategy.strategy_id} className="signal-monitor__checkbox">
                  <input
                    type="checkbox"
                    disabled={!canOperate}
                    checked={selectedStrategyIds.has(strategy.strategy_id)}
                    onChange={() => toggleStrategy(strategy.strategy_id)}
                  />
                  {strategy.display_name}
                </label>
              ))}
          </fieldset>
        </div>

        {canOperate && readiness && (
          <section aria-labelledby="live-scanner-readiness-heading" className="live-scanner__section">
            <h3 id="live-scanner-readiness-heading">Live Paper Session Readiness</h3>
            <span
              role="status"
              className={`badge ${readiness.can_start ? "badge--active" : "badge--danger"}`}
            >
              {readiness.can_start ? "● READY" : "● BLOCKED"}
            </span>
            <p className="signal-monitor__hint">
              {readiness.can_start
                ? "All mandatory checks passed. Review configuration before starting."
                : readiness.safe_reason}
            </p>
            <span className="badge badge--historical">
              Real Trading: {readiness.real_trading_state}
            </span>
          </section>
        )}

        {canOperate && (
          <div className="live-scanner__actions">
            {!config?.desired.enabled ? (
              <button
                type="button"
                className="market-data-monitor__refresh-button"
                disabled={
                  applyPhase === "validating" ||
                  applyPhase === "saving" ||
                  applyPhase === "applying" ||
                  !readiness?.can_start
                }
                onClick={() => void handleStart()}
              >
                START LIVE PAPER SESSION
              </button>
            ) : (
              <button
                type="button"
                className="market-data-monitor__refresh-button"
                disabled={applyPhase === "validating" || applyPhase === "saving" || applyPhase === "applying"}
                onClick={() => void handleApply(true)}
              >
                Apply Configuration
              </button>
            )}
            {config?.desired.enabled && (
              <button
                type="button"
                className="live-scanner__stop-button"
                disabled={applyPhase === "validating" || applyPhase === "saving" || applyPhase === "applying"}
                onClick={() => void handleStop()}
              >
                STOP LIVE PAPER SESSION
              </button>
            )}
          </div>
        )}
        {sessionMessage && (
          <p role="status" className="signal-monitor__hint">
            {sessionMessage}
          </p>
        )}
        <p className="signal-monitor__hint">
          STOP disables the signal pipeline for this scanner (bars keep being recorded, but no new
          signals are generated) - it does not terminate the underlying worker process. A true
          multi-state PAUSE/RESUME lifecycle with process-level control is not implemented yet
          (see taskReport.md, "Start / Pause / Resume / Stop").
        </p>

        {applyPhase !== "idle" && (
          <p role="status" className="live-scanner__apply-status">
            {applyLabel[applyPhase]}
            {applyPhase === "effective" && config && ` — ${statusNotification(config)}`}
          </p>
        )}
        {applyError && (
          <p role="alert" className="dialog__error">
            {applyError}
          </p>
        )}
      </section>

      {config && (
        <div className="live-scanner__state-grid">
          <section aria-labelledby="live-scanner-desired-heading" className="market-data-monitor__card">
            <h2 id="live-scanner-desired-heading">Desired Configuration</h2>
            <dl>
              <dt>Version</dt>
              <dd>{config.desired.configuration_version}</dd>
              <dt>Enabled</dt>
              <dd>{config.desired.enabled ? "Yes" : "No"}</dd>
              <dt>Timeframe</dt>
              <dd>{config.desired.timeframe}</dd>
              <dt>Strategies</dt>
              <dd>{config.desired.strategy_ids.length > 0 ? config.desired.strategy_ids.join(", ") : "None selected"}</dd>
              <dt>Requested By</dt>
              <dd>{config.requested_by || "—"}</dd>
              <dt>Requested At</dt>
              <dd>{formatTimestamp(config.requested_at)}</dd>
            </dl>
          </section>

          <section aria-labelledby="live-scanner-effective-heading" className="market-data-monitor__card">
            <h2 id="live-scanner-effective-heading">Effective Configuration</h2>
            <span className={`badge ${STATUS_CLASS[config.status] ?? ""}`}>
              {STATUS_LABELS[config.status] ?? config.status}
            </span>
            <dl>
              <dt>Effective Version</dt>
              <dd>{config.effective.configuration_version || "Never reconciled"}</dd>
              <dt>Timeframe</dt>
              <dd>{config.effective.timeframe || "—"}</dd>
              <dt>Strategies</dt>
              <dd>{config.effective.strategy_ids.length > 0 ? config.effective.strategy_ids.join(", ") : "—"}</dd>
              <dt>Universe Requested</dt>
              <dd>{config.effective.universe_requested_count}</dd>
              <dt>Universe Subscribed</dt>
              <dd>{config.effective.universe_subscribed_count}</dd>
            </dl>
            {config.status === "DEGRADED" && (
              <p role="alert" className="dialog__error">
                Reason: {config.effective.universe_requested_count - config.effective.universe_subscribed_count}{" "}
                instrument(s) requested but not subscribed - desired state and effective state do
                not match. The worker could not resolve or subscribe to every requested instrument.
              </p>
            )}
            {config.status === "APPLYING" && (
              <p className="signal-monitor__hint">
                Desired version {config.desired.configuration_version} has not been applied by the
                worker yet (effective version {config.effective.configuration_version || 0}).
              </p>
            )}
          </section>
        </div>
      )}

      <section aria-labelledby="live-scanner-activity-heading" className="live-scanner__section">
        <h2 id="live-scanner-activity-heading">Live Activity</h2>
        <p className="signal-monitor__hint">
          The current backend does not persist a per-instrument "currently scanning" pointer, a
          per-strategy live counter, or an intraday signal count - these are shown honestly below
          rather than fabricated. Feed/packet/bar timestamps come from the real worker status
          above.
        </p>
        <dl>
          <dt>Current Stock</dt>
          <dd>Not provided by the current backend</dd>
          <dt>Current Strategy</dt>
          <dd>Not provided by the current backend</dd>
          <dt>Bars Processed</dt>
          <dd>Not provided by the current backend</dd>
          <dt>Signals Today</dt>
          <dd>Not provided by the current backend</dd>
        </dl>
      </section>

      <section aria-labelledby="live-scanner-signals-heading" className="live-scanner__section">
        <h2 id="live-scanner-signals-heading">Signals</h2>
        <p className="signal-monitor__hint">
          Qualifying signals are shown on the existing Active Signal Monitor screen (Market Data
          nav item) - this console does not duplicate that table.
        </p>
      </section>
    </div>
  );
}

function ErrorBanner({ message }: { message: string }): JSX.Element {
  return (
    <p role="alert" className="dialog__error">
      {message}
    </p>
  );
}
