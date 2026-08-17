// frontend/src/common/components/InstrumentPicker.tsx
//
// Checkpoint 63.x (follow-up): a single, reusable instrument-selection
// control, replacing free-text "type an instrument ID" inputs across the
// project. Backed ONLY by real data - `getCurrentQuotes()`, the same
// "observed instruments" source `LiveMarketDataMonitor`'s universe
// checklist already uses - never an invented/hard-coded stock list.
//
// INDEX (NIFTY/SENSEX) SELECTION - HONEST DISCLOSURE: this project has
// no real NIFTY/SENSEX constituent data anywhere (confirmed by a fresh
// audit). A web search for a primary source (NSE/niftyindices.com) could
// not be fetched in this environment (image-based PDF, timed-out CSV);
// the one secondary source that WAS fetchable is demonstrably stale - it
// still lists "HDFC Ltd" as a constituent, which merged into HDFCBANK in
// July 2023 and has not existed as a separate listed stock since. Rather
// than embed data known to be wrong, the index option below is shown but
// disabled, with an explicit label explaining why - never silently
// omitted (which would look like an oversight) and never filled with
// unverified data (which would be a fabrication).
import { useEffect, useState } from "react";

import { getCurrentQuotes } from "../api/marketDataApi";
import type { QuoteResponse } from "../api/marketDataApi";

export type ExchangeFilter = "ALL" | "NSE" | "BSE";

function useObservedInstruments(): { instruments: string[]; loading: boolean; error: string | null } {
  const [quotes, setQuotes] = useState<QuoteResponse[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    getCurrentQuotes()
      .then((result) => {
        if (!cancelled) setQuotes(result);
      })
      .catch(() => {
        if (!cancelled) setError("Unable to load the observed instrument list.");
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const instruments = Array.from(
    new Set((quotes ?? []).map((q) => `${q.exchange}:${q.symbol}`)),
  ).sort();

  return { instruments, loading: quotes === null && error === null, error };
}

function filterByExchange(instruments: string[], exchange: ExchangeFilter): string[] {
  if (exchange === "ALL") return instruments;
  return instruments.filter((id) => id.startsWith(`${exchange}:`));
}

/** The "pick an index" affordance every instrument picker on this page
 * shows, disabled, with the honest reason why - see module docstring. */
function IndexUnavailableNotice(): JSX.Element {
  return (
    <p className="strategy-config-page__help-text">
      <strong className="badge badge--pending">INDEX SELECTION UNAVAILABLE</strong> — NIFTY/SENSEX
      constituent selection is not offered: this platform has no verified, current index-membership
      data source. Pick from observed instruments below instead.
    </p>
  );
}

export interface InstrumentPickerSingleProps {
  value: string;
  onChange: (instrumentId: string) => void;
  label?: string;
  id: string;
  /** Fixed, always-available options shown alongside real observed
   * instruments - e.g. the deterministic `NSE:FIXTURE01` synthetic
   * fixture the single-instrument backtest fixture flow depends on,
   * which will never appear in live-observed quotes. Still a pick,
   * never free text - just a known-in-advance option instead of an
   * empty-until-observed one. */
  extraOptions?: string[];
}

/** A single-instrument picker (e.g. the Workbench's single-instrument
 * Run Backtest form) - a real <select> over observed instruments, never
 * a free-text field. */
export function InstrumentPickerSingle(props: InstrumentPickerSingleProps): JSX.Element {
  const { instruments, loading, error } = useObservedInstruments();
  const [exchange, setExchange] = useState<ExchangeFilter>("ALL");
  const combined = Array.from(new Set([...(props.extraOptions ?? []), ...instruments])).sort();
  const filtered = filterByExchange(combined, exchange);

  return (
    <div className="instrument-picker">
      <div className="instrument-picker__row">
        <label htmlFor={`${props.id}-exchange`}>Exchange</label>
        <select
          id={`${props.id}-exchange`}
          value={exchange}
          onChange={(e) => setExchange(e.target.value as ExchangeFilter)}
        >
          <option value="ALL">All Exchanges</option>
          <option value="NSE">NSE</option>
          <option value="BSE">BSE</option>
        </select>
      </div>
      <IndexUnavailableNotice />
      <label htmlFor={props.id}>{props.label ?? "Instrument"}</label>
      {loading && <p className="strategy-config-page__help-text">Loading observed instruments…</p>}
      {error && <p className="strategy-config-page__help-text">{error}</p>}
      {!loading && !error && filtered.length === 0 && (
        <p className="strategy-config-page__help-text">
          No observed instruments yet — the market-data pipeline has not recorded a quote for any
          instrument. Nothing can be selected until at least one instrument has been observed.
        </p>
      )}
      {!loading && filtered.length > 0 && (
        <select id={props.id} value={props.value} onChange={(e) => props.onChange(e.target.value)}>
          <option value="" disabled>
            Select an instrument…
          </option>
          {filtered.map((instrumentId) => (
            <option key={instrumentId} value={instrumentId}>
              {instrumentId}
            </option>
          ))}
        </select>
      )}
    </div>
  );
}

export interface InstrumentPickerMultiProps {
  value: string[];
  onChange: (instrumentIds: string[]) => void;
  label?: string;
  idPrefix: string;
}

/** A multi-instrument picker (e.g. the DB-first historical run's
 * universe, or a watchlist) - real checkboxes over observed instruments,
 * with a select-all/clear-all pair, never comma-separated free text. */
export function InstrumentPickerMulti(props: InstrumentPickerMultiProps): JSX.Element {
  const { instruments, loading, error } = useObservedInstruments();
  const [exchange, setExchange] = useState<ExchangeFilter>("ALL");
  const filtered = filterByExchange(instruments, exchange);
  const selected = new Set(props.value);

  function toggle(instrumentId: string): void {
    const next = new Set(selected);
    if (next.has(instrumentId)) next.delete(instrumentId);
    else next.add(instrumentId);
    props.onChange(Array.from(next));
  }

  return (
    <div className="instrument-picker">
      <div className="instrument-picker__row">
        <label htmlFor={`${props.idPrefix}-exchange`}>Exchange</label>
        <select
          id={`${props.idPrefix}-exchange`}
          value={exchange}
          onChange={(e) => setExchange(e.target.value as ExchangeFilter)}
        >
          <option value="ALL">All Exchanges</option>
          <option value="NSE">NSE</option>
          <option value="BSE">BSE</option>
        </select>
      </div>
      <IndexUnavailableNotice />
      <p>{props.label ?? "Universe"}</p>
      {loading && <p className="strategy-config-page__help-text">Loading observed instruments…</p>}
      {error && <p className="strategy-config-page__help-text">{error}</p>}
      {!loading && !error && filtered.length === 0 && (
        <p className="strategy-config-page__help-text">
          No observed instruments yet — the market-data pipeline has not recorded a quote for any
          instrument. Nothing can be selected until at least one instrument has been observed.
        </p>
      )}
      {!loading && filtered.length > 0 && (
        <>
          <div className="instrument-picker__actions">
            <button type="button" onClick={() => props.onChange(filtered)}>
              Select All
            </button>
            <button type="button" onClick={() => props.onChange([])}>
              Clear
            </button>
          </div>
          <ul className="instrument-picker__checklist">
            {filtered.map((instrumentId) => (
              <li key={instrumentId}>
                <label>
                  <input
                    type="checkbox"
                    checked={selected.has(instrumentId)}
                    onChange={() => toggle(instrumentId)}
                  />
                  {instrumentId}
                </label>
              </li>
            ))}
          </ul>
        </>
      )}
    </div>
  );
}
