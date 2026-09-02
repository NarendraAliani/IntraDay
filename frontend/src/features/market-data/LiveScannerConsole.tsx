// frontend/src/features/market-data/LiveScannerConsole.tsx
//
// Checkpoint 64.5: the original operator-facing "LIVE SCANNER" control
// console. Checkpoint 64.93 is this screen's PRODUCTIZATION - the brief's
// own "USER -> CONFIGURE -> VALIDATE -> EXPLICIT START -> SCAN SELECTED
// UNIVERSE -> ... -> CANONICAL SIGNAL -> (Telegram/Discord/Live Console)"
// pipeline made real on one page. Every addition below REUSES an existing
// backend capability found during this checkpoint's audit rather than
// inventing one:
//   - Notification channels: NEW `listNotificationChannels()` registry
//     endpoint (Checkpoint 64.93), backed by the EXISTING Telegram/
//     Discord settings services (Checkpoint 22) - no duplicated channel
//     model.
//   - Scanner runtime state (distinct from the Market Data Worker):
//     `getLivePaperWorkbench()` (Checkpoint 64.14/64.18) already
//     returns `session_state` (STARTING/RUNNING/...) and
//     `scanner_progress` (current_instrument, current_strategy,
//     universe_total/processed, signals_found, status, stale) - this
//     page simply WIRES it instead of showing "Not provided" for data
//     the backend has had all along.
//   - Live signal console: `listSignals()` (Checkpoint 62/64.9/64.81)
//     already returns the canonical signal with its Telegram/Discord
//     fan-out status, scan_run_id, and strategy_version_identifier -
//     reused verbatim, same polling pattern LivePaperOperationsConsole
//     already established (Checkpoint 64.15 §15's "one interval per
//     data source").
//   - Gainz: the strategy registry (`listStrategies()`) simply never
//     registers `gainz_algo` (see `registry.py`'s `build_default_
//     registry()`) - this page renders ONLY what that registry
//     returns, so Gainz never appears as selectable. Nothing here
//     special-cases it; the honesty is structural, not a UI branch.
//
// HONESTY RULES ENFORCED THROUGHOUT THIS FILE (unchanged since 64.5):
//   - Every number shown comes from a real API response field.
//   - A field the backend genuinely does not track (bars processed) is
//     shown as an explicit "Not provided by the current backend"
//     string, never a fabricated 0/placeholder.
//   - START/STOP map to the single `enabled` boolean the backend
//     actually has.
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { listWatchlists } from "../../common/api/backtestingApi";
import { ApiNetworkError, ApiRequestError } from "../../common/api/client";
import {
  getLivePaperReadiness,
  getLivePaperWorkbench,
  startLivePaperSession,
  stopLivePaperSession,
} from "../../common/api/marketDataApi";
import type {
  LivePaperReadinessResponse,
  LivePaperWorkbenchResponse,
} from "../../common/api/marketDataApi";
import {
  getScannerConfiguration,
  listNotificationChannels,
  updateScannerConfiguration,
} from "../../common/api/scannerConfigApi";
import type {
  NotificationChannel,
  ScannerConfigurationResponse,
} from "../../common/api/scannerConfigApi";
import { listSignals } from "../../common/api/signalApi";
import type { SignalResponse } from "../../common/api/signalApi";
import { listStrategies } from "../../common/api/strategyApi";
import type { StrategySummary } from "../../common/api/strategyApi";
import { useAuth } from "../../common/auth/AuthContext";
import { ConfirmDialog } from "../../common/components/ConfirmDialog";
import { InstrumentPickerMulti } from "../../common/components/InstrumentPicker";
import { TIMEFRAME_OPTIONS, WorkerStatusCard } from "./LiveMarketDataMonitor";

// Part B: exactly the three conceptual choices the checkpoint names,
// in the order it names them - the wire value stays `ALL_CONFIGURED`
// (the already-shipped, already-tested backend enum: renaming it would
// be a breaking contract change for zero behavioral gain), the LABEL
// is "All Stocks".
type UniverseMode = "ALL_CONFIGURED" | "WATCHLIST" | "SELECTED";

const UNIVERSE_MODE_LABEL: Record<UniverseMode, string> = {
  ALL_CONFIGURED: "All Stocks",
  WATCHLIST: "Watchlist",
  SELECTED: "Selected Stocks",
};

type ApplyPhase = "idle" | "validating" | "saving" | "applying" | "effective" | "failed";

const POLL_INTERVAL_MS = 2000;
const POLL_TIMEOUT_MS = 30000;
const WORKBENCH_POLL_MS = 5000;
const SIGNALS_POLL_MS = 5000;

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

function formatTradeValue(value: string | null | undefined): string {
  if (value === null || value === undefined) return "—";
  return `₹${value}`;
}

function symbolFromInstrumentId(instrumentId: string): string {
  const parts = instrumentId.split(":");
  return parts[parts.length - 1] ?? instrumentId;
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
  const [channels, setChannels] = useState<NotificationChannel[] | null>(null);

  // --- Draft form state (what the operator is currently editing) ---
  const [timeframe, setTimeframe] = useState<string>("5m");
  const [universeMode, setUniverseMode] = useState<UniverseMode>("ALL_CONFIGURED");
  const [selectedInstrumentIds, setSelectedInstrumentIds] = useState<string[]>([]);
  const [selectedWatchlistName, setSelectedWatchlistName] = useState<string>("");
  const [selectedStrategyIds, setSelectedStrategyIds] = useState<Set<string>>(new Set());
  const [selectedChannelIds, setSelectedChannelIds] = useState<Set<string>>(new Set());

  const [applyPhase, setApplyPhase] = useState<ApplyPhase>("idle");
  // Checkpoint 64.13: the Pre-Session Readiness gate - re-fetched
  // independently of the scanner-config polling above; START stays
  // disabled unless the backend's own current readiness says
  // `can_start`, AND (Checkpoint 64.93 Part E) the frontend's own
  // configuration-validity computation below finds no problems. The
  // backend independently re-checks configuration validity itself on
  // every start request too - this frontend check is UX only, never
  // the actual enforcement (see startLivePaperSession()/
  // update_scanner_configuration's server-side validation).
  const [readiness, setReadiness] = useState<LivePaperReadinessResponse | null>(null);
  const [sessionMessage, setSessionMessage] = useState<string | null>(null);
  const [showReconfigureConfirm, setShowReconfigureConfirm] = useState(false);

  // Checkpoint 64.93 Part H: the scanner's OWN runtime state (session_
  // state + scanner_progress), fetched from the SAME workbench endpoint
  // LivePaperOperationsConsole already polls - never a second status
  // model. Deliberately a SEPARATE poll from `readiness` above (they
  // answer different questions and existed as different endpoints
  // before this checkpoint).
  const [workbench, setWorkbench] = useState<LivePaperWorkbenchResponse | null>(null);
  const [workbenchError, setWorkbenchError] = useState<string | null>(null);

  // Checkpoint 64.93 Part I/J: this screen's OWN live signal console -
  // polls the same `listSignals()` API the global Active Signal Monitor
  // uses, so a signal shows up here without navigating away.
  const [signals, setSignals] = useState<SignalResponse[] | null>(null);
  const [signalsError, setSignalsError] = useState<string | null>(null);

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

  useEffect(() => {
    let cancelled = false;
    function load(): void {
      getLivePaperWorkbench()
        .then((result) => {
          if (!cancelled) {
            setWorkbench(result);
            setWorkbenchError(null);
          }
        })
        .catch((error: unknown) => {
          if (!cancelled) setWorkbenchError(describeError(error));
        });
    }
    load();
    const interval = setInterval(load, WORKBENCH_POLL_MS);
    return () => {
      cancelled = true;
      clearInterval(interval);
    };
  }, []);

  useEffect(() => {
    let cancelled = false;
    function load(): void {
      listSignals({ pageSize: 15, sort: "newest" })
        .then((result) => {
          if (!cancelled) {
            setSignals(result.items);
            setSignalsError(null);
          }
        })
        .catch((error: unknown) => {
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
      setSelectedChannelIds(new Set(result.desired.notification_channels ?? []));
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
    listNotificationChannels()
      .then((result) => {
        if (!cancelled) setChannels(result);
      })
      .catch(() => {
        if (!cancelled) setChannels([]);
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

  // Checkpoint 64.93 Part E: the explicit, itemized "why not ready"
  // list - a client-side CONVENIENCE only. The backend independently
  // re-validates every one of these on the actual write (Part L); this
  // never becomes the enforcement path.
  const configurationProblems = useMemo(() => {
    const problems: string[] = [];
    if (universeMode === "WATCHLIST" && !selectedWatchlistName) {
      problems.push("Watchlist not selected.");
    }
    if (universeMode === "SELECTED" && selectedInstrumentIds.length === 0) {
      problems.push("Selected Stocks list is empty.");
    }
    if (selectedStrategyIds.size === 0) {
      problems.push("No strategy selected.");
    }
    if (strategies) {
      const byId = new Map(strategies.map((s) => [s.strategy_id, s]));
      for (const strategyId of selectedStrategyIds) {
        const strategy = byId.get(strategyId);
        if (!strategy || !strategy.is_active) {
          problems.push(`Strategy "${strategyId}" is not currently selectable.`);
        }
      }
    }
    if (channels) {
      const byId = new Map(channels.map((c) => [c.channel_id, c]));
      for (const channelId of selectedChannelIds) {
        const channel = byId.get(channelId);
        if (channel && !channel.configured) {
          problems.push(`${channel.display_name} is enabled but not configured.`);
        }
      }
    }
    if (readiness && !readiness.can_start) {
      problems.push(readiness.safe_reason);
    }
    return problems;
  }, [
    universeMode,
    selectedWatchlistName,
    selectedInstrumentIds,
    selectedStrategyIds,
    strategies,
    channels,
    selectedChannelIds,
    readiness,
  ]);
  const isConfigurationReady = configurationProblems.length === 0;

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

  function draftRequestBody(enabled: boolean): {
    enabled: boolean;
    timeframe: string;
    universe_mode: UniverseMode;
    selected_instrument_ids: string[];
    selected_watchlist_name: string;
    selected_strategy_ids: string[];
    selected_notification_channels: string[];
  } {
    return {
      enabled,
      timeframe,
      universe_mode: universeMode,
      selected_instrument_ids: universeMode === "SELECTED" ? selectedInstrumentIds : [],
      selected_watchlist_name: universeMode === "WATCHLIST" ? selectedWatchlistName : "",
      selected_strategy_ids: Array.from(selectedStrategyIds),
      selected_notification_channels: Array.from(selectedChannelIds),
    };
  }

  async function handleApply(enabled: boolean): Promise<void> {
    setApplyError(null);
    setApplyPhase("validating");
    await new Promise((resolve) => setTimeout(resolve, 150)); // let the "Validating…" state paint
    setApplyPhase("saving");
    try {
      const result = await updateScannerConfiguration(draftRequestBody(enabled));
      setConfig(result);
      beginPollingForEffective(result.desired.configuration_version);
    } catch (error) {
      setApplyPhase("failed");
      setApplyError(describeError(error));
    }
  }

  // Checkpoint 64.13 §6/§7 / Checkpoint 64.93 Part F: explicit,
  // human-triggered START - first saves the operator's current draft
  // selections as the desired configuration (still disabled), THEN
  // calls the real, backend-enforced start gate. No control changing
  // alone ever starts a scan; only this handler, invoked by pressing
  // START, does.
  async function handleStart(): Promise<void> {
    setApplyError(null);
    setSessionMessage(null);
    setApplyPhase("validating");
    try {
      const saved = await updateScannerConfiguration(draftRequestBody(false));
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

  function toggleChannel(channelId: string): void {
    setSelectedChannelIds((prev) => {
      const next = new Set(prev);
      if (next.has(channelId)) next.delete(channelId);
      else next.add(channelId);
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

  const scannerProgress = workbench?.scanner_progress ?? null;
  const scannerState = workbench?.session_state ?? null;
  const effectiveSessionConfig = workbench?.effective_session_configuration ?? null;

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
        <h2 id="live-scanner-health-heading">Market Data Worker</h2>
        <p className="signal-monitor__hint">
          The worker that ingests packets/bars from the provider - distinct from the scanner
          runtime below (Part H). A HEALTHY worker does not by itself mean the scanner is
          SCANNING.
        </p>
        <div className="market-data-monitor__summary">
          <WorkerStatusCard />
        </div>
      </section>

      <section aria-labelledby="live-scanner-config-heading" className="live-scanner__section">
        <h2 id="live-scanner-config-heading">Scanner Configuration</h2>

        {!canOperate && (
          <p className="settings-card__readonly-note">
            You have read-only access to this screen - configuration changes require the
            configuration-operator role.
          </p>
        )}

        <div className="live-scanner__field-stack">
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
            <legend className="signal-monitor__field-label">Scan Universe</legend>
            <p className="signal-monitor__hint">
              Pending reconnect: unlike timeframe/strategy, a universe change is applied only the
              next time the worker reconnects to Dhan (researched - Dhan's documented WebSocket
              protocol offers no verified per-instrument unsubscribe distinct from a full
              disconnect, see docs/architecture/DHAN_MARKET_DATA_CAPABILITY_RESEARCH.md), so this
              can take longer than other changes to reach "Effective".
            </p>
            {(["ALL_CONFIGURED", "WATCHLIST", "SELECTED"] as UniverseMode[]).map((mode) => (
              <label key={mode} className="signal-monitor__radio">
                <input
                  type="radio"
                  name="live-scanner-universe-mode"
                  checked={universeMode === mode}
                  disabled={!canOperate}
                  onChange={() => setUniverseMode(mode)}
                />
                {UNIVERSE_MODE_LABEL[mode]}
              </label>
            ))}

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
            <p className="signal-monitor__hint">
              Rendered from the backend strategy registry - a strategy the registry marks
              unavailable or does not return at all simply cannot appear here.
            </p>
            {strategies === null && <p className="signal-monitor__hint">Loading strategies…</p>}
            {strategies !== null && strategies.length === 0 && (
              <p className="signal-monitor__hint">No strategies registered.</p>
            )}
            {strategies !== null &&
              strategies.map((strategy) => (
                <label key={strategy.strategy_id} className="signal-monitor__checkbox">
                  <input
                    type="checkbox"
                    disabled={!canOperate || !strategy.is_active}
                    checked={selectedStrategyIds.has(strategy.strategy_id)}
                    onChange={() => toggleStrategy(strategy.strategy_id)}
                  />
                  {strategy.display_name}
                  {!strategy.is_active && (
                    <span className="badge badge--historical badge--inline">
                      Not currently selectable
                    </span>
                  )}
                </label>
              ))}
          </fieldset>

          <fieldset className="signal-monitor__field live-scanner__fieldset">
            <legend className="signal-monitor__field-label">Notification Channels</legend>
            <p className="signal-monitor__hint">
              Rendered from the backend notification-channel registry. A channel that is not
              configured is shown as such and cannot be relied on for delivery even if enabled
              here.
            </p>
            {channels === null && (
              <p className="signal-monitor__hint">Loading notification channels…</p>
            )}
            {channels !== null && channels.length === 0 && (
              <p className="signal-monitor__hint">No notification channels registered.</p>
            )}
            {channels !== null &&
              channels.map((channel) => (
                <label key={channel.channel_id} className="signal-monitor__checkbox">
                  <input
                    type="checkbox"
                    disabled={!canOperate}
                    checked={selectedChannelIds.has(channel.channel_id)}
                    onChange={() => toggleChannel(channel.channel_id)}
                  />
                  {channel.display_name}
                  <span
                    className={`badge badge--inline ${channel.configured ? "badge--active" : "badge--danger"}`}
                  >
                    {channel.configured ? "Configured" : "Not configured"}
                  </span>
                  <span
                    className={`badge badge--inline ${channel.enabled ? "badge--active" : "badge--historical"}`}
                  >
                    {channel.enabled ? "Enabled" : "Disabled"}
                  </span>
                </label>
              ))}
          </fieldset>
        </div>

        <section
          aria-labelledby="live-scanner-readiness-heading"
          className="live-scanner__section"
        >
          <h3 id="live-scanner-readiness-heading">Readiness</h3>
          <span role="status" className={`badge ${isConfigurationReady ? "badge--active" : "badge--danger"}`}>
            {isConfigurationReady ? "● READY TO SCAN" : "● NOT READY"}
          </span>
          {!isConfigurationReady && (
            <ul className="live-scanner__reason-list">
              {configurationProblems.map((reason) => (
                <li key={reason}>{reason}</li>
              ))}
            </ul>
          )}
          {readiness && (
            <span className="badge badge--historical">
              Real Trading: {readiness.real_trading_state}
            </span>
          )}
        </section>

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
                  !isConfigurationReady
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
                onClick={() => setShowReconfigureConfirm(true)}
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
              <dt>Universe</dt>
              <dd>{UNIVERSE_MODE_LABEL[(config.desired.universe_mode as UniverseMode) ?? "ALL_CONFIGURED"]}</dd>
              <dt>Strategies</dt>
              <dd>{config.desired.strategy_ids.length > 0 ? config.desired.strategy_ids.join(", ") : "None selected"}</dd>
              <dt>Notification Channels</dt>
              <dd>
                {config.desired.notification_channels && config.desired.notification_channels.length > 0
                  ? config.desired.notification_channels.join(", ")
                  : "None selected"}
              </dd>
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
            {config.status !== "STOPPED" && config.status !== "EFFECTIVE" && (
              <p role="status" className="signal-monitor__hint">
                CONFIGURATION CHANGE PENDING
              </p>
            )}
            <dl>
              <dt>Effective Version</dt>
              <dd>{config.effective.configuration_version || "Never reconciled"}</dd>
              <dt>Timeframe</dt>
              <dd>{config.effective.timeframe || "—"}</dd>
              <dt>Strategies</dt>
              <dd>{config.effective.strategy_ids.length > 0 ? config.effective.strategy_ids.join(", ") : "—"}</dd>
              <dt>Notification Channels (operational)</dt>
              <dd>
                {config.effective.notification_channels && config.effective.notification_channels.length > 0
                  ? config.effective.notification_channels.join(", ")
                  : "None"}
              </dd>
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

      <section aria-labelledby="live-scanner-runtime-heading" className="live-scanner__section">
        <h2 id="live-scanner-runtime-heading">Scanner Runtime</h2>
        <p className="signal-monitor__hint">
          The SCANNER's own state - distinct from the Market Data Worker above. A HEALTHY worker
          with the scanner STOPPED is a real, valid, and common state.
        </p>
        {workbenchError && <ErrorBanner message={workbenchError} />}
        <dl>
          <dt>Scanner State</dt>
          <dd>{scannerState ?? "Unknown"}</dd>
          <dt>Effective Configuration Version</dt>
          <dd>{effectiveSessionConfig?.effective_configuration_version ?? "Never reconciled"}</dd>
        </dl>
        {scannerProgress ? (
          <dl>
            <dt>Scan Status</dt>
            <dd>
              {scannerProgress.status}
              {scannerProgress.stale && (
                <span className="badge badge--danger badge--inline">
                  STALE
                </span>
              )}
            </dd>
            <dt>Current Stock</dt>
            <dd>{scannerProgress.current_instrument || "—"}</dd>
            <dt>Current Strategy</dt>
            <dd>{scannerProgress.current_strategy || "—"}</dd>
            <dt>Universe Progress</dt>
            <dd>
              {scannerProgress.universe_processed} / {scannerProgress.universe_total} (
              {scannerProgress.progress_percent}%)
            </dd>
            <dt>Bars Processed</dt>
            <dd>Not provided by the current backend</dd>
            <dt>Signals Today</dt>
            <dd>{scannerProgress.signals_found}</dd>
            <dt>Last Progress At</dt>
            <dd>{formatTimestamp(scannerProgress.last_progress_at)}</dd>
            {scannerProgress.last_error_safe && (
              <>
                <dt>Last Error</dt>
                <dd role="alert">{scannerProgress.last_error_safe}</dd>
              </>
            )}
          </dl>
        ) : (
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
        )}
      </section>

      <section aria-labelledby="live-scanner-signals-heading" className="live-scanner__section">
        <h2 id="live-scanner-signals-heading">Live Signals</h2>
        <p className="signal-monitor__hint">
          The canonical signal event fanned out to Telegram/Discord/this console - a delivery
          problem on one channel never hides the signal here. The full history remains available
          on the Active Signal Monitor screen.
        </p>
        {signalsError && <ErrorBanner message={signalsError} />}
        {!signalsError && signals === null && (
          <p className="signal-monitor__hint">Loading signals…</p>
        )}
        {!signalsError && signals !== null && signals.length === 0 && (
          <p className="market-data-monitor__empty">No signals yet this session.</p>
        )}
        {!signalsError && signals !== null && signals.length > 0 && (
          <table className="signal-monitor__table">
            <caption className="sr-only">Live signals produced by the scanner</caption>
            <thead>
              <tr>
                <th scope="col">Timestamp</th>
                <th scope="col">Stock</th>
                <th scope="col">Strategy</th>
                <th scope="col">Version</th>
                <th scope="col">Signal</th>
                <th scope="col">Timeframe</th>
                <th scope="col">Entry</th>
                <th scope="col">Stop Loss</th>
                <th scope="col">Target(s)</th>
                <th scope="col">Strength/Score</th>
                <th scope="col">Signal ID</th>
                <th scope="col">Scan Run</th>
                <th scope="col">Notification Status</th>
              </tr>
            </thead>
            <tbody>
              {signals.map((signal) => {
                const targets = [
                  signal.trade_plan?.target_1,
                  signal.trade_plan?.target_2,
                  signal.trade_plan?.target_3,
                ]
                  .filter((v): v is string => v !== null && v !== undefined)
                  .map((v) => `₹${v}`)
                  .join(", ");
                return (
                  <tr key={signal.signal_id}>
                    <td>{formatTimestamp(signal.signal_timestamp)}</td>
                    <td>{symbolFromInstrumentId(signal.instrument_id)}</td>
                    <td>{signal.strategy_id}</td>
                    <td>{signal.strategy_version_identifier ?? "—"}</td>
                    <td>{signal.direction}</td>
                    <td>{signal.timeframe}</td>
                    <td>{formatTradeValue(signal.trade_plan?.entry_price)}</td>
                    <td>{formatTradeValue(signal.trade_plan?.stop_loss)}</td>
                    <td>{targets || "—"}</td>
                    <td>Not provided by the current backend</td>
                    <td>
                      <code>{signal.signal_id.slice(0, 8)}</code>
                    </td>
                    <td>{signal.scan_run_id ? <code>{signal.scan_run_id.slice(0, 8)}</code> : "—"}</td>
                    <td>
                      <span aria-label={`Telegram: ${signal.telegram?.status ?? "not provided"}`}>
                        Telegram: {signal.telegram?.status ?? "Not provided"}
                      </span>
                      <br />
                      <span aria-label={`Discord: ${signal.discord?.status ?? "not provided"}`}>
                        Discord: {signal.discord?.status ?? "Not provided"}
                      </span>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
      </section>

      {showReconfigureConfirm && (
        <ConfirmDialog
          titleId="live-scanner-reconfigure-confirm-title"
          title="Apply configuration to the RUNNING session?"
          confirmLabel="Apply now"
          status="idle"
          onCancel={() => setShowReconfigureConfirm(false)}
          onConfirm={() => {
            setShowReconfigureConfirm(false);
            void handleApply(true);
          }}
        >
          <p>
            This Live Paper Session is currently RUNNING. Applying this configuration change will
            take effect on the worker&apos;s next reconciliation cycle - it does NOT stop the
            session first.
          </p>
          <p>
            <strong>Timeframe:</strong> {timeframe}
            <br />
            <strong>Universe:</strong> {UNIVERSE_MODE_LABEL[universeMode]}
            <br />
            <strong>Strategies:</strong>{" "}
            {selectedStrategyIds.size > 0 ? Array.from(selectedStrategyIds).join(", ") : "None selected"}
            <br />
            <strong>Notification Channels:</strong>{" "}
            {selectedChannelIds.size > 0 ? Array.from(selectedChannelIds).join(", ") : "None selected"}
          </p>
        </ConfirmDialog>
      )}
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
