// frontend/src/features/backtesting/WatchlistPage.tsx
//
// Checkpoint 27 Part 19: lightweight, research-only named instrument
// lists. No quantity/side/order control exists anywhere on this page.
//
// CHECKPOINT-WATCHLIST-B, Phase B of WATCHLIST_REDESIGN_ROADMAP.md:
// each saved watchlist now renders a real price/change%/volume/
// sparkline table (CHECKPOINT-WATCHLIST-A's own
// `GET .../market-data/` endpoint) instead of a plain comma-separated
// instrument-id string. Reuses ScreenerPage.tsx's own established mode
// badge convention (`.badge--historical`/`.badge--active`) rather than
// inventing a new visual language - "Historical mode" is the always-
// available default (no live infrastructure required), "Live mode"
// only when the endpoint's own envelope reports it.
import { useEffect, useState } from "react";

import { ApiNetworkError, ApiRequestError } from "../../common/api/client";
import { ErrorState } from "../../common/components/ErrorState";
import { InstrumentPickerMulti } from "../../common/components/InstrumentPicker";
import { LoadingState } from "../../common/components/LoadingState";
import { Sparkline } from "../../common/components/Sparkline";
import {
  deleteWatchlist,
  getWatchlistMarketData,
  listWatchlists,
  saveWatchlist,
} from "../../common/api/backtestingApi";
import type {
  WatchlistInstrumentMarketData,
  WatchlistMarketDataResponse,
  WatchlistResponse,
} from "../../common/api/backtestingApi";

function describeError(error: unknown): string {
  if (error instanceof ApiRequestError || error instanceof ApiNetworkError) {
    return error.message;
  }
  return "An unexpected error occurred.";
}

function formatDecimal(value: string | null | undefined, fractionDigits = 2): string | null {
  if (value === null || value === undefined) return null;
  const parsed = Number.parseFloat(value);
  if (!Number.isFinite(parsed)) return null;
  return parsed.toFixed(fractionDigits);
}

function volumeBasisLabel(
  basis: WatchlistInstrumentMarketData["volume_basis"],
): string {
  if (basis === "SESSION_TO_DATE") return "session-to-date";
  if (basis === "HISTORICAL_DAY") return "full day";
  return "";
}

/** One instrument's row - honest about every field per
 * WATCHLIST_REDESIGN_ROADMAP.md's own "no invented fields, no
 * fabricated/silently-stale price" rule. A `NOT_GATE_VERIFIED`
 * instrument shows a plain badge (reusing ScreenerPage.tsx's own
 * "Not verified" convention) in place of the sparkline, never a
 * blank cell pretending nothing is wrong. */
function InstrumentRow({
  row,
  envelopeMode,
}: {
  row: WatchlistInstrumentMarketData;
  envelopeMode: string;
}): JSX.Element {
  const price = formatDecimal(row.price, 4);
  const change = formatDecimal(row.change_percent, 2);
  const volume = formatDecimal(row.volume, 0);
  const changeClass =
    change === null
      ? ""
      : Number.parseFloat(change) >= 0
        ? "watchlist-page__change--positive"
        : "watchlist-page__change--negative";
  // A row can fall back to the historical price even while the
  // envelope is genuinely LIVE (no fresh quote for this one symbol) -
  // said plainly rather than left implicit, per the roadmap's own
  // "must work with zero live infrastructure" reasoning.
  const showHistoricalFallbackNote = envelopeMode === "LIVE" && row.price_source === "HISTORICAL";

  return (
    <tr>
      <td>{row.instrument_id}</td>
      <td>
        {price === null ? (
          "—"
        ) : (
          <>
            ₹{price}
            {showHistoricalFallbackNote && (
              <span className="watchlist-page__price-note">last close (no live quote)</span>
            )}
          </>
        )}
      </td>
      <td className={changeClass}>{change === null ? "—" : `${change}%`}</td>
      <td>
        {volume === null ? (
          "—"
        ) : (
          <>
            {volume}
            {row.volume_basis && (
              <span className="watchlist-page__cell-muted"> ({volumeBasisLabel(row.volume_basis)})</span>
            )}
          </>
        )}
      </td>
      <td>
        {row.gate_status === "NOT_GATE_VERIFIED" ? (
          <span className="badge badge--pending" title={row.coverage_detail}>
            Not verified
          </span>
        ) : (
          <Sparkline closes={row.sparkline ?? []} />
        )}
      </td>
      <td className="watchlist-page__cell-muted">
        {row.as_of}
        {row.is_stale && (
          <span className="badge badge--pending badge--inline">Stale</span>
        )}
      </td>
    </tr>
  );
}

/** Loads and renders ONE watchlist's own market-data table - a
 * separate component so each watchlist fetches independently and a
 * failure on one never blocks the others. */
function WatchlistMarketDataSection({ name }: { name: string }): JSX.Element {
  const [data, setData] = useState<WatchlistMarketDataResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    async function load(): Promise<void> {
      try {
        const response = await getWatchlistMarketData(name);
        if (!cancelled) setData(response);
      } catch (err) {
        if (!cancelled) setError(describeError(err));
      }
    }
    void load();
    return () => {
      cancelled = true;
    };
  }, [name]);

  if (error) return <ErrorState message={error} />;
  if (!data) return <LoadingState label={`Loading market data for ${name}…`} />;

  const modeBadgeClass = data.mode === "LIVE" ? "badge badge--active" : "badge badge--historical";
  const modeLabel = data.mode === "LIVE" ? "Live mode" : "Historical mode";

  if (data.results.length === 0) {
    return <p>No instruments in this watchlist yet.</p>;
  }

  return (
    <>
      <span className={`${modeBadgeClass} badge--inline`}>{modeLabel}</span>
      <div className="table-scroll">
        <table className="market-data-monitor__table">
          <thead>
            <tr>
              <th scope="col">Symbol</th>
              <th scope="col">Price</th>
              <th scope="col">Change %</th>
              <th scope="col">Volume</th>
              <th scope="col">Sparkline</th>
              <th scope="col">As of</th>
            </tr>
          </thead>
          <tbody>
            {data.results.map((row) => (
              <InstrumentRow key={row.instrument_id} row={row} envelopeMode={data.mode} />
            ))}
          </tbody>
        </table>
      </div>
    </>
  );
}

export function WatchlistPage(): JSX.Element {
  const [watchlists, setWatchlists] = useState<WatchlistResponse[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [name, setName] = useState("");
  const [instruments, setInstruments] = useState<string[]>([]);
  // CHECKPOINT-FRONTEND-5 Issue 3: which existing watchlist (by name) is
  // being edited, or `null` for the ordinary "create new" form. `save()`/
  // `WatchlistService.save()` (confirmed directly) is already an UPSERT
  // keyed by `(owner, name)`, so editing an existing watchlist's own
  // instrument list reuses the exact same `saveWatchlist` call as
  // creating one - no new backend endpoint was needed. Rename is
  // deliberately OUT OF SCOPE for this checkpoint (a separate concern -
  // there is no atomic rename operation, only upsert-by-name), so the
  // name field is locked while editing.
  const [editingName, setEditingName] = useState<string | null>(null);

  async function reload(): Promise<void> {
    try {
      setWatchlists(await listWatchlists());
    } catch (err) {
      setError(describeError(err));
    }
  }

  useEffect(() => {
    void reload();
  }, []);

  function startEdit(watchlist: WatchlistResponse): void {
    setEditingName(watchlist.name);
    setName(watchlist.name);
    setInstruments(watchlist.instrument_ids);
  }

  function cancelEdit(): void {
    setEditingName(null);
    setName("");
    setInstruments([]);
  }

  async function handleSave(): Promise<void> {
    if (!name.trim()) return;
    try {
      await saveWatchlist({
        name: (editingName ?? name).trim(),
        instrument_ids: instruments,
      });
      setName("");
      setInstruments([]);
      setEditingName(null);
      await reload();
    } catch (err) {
      setError(describeError(err));
    }
  }

  async function handleDelete(watchlistName: string): Promise<void> {
    try {
      await deleteWatchlist(watchlistName);
      if (editingName === watchlistName) cancelEdit();
      await reload();
    } catch (err) {
      setError(describeError(err));
    }
  }

  if (error) return <ErrorState message={error} />;
  if (!watchlists) return <LoadingState label="Loading watchlists…" />;

  return (
    <div className="watchlist-page">
      <h1>Research Watchlists</h1>
      <p className="configuration-viewer__subtitle">
        Named instrument lists for research use - usable as a backtest universe. This is not an
        order screen.
      </p>

      <form
        onSubmit={(e) => {
          e.preventDefault();
          void handleSave();
        }}
        className="watchlist-page__form"
      >
        <h2>{editingName ? `Editing "${editingName}"` : "New watchlist"}</h2>
        <div className="strategy-config-page__field">
          <label htmlFor="watchlist-name">Watchlist name</label>
          <input
            id="watchlist-name"
            value={name}
            onChange={(e) => setName(e.target.value)}
            disabled={editingName !== null}
          />
        </div>
        <InstrumentPickerMulti
          idPrefix="watchlist-instruments"
          label="Instruments"
          value={instruments}
          onChange={setInstruments}
        />
        <div className="watchlist-page__form-actions">
          <button type="submit" disabled={!name.trim()}>
            {editingName ? "Save changes" : "Save Watchlist"}
          </button>
          {editingName && (
            <button type="button" onClick={cancelEdit}>
              Cancel
            </button>
          )}
        </div>
      </form>

      {watchlists.length === 0 ? (
        <p>No watchlists yet.</p>
      ) : (
        watchlists.map((w) => (
          <section key={w.name} className="watchlist-page__section" aria-label={`Watchlist ${w.name}`}>
            <div className="watchlist-page__section-header">
              <h2>{w.name}</h2>
              <button type="button" onClick={() => startEdit(w)}>
                Edit
              </button>
              <button type="button" onClick={() => void handleDelete(w.name)}>
                Delete
              </button>
            </div>
            {w.instrument_ids.length === 0 ? (
              <p>(empty)</p>
            ) : (
              <WatchlistMarketDataSection name={w.name} />
            )}
          </section>
        ))
      )}
    </div>
  );
}
