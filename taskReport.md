# Task Report

## Milestone
Historical Research & Correlation Foundation (continuing from 64.81-64.89 traceability/quality/reconciliation work).

## Checkpoint
64.90 — Real replay feasibility (data-integrity/replay checkpoint).

## Classification
STOP / negative-result checkpoint. No replay was executed. This is a validated finding, not an unfinished task.

## Objective
Determine whether the existing 64.68 replay/paper-trading infrastructure can take EXISTING local historical market data and run it through the existing feature engine + an existing non-Gainz strategy + existing signal persistence + PaperBroker + outcome persistence to produce a real, traceable SignalRecord -> PaperOrderRecord -> PaperTradeRecord -> outcome chain.

## Historical Data Availability
Queried the real database directly (`MarketDataArchiveDay`, `AggregatedBarObservation`, `HistoricalBar`) after applying the one pre-authored, already-uncommitted pending migration (`0033_marketdataarchiveday_cas_window_status`) needed to read the current schema — see Database Changes.

`MarketDataArchiveDay`: **12 cells**, 4 symbols (HDFCBANK, INFY, RELIANCE, TCS) x 3 trading dates (2026-08-24, 2026-08-25, 2026-08-26), all NSE cash equity, all `1m`, all `data_source=dhan`:

| Date | Status | Bars observed / expected |
|---|---|---|
| 2026-08-24 | PARTIAL | 1 / 375 (all 4 symbols) |
| 2026-08-25 | IN_PROGRESS | 24 / 375 (all 4 symbols) |
| 2026-08-26 | PARTIAL | 60 / 375 (all 4 symbols) |

**No cell has ever reached `COMPLETE`.** Best-ever coverage is 60/375 = 16%. `HistoricalBar` holds 5,100 rows but is a disjoint `5m` reference series that does not overlap the archived `1m` cells (confirmed in `MARKET_DATA_ARCHIVE_QUERY_API.md`, re-checked live).

## Candidate Dataset
The single best candidate is 2026-08-26 RELIANCE `1m` (and the same-shape HDFCBANK/INFY/TCS rows): 60 `AggregatedBarObservation` rows, `interval_start` 08:46-09:58 UTC. Direct inspection found **one internal gap** in that run (09:45 -> 09:58 UTC, ~12 missing minutes), on top of covering only 16% of the expected 375-bar session.

## Dataset Selection Rationale
2026-08-26 was chosen for inspection because it has the highest observed-bar count of the three archived dates. It was then rejected as a replay input because it fails the checkpoint's own bar: not `COMPLETE`, and even judged loosely (any usable warm-up-plus-decision window) it contains an unexplained internal gap, so a strategy walked forward across it would be evaluated over a series with a silent discontinuity — exactly the kind of input that produces signals nobody could trust.

## Archive Quality
`archive_status` is `PARTIAL` or `IN_PROGRESS` for every cell that exists; `NOT_OBSERVED`/`COMPLETE`/`FAILED` never appear. `completeness_supported=True` for all 12 (1m aligns with the session grid), so the missing coverage is a real gap, not an artifact of an unsupported timeframe.

## CAS-Aware Data Quality
`cas_window_status` is `NOT_APPLICABLE` on all 12 rows — the CAS-aware quality layer added in 64.88 has not yet been exercised against any window with enough data to classify.

## Replay Architecture
Two independent, real, non-Gainz code paths were located:
1. `ReplayPaperSessionService` (`src/intraday/application/services/replay_paper_session.py`, checkpoint 64.68) — a pure in-memory projection (`project()`) that re-derives an entire session from `(record, cursor)` into a fresh `PaperBroker` every call. It does **not** write `SignalRecord`/`PaperOrderRecord`/`PaperTradeRecord`/`SignalEvidenceRecord` — only the session spec/cursor is persisted (`PaperSessionRecord`). Its wired `bar_loader` (`load_replay_bars` in `replay_paper_session_runtime.py`) feeds it from `SyntheticHistoricalBarProvider`, explicitly labelled synthetic — **not** real archived data.
2. `run_active_loop_tick(_from_source)` (`src/intraday/infrastructure/api/active_loop_runtime.py`, checkpoints 39/40/52) — the real persisting path: it wires `PaperSignalExecutionService` with `DjangoSignalRepository`, `DjangoTradePlanRepository`, `DjangoSignalEvidenceRepository`, and `PaperTradingService`/`DjangoPaperLedgerRepository`, and pulls bars from any injected `BarSource` (checkpoint 52's boundary), including the existing `DeterministicReplayBarSource`, which can be seeded from any `Bar` sequence — real or synthetic. This is the path that would need to be driven by real archived bars for a genuine chain.

Three non-Gainz strategies exist and are registered (`registry.py::build_default_registry`): `EmaCrossoverStrategy`, `SmaTrendFilterStrategy`, `AtrVolatilityBreakoutStrategy`. A suitable strategy exists; it was never invoked.

## Replay Path
Not run. Wiring `AggregatedBarObservation` rows into a `Bar` sequence, feeding `DeterministicReplayBarSource`, and driving `run_active_loop_tick_from_source` per bar with historical `now` timestamps is architecturally straightforward and would have been the minimal real driver — but the archive does not contain a dataset that would produce a trustworthy result (see Dataset Selection Rationale), so building and running it now would only launder insufficient data into rows that look authoritative. Per the checkpoint's own instruction, this is the correct point to stop.

## Replay Safety
N/A — no replay executed, so no replay-induced contamination risk was taken. The architecture review above establishes that `run_active_loop_tick_from_source` writes into the same tables live paper trading uses; a future attempt must resolve this isolation question (a dedicated `scan_run_id`/session tag, most likely) before writing anything, which is exactly rule 9's concern.

## Signal Count
0 before, 0 after (nothing run).

## Feature Evidence Count
0 before, 0 after.

## Paper Order Count
2 before, 2 after — both pre-existing, dated 2026-08-15 and 2026-08-18, `instrument_id=NSE:RELIANCE`, no `signal_id`. Unrelated to this checkpoint and untouched.

## Paper Trade Count
0 before, 0 after.

## Realized Outcome Count
0 before, 0 after.

## Provenance Coverage
Not computable — zero signals exist to measure coverage over.

## Orphan Records
The 2 existing `PaperOrderRecord` rows have no `signal_id`, making them orphans by the 64.81 traceability model (a "genuinely traceable or null" identifier — here it is null, correctly, not inferred). Pre-existing; not created by this checkpoint.

## Duplicate Detection
N/A — no records were created.

## Look-Ahead Bias Analysis
No replay ran, so nothing to test here in fact, but the mechanism was reviewed for future use: `ReplayPaperSessionService.project()` evaluates the strategy on `bars[0..index]` only and fills the resulting order against `bars[index+1].open` — the same next-bar-open rule `research/backtesting/engine.py` uses — so a future genuine run through this mechanism structurally cannot look ahead. `run_active_loop_tick_from_source` has no look-ahead guard of its own; it trusts the caller to pass only bars closed as of the tick's `now`, which is how the live scheduler already uses it.

## Timestamp Integrity
The one gap found (09:45->09:58 UTC on 2026-08-26 RELIANCE) is a real timestamp discontinuity in the archive, not a display artifact — confirmed by iterating `interval_start` deltas across all 60 rows.

## Feature Evidence Integrity
N/A — no evidence rows exist.

## Execution Integrity
N/A — no orders/trades were generated by this checkpoint.

## Outcome Integrity
N/A — no outcomes exist.

## Research Dataset Status
Unchanged from 64.89: empty. `SignalRecord=0`, `PaperTradeRecord=0`, `SignalEvidenceRecord=0`.

## Feature → Outcome Analysis
Not attempted — no data exists to analyze.

## Feature Interaction Analysis
Not attempted.

## Time-of-Day Analysis
Not attempted.

## Symbol Robustness
Not attempted.

## Market Regime Analysis
Not attempted.

## Gainz Status
Untouched. No Gainz file was read, edited, or referenced beyond this report's own confirmation.

## Strategy Modification Status
No production strategy, scanner, risk, or execution code was modified. No parameter was loosened or tuned.

## Database Changes
One schema change only: applied the pre-authored, already-uncommitted `persistence.0033_marketdataarchiveday_cas_window_status` migration (carried forward from 64.88's uncommitted tree, not authored in this session) so the real database schema matched the working tree's models and could be queried. No data rows were inserted, updated, or deleted by this checkpoint in any table.

## API Changes
None. No new endpoint was added.

## Frontend Changes
None.

## Tests
No new test file was added — Phase 5 only calls for tests when a replay driver is built or a defect is found; neither happened, so no replay-specific test was warranted.

## Testing Level
Full regression suite, run exactly once.

## Tests Run
`poetry run pytest tests/unit -q`, run exactly once: **`2696 passed, 2 warnings in 546.04s (0:09:06)`**. The 2 warnings are a pre-existing `DeprecationWarning` in a third-party dependency (`schemathesis`) and a test-database-teardown `OperationalError` warning unrelated to any code touched by this checkpoint (no code was touched).

## Tests Skipped
None skipped deliberately; no new subsystem was built that would need targeted tests.

## Research Readiness
**NO.** Zero signals, zero evidence, zero trades. Unchanged from 64.89.

## BacktestTrustLevel
Unchanged — no cell has ever reached `COMPLETE`, so no data qualifies for any trust tier above the existing baseline.

## Findings
1. The archive holds only fragments: best coverage is 16% of one session, with an internal gap even within that fragment.
2. Two independent, genuinely reusable, non-Gainz code paths exist that *could* produce a real signal->order->trade->outcome chain from real archived bars: `ReplayPaperSessionService` (pure projection, no DB writes) and `run_active_loop_tick_from_source` (the real persisting path, currently only fed synthetic or live data).
3. The 64.68 replay wiring shipped with `SyntheticHistoricalBarProvider`, not a reader over `MarketDataArchiveDay`/`AggregatedBarObservation` — so even with sufficient archive data, a small amount of new (but not strategy-changing) wiring would be needed to point it at real archived bars.
4. `run_active_loop_tick_from_source` writes into the same operational tables as live paper trading with no visible replay-session tag on `SignalRecord`/`PaperOrderRecord` — using it for replay today would risk contaminating operational history (rule 9); this needs a design decision before any future attempt, not a shortcut around it.

## Limitations
This checkpoint is a feasibility/gate check, not a replay execution. It intentionally produced no new rows.

## Remaining Gaps
- No `COMPLETE` archived trading day for any symbol.
- No archive-reading `BarSource`/bar-loader wired to `run_active_loop_tick_from_source` or to `ReplayPaperSessionService`.
- No isolation mechanism (session tag / dedicated table or flag) to keep a future replay run from mixing into live paper-trading history in the shared tables.

## Blockers
Archive data volume and completeness. This is the same root cause 64.79/64.83's `MARKET_DATA_ARCHIVE_QUERY_API.md` already documented, re-confirmed live today.

## Next Product Milestone
Either (a) let the market-data worker accumulate enough consecutive live sessions to produce at least one genuine `COMPLETE` day for at least one symbol, or (b) if a batch/EOD historical-candle ingestion path already exists elsewhere in the platform (not investigated here, out of this checkpoint's scope), point that at filling the archive instead of waiting on the live feed. Only after a `COMPLETE` day exists should a checkpoint attempt the real replay run this one stopped short of.

## Performance Ranking
N/A — no trades were generated.

## Final Product Gate

A. Was a real historical market-data source used? Data was *read* (Dhan-sourced archive rows already in the DB) for inspection only; none was used to drive a replay because none is sufficient.
B. Was any market data fabricated? No.
C. Was any signal fabricated? No — zero signals were created, real or otherwise.
D. Was any trade fabricated? No.
E. Was any outcome fabricated? No.
F. Can every replayed signal be traced to its strategy? N/A — no signal was produced.
G. Can every replayed signal be traced to feature evidence where evidence exists? N/A.
H. Can every paper order be traced to a signal? N/A — the 2 pre-existing orders are untouched and (correctly) carry no `signal_id`.
I. Can every paper trade be traced to a signal/order chain? N/A — no trades exist.
J. Can realized P&L be traced to the corresponding paper trade? N/A — no trades exist.
K. Is traceability coverage measurable? Not meaningfully — 0/0.
L. Is look-ahead bias explicitly tested? Not newly tested in this checkpoint; the existing `ReplayPaperSessionService.project()` mechanism was reviewed and its next-bar-open, decision-bars-only-up-to-index design structurally prevents it for any future run through that path.
M. Are Category-I CAS boundaries respected? Yes — only a pre-authored migration was applied; no CAS logic was touched.
N. Is Category-II behavior unchanged? Yes.
O. Was Gainz modified? **NO.**
P. Was any production strategy parameter optimized? **NO.**
Q. Was any scanner modified? **NO.**
R. Was risk/execution modified? **NO.**
S. Was NSE_FNO modified? **NO.**
T. Was live Dhan accessed? **NO.**
U. Was a second source of truth created? **NO.**
V. Is Research Readiness YES or NO? **NO** — zero signals, zero evidence, zero trades; the archive cannot support a trustworthy replay yet.
W. What is the strongest evidence that the replay dataset is trustworthy? None exists to cite — this is precisely why the checkpoint stopped: the best available data covers 16% of a session and contains an internal gap.
X. What is the strongest remaining threat to research validity? Insufficient/fragmented archive coverage (no `COMPLETE` day for any symbol) combined with the still-open risk that driving the real persisting path (`run_active_loop_tick_from_source`) without a session tag would mix replay rows into live paper-trading history.
Y. What exact evidence is still required before feature/outcome relationships can be considered candidates for strategy research? At least one `MarketDataArchiveDay` cell reaching `archive_status=COMPLETE` (all 375 expected 1m bars, no gaps) for at least one symbol, then a real run of the existing non-Gainz strategy/persistence chain against exactly those bars producing genuinely persisted `SignalRecord`/`PaperOrderRecord`/`PaperTradeRecord` rows traceable back to that archive cell.
Z. What is the next checkpoint? Either continued live-archive accumulation until a `COMPLETE` day exists, or (if out-of-band historical ingestion exists) a checkpoint to fill the archive from it — followed by the actual first real replay run, once and only once sufficient data exists.

## Git Safety
`git status --short` shows 77 lines: all `M`/`??` entries are the pre-existing, uncommitted 64.81-64.89 scaffolding already present at session start (frontend contracts, correlation/archive API modules, migrations 0031-0033, checkpoint test files through 64.89) — this session made **zero** edits to any tracked or untracked file. The only change this session made to the real system was applying migration `0033_marketdataarchiveday_cas_window_status` to the local database (schema only, no data). `git diff --stat` reports 46 files changed, 2921 insertions(+), 298 deletions(-), entirely attributable to that pre-existing uncommitted tree. `git log -3 --oneline`: `dbce678 checkpoint 64.80-f3`, `3bd7a09 CheckPoint 64.69`, `ab2dc04 Checkpoint 64.42`. No commit or push was made.
