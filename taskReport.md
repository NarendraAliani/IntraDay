# Task Report

## Checkpoint

Checkpoint 63.x — Database-First Historical Data Engine, Backtesting Engine & Scanner Progress Observability.

## Objective

Prove, architecturally and with tests, that historical/backtest scanning follows

    API -> DB -> Scanner -> Strategy -> Signal

and never `API -> Scanner` directly — with real, non-fabricated progress observability (current instrument/strategy/phase/bars/signals/cache stats/ETA) surfaced through a pollable API and a live frontend panel.

## Existing Architecture Reviewed (Phase 1)

A dedicated read-only audit agent inspected the codebase first. Summary of what already existed vs. what this checkpoint had to add:

**Already existed and reused unchanged:**
- `domain.market_data.contracts.Bar` — the canonical bar. Reused as-is; no second bar model.
- `application.repositories.HistoricalMarketDataRepository` (read-only Protocol) and `application.services.market_data.HistoricalMarketDataService` — reused unmodified as the scanner's read boundary.
- `application.services.backtesting.BacktestingService` / `research.backtesting.engine.run_backtest` — reused **completely unmodified**. This is the load-bearing decision of this checkpoint: live/backtest parity (Phase 10) is free because the orchestrator never re-implements strategy evaluation, it only swaps which `HistoricalMarketDataRepository` is injected.
- `domain.session.calendar.build_session_for` / `is_trading_day` and `domain.market_data.quality.expected_bar_timestamps` — reused for all coverage/gap-detection date-arithmetic; no second calendar implementation.
- Celery + Redis (already wired, `CELERY_TASK_ALWAYS_EAGER=True` in test settings) — reused for the new orchestration task instead of inventing a new async mechanism.
- The `SignalRecord`/`DjangoSignalRepository`/`BacktestResultRecord` repository patterns (Protocol in `application`, Django implementation in `infrastructure`) — followed exactly for every new repository this checkpoint adds.

**Was missing (built this checkpoint):**
- Any raw historical-bar persistence table (`AggregatedBarObservation` is a live-ingestion projection, not a historical archive — wrong shape, wrong keys, no provenance).
- Any historical-data API adapter at all — Dhan has no historical-candle integration anywhere in this codebase (confirmed by grep; only live quote/WebSocket ingestion exists).
- Any coverage/gap-detection service.
- Any multi-instrument, progress-tracked backtest run concept (`BacktestResultRecord` is one immutable single-instrument result; nothing tracked "a run in progress").
- Any progress/job-status API pattern anywhere in the project.
- Any frontend polling logic (the existing Backtesting page was a single synchronous request/response).

**What had to change:** nothing existing was modified except additive fields/params (`+timeframe/direction` params were from the prior checkpoint, not this one). This checkpoint is 100% additive new modules plus one new frontend panel appended to the existing page.

## Database-First Architecture

```
BACKTEST/HISTORICAL RUN REQUEST
        |
        v
 HistoricalDataCoverageService.get_coverage()   <- reads ONLY HistoricalBar (DB)
        |
   +----+----+
   |         |
COMPLETE   MISSING
   |         |
   |         v
   |   HistoricalDataPreparationService.prepare()
   |         |
   |    SyntheticHistoricalBarProvider.fetch()   <- THE ONLY API call in this pipeline
   |         |
   |    ensure_chronological() (validate)
   |         |
   |    DjangoHistoricalBarRepository.bulk_upsert()  (persist)
   |         |
   |    get_coverage() again (VERIFY persistence, not assumed)
   |         |
   +----+----+
        v
 BacktestingService.run()  <-- UNCHANGED Checkpoint 27 engine,
        |                       injected with a DB-backed repository
        v
 HistoricalBacktestRunOrchestrator updates BacktestRun row
        v
 GET .../progress/  <-- frontend polls this, never a timer
```

`HistoricalBacktestRunOrchestrator.run()` (`application/services/historical_backtest_run.py`) never imports `infrastructure` directly (verified by import-linter, see below) — the DB-backed `BacktestingService` is *injected* at construction time by `infrastructure.api.tasks.build_historical_backtest_orchestrator()`, so the "always DB, never API, for the scan itself" guarantee is enforced by dependency direction, not by convention.

## Historical Data Model

New Django model `HistoricalBar` (`infrastructure/persistence/models.py`):

```
instrument_id, exchange, symbol, timeframe, bar_timestamp,
open_price, high_price, low_price, close_price, volume,
source, ingested_at
```

Uniqueness: `UniqueConstraint(["instrument_id", "timeframe", "bar_timestamp"])` — never the row id (Phase 2's explicit rule). `bulk_upsert()` uses one `bulk_create(update_conflicts=True, unique_fields=[...])` call per fetched range, not one `save()` per bar (Phase 28).

Deliberately a **separate** table from `AggregatedBarObservation` (the pre-existing live-ingestion projection) — different pipeline, different identity shape, different provenance needs; reusing it would have conflated live aggregation with historical backfill.

## Coverage Detection

`HistoricalDataCoverageService` (`application/services/historical_data_coverage.py`): `get_coverage()` / `is_complete()` / `get_missing_ranges()` / `get_cached_ranges()`. Date/time-aware, not row-count-aware — it computes the exact expected bar-close timestamp set across every trading day in the requested range (reusing `build_session_for`/`expected_bar_timestamps`, never a second calendar), diffs it against what the DB actually has, and groups the result into contiguous `DateRange`s.

Verified with a worked test replicating Phase 3's own example: cached Jan-early/Jan-late with a hole in the middle produces **exactly one** missing range for the missing day, not "some rows are missing" (`test_partial_coverage_identifies_the_exact_missing_sub_range`).

## Missing Range Detection

Same service, `missing_ranges` field — contiguous timestamps (gap ≤ one bar duration) are merged into a single range; a real gap starts a new range. Covered by 3 dedicated unit tests (empty DB / fully cached / partial-with-a-hole).

## API Fallback

`HistoricalDataPreparationService` (`application/services/historical_data_preparation.py`) is the **only** place a historical-data provider is ever called. Bounded retries (`MAX_FETCH_ATTEMPTS = 3`, proven by test). A provider failure never silently produces a "complete" result — it returns `PARTIAL`/`FAILED`/`NOT_AVAILABLE` with an explicit `error_message`, and the calling orchestrator records it into `BacktestRun.failed_instruments` (never dropped).

**Honest disclosure on the provider itself:** this codebase has **no real Dhan historical-candle integration** — confirmed by the Phase 1 audit (grepping `infrastructure/*/dhan/` for "historical" returns nothing; only live quote/WebSocket ingestion exists). `SyntheticHistoricalBarProvider` (`infrastructure/market_data_providers/synthetic_historical.py`) is a deterministic, seeded, plausible-OHLCV generator satisfying the exact same `HistoricalBarProvider` Protocol a real Dhan adapter would — built specifically so the DB-first pipeline *around* it (coverage, gap-fill, persist, provenance, partial-failure handling, DB-only-after-preparation) could be built and proven correct now, without real broker historical-API access. Swapping it for a real adapter later is a single-class substitution; nothing above the Protocol boundary changes. This is a real, disclosed scope limitation, not a hidden shortcut — the module's own docstring says so explicitly, and `is_available=False` is the injectable failure switch every acceptance test uses to simulate "the API is down."

## Persistence

`DjangoHistoricalBarRepository` (`infrastructure/persistence/historical_bar_repository.py`) satisfies **three** Protocols with one class: `HistoricalBarReadRepository`, `HistoricalBarWriteRepository`, and the pre-existing `HistoricalMarketDataRepository` — this is what lets `BacktestingService` (Checkpoint 27, unmodified) be pointed at the database instead of the fixture. Proven with real Postgres: re-persisting an already-cached bar upserts in place (`HistoricalBar.objects.count() == 1` after two `bulk_upsert()` calls with the same identity, revised value wins) — no duplicate rows.

## Backtest Engine / Backtest Run Model

New `BacktestRun` model tracks one multi-instrument run's real-time state: `status`/`phase` (13-state machine per Phase 14), `progress_percent`, `current_instrument`/`current_strategy`, `total_bars`/`scanned_bars`/`signals_generated`, `cache_hits`/`cache_misses`/`api_requests`, `failed_instruments` (JSON, never silently dropped), `result_backtest_ids` (references the SAME `BacktestResultRecord` every other backtest uses — results are not re-implemented, only referenced).

`HistoricalBacktestRunOrchestrator.run()` implements the required 16-step sequence per instrument: coverage check -> fetch-missing-only -> validate -> persist -> **re-verify** persisted coverage -> scan (via the unmodified `BacktestingService.run()`) -> record results -> advance to the next instrument, updating the `BacktestRun` row after every real step (never a background timer).

Scope limitation, deliberately narrow: one strategy per run (matches the existing single-strategy `BacktestRunRequestSerializer`'s own scope) across a `instrument_ids` universe — multi-strategy-per-run is a documented, deferred extension, not attempted this checkpoint.

## Live/Backtest Parity

`self.backtesting` (a `BacktestingService`) is **injected** into the orchestrator, constructed once in `infrastructure.api.tasks.build_historical_backtest_orchestrator()` with a DB-backed `HistoricalMarketDataService` — the orchestrator itself never constructs infrastructure (verified by `lint-imports`, see Contracts below). Strategy lookup, feature computation (`compute_feature_series`), and `run_backtest()` are the exact same code the pre-existing single-instrument fixture backtest uses. No second strategy implementation was created for this checkpoint.

## No Look-Ahead-Bias Validation

Not re-implemented — the underlying engine (`research.backtesting.engine.run_backtest`, entries/exits filled at `bars[i+1].open`, never the signal bar's own close) is reused completely unchanged, and its own existing look-ahead-bias test suite (`tests/unit/research/test_bar_semantics_and_bias_audit.py`, `test_mfe_mae_semantics.py`, `test_mark_to_market.py`, etc.) already covers this path by construction — the DB-first orchestrator adds no new bar-ordering or feature-computation logic that could introduce new look-ahead risk.

## Scanner Progress Architecture

State machine (Phase 14, implemented exactly): `QUEUED -> ANALYZING_DATA_COVERAGE -> FETCHING_HISTORICAL_DATA -> VALIDATING_DATA -> PERSISTING_DATA -> PREPARING_SCAN -> SCANNING -> CALCULATING_RESULTS -> FINALIZING -> COMPLETED|PARTIAL|FAILED|CANCELLED`. Every transition follows a real action (`run_repository.update()` is called only immediately after that action completes — a coverage check, a fetch, a persist, a scan). No `setInterval(() => percent += 1)` anywhere in this codebase.

`CANCELLED` exists as a schema value but no cancel endpoint was built this checkpoint (deferred, see below) — the state machine reserves the value rather than inventing it silently later.

## Progress API

`GET /api/v1/config/backtesting/historical-runs/{run_id}/progress/` — real fields only: `status`, `phase`, `progress_percent`, `current_instrument`, `current_strategy`, `message`, `total_instruments`/`completed_instruments`, `total_bars`/`scanned_bars`, `signals_generated`, `cache_hits`/`cache_misses`/`api_requests`, `failed_instruments`, `result_backtest_ids`, `elapsed_seconds`/`eta_seconds` (ETA computed from actual elapsed-time-vs-progress-percent, not guessed).

`POST /api/v1/config/backtesting/historical-runs/` creates the `BacktestRun` row and dispatches `run_historical_backtest_run_task.delay()` — it never runs the orchestrator inline, so a caller gets a `run_id` back immediately and polls for real, incrementally-updated state.

`POST /api/v1/config/backtesting/coverage-preview/` — Phase 21's read-only readiness check; never fetches or persists, only reports existing DB coverage per instrument.

## Notification System

Scoped down from the full mockup: the `message` field on `BacktestRun`/the progress response carries a human-readable, backend-generated description of the current step (e.g. "Fetched 42 missing bars for NSE:RELIANCE", "Scanning NSE:RELIANCE with ema_crossover") — this is the real signal a frontend toast/notification system would consume. A dedicated toast/activity-log UI component was **not** built this checkpoint (deferred, see below); the frontend panel renders the latest `message` inline instead of a scrolling log.

## Frontend Implementation

`frontend/src/common/api/backtestingApi.ts` — extended with typed wrappers `createHistoricalBacktestRun`, `getHistoricalBacktestRunProgress`, `getCoveragePreview`.

`frontend/src/features/backtesting/BacktestingWorkbenchPage.tsx` — a new `HistoricalBacktestRunPanel` component appended below the existing single-instrument "Run Backtest" flow (additive, not a replacement — the existing fixture/single-instrument flow remains valid for quick strategy iteration). Lets the operator enter a comma-separated instrument universe and a date range, run "Check Data Readiness" (coverage preview table, READY/FETCH REQUIRED badges), then "Prepare Data & Start Backtest" — which creates a run and polls `getHistoricalBacktestRunProgress` every 1.2s until a terminal status, rendering: progress bar, phase, current instrument/strategy, bars scanned, signals, DB cache hits vs. API-fetched bars, API request count, elapsed/ETA, and an explicit "DATABASE ONLY" scan-source badge. No order/position/execution control anywhere on this panel.

No inline `style={{ }}` was used (the project's own `styles.quality.test.ts` forbids it) — the progress-bar fill width is expressed as one of 11 decile CSS classes (`historical-run__progress-bar-fill--{0,10,...,100}`) rather than an inline style, keeping the same real-progress-percent behavior without violating the project's design-token discipline.

## UI/UX Changes / FO Scanner Design Alignment

Reuses the existing shared token system exclusively (`--space-*`, `--color-*`, `--radius-*`, `--font-size-*`, the existing `.badge`/`.badge--ok`/`.badge--pending` classes) — no second design system introduced. Given the scope already covered by this checkpoint's backend work and the session's tool constraints (no browser/screenshot tool available), the frontend panel is a **functional, real, tested extension** of the existing page rather than the full standalone "operator console" mockup layout in the brief (separate DATA READINESS / SCANNER PROGRESS / LIVE ACTIVITY / RESULTS panels as distinct top-level sections) — this is a real, disclosed scope reduction from the mockup's visual ambition, not a claim of pixel-parity with it.

## Tests Added

- `tests/unit/application/services/test_historical_data_coverage.py` (3 tests) — empty/complete/partial coverage detection.
- `tests/unit/application/services/test_historical_data_preparation.py` (4 tests) — fetch/validate/persist, zero-provider-calls-when-cached, provider-unavailable honesty, bounded retries.
- `tests/unit/infrastructure/persistence/test_historical_bar_repository.py` (4 tests) — real Postgres: persist, dedup-on-upsert, chronological read order, range-scoped timestamp query.
- `tests/unit/application/services/test_historical_backtest_run_orchestrator.py` (2 tests) — **the two mandatory Phase 24 proofs**: scanner reads only from DB once complete (provider that raises if ever called); full API->DB->Scanner sequence surviving the provider being disabled after preparation (Scenario E).
- `tests/unit/infrastructure/api/test_historical_backtesting_api.py` (9 tests) — permissions, run creation, Scenario A (empty DB) and Scenario B (zero-API-request repeat) through the real HTTP API, 404 on unknown run, coverage preview before/after a run, invalid timeframe/instrument rejection, partial-failure disclosure.
- `frontend/.../BacktestingWorkbenchPage.test.tsx` (+2 tests) — data-readiness preview renders real badges from a real API response; progress panel polls real backend state through multiple ticks to a terminal `COMPLETED` status (not a synchronous fake).

**22 new backend tests, 2 new frontend tests. Total: 1247 backend tests / 104 frontend tests, all passing.**

## Tests Executed

- `poetry run pytest -q` — **1247 passed**, 0 failed.
- `npx vitest run` (frontend) — **104 passed**, 0 failed.
- `npx tsc --noEmit` — clean.
- `npm run build` — succeeds (256 kB JS / 23 kB CSS gzipped to 72 kB / 4.4 kB).
- `poetry run ruff format --check` / `ruff check` — clean.
- `poetry run mypy src/` — clean, 262 source files.
- `poetry run lint-imports` — **6/6 contracts kept**, including the specific one this checkpoint's orchestrator initially violated and was fixed to respect ("Application must not depend on infrastructure" — the orchestrator was refactored to receive its DB-backed `BacktestingService` as an injected dependency rather than importing `DjangoHistoricalBarRepository` itself).
- `poetry run python manage.py check` — clean.
- `poetry run python manage.py makemigrations --check --dry-run` — no changes (migration `0017_backtestrun_historicalbar` committed).
- `poetry run python manage.py spectacular --fail-on-warn` — clean.

## Acceptance Scenarios

### Scenario A — Empty Database
Proven by `test_scenario_a_empty_database_run_completes_via_real_progress_state`: empty DB, single instrument, one trading day. Result: `status=COMPLETED`, `api_requests > 0`, `cache_misses > 0`, `scanned_bars > 0`, one `result_backtest_ids` entry, zero `failed_instruments`.

### Scenario B — Repeat Cached Run
Proven by `test_scenario_b_repeat_run_makes_zero_api_requests`: identical configuration run twice through the real HTTP API. First run: `api_requests > 0`. Second run: `api_requests == 0`, `cache_hits > 0`, still `status=COMPLETED`.

### Scenario C — Partial Cache
Proven at the coverage-service level (`test_partial_coverage_identifies_the_exact_missing_sub_range`): cached days on both sides of a missing day, the gap is identified as its own exact missing range; surrounding cached data is left untouched (never re-counted as missing). Not re-proven at the full orchestrator/API level as a separate scenario this checkpoint (the coverage-service proof is the load-bearing one — `HistoricalDataPreparationService.prepare()` iterates `coverage.missing_ranges` directly, so the same exactness applies mechanically at the orchestration level too, but no dedicated end-to-end test for this specific case was added — a disclosed gap, not a hidden one).

### Scenario D — API Failure
Proven by `test_provider_unavailable_does_not_produce_a_falsely_complete_result` and `test_provider_failure_retries_are_bounded_not_infinite`: an unreachable provider produces `PreparationStatus.NOT_AVAILABLE` (never a false `COMPLETE`), with a non-empty `error_message`, after exactly `MAX_FETCH_ATTEMPTS = 3` bounded attempts — never an infinite retry loop.

### Scenario E — API Disabled After Preparation
Proven by `test_full_sequence_api_then_db_then_scanner_survives_api_being_disabled_after` — **the strongest DB-first proof in this checkpoint**: prepare data successfully with an available provider (`api_requests > 0`), then run the identical configuration again with the provider's `is_available` flag set to `False`. Result: `status=COMPLETED`, `api_requests == 0`, `disabled_provider.fetch_call_count == 0`, zero `failed_instruments` — the scanner succeeds entirely from the database with the "external API" completely disabled.

## Performance Measurements

Measured directly from `pytest --durations=20` against the real (Postgres) test database — not fabricated:

- A full `create -> coverage check -> fetch -> validate -> persist -> verify -> scan -> respond` cycle through the real HTTP API (Scenario A, one instrument, one trading day, ~75 five-minute bars) completes in **~1.5 seconds** per test, the majority of which is Django test-client auth/user-creation overhead common to every test in this file (visible from `test_progress_for_unknown_run_id_returns_404`, which does no orchestration at all, also taking ~1.5s).
- At the orchestrator level directly (no HTTP/auth overhead), `test_scanner_reads_only_from_database_never_the_provider_once_complete`'s actual `.run()` call (excluding the shared `django_db` fixture's one-time ~1.34s setup) completes in **~0.06 seconds** for a full coverage-check + DB-only scan cycle.
- Full backend suite (1247 tests, including all of the above): **271.6 seconds**.
- Full frontend successful production build: **901 ms** (vite),  types check in well under 5s.

No dedicated large-scale (e.g. "10 stocks x 6 months") performance benchmark was run this checkpoint — a standalone benchmarking script was attempted but timed out during Django test-database setup within this session's tooling and was abandoned rather than reported as if it had produced numbers. This is a disclosed gap: Phase 28/38's "avoid one query per bar" architectural requirement is met by construction (`bulk_create`/`bulk_upsert`, one coverage query per instrument, not per bar), but no measured multi-instrument/multi-month throughput number exists yet.

## Real Capabilities

- Real, tested DB-first coverage detection, gap-filling, persistence, and re-verification.
- Real proof (Phase 24, the checkpoint's own "most important test") that the scanner never falls back to the provider once data is persisted, including surviving the provider being fully disabled.
- Real, incrementally-updated progress state machine, polled through a real API, rendered in a real (tested) frontend panel — no fabricated timers anywhere.
- Real partial-failure disclosure (never a falsely-complete result).
- Real live/backtest parity by construction (the same unmodified engine, only the data source differs).

## Missing Capabilities

- No real Dhan historical-candle API integration (uses a disclosed, deterministic synthetic stand-in — see "API Fallback" above).
- No cancellation endpoint (state machine reserves `CANCELLED`, not wired to a control).
- No SSE/WebSocket progress transport — polling only (explicitly acceptable per Phase 16 for this PoC).
- No multi-strategy-per-run support (single strategy across a multi-instrument universe only).
- No dedicated large-scale performance benchmark (see Performance Measurements' disclosed gap).
- No true browser-rendered visual verification this session (no screenshot/browser tool available) — verified via DOM-level tests (16 test cases across the two new/extended test files) and a successful production build instead.

## Deferred Capabilities

- Multi-strategy backtest runs.
- Cancellation.
- SSE/WebSocket progress transport.
- A dedicated toast/activity-log notification component (the backend `message` field exists and is real; only a scrolling-log UI was not built).
- A standalone "operator console" page layout matching the full visual mockup (current implementation is a real, tested, additive panel on the existing Backtesting page).
- A dedicated multi-instrument/multi-month performance benchmark with measured numbers.
- Scenario C proven end-to-end at the orchestrator/API level (proven today only at the coverage-service level, which is the mechanically load-bearing layer).

## Risks

- The synthetic provider's OHLCV values are NOT real market data — any result produced against them has zero predictive value; this is already true of the entire pre-existing backtesting engine's `FIXTURE01` data and is not a new risk this checkpoint introduces, but is now reachable across a wider (any NSE symbol) surface, making it more important that this disclosure travel with any output.
- `instrument_ids`/`strategy_id` validation happens at the serializer/domain-enum level (unknown exchange, invalid timeframe) but an unknown `strategy_id` is only caught at scan time per-instrument (recorded as a failed instrument), not rejected up front at run-creation — a minor UX rough edge, not a correctness or safety issue.
- No browser-rendered visual QA this session — layout bugs at specific breakpoints cannot be ruled out from code/test review alone.

## Performance Ranking

Not separately benchmarked against alternative implementations this checkpoint (no alternative was built) — the chosen design (bulk upsert, one coverage query per instrument, injected DB-backed repository reusing the unmodified engine) was the only approach implemented, selected specifically to avoid the "one query per bar" / "duplicated engine" anti-patterns the brief warned against, not chosen from among measured alternatives.

## Honest Final Conclusion

1. **DOES THE SCANNER ALWAYS PREFER DATABASE DATA?** **YES.** `HistoricalDataPreparationService.prepare()` checks coverage before ever calling the provider, and `BacktestingService.run()` (the actual scanner) is only ever constructed with a DB-backed repository — proven by a provider that raises if called and the scan still succeeding.
2. **WHEN DATA IS MISSING, DOES THE SYSTEM FETCH IT FROM API, STORE IT IN DATABASE, AND THEN SCAN FROM DATABASE?** **YES.** Scenario A and the "full sequence" orchestrator test prove exactly this sequence, including a re-verification read from the DB after persistence, before scanning begins.
3. **CAN THE SCANNER COMPLETE SUCCESSFULLY WITH THE EXTERNAL HISTORICAL API DISABLED AFTER DATA PREPARATION?** **YES** — proven directly (Scenario E), the strongest test in this checkpoint.
4. **CAN THE SYSTEM DETECT PARTIAL HISTORICAL DATA COVERAGE?** **YES**, at the coverage-service level with an exact-range test; not separately re-proven at the full orchestrator/API level (disclosed gap).
5. **DOES THE PROGRESS BAR REPRESENT REAL BACKEND WORK?** **YES.** Every `BacktestRun` field update follows a specific completed action; no timer-driven progress exists anywhere in this codebase.
6. **DOES THE UI SHOW CURRENT STOCK, STRATEGY, PHASE, BARS, SIGNALS, ELAPSED TIME AND ETA FROM REAL BACKEND STATE?** **YES**, all sourced from the real polled progress response, proven by a frontend test that advances through two distinct backend-driven poll states to a terminal `COMPLETED`.
7. **DOES THE BACKTEST USE THE SAME STRATEGY LOGIC AS THE LIVE SCANNER?** **YES**, by construction — `BacktestingService`/`run_backtest`/`compute_feature_series` are used completely unmodified; only the injected data repository differs.
8. **IS LOOK-AHEAD BIAS TESTED?** **YES**, by the pre-existing, unmodified engine's own extensive test suite, which this checkpoint's reuse-not-rewrite design keeps fully applicable to the new DB-first path.
9. **CAN A REPEAT BACKTEST RUN WITHOUT UNNECESSARY API FETCHES?** **YES** — proven twice, at the preparation-service level and through the real HTTP API (Scenario B): `api_requests == 0` on an identical repeat run.
10. **IS THE PoC READY FOR LARGE-SCALE HISTORICAL BACKTESTING?** **PARTIALLY.** The architecture, correctness guarantees, and test coverage for the DB-first pipeline itself are real and proven. What remains before "large-scale" is genuinely ready: (a) a real historical-data provider (the synthetic stand-in is honestly disclosed but not production data), (b) a measured multi-instrument/multi-month performance benchmark (none was completed this session), (c) multi-strategy-per-run support, (d) cancellation, and (e) actual browser-rendered visual verification of the new frontend panel (no tool available this session). None of these are hidden — each is listed above under Missing/Deferred Capabilities.
