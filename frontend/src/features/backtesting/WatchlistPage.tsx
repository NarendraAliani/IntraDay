// frontend/src/features/backtesting/WatchlistPage.tsx
//
// Checkpoint 27 Part 19: lightweight, research-only named instrument
// lists. No quantity/side/order control exists anywhere on this page.
import { useEffect, useState } from "react";

import { ApiNetworkError, ApiRequestError } from "../../common/api/client";
import { ErrorState } from "../../common/components/ErrorState";
import { LoadingState } from "../../common/components/LoadingState";
import { deleteWatchlist, listWatchlists, saveWatchlist } from "../../common/api/backtestingApi";
import type { WatchlistResponse } from "../../common/api/backtestingApi";

function describeError(error: unknown): string {
  if (error instanceof ApiRequestError || error instanceof ApiNetworkError) {
    return error.message;
  }
  return "An unexpected error occurred.";
}

export function WatchlistPage(): JSX.Element {
  const [watchlists, setWatchlists] = useState<WatchlistResponse[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [name, setName] = useState("");
  const [instruments, setInstruments] = useState("");

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

  async function handleSave(): Promise<void> {
    if (!name.trim()) return;
    try {
      await saveWatchlist({
        name: name.trim(),
        instrument_ids: instruments
          .split(",")
          .map((s) => s.trim())
          .filter(Boolean),
      });
      setName("");
      setInstruments("");
      await reload();
    } catch (err) {
      setError(describeError(err));
    }
  }

  async function handleDelete(watchlistName: string): Promise<void> {
    try {
      await deleteWatchlist(watchlistName);
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
        <div className="strategy-config-page__field">
          <label htmlFor="watchlist-name">Watchlist name</label>
          <input id="watchlist-name" value={name} onChange={(e) => setName(e.target.value)} />
        </div>
        <div className="strategy-config-page__field">
          <label htmlFor="watchlist-instruments">Instruments (comma-separated)</label>
          <input
            id="watchlist-instruments"
            value={instruments}
            onChange={(e) => setInstruments(e.target.value)}
            placeholder="NSE:FIXTURE01, NSE:TESTCO"
          />
        </div>
        <button type="submit" disabled={!name.trim()}>
          Save Watchlist
        </button>
      </form>

      {watchlists.length === 0 ? (
        <p>No watchlists yet.</p>
      ) : (
        <ul className="watchlist-page__list">
          {watchlists.map((w) => (
            <li key={w.name}>
              <strong>{w.name}</strong>: {w.instrument_ids.join(", ") || "(empty)"}
              <button type="button" onClick={() => void handleDelete(w.name)}>
                Delete
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
