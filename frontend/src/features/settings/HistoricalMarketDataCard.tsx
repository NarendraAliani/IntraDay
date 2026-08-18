// frontend/src/features/settings/HistoricalMarketDataCard.tsx
//
// Follow-up to Checkpoint 63.x: the Settings page's manual "fetch real
// stock data from Dhan into the database" trigger - the UI half of
// `market_data_sync_views.py`. Reuses `InstrumentPickerMulti` verbatim
// (its own exchange-select + "Select All" + search already covers "one
// exchange," "all instruments," and "hand-picked instruments" in one
// control - no separate machinery needed for that) and mirrors
// `BacktestingWorkbenchPage.tsx`'s own real (never timer-driven)
// progress-polling pattern for the analogous `HistoricalBacktestRunPanel`.
//
// TIMEFRAME CHECKBOXES (an explicit, approved decision, not a default):
// checking several timeframes fetches ALL of them in one run - one
// combined progress bar over every instrument x timeframe combination,
// counted server-side as `total_combinations`/`completed_combinations`
// (see `MarketDataSyncRunOrchestrator`'s own docstring).
import { useEffect, useState } from "react";

import { ApiNetworkError, ApiRequestError } from "../../common/api/client";
import {
  createMarketDataSyncRun,
  getMarketDataSyncRunProgress,
} from "../../common/api/marketDataSyncApi";
import type { MarketDataSyncRunProgress } from "../../common/api/marketDataSyncApi";
import { InstrumentPickerMulti } from "../../common/components/InstrumentPicker";

const TERMINAL_RUN_STATUSES = new Set(["COMPLETED", "PARTIAL", "FAILED", "CANCELLED"]);
const POLL_INTERVAL_MS = 1200;

const TIMEFRAME_OPTIONS: { value: string; label: string }[] = [
  { value: "1d", label: "Daily" },
  { value: "1m", label: "1 minute" },
  { value: "5m", label: "5 minute" },
  { value: "15m", label: "15 minute" },
  { value: "1h", label: "1 hour" },
];

function todayIsoDate(): string {
  return new Date().toISOString().slice(0, 10);
}

function describeError(error: unknown): string {
  if (error instanceof ApiRequestError || error instanceof ApiNetworkError) {
    return error.message;
  }
  return "An unexpected error occurred.";
}

type SyncPhase =
  | { phase: "idle" }
  | { phase: "starting" }
  | { phase: "polling"; progress: MarketDataSyncRunProgress }
  | { phase: "done"; progress: MarketDataSyncRunProgress }
  | { phase: "error"; message: string };

function TimeframeCheckboxes(props: {
  value: string[];
  onChange: (next: string[]) => void;
}): JSX.Element {
  const selected = new Set(props.value);

  function toggle(timeframe: string): void {
    const next = new Set(selected);
    if (next.has(timeframe)) next.delete(timeframe);
    else next.add(timeframe);
    props.onChange(Array.from(next));
  }

  return (
    <fieldset className="strategy-config-page__field">
      <legend>Timeframes</legend>
      <div className="instrument-picker__checklist instrument-picker__checklist--inline">
        {TIMEFRAME_OPTIONS.map((option) => (
          <label key={option.value}>
            <input
              type="checkbox"
              checked={selected.has(option.value)}
              onChange={() => toggle(option.value)}
            />
            {option.label}
          </label>
        ))}
      </div>
    </fieldset>
  );
}

export function HistoricalMarketDataCard(): JSX.Element {
  const [instrumentIds, setInstrumentIds] = useState<string[]>([]);
  const [timeframes, setTimeframes] = useState<string[]>(["1d"]);
  const [startDate, setStartDate] = useState(todayIsoDate);
  const [endDate, setEndDate] = useState(todayIsoDate);
  const [state, setState] = useState<SyncPhase>({ phase: "idle" });
  const [runId, setRunId] = useState<string | null>(null);

  useEffect(() => {
    if (state.phase !== "polling" || runId === null) return undefined;
    let cancelled = false;
    const interval = setInterval(async () => {
      try {
        const progress = await getMarketDataSyncRunProgress(runId);
        if (cancelled) return;
        setState(
          TERMINAL_RUN_STATUSES.has(progress.status)
            ? { phase: "done", progress }
            : { phase: "polling", progress },
        );
      } catch (error) {
        if (!cancelled) setState({ phase: "error", message: describeError(error) });
      }
    }, POLL_INTERVAL_MS);
    return () => {
      cancelled = true;
      clearInterval(interval);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [state.phase, runId]);

  async function handleFetch(): Promise<void> {
    setState({ phase: "starting" });
    try {
      const created = await createMarketDataSyncRun({
        instrument_ids: instrumentIds,
        timeframes,
        start_date: startDate,
        end_date: endDate,
      });
      setRunId(created.run_id);
      const progress = await getMarketDataSyncRunProgress(created.run_id);
      setState(
        TERMINAL_RUN_STATUSES.has(progress.status)
          ? { phase: "done", progress }
          : { phase: "polling", progress },
      );
    } catch (error) {
      setState({ phase: "error", message: describeError(error) });
    }
  }

  const progress = state.phase === "polling" || state.phase === "done" ? state.progress : null;
  const busy = state.phase === "starting" || state.phase === "polling";
  const canFetch = instrumentIds.length > 0 && timeframes.length > 0;

  return (
    <section className="settings-card" aria-label="Historical Market Data">
      <div className="settings-card__header">
        <h2>Historical Market Data</h2>
      </div>
      <p className="strategy-config-page__help-text">
        Fetch real historical OHLCV bars from Dhan (daily or intraday candles) and save them to the
        database, so backtests and future scans have genuine market history to work from instead of
        having to fetch it on demand. Pick one stock, hand-pick several, or select an entire exchange
        below. Check as many timeframes as you need - all of them are fetched together in one run.
      </p>

      <InstrumentPickerMulti
        value={instrumentIds}
        onChange={setInstrumentIds}
        idPrefix="market-data-sync"
        label="Instruments to fetch"
      />

      <div className="historical-run__config">
        <TimeframeCheckboxes value={timeframes} onChange={setTimeframes} />
        <div className="strategy-config-page__field">
          <label htmlFor="market-data-sync-start">Start Date</label>
          <input
            id="market-data-sync-start"
            type="date"
            value={startDate}
            onChange={(e) => setStartDate(e.target.value)}
          />
        </div>
        <div className="strategy-config-page__field">
          <label htmlFor="market-data-sync-end">End Date</label>
          <input
            id="market-data-sync-end"
            type="date"
            value={endDate}
            onChange={(e) => setEndDate(e.target.value)}
          />
        </div>
      </div>

      <div className="historical-run__actions">
        <button type="button" onClick={() => void handleFetch()} disabled={!canFetch || busy}>
          {busy ? "Fetching…" : "Fetch & Save"}
        </button>
        {instrumentIds.length === 0 && (
          <span className="strategy-config-page__help-text">Select at least one instrument.</span>
        )}
        {instrumentIds.length > 0 && timeframes.length === 0 && (
          <span className="strategy-config-page__help-text">Select at least one timeframe.</span>
        )}
      </div>

      {progress && (
        <div className="historical-run__progress" role="status">
          <p>
            <strong>{progress.status}</strong> — {progress.progress_percent.toFixed(1)}% (
            {progress.completed_combinations}/{progress.total_combinations} instrument×timeframe
            combinations)
          </p>
          {progress.message && (
            <p className="strategy-config-page__help-text">{progress.message}</p>
          )}
          <p className="strategy-config-page__help-text">
            Bars fetched: {progress.bars_fetched} · Bars persisted: {progress.bars_persisted} ·
            Cache hits: {progress.cache_hits} · API requests: {progress.api_requests}
          </p>
          {Array.isArray(progress.failed_combinations) && progress.failed_combinations.length > 0 && (
            <div className="backtest-results__warning">
              <p>Incomplete data — the following combinations were skipped:</p>
              <ul>
                {(
                  progress.failed_combinations as {
                    instrument_id: string;
                    timeframe: string;
                    reason: string;
                  }[]
                ).map((failure) => (
                  <li key={`${failure.instrument_id}-${failure.timeframe}`}>
                    {failure.instrument_id} ({failure.timeframe}): {failure.reason}
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>
      )}

      {state.phase === "error" && <p className="backtest-results__warning">{state.message}</p>}
    </section>
  );
}
