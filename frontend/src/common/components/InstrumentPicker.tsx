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
// Shows ONLY the company name (never a bare/parenthetical instrument
// id) - the underlying instrument id is still what's actually
// submitted as the value, just not shown. Includes a real-time,
// client-side search filter (over the already-fetched exchange list -
// no network round-trip per keystroke) since an exchange can carry
// thousands of instruments.
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
import { useEffect, useMemo, useState } from "react";

import { getCurrentQuotes, listInstruments } from "../api/marketDataApi";
import { listWatchlists } from "../api/backtestingApi";
import type { WatchlistResponse } from "../api/backtestingApi";
import { Pagination, paginate } from "./Pagination";

// Checkpoint FRONTEND-DATA-TABLES: an exchange can carry ~8,558
// tradable instruments (confirmed via screenshot review) - rendering
// all of them as DOM checkboxes at once is a real scroll/performance
// burden. 100/page keeps each render small while still showing a
// substantial, useful page of results (most searches narrow this down
// well below one page anyway).
const INSTRUMENTS_PER_PAGE = 100;

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

function matchesSearch(entry: UniverseEntry, query: string): boolean {
  if (!query) return true;
  const needle = query.trim().toLowerCase();
  return (
    entry.displayName.toLowerCase().includes(needle) ||
    entry.instrumentId.toLowerCase().includes(needle)
  );
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

function SearchInput(props: {
  id: string;
  value: string;
  onChange: (query: string) => void;
  resultCount: number;
}): JSX.Element {
  return (
    <div className="instrument-picker__row">
      <label htmlFor={props.id}>Search stocks</label>
      <input
        id={props.id}
        type="text"
        placeholder="Type a company name or symbol…"
        value={props.value}
        onChange={(e) => props.onChange(e.target.value)}
      />
      <span className="instrument-picker__result-count">
        {props.resultCount} match{props.resultCount === 1 ? "" : "es"}
      </span>
    </div>
  );
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
 * Run Backtest form) - a real <select>, filterable by a live search
 * box, over real instruments shown by company name only, never a
 * free-text field. */
export function InstrumentPickerSingle(props: InstrumentPickerSingleProps): JSX.Element {
  const [exchange, setExchange] = useState<ExchangeFilter>("ALL");
  const [query, setQuery] = useState("");
  const { entries, loading, error } = useInstrumentUniverse(exchange);

  const combined = useMemo(() => {
    const byId = new Map(entries.map((e) => [e.instrumentId, e]));
    for (const extra of props.extraOptions ?? []) {
      if (!byId.has(extra)) byId.set(extra, { instrumentId: extra, displayName: extra });
    }
    return Array.from(byId.values()).sort((a, b) => a.displayName.localeCompare(b.displayName));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [entries]);

  const filtered = useMemo(() => combined.filter((e) => matchesSearch(e, query)), [combined, query]);

  return (
    <div className="instrument-picker">
      <ExchangeSelect id={`${props.id}-exchange`} value={exchange} onChange={setExchange} />
      <IndexUnavailableNotice />
      {!loading && combined.length > 0 && (
        <SearchInput
          id={`${props.id}-search`}
          value={query}
          onChange={setQuery}
          resultCount={filtered.length}
        />
      )}
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
          {filtered.map((entry) => (
            <option key={entry.instrumentId} value={entry.instrumentId}>
              {entry.displayName}
            </option>
          ))}
        </select>
      )}
    </div>
  );
}

/** CHECKPOINT-FRONTEND-8: a "load from watchlist" convenience, added
 * ONCE here (the one shared `InstrumentPickerMulti`) so every real
 * consumer (Backtesting, the Watchlists page's own create/edit form,
 * the Screener, the Live Scanner's own SELECTED-mode universe,
 * Settings' Historical Market Data fetch) gets it automatically -
 * never patched per-page. Reuses the existing `listWatchlists()` read
 * endpoint (`WatchlistService`/`DjangoWatchlistRepository` - the SAME
 * mechanism `CHECKPOINT-WATCHLIST-A/B` built), no new backend call.
 *
 * ADDITIVE, not a destructive replace: "Load" unions the chosen
 * watchlist's own instrument_ids into the CURRENT selection (a
 * `Set`, so already-selected/duplicate instruments are a no-op, never
 * a duplicate entry) - deliberately, so an operator can combine a
 * saved watchlist with a few extra manual picks in the same session,
 * never lose picks they already made by loading a watchlist. Not
 * offered on `InstrumentPickerSingle` - "load a watchlist's
 * instruments" has no sensible meaning for a picker that can only
 * ever hold one instrument. */
function WatchlistLoader(props: {
  idPrefix: string;
  currentValue: string[];
  onLoad: (instrumentIds: string[]) => void;
}): JSX.Element | null {
  const [watchlists, setWatchlists] = useState<WatchlistResponse[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [selectedName, setSelectedName] = useState("");

  useEffect(() => {
    let cancelled = false;
    async function load(): Promise<void> {
      try {
        const result = await listWatchlists();
        if (!cancelled) setWatchlists(result);
      } catch {
        if (!cancelled) setError("Unable to load your saved watchlists.");
      }
    }
    void load();
    return () => {
      cancelled = true;
    };
  }, []);

  if (error) {
    return <p className="strategy-config-page__help-text">{error}</p>;
  }
  if (watchlists === null) {
    return <p className="strategy-config-page__help-text">Loading saved watchlists…</p>;
  }
  if (watchlists.length === 0) {
    return null; // No watchlists saved yet - nothing honest to offer here.
  }

  function handleLoad(): void {
    const watchlist = watchlists?.find((w) => w.name === selectedName);
    if (!watchlist) return;
    const merged = new Set([...props.currentValue, ...watchlist.instrument_ids]);
    props.onLoad(Array.from(merged));
  }

  return (
    <div className="instrument-picker__row instrument-picker__watchlist-loader">
      <label htmlFor={`${props.idPrefix}-watchlist`}>Load from watchlist</label>
      <select
        id={`${props.idPrefix}-watchlist`}
        value={selectedName}
        onChange={(e) => setSelectedName(e.target.value)}
      >
        <option value="">Select a saved watchlist…</option>
        {watchlists.map((w) => (
          <option key={w.name} value={w.name}>
            {w.name} ({w.instrument_ids.length})
          </option>
        ))}
      </select>
      <button type="button" disabled={!selectedName} onClick={handleLoad}>
        Add to selection
      </button>
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
 * universe, or a watchlist) - real checkboxes, filterable by a live
 * search box, over real instruments shown by company name only, with a
 * select-all/clear-all pair, never comma-separated free text.
 * "Select All" selects every CURRENTLY VISIBLE (i.e. matching the
 * active search) instrument - every instrument on the exchange when
 * there's no search query. */
export function InstrumentPickerMulti(props: InstrumentPickerMultiProps): JSX.Element {
  const [exchange, setExchange] = useState<ExchangeFilter>("ALL");
  const [query, setQuery] = useState("");
  const [page, setPage] = useState(1);
  const { entries, loading, error, isFullExchangeList } = useInstrumentUniverse(exchange);
  const filtered = useMemo(() => entries.filter((e) => matchesSearch(e, query)), [entries, query]);
  const { pageItems, totalPages, currentPage } = paginate(filtered, page, INSTRUMENTS_PER_PAGE);
  const selected = new Set(props.value);

  function updateQuery(next: string): void {
    setQuery(next);
    setPage(1);
  }

  function updateExchange(next: ExchangeFilter): void {
    setExchange(next);
    setPage(1);
  }

  function toggle(instrumentId: string): void {
    const next = new Set(selected);
    if (next.has(instrumentId)) next.delete(instrumentId);
    else next.add(instrumentId);
    props.onChange(Array.from(next));
  }

  return (
    <div className="instrument-picker">
      <ExchangeSelect id={`${props.idPrefix}-exchange`} value={exchange} onChange={updateExchange} />
      <WatchlistLoader
        idPrefix={props.idPrefix}
        currentValue={props.value}
        onLoad={props.onChange}
      />
      <IndexUnavailableNotice />
      {!loading && entries.length > 0 && (
        <SearchInput
          id={`${props.idPrefix}-search`}
          value={query}
          onChange={updateQuery}
          resultCount={filtered.length}
        />
      )}
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
            <button type="button" onClick={() => props.onChange(filtered.map((e) => e.instrumentId))}>
              Select All{query ? " (Matching)" : ""}
              {/* Checkpoint FRONTEND-DATA-TABLES: "Select All" still
                  selects every filtered instrument across ALL pages,
                  not just the page currently visible - unchanged
                  behavior, called out explicitly below so pagination
                  never makes this button look narrower than it is. */}
            </button>
            <button type="button" onClick={() => props.onChange([])}>
              Clear
            </button>
          </div>
          {totalPages > 1 && (
            <p className="strategy-config-page__help-text">
              Showing {pageItems.length} of {filtered.length} instruments on this page — "Select
              All" still applies to all {filtered.length}, not just this page.
            </p>
          )}
          <ul className="instrument-picker__checklist">
            {pageItems.map((entry) => (
              <li key={entry.instrumentId}>
                <label>
                  <input
                    type="checkbox"
                    checked={selected.has(entry.instrumentId)}
                    onChange={() => toggle(entry.instrumentId)}
                  />
                  {entry.displayName}
                </label>
              </li>
            ))}
          </ul>
          <Pagination
            page={currentPage}
            totalPages={totalPages}
            onChange={setPage}
            totalItems={filtered.length}
            itemLabel="instrument"
          />
        </>
      )}
    </div>
  );
}
