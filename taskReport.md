# Task Report

## Milestone
Real NSE session capture readiness (historical-data foundation track).

## Checkpoint
65.13 — REAL NSE SESSION CAPTURE READINESS: LIVE-DATA PREPARATION / NO STRATEGY CHANGES / NO BACKTEST CHANGES.

## Classification
OFFLINE, READ-ONLY AUDIT + DOCUMENTATION. Market was closed throughout. No live connection, no worker start, no scanner start, no notifications, no orders, no new tables, no data insertion/relabeling.

## Objective
Prepare (audit + document) the existing live market-data/archive pipeline so the *next* real NSE trading session can be captured as a genuine, auditable, COMPLETE historical session — without performing that capture now.

## 65.12 Findings Carried Forward
- `HistoricalBar.provenance` (migration `0036`) added: `REAL_DHAN` / `SYNTHETIC_TEST` / `UNKNOWN`.
- All 5,100 pre-65.12 `HistoricalBar` rows left `UNKNOWN` (not relabeled, not inferred).
- No genuine Dhan historical-candle ingestion path exists; only `SyntheticHistoricalBarProvider` is wired into `HistoricalDataPreparationService`/`backtesting_views.py`.
- 0 `MarketDataArchiveDay` cells are `COMPLETE` (as of 65.12's audit: 4 `IN_PROGRESS`, 16 `PARTIAL`).
- `is_research_eligible()` returns `True` only for `REAL_DHAN`; not wired into any backtest default path.

## Live Ingestion Architecture
Audited (read-only) end to end: `domain/market_data/archive.py` (`ArchiveStatus`, `assess_archive_day`, `TradingSessionIdentity`, `trading_date_for`), `domain/market_data/quality.py` (duplicate/out-of-order rejection, `expected_bar_timestamps`, `missing_bar_timestamps`, CAS-aware siblings), `application/services/market_data_archive.py` (`MarketDataArchiveService.refresh_trading_date`/`describe_trading_date`, worst-status day rollup), `application/services/market_data_reconciliation.py` and `..._persistence.py`, `infrastructure/persistence/live_market_data_repositories.py`, `infrastructure/persistence/management/commands/run_market_data_worker.py` (1195 lines), and the existing docs `docs/architecture/DAILY_MARKET_DATA_ARCHIVE_ARCHITECTURE.md` and `MARKET_DATA_ARCHIVE_QUERY_API.md`. No prior behavior was assumed without reading source.

## Dhan Boundary
Confirmed: Dhan connectivity lives exclusively in `infrastructure/market_data_providers/dhan/*` and is invoked only from `run_market_data_worker.py`. `MarketDataArchiveService` and `MarketDataReconciliationService` never call Dhan directly — they read persisted `LiveQuoteObservation`/`AggregatedBarObservation` rows. The only currently-wired "independent" reference fetch (`HistoricalDataPreparationService`) is itself Dhan-REST, which the existing docs already flag as *not independent* (Dhan-vs-Dhan is corroboration, not candle authority) — this is a pre-existing, already-documented limitation, not a new finding.

## Observation Flow
Confirmed path: Dhan WebSocket quote → `LiveQuoteObservation` (append-only, stamped with `trading_date_for()` at the single write boundary) → `aggregate_quotes_into_bars` → `AggregatedBarObservation` (upsert by `(symbol, timeframe, interval_start)`) → `MarketDataArchiveService.refresh_trading_date()` reads both tables → `assess_archive_day()` (pure domain function) → `ArchiveDayAssessment` → upserted into `MarketDataArchiveDay` (a recomputable projection, not a second source of truth).

## Aggregation
One-minute bucket boundaries anchor at the UTC epoch (09:15 IST = 03:45 UTC = offset 225 minutes); `domain/market_data/archive.py::_minutes_supported` verifies a timeframe's duration tiles the session window without straddling an edge. 1m/3m/5m/15m are supported; 30m/1h/DAY/TICK are explicitly unsupported (never silently mis-measured). `quality.py` rejects duplicate and out-of-order bars as input rather than silently reordering/dropping.

## Archive Status
Five-value vocabulary confirmed unchanged: `NOT_OBSERVED`, `IN_PROGRESS`, `PARTIAL`, `COMPLETE`, `FAILED`. Decision order in `assess_archive_day` (non-trading day → failed-ingestion → no-data → session-not-closed → unsupported-timeframe → missing-bars → COMPLETE) read in full; no loosening proposed or made.

## Target Next Session
1–3 liquid NSE cash-equity symbols already present in the operator's configured watchlist (the worker resolves its subscription set from `DjangoWatchlistRepository` — no hardcoded symbol list in code), one full 09:15–15:30 IST session. This is the smallest run that exercises every already-built, already-tested mechanism without added load or scope creep into options/index/sector.

## Symbols
1–3 liquid NSE cash-equity symbols (exact tickers to be chosen by the operator from the existing watchlist at go-ahead time — not fixed in this checkpoint, since the market is closed and no watchlist read was needed to audit the mechanism).

## Timeframe
`ONE_MINUTE` only — completeness-supported, and the finest granularity the archive already proves against.

## Session Window
09:15–15:30 IST continuous session (or 09:15–15:15 IST continuous window for a CATEGORY_I_CAS symbol, via `CasAwareSession`/`is_continuous_completeness_supported` — the CAS-aware sibling, not the plain 375-minute path).

## Session Boundary
Uses the existing, validated `domain/session/calendar.py` (weekend/holiday-aware `is_trading_day`, `market_open`/`market_close`) — no new exchange-rule logic invented. Verified `IN_PROGRESS` can never become `COMPLETE`/`PARTIAL` while `as_of < continuous_closed_at`.

## CAS Handling
`CasAwareSession`, `classify_cas_window_status`, `is_continuous_completeness_supported`, and the CAS-window-status field on `ArchiveDayAssessment` were read. Completeness for a CATEGORY_I_CAS instrument is correctly assessed against its 09:15–15:15 continuous window, not the 375-minute plain window — confirmed by the passing `test_checkpoint_64_88_cas_aware_quality.py` suite. **No CAS defect was found in this audit.** No CAS semantics were modified.

## Completeness
`COMPLETE` requires: trading day, session closed (continuous close, CAS-aware where applicable), timeframe completeness-supported, and the set difference between expected and observed closed-bar-close timestamps is empty. The gate was read, not weakened, not modified.

## Gap Detection
`missing_bar_timestamps()` (and the CAS-aware sibling) computes exact missing bar-close instants against `expected_bar_timestamps()`; `ArchiveDayAssessment.missing_bar_count`/`missing_bar_timestamps` expose them per cell. No auto-fill, no interpolation, no fabrication anywhere in the read path.

## Duplicate Detection
`quality.py`'s bar-sequence validator rejects a duplicate bar timestamp as an input error rather than silently dropping/reordering it; `assess_archive_day` separately records `duplicate_bar_timestamps` (deduplicated) and explicitly does not double-count duplicates toward `closed_bar_count` coverage.

## Timestamp Integrity
Quotes are stamped from `Quote.timestamp` (source instant), never `fetched_at` (local receive clock); bars are stamped from `interval_end`. `trading_date_for()` uses `instant.astimezone(Asia/Kolkata).date()`, not a naive `.date()` — this is the single canonical derivation, asserted by test, and is the fix that prevents the entire 09:15–11:00 IST opening range from being misfiled under the previous UTC day.

## Recovery
`LiveQuoteObservation`/`AggregatedBarObservation` writes are append-only/per-observation, so a worker restart mid-session does not lose already-persisted data. `MarketDataArchiveDay` is a pure, recomputable projection (§5 of the architecture doc) — refreshing after a restart reproduces the correct state from whatever was genuinely observed. `WorkerRuntimeStatus` (Checkpoint 22/64.63, `worker_stop_request.py`) provides the existing process-independent stop/restart-state mechanism. No new distributed scheduler or infrastructure was built or is proposed.

## Reconciliation
`MarketDataReconciliationService` (64.79) computes; `MarketDataReconciliationPersistenceService` (64.84) persists — five columns on the archive cell (`reconciliation_status`, `reconciliation_outcome`, `reconciliation_reason`, `reconciliation_evidence_source`, `reconciled_at`). A refresh never overwrites reconciliation columns, so recomputing the archive from its own observations can never self-promote to "reconciled." The only wired reference fetch is Dhan-REST (not independent) — this is a pre-existing, already-documented gap, unchanged by 65.13. No reconciliation was executed in 65.13 (no session to reconcile).

## Provenance
Verified but not exercised: no `REAL_DHAN` row exists or was created. `is_research_eligible()` unchanged. No relabeling performed.

## REAL_DHAN Path
Confirmed the *intended* future path: COMPLETE `MarketDataArchiveDay` cell → (future checkpoint) archive-to-`HistoricalBar` projector or a genuine Dhan-historical-candle-backed `HistoricalBarProvider` → stamps `PROVENANCE_REAL_DHAN`. This projector does not exist yet and was **not built** in 65.13 (explicitly out of scope, Part K).

## UNKNOWN Handling
Unchanged. All pre-65.12 rows remain `UNKNOWN`; no inference or backfill was performed.

## SYNTHETIC Handling
Unchanged. `SyntheticHistoricalBarProvider` remains the only wired `HistoricalBarProvider`, honestly labelled `SYNTHETIC_TEST`.

## HistoricalBar Projection Status
No archive→HistoricalBar projection exists. This remains a named future checkpoint, not built or scaffolded in 65.13.

## Backtest Relationship
Confirmed and preserved: Dhan live ingestion → archive → (future) verified historical repository → backtest, never backtest → Dhan live API. `BacktestingService`, `HistoricalMarketDataService`, `run_backtest`, `TradePlan`, `OrderIntent`, `RiskDecision`, execution, accounting — **not touched**.

## Market Context Relationship
`price_vs_ma_pct`, `rebound_candidate`, `ma_divergence`, `market_regime` — **not touched** in this checkpoint (these files show as modified/untracked in `git status` only because they are carried-forward uncommitted work from 65.03–65.11, prior to this checkpoint's session — see Git Safety below).

## Gainz Relationship
Gainz reference/adapter/Alpha/profiles/scoring/consensus — **not touched** in this checkpoint.

## Database Changes
None made or proposed in 65.13. No new table, no migration executed, no data inserted, no data relabeled.

## API Changes
None.

## Frontend Changes
None.

## Tests

## Testing Level
REDUCED, TARGETED ONLY — no full regression run, per Part R.

## Tests Run
```
tests/unit/domain/test_market_data_quality.py
tests/unit/domain/test_checkpoint_64_88_cas_aware_quality.py
tests/unit/domain/test_market_data_aggregation.py
tests/unit/research/test_checkpoint_64_73_market_data_archive.py
tests/unit/research/test_checkpoint_64_75_observation_provenance.py
tests/unit/research/test_checkpoint_64_79_equity_reconciliation.py
tests/unit/research/test_checkpoint_64_79_reconciliation_service.py
tests/unit/research/test_checkpoint_64_84_reconciliation_persistence.py
tests/unit/research/test_checkpoint_65_12_provenance.py
tests/unit/infrastructure/persistence/test_market_data_archive_repository.py
tests/unit/infrastructure/persistence/test_checkpoint_64_84_reconciliation_persistence_db.py
tests/unit/infrastructure/persistence/test_checkpoint_64_92_archive_observability_and_lineage.py
tests/unit/infrastructure/api/test_checkpoint_64_83_archive_api.py
tests/unit/infrastructure/api/test_checkpoint_64_84_archive_reconciliation_fields.py
```
Result: **207 passed, 0 failed**, 1 unrelated deprecation warning (schemathesis/jsonschema library warning, not project code).

## Tests Skipped
Full platform regression — not run, per Part R (no production source file was changed in 65.13, so there is no shared-contract change requiring it). Strategy/Gainz/MarketContext/backtest/frontend test suites — out of scope, not run.

## Escalation Decision
No escalation required. No defect found that would require deviating from the directive's constraints (see CAS Handling / Completeness above — none found). No tiny migration was needed (none proposed).

## Gainz Status
Unchanged from 65.12.

## NSE_FNO Status
Not implemented. Unchanged.

## BacktestTrustLevel
Unchanged; untouched by 65.13.

## Research Readiness
Still **NO** — unchanged. This checkpoint adds no new evidence toward the 5-criterion gate; it only prepares the capture path.

## Next-Session Capture Checklist
1. Confirm trading day via `domain.session.calendar.is_trading_day`.
2. Start `run_market_data_worker` (Dhan provider) scoped to 1–3 chosen watchlist symbols only.
3. Let it run untouched 09:15–15:30 IST; monitor `WorkerRuntimeStatus` only.
4. At/after session close, run `market_data_archive --date <date> --refresh` for those symbols and `ONE_MINUTE`.
5. Read back `describe_trading_date()`; record `ArchiveStatus` per cell.
6. Record reconciliation outcome (expect `NOT_RECONCILED` unless an independent source is separately fetched).
7. Do not proceed to any archive→HistoricalBar projection or REAL_DHAN stamping in that same session — that is a future checkpoint.

## Remaining Gaps
- No genuine Dhan-historical-candle-backed `HistoricalBarProvider` exists (carried forward from 65.12).
- No archive-to-HistoricalBar projection path exists.
- No independent (non-Dhan) reconciliation reference source exists — `TRADING_GRADE_BAR` condition 3 remains unmet.
- 0 `MarketDataArchiveDay` cells are currently `COMPLETE` (unchanged by 65.13 — no capture was performed).

## Blockers
Same root blocker as 65.12: no genuine independent historical-candle source, and no capture has yet been run end-to-end across one full real NSE session. 65.13 removes zero blockers by design (audit/readiness only); it prepares the procedure to remove the "no full session ever captured" blocker at the next market open.

## Next Product Milestone
Execute the rehearsed procedure above at the next real NSE market open (explicit human go-ahead required), producing the first genuinely `COMPLETE` `MarketDataArchiveDay` cell for 1–3 symbols. That is the concrete prerequisite for the archive→HistoricalBar/REAL_DHAN projection checkpoint that follows.

## Performance Ranking
(65.12 → 65.13)
- Capture Readiness: improved (procedure now explicit and documented; was implicit before)
- Session Integrity: unchanged (mechanisms already sound, re-verified)
- Completeness: unchanged (gate re-verified, not weakened)
- Provenance: unchanged (no rows touched)
- Dhan Boundary: unchanged, re-confirmed clean
- Archive Reliability: unchanged (re-verified via passing targeted tests)
- Recovery: unchanged (existing mechanism documented, not extended)
- Reconciliation: unchanged
- Testing: unchanged in scope (207 targeted tests, all passing, same reduced-testing discipline as 65.12)
- Performance: N/A — no runtime code changed
- Maintainability: slightly improved (capture procedure now written down, reducing future improvisation risk)
- Safety: unchanged — no live call, no data mutation, no code touched

## Final Product Gate

A. Is the existing live-ingestion path completely understood? **YES** — audited end to end (Dhan provider → `LiveQuoteObservation`/`AggregatedBarObservation` → `MarketDataArchiveService` → `MarketDataArchiveDay`).

B. Is the next-session capture target explicitly defined? **YES** — 1–3 liquid NSE cash-equity symbols from the existing watchlist, `ONE_MINUTE`, 09:15–15:30 IST.

C. Is the target limited to a small initial symbol set? **YES** — 1–3 symbols, not the full NSE universe.

D. Is one-minute aggregation understood and validated? **YES** — bucket-alignment logic read; existing aggregation/quality tests re-run and passing.

E. Are 09:15–15:30 session boundaries explicit? **YES** — via the existing `domain/session/calendar.py`, reused unmodified (with the CAS-aware 09:15–15:15 sibling for CATEGORY_I_CAS symbols).

F. Is CAS handling preserved? **YES** — read, not modified; no defect found.

G. Is COMPLETE defined and not weakened? **YES** — completeness gate read verbatim from `assess_archive_day`; nothing loosened.

H. Can gaps and duplicates be detected? **YES** — `missing_bar_timestamps`/`duplicate_bar_timestamps`, confirmed by passing tests.

I. Can forming sessions remain IN_PROGRESS? **YES** — `as_of < continuous_closed_at` guard confirmed; can never be COMPLETE/PARTIAL while forming.

J. Can a future complete session produce REAL_DHAN provenance? **YES, in principle, via a projector that does not yet exist** — the mechanism (`HistoricalBarProvider.provenance` attribute, `is_research_eligible`) is in place from 65.12; the actual Dhan-historical-candle-backed provider/projector is a future checkpoint, not built here.

K. Is Dhan kept outside the backtest execution layer? **YES** — confirmed unchanged; `BacktestingService` etc. not touched, no Dhan call added to that layer.

L. Was any live Dhan call made during this checkpoint? **NO**

M. Was the live worker started? **NO**

N. Was the scanner started? **NO**

O. Were notifications sent? **NO**

P. Were orders placed? **NO**

Q. Was existing historical data deleted? **NO**

R. Was existing historical data relabeled? **NO**

S. Was synthetic data generated? **NO**

T. Was synthetic data inserted into the database? **NO**

U. Was REAL_DHAN assigned to any existing row? **NO**

V. Was Gainz modified? **NO**

W. Was Market Context modified? **NO**

X. Was Backtest modified? **NO**

Y. Was Scanner modified? **NO**

Z. Was NSE_FNO modified? **NO**

AA. Was frontend modified? **NO**

AB. Was a new table created? **NO**

AC. Was full regression run? **NO** — reduced, targeted tests only (207 passed).

AD. What exact commands/procedures should be executed at the next NSE market open? Confirm trading day → start `run_market_data_worker` (Dhan provider) scoped to the 1–3 chosen watchlist symbols → let it run untouched 09:15–15:30 IST → at/after close run `python manage.py market_data_archive --date <trading_date> --refresh` (or `MarketDataArchiveService.refresh_trading_date()`) for those symbols/`ONE_MINUTE` → read back `describe_trading_date()`.

AE. What must be verified immediately at 15:30/after session close? Observation count, expected vs. closed bar count, first/last observation timestamps, `missing_bar_timestamps`, `duplicate_bar_timestamps`, resulting `ArchiveStatus` per cell and day rollup, `reconciliation_status` (expect `NOT_RECONCILED` absent an independent source).

AF. What exact condition will allow the archive cell to become COMPLETE? Continuous session closed (CAS-aware where applicable) AND timeframe completeness-supported (`ONE_MINUTE` qualifies) AND the set difference between `expected_bar_timestamps()`/`expected_continuous_bar_timestamps()` and observed closed-bar timestamps is empty.

AG. What exact condition will allow the resulting bars to become REAL_DHAN? Not achievable today — requires a future checkpoint to build a genuine Dhan-historical-candle-backed `HistoricalBarProvider` (or an archive-to-HistoricalBar projector) that declares `PROVENANCE_REAL_DHAN` and is deliberately selected in place of `SyntheticHistoricalBarProvider`; that provider/projector does not exist as of 65.13.

AH. What is the smallest next checkpoint after the next complete session is captured? Build the archive→HistoricalBar projection (or genuine Dhan-historical-candle provider) that turns a COMPLETE `MarketDataArchiveDay` cell into `HistoricalBar` rows honestly stamped `REAL_DHAN` — strictly scoped to that projection, no backtest/strategy/Gainz/MarketContext changes bundled in.

## Git Safety
`git status --short` shows a working tree with substantial **carried-forward, uncommitted work from checkpoints 65.03–65.12** (feature-engine files `price_vs_ma_pct.py`, `rebound_candidate.py`, `ma_divergence.py`, `market_regime.py`, `docs/research/MARKET_CONTEXT_INTELLIGENCE.md`, `domain/market_data/provenance.py`, migration `0036_historicalbar_provenance.py`, and modifications to `historical_bars.py`, `historical_data_preparation.py`, `strategy_execution.py`, `contracts.py`, `backtesting_views.py`, `synthetic_historical.py`, `historical_bar_repository.py`, `models.py`, `definitions.py`, `field_registry.py`, `coordinator.py`, `sma_trend_filter.py`, and associated test files) — **none of these were created, modified, or touched by 65.13**. 65.13's own changes are exactly two files: `docs/architecture/DAILY_MARKET_DATA_ARCHIVE_ARCHITECTURE.md` (Part T addition, the "Checkpoint 65.13" section appended) and `D:\IntraDay\taskReport.md` (this file, overwritten). No commit or push was performed. No prior work was deleted or cleaned.

`git log -3 --oneline`:
```
01b5f14 checkpoint 64.99
7356ebf checkPoint 64.97
49ed106 checkpoint 64.90
```
