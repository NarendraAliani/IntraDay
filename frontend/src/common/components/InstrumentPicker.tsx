// frontend/src/common/components/InstrumentPicker.tsx
//
// Checkpoint 63.x (follow-up): a single, reusable instrument-selection
// control, replacing free-text "type an instrument ID" inputs across the
// project. Backed by TWO real data sources, never an invented/hard-coded
// stock list:
//
//   - `listInstruments(exchange)` - the REAL "every tradable instrument
//     on this exchange, with its real company name" list (Dhan's
//     published scrip master), so "Select All" genuinely means all
//     stocks on the selected exchange, AND the picker shows a
//     recognizable company name ("Reliance Industries") instead of a
//     bare instrument id. This is what drives the picker whenever a
//     specific exchange is selected.
//   - `getCurrentQuotes()` - the "observed instruments" fallback (the
//     same source `LiveMarketDataMonitor`'s universe checklist already
//     uses), used only when the exchange master list could not be
//     fetched (`data_source: "UNAVAILABLE"`) - degrades honestly rather
//     than showing nothing. Observed-only entries have no real display
//     name available, so they fall back to showing their bare symbol.
//
// A REAL BUG this session found and fixed: the first version of this
// picker showed Dhan's own dummy API-testing scrips ("011NSETEST",
// "0ABCL31" bonds) instead of real stocks - traced by actually
// fetching and inspecting the live scrip-master CSV (not guessing),
// which found the one column that genuinely distinguishes a real
// tradable share (`SEM_EXCH_INSTRUMENT_TYPE == "ES"`) from test/bond
// rows that otherwise look identical. See
// infrastructure/market_data_providers/dhan/instrument_master.py for
// the full account.
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

import { getCurrentQuotes, listInstruments } from "../api/marketDataApi";

export type ExchangeFilter = "ALL" | "NSE" | "BSE";

export interface UniverseEntry {
  instrumentId: string;
  displayName: string;
}

interface UniverseState {
  entries: UniverseEntry[];
  loading: boolean;
  error: string | null;
  /** Whether the real per-exchange master list backed this result, or
   * it fell back to only observed instruments - shown to the operator
   * so "Select All" is never silently narrower than it looks. */
  isFullExchangeList: boolean;
}

function useInstrumentUniverse(exchange: ExchangeFilter): UniverseState {
  const [state, setState] = useState<UniverseState>({
    entries: [],
    loading: true,
    error: null,
    isFullExchangeList: false,
  });

  useEffect(() => {
    let cancelled = false;
    setState((prev) => ({ ...prev, loading: true, error: null }));

    async function load(): Promise<void> {
      const exchangesToFetch: ("NSE" | "BSE")[] = exchange === "ALL" ? ["NSE", "BSE"] : [exchange];
      try {
        const [masterResults, quotes] = await Promise.all([
          Promise.all(exchangesToFetch.map((ex) => listInstruments(ex))),
          getCurrentQuotes(),
        ]);
        if (cancelled) return;

        const byId = new Map<string, UniverseEntry>();
        for (const result of masterResults) {
          for (const instrument of result.instruments) {
            byId.set(instrument.instrument_id, {
              instrumentId: instrument.instrument_id,
              displayName: instrument.display_name,
            });
          }
        }
        const anyMasterAvailable = masterResults.some((r) => r.data_source === "DHAN_SCRIP_MASTER");

        for (const quote of quotes) {
          const instrumentId = `${quote.exchange}:${quote.symbol}`;
          if (exchange !== "ALL" && !instrumentId.startsWith(`${exchange}:`)) continue;
          if (!byId.has(instrumentId)) {
            // Observed but not in the master list (or master unavailable) -
            // no real company name known, so fall back to the bare symbol
            // rather than inventing one.
            byId.set(instrumentId, { instrumentId, displayName: quote.symbol });
          }
        }

        const entries = Array.from(byId.values()).sort((a, b) =>
          a.displayName.localeCompare(b.displayName),
        );
        setState({ entries, loading: false, error: null, isFullExchangeList: anyMasterAvailable });
      } catch {
        if (!cancelled) {
          setState({
            entries: [],
            loading: false,
            error: "Unable to load the instrument list.",
            isFullExchangeList: false,
          });
        }
      }
    }
    void load();
    return () => {
      cancelled = true;
    };
  }, [exchange]);

  return state;
}

/** The "pick an index" affordance every instrument picker on this page
 * shows, disabled, with the honest reason why - see module docstring. */
function IndexUnavailableNotice(): JSX.Element {
  return (
    <p className="strategy-config-page__help-text">
      <strong className="badge badge--pending">INDEX SELECTION UNAVAILABLE</strong> — NIFTY/SENSEX
      constituent selection is not offered: this platform has no verified, current index-membership
      data source. Pick from the instruments below instead.
    </p>
  );
}

function ExchangeSelect(props: {
  id: string;
  value: ExchangeFilter;
  onChange: (exchange: ExchangeFilter) => void;
}): JSX.Element {
  return (
    <div className="instrument-picker__row">
      <label htmlFor={props.id}>Exchange</label>
      <select
        id={props.id}
        value={props.value}
        onChange={(e) => props.onChange(e.target.value as ExchangeFilter)}
      >
        <option value="ALL">All Exchanges</option>
        <option value="NSE">NSE</option>
        <option value="BSE">BSE</option>
      </select>
    </div>
  );
}

function optionLabel(entry: UniverseEntry): string {
  // "Reliance Industries (NSE:RELIANCE)" - the real company name up
  // front (what the operator recognizes), the exact instrument id in
  // parentheses (what actually gets submitted) so it's never ambiguous
  // which underlying instrument a name maps to.
  return `${entry.displayName} (${entry.instrumentId})`;
}

export interface InstrumentPickerSingleProps {
  value: string;
  onChange: (instrumentId: string) => void;
  label?: string;
  id: string;
  /** Fixed, always-available options shown alongside real instruments -
   * e.g. the deterministic `NSE:FIXTURE01` synthetic fixture the
   * single-instrument backtest fixture flow depends on, which will
   * never appear in a real exchange's instrument list. Still a pick,
   * never free text - just a known-in-advance option. */
  extraOptions?: string[];
}

/** A single-instrument picker (e.g. the Workbench's single-instrument
 * Run Backtest form) - a real <select> over real instruments (shown by
 * company name), never a free-text field. */
export function InstrumentPickerSingle(props: InstrumentPickerSingleProps): JSX.Element {
  const [exchange, setExchange] = useState<ExchangeFilter>("ALL");
  const { entries, loading, error } = useInstrumentUniverse(exchange);
  const byId = new Map(entries.map((e) => [e.instrumentId, e]));
  for (const extra of props.extraOptions ?? []) {
    if (!byId.has(extra)) byId.set(extra, { instrumentId: extra, displayName: extra });
  }
  const combined = Array.from(byId.values()).sort((a, b) => a.displayName.localeCompare(b.displayName));

  return (
    <div className="instrument-picker">
      <ExchangeSelect id={`${props.id}-exchange`} value={exchange} onChange={setExchange} />
      <IndexUnavailableNotice />
      <label htmlFor={props.id}>{props.label ?? "Instrument"}</label>
      {loading && <p className="strategy-config-page__help-text">Loading instruments…</p>}
      {error && <p className="strategy-config-page__help-text">{error}</p>}
      {!loading && !error && combined.length === 0 && (
        <p className="strategy-config-page__help-text">
          No instruments available yet for this exchange.
        </p>
      )}
      {!loading && combined.length > 0 && (
        <select id={props.id} value={props.value} onChange={(e) => props.onChange(e.target.value)}>
          <option value="" disabled>
            Select a stock…
          </option>
          {combined.map((entry) => (
            <option key={entry.instrumentId} value={entry.instrumentId}>
              {optionLabel(entry)}
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
 * universe, or a watchlist) - real checkboxes over real instruments
 * (shown by company name), with a select-all/clear-all pair, never
 * comma-separated free text. "Select All" selects every instrument on
 * the chosen exchange when the real exchange master list is
 * available. */
export function InstrumentPickerMulti(props: InstrumentPickerMultiProps): JSX.Element {
  const [exchange, setExchange] = useState<ExchangeFilter>("ALL");
  const { entries, loading, error, isFullExchangeList } = useInstrumentUniverse(exchange);
  const selected = new Set(props.value);

  function toggle(instrumentId: string): void {
    const next = new Set(selected);
    if (next.has(instrumentId)) next.delete(instrumentId);
    else next.add(instrumentId);
    props.onChange(Array.from(next));
  }

  return (
    <div className="instrument-picker">
      <ExchangeSelect id={`${props.idPrefix}-exchange`} value={exchange} onChange={setExchange} />
      <IndexUnavailableNotice />
      <p>{props.label ?? "Universe"}</p>
      {loading && <p className="strategy-config-page__help-text">Loading instruments…</p>}
      {error && <p className="strategy-config-page__help-text">{error}</p>}
      {!loading && !error && entries.length === 0 && (
        <p className="strategy-config-page__help-text">No instruments available yet.</p>
      )}
      {!loading && entries.length > 0 && (
        <>
          {!isFullExchangeList && (
            <p className="strategy-config-page__help-text">
              <strong className="badge badge--pending">OBSERVED INSTRUMENTS ONLY</strong> — the full
              exchange instrument list is currently unavailable; "Select All" only selects
              instruments already observed by the market-data pipeline.
            </p>
          )}
          <div className="instrument-picker__actions">
            <button type="button" onClick={() => props.onChange(entries.map((e) => e.instrumentId))}>
              Select All
            </button>
            <button type="button" onClick={() => props.onChange([])}>
              Clear
            </button>
          </div>
          <ul className="instrument-picker__checklist">
            {entries.map((entry) => (
              <li key={entry.instrumentId}>
                <label>
                  <input
                    type="checkbox"
                    checked={selected.has(entry.instrumentId)}
                    onChange={() => toggle(entry.instrumentId)}
                  />
                  {optionLabel(entry)}
                </label>
              </li>
            ))}
          </ul>
        </>
      )}
    </div>
  );
}
