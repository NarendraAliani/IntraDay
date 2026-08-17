# Task Report

## Checkpoint

Checkpoint 62.x (product/UI request, scoped down after a backend
audit and an explicit user decision)

## Objective

The user requested redesigning the "Live Market Data Monitor" frontend
page into an "Active Signal Monitor" (FO-Scanner-style operator
console: timeframe/universe/strategy selectors, a table of qualifying
strategy signals, an expandable explanation panel). Before touching
any UI, per the user's own explicit "backend audit before UI changes"
instruction, a research pass was run to determine what backend
capability actually exists to build the signal table against.

## Research Performed

A background audit agent inspected: `domain/signal/`,
`signal_intelligence/`, `application/`, `infrastructure/api/urls.py`,
`trading_engine/strategy_execution/registry.py`,
`domain/shared_kernel/contracts.py` (Timeframe enum), the existing
`frontend/src/features/market-data/LiveMarketDataMonitor.tsx`, and the
frontend shared component library.

## Findings

- `domain.signal.contracts.Signal` exists as a value object
  (strategy_id, instrument_id, direction, timestamp, theoretical
  entry/stop-loss/targets, status, confidence) - but had **no
  repository and no persistence** anywhere in the codebase.
- **No signal-listing API endpoint existed** - `urls.py` had zero
  signal-prefixed routes.
- Only **3 real registered strategies**: `ema_crossover`,
  `sma_trend_filter`, `atr_volatility_breakout` - NOT "Trend
  Follower/Mean Reversion/Breakout Hunter/Scalping Alpha" as the
  request's mockup implied.
- Real, supported `Timeframe` values: `TICK, 1m, 3m, 5m, 15m, 30m, 1h,
  1d`.
- No signal explainability/reason-trail data existed anywhere.
- No existing API endpoint implements pagination - nothing to
  pattern-match against.
- The current frontend page is explicitly, deliberately
  observation-only (its own comments state it excludes Buy/Sell/
  Entry/SL/Target fields on purpose).
- A real, reusable frontend design-system/component library exists
  (badges, empty/error/loading states, theme tokens).

## Hidden Gaps Discovered

The requested signal table (entry/SL/targets/explanation, populated
from real strategy output) could not be honestly built - doing so
would have required either fabricating data (explicitly forbidden by
the user's own "no hallucinated data" rule in the same request) or
building a real backend signal-persistence pipeline first, which did
not exist.

## Architecture Decisions

Given this finding, the user was asked how to proceed and explicitly
chose: **"Build the minimal backend signal pipeline first."** This
checkpoint's remaining scope is that backend work - see Decision 218
in `ARCHITECTURE_DECISIONS.md` for the full rationale.

## Implementation Performed

1. New `SignalRecord` Django model (migrated) - the first persistence
   for `domain.signal.contracts.Signal` in this project.
2. New `DjangoSignalRepository`: `record_signal()` (idempotent
   upsert keyed on the already-deterministic `signal_id`) and
   `list_signals()` (server-side paginated, with `strategy_id`/
   `instrument_id` filters).
3. New `GET /api/v1/config/signals/` - read-only, authenticated, the
   first paginated list endpoint in this project.
4. New optional `SignalRecorder` Protocol on
   `PaperSignalExecutionService` (mirrors the existing
   `ExitPlanAttacher` opt-in pattern, defaults to `None` - purely
   additive, no pre-existing caller/test is affected). Wired to
   `DjangoSignalRepository()` in the real composition root
   (`active_loop_runtime.py`).
5. A real signal is recorded if and only if `evaluate_and_submit()`
   genuinely produces one (never for a skipped/neutral/already-
   processed evaluation) - reuses the EXISTING signal-producing path,
   never a second signal-generation mechanism.

## Files Created

- `src/intraday/infrastructure/persistence/signal_repository.py`
- `src/intraday/infrastructure/api/signal_views.py`
- `src/intraday/infrastructure/persistence/migrations/0016_signalrecord.py`
- `tests/unit/application/services/test_paper_signal_execution_signal_recording.py`
- `tests/unit/infrastructure/persistence/test_signal_repository.py`
- `tests/unit/infrastructure/api/test_signal_api.py`

## Files Modified

- `src/intraday/infrastructure/persistence/models.py` (`SignalRecord`)
- `src/intraday/application/services/paper_signal_execution.py`
  (`SignalRecorder` Protocol, `_maybe_record_signal()`)
- `src/intraday/infrastructure/api/active_loop_runtime.py` (wiring)
- `src/intraday/infrastructure/api/urls.py` (`/signals/` route)
- `docs/architecture/ARCHITECTURE_DECISIONS.md` (Decision 218)
- `docs/architecture/ACTIVE_PRODUCT_GAP_REGISTER.md`
- `taskReport.md` (true overwrite - this file)

## Files Deleted

None.

## Tests Added

14 new tests:
- 4 in `test_paper_signal_execution_signal_recording.py`: a real
  signal is recorded exactly once with correct fields; a flat/no-
  signal bar series records NOTHING (the direct proof a normal
  market update does not fabricate a signal); an already-processed
  signal is not re-recorded; `signal_recorder=None` (default) changes
  nothing.
- 6 in `test_signal_repository.py`: record+list, idempotent
  re-recording of the same `signal_id`, pagination, strategy/
  instrument filters, page-size bound (max 200).
- 4 in `test_signal_api.py`: authentication required, honest empty
  state, a real persisted signal returned correctly via the API,
  pagination query params.

## Tests Executed

- New tests alone: **14 passed**.
- `poetry run pytest tests/unit/architecture -q`: **52 passed**
  (every architecture/safety-boundary test, confirming no order-
  placement code path was introduced).
- `poetry run pytest -q` (full backend suite): **1224 passed**
  (1210 pre-existing + 14 new; every pre-existing test remains
  green - a real bug WAS caught by re-running them: the `timeframe`
  field was initially too narrow, causing a genuine `DataError` in
  `test_active_loop_runtime.py`, fixed before this report).
- `ruff format --check`, `ruff check`: clean.
- `mypy` (strict, project code) on every touched file: clean.
- `lint-imports` (`.importlinter`, 6 contracts): 6/6 kept -
  `paper_signal_execution.py` (application layer) still does not
  import `infrastructure.*` directly, per Contract 6.
- `manage.py check`: clean. `makemigrations --check --dry-run`: no
  pending migrations. `spectacular --fail-on-warn`: clean.

## Failure Injection

Not applicable to this checkpoint's scope.

## Performance Benchmark

Not measured this checkpoint.

## Long-Run Stability

Not tested this checkpoint.

## End-to-End Paper Pipeline

Not newly exercised - `evaluate_and_submit()` itself was already
proven end-to-end in prior checkpoints; this checkpoint only added an
observation hook onto that existing, unchanged path.

## Frontend Audit

Performed as background research only (see Findings above) - no
frontend code was written or modified this checkpoint. The requested
UI redesign (control bar, FO-Scanner-style signal table, explanation
panel) remains entirely undone.

## Security Review

No credentials touched. `TRADING_MODE` remains PAPER throughout - the
new signals API is strictly read-only, and the full architecture
safety-boundary test suite (52 tests) was re-run and confirmed
passing, including the mechanical scan for forbidden order-placement
imports.

## Deployment Review

Not performed this checkpoint.

## Current Product Readiness

A real, tested, minimal signal-persistence backend now exists where
none did before. The frontend "Active Signal Monitor" experience the
user actually asked to see remains completely unbuilt - this
checkpoint deliberately stopped at the backend, per the user's own
explicit choice, rather than building a UI in the same turn.

## Performance Ranking

**ENGINEERING MATURITY: 8.9/10** - unchanged.

**ACTIVE PRODUCT MATURITY: ~5.7-5.8/10** - unchanged from Checkpoint
62; a real backend capability was added, but the product-facing
experience the user is actually trying to reach (an operator being
able to see live signals in the UI) is not yet reachable.

| Area | Score |
|---|---|
| Signal persistence/API | 6.5/10 - real, tested, but only 4 fields captured (no SL/targets/explanation) |
| Frontend | 2.0/10 - unchanged, 17+ consecutive checkpoints with none |
| Everything else | unchanged from Checkpoint 62's own scorecard |

## Remaining Gaps

The frontend redesign itself (all of it); `SignalRecord` explanation/
SL/target fields; reconnect-with-backoff; token lifecycle; watchdog;
correct minute-boundary bar semantics; instrument master beyond four
symbols; performance/load/long-run testing; live/backtest parity;
real Dhan connectivity.

## Blocked Items

Real Dhan connectivity - unchanged (Checkpoint 41).

## Risks

Building a UI later against `SignalRecord` as it currently stands will
only be able to show strategy/instrument/direction/price/risk-status/
order-status - NOT entry/SL/targets/explanation, which the request's
own mockup implied. Any future UI work must either honestly omit those
columns or this backend must be extended first (a further, separate,
real decision - not something to default into silently).

## Next Checkpoint

The actual frontend "Active Signal Monitor" redesign, built strictly
against the real `GET /api/v1/config/signals/` contract now available
- honestly using only the fields it returns, with an explicit "not yet
available" state for anything the mockup showed that the backend does
not yet provide (explanation, SL, targets).

## Honest Final Conclusion

The user asked for a UI redesign; a backend audit found the UI could
not be built honestly without fabricating data; the user was asked and
chose to build the missing backend first. That backend - a real
Signal persistence layer, repository, and paginated API, wired into
the actual signal-producing path and proven never to record a
fabricated signal - now exists and is tested. The frontend experience
itself, which is what the user actually wants to see and use, remains
completely unbuilt. This checkpoint is honestly a backend-only
prerequisite step, not the product experience requested.
