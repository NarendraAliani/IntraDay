# CHECKPOINT-WATCHLIST-A — Read-Only Watchlist Market-Data Endpoint

Phase A of `WATCHLIST_REDESIGN_ROADMAP.md`. Backend only, no UI change,
no new domain/application service — per the roadmap's own explicit
architecture reasoning, this is a thin view composing existing
repositories/services directly, exactly like `coverage_preview_view`'s
own established shape.

## What was built

- **`GET /api/v1/config/watchlists/<name>/market-data/`**
  ([watchlist_market_data_views.py](src/intraday/infrastructure/api/watchlist_market_data_views.py)) —
  for every instrument in the named, owner-scoped watchlist, resolves:
  - **`price`/`price_source`** — the latest gate-verified daily close
    (`"HISTORICAL"`) by default; overridden with a genuinely fresh
    `LiveQuoteObservation` (`"LIVE"`) only when both (a) the envelope
    `mode` is `"LIVE"` (a lightweight
    `WorkerRuntimeStatus.worker_state == "RUNNING"` check — NOT the
    full `evaluate_live_paper_readiness()` gate) AND (b) a quote
    genuinely exists for that specific instrument. Falls back to the
    historical row honestly, never an error, when (b) fails alone —
    the roadmap's own explicit "must work with zero live
    infrastructure" requirement, proven directly by
    `test_live_mode_with_running_worker_but_no_quote_falls_back_to_historical`.
  - **`change_percent`** — `(latest gate-verified daily close − prior
    gate-verified daily close) / prior close * 100`, "vs. previous
    close," `null` when not gate-verified or no prior trading day is
    in range.
  - **`volume`/`volume_basis`** — the latest daily-close bar's own
    volume (`"HISTORICAL_DAY"`) or, in Live mode with a fresh quote, a
    best-effort sum of today's `AggregatedBarObservation` volumes for
    that instrument (`"SESSION_TO_DATE"`) — the two are always labeled
    distinctly, never conflated, per the roadmap's own explicit rule.
  - **`sparkline`** — the last 5 gate-verified trading-day closes,
    oldest first, Historical data only even when the envelope is
    `"LIVE"` (the roadmap's own explicit scope limit).
  - **`gate_status`/`coverage_detail`** — an instrument whose daily-bar
    range isn't gate-verified reports `"NOT_GATE_VERIFIED"` with the
    real `ResearchDataRejectedError` reason/detail, reusing
    `CHECKPOINT-SCANNER-B`'s own `screening_views.py` honesty pattern
    verbatim — never a fabricated or silently-stale price.
- **`application/contracts/watchlist_market_data.py`** — the wire
  contract (`WatchlistMarketDataResponseSerializer`/
  `WatchlistInstrumentMarketDataSerializer`).
- URL registered at
  [urls.py:340-345](src/intraday/infrastructure/api/urls.py#L340-L345).
- OpenAPI schema + `frontend/shared/generated_contracts/api-types.ts`
  regenerated (`npm run generate:api`) — clean, zero warnings.

## A real, direct finding this checkpoint made (not assumed)

`Timeframe.DAY` is **not usable** with `HistoricalDataCoverageService`/
`ResearchDataGateService` for a CAS-aware continuous-trading
instrument (RELIANCE/TCS/HDFCBANK/INFY): a 1-day bar duration never
fits inside `continuous_trading_open -> continuous_trading_close`, so
`expected_continuous_bar_timestamps()` always returns an empty tuple —
a `Timeframe.DAY` gate call would always reject `NO_DATA`. Confirmed
directly by reading `domain/session/contracts.py`'s own arithmetic,
not merely inferred. The endpoint instead derives each trading day's
"close" from the **last gate-verified `FIVE_MINUTE` bar of that day**
(the one granularity this project's own migration checkpoints actually
populate) — an end-of-day-chart convention, not a new data source.

## Honest, real complication confirmed (matches the roadmap's own
"honest complications" section)

`ResearchDataGateService` requires **full coverage of the entire
requested window**, not just the days a caller cares about. With this
project's real migrated coverage currently sparse (per the CHECKPOINT
83–90 migration work), a wide lookback window (`_SPARKLINE_LOOKBACK_
CALENDAR_DAYS = 21`, chosen to reliably contain 5 trading days across
weekends/holidays) will report most real instruments as
`NOT_GATE_VERIFIED` today, honestly, until more days are migrated —
this is correct, intended behavior per the project's own trusted-data
discipline, not a bug to work around.

## Testing

[tests/unit/infrastructure/api/test_watchlist_market_data_api.py](tests/unit/infrastructure/api/test_watchlist_market_data_api.py) —
real PostgreSQL, real `ResearchDataGateService`/`WorkerRuntimeStatus`
reads, `_now()` and the lookback-window constant patched per-test
(never the gate itself) to pin the window onto
`CHECKPOINT-SCANNER-B`'s own established gate-eligible fixture date
(2026-08-17). 8 tests, all passing:
- gate-verified instrument → historical price/sparkline/as-of label.
- zero-data instrument → honest `NOT_GATE_VERIFIED`.
- mixed watchlist → each instrument reported independently.
- default mode is `HISTORICAL` with no `WorkerRuntimeStatus` row at
  all (proves the "zero live infrastructure" default).
- `LIVE` mode with a running worker + a fresh quote → live
  price/session-to-date volume, sparkline/gate_status unaffected.
- `LIVE` mode with a running worker but no quote for this instrument →
  honest fallback to the historical row, envelope still `LIVE`.
- unknown watchlist → 404.
- unauthenticated → 401/403.

Full backend suite run this checkpoint: `poetry run pytest tests/unit -q`
→ **5 failed, 3411 passed**, none of them in any watchlist file, all
five matching the exact pre-existing failures already present in this
session's own pre-flight test run (before this checkpoint touched
anything): `test_checkpoint_64_52_database_first_backtest.py` (2),
`test_api_boundaries.py::test_application_services_and_contracts_stay_infrastructure_free`,
`test_checkpoint_64_48_gainz_adapter_design.py::test_k_no_gainz_reference_file_exists_in_repo`,
`test_checkpoint_64_49_gainz_feature_registry.py::test_zz_no_real_gainz_source_file_exists`
— no regression introduced by this checkpoint's work.

## RULES compliance

- No new domain/application service — the view composes
  `DjangoHistoricalBarRepository`, `DjangoAggregatedBarRepository`,
  `ResearchDataGateService`, `LiveMarketDataService`, and
  `DjangoWorkerRuntimeStatusRepository` directly.
- No UI change — Phase B's own concern, per `WATCHLIST_REDESIGN_ROADMAP.md`.
- No live session launched, no strategy code touched, no registry
  changed.

---
🤖 Generated with [Claude Code](https://claude.com/claude-code)
