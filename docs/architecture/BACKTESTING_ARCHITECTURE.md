# Backtesting Architecture (Checkpoint 27)

## Objective

A backtesting proof of concept and Strategy Workbench UX built entirely
on top of the existing Checkpoint 26 strategy engine - no duplicate
strategy implementation, no duplicate parameter schema, no live
execution anywhere. Backtesting/research only; SAMPLE_BAR remains
blocked from live actionable trading.

## Pre-existing foundations reused (Part 1 audit)

- `research/backtesting/__init__.py` existed only as Checkpoint 4
  scaffolding (a functionally-inert placeholder import proving
  `.importlinter`'s narrow exception was expressible). No backtest
  engine code existed before this checkpoint.
- `application/services/market_data.HistoricalMarketDataService` and
  `application/repositories.HistoricalMarketDataRepository` (Checkpoint
  14) are reused as-is - the ONLY bar source for backtesting.
- `signal_intelligence.theoretical_outcome` (Checkpoint 21) already
  implements MFE/MAE, but for a DIFFERENT computation basis (a fixed
  future horizon from a `DirectionalIndication`, not a trade's actual
  holding period) - so the backtest engine's own MFE/MAE (per-trade,
  holding-period-based) is a new, small computation, not a duplicate
  (see `engine._mfe_mae`'s own docstring for the full reasoning).
- No prior trade ledger, equity curve, or performance-metrics code
  existed anywhere in the codebase.

## Architectural contract

```
historical bars (HistoricalMarketDataRepository)
      |
feature computation (signal_intelligence.feature_engine, via injected
      |                compute_feature_series - see "Import boundary" below)
selected strategy (trading_engine.strategy_execution.Strategy, from
      |             StrategyRegistry - the SAME registry Checkpoint 26 built)
strategy signal (StrategySignal, per bar)
      |
simulated execution (research.backtesting.engine)
      |
simulated position -> trade ledger (SimulatedTrade)
      |
equity curve (EquityPoint)
      |
performance metrics (BacktestMetrics)
```

`research.backtesting.engine` never imports Dhan, the Django ORM, or
any broker/order-execution module - proven by
`tests/unit/architecture/test_backtesting_sample_bar_boundary.py`.

## Import boundary (a real violation found and fixed)

`.importlinter` contract 4 forbids `intraday.trading_engine` <->
`intraday.signal_intelligence`/`intraday.research` cross-imports except
the ONE named exception: `research.backtesting -> trading_engine.
strategy_execution`. Two consequences, both discovered live during this
checkpoint's Part 1 audit (re-running `lint-imports`, matching
Checkpoint 26's own precedent):

1. **Strategy reuse is legal, feature computation is not.** `research.
   backtesting` may import `Strategy`/`StrategyRegistry`/
   `StrategyConfigurationValues` from `trading_engine.strategy_execution`
   directly - and does, via `research.backtesting/__init__.py`'s own
   re-export surface (the SOLE place that import happens, keeping the
   exempted edge singular and auditable rather than a set of submodule-
   specific holes). It may NOT import `signal_intelligence.feature_engine`
   - so `engine.run_backtest()` takes `compute_feature_series` as an
   INJECTED callable; the real dispatcher
   (`application.services.strategy_execution.compute_feature_series`,
   Checkpoint 26) is supplied only at the application layer, where
   `.importlinter` contract 3's layering permits composing both
   contexts.
2. Import-linter's `ignore_imports` matches the EXACT source/target
   module pair named in `.importlinter` - not any submodule pair. An
   earlier draft of `research.backtesting.contracts`/`.engine` importing
   `trading_engine.strategy_execution.contracts` directly (rather than
   the package's own `__init__`) broke the contract; fixed by routing
   every cross-context import through `research/backtesting/__init__.py`.

## Strategy reuse (Part 4) - no duplicate implementation

The engine calls the exact same `Strategy.evaluate()` Checkpoint 26's
live diagnostic coordinator calls, with the exact same
`StrategyConfigurationValues`. No `BacktestEmaStrategy` or equivalent
exists anywhere in this codebase. A repo-wide search for
`class.*Backtest.*Strategy` returns zero matches (Non-Redundancy Audit).

## Execution model (Part 5) - chosen and documented, never left implicit

- A signal computed from bar `i`'s CLOSE (the bar's own documented
  close-time convention) is never executable at that same instant.
- Entry and every direction-flip exit fill at bar `i+1`'s OPEN - the
  first price actually observable after the decision. This is the
  single deterministic rule; no other timing exists.
- If the series ends with a position open, it force-closes at the FINAL
  bar's own CLOSE (`reason="end_of_data"`) - the last bar that exists,
  not future information.
- Feature series are computed ONCE over the full history (each output
  at index `i` depends only on `bars[0..i]` - Checkpoint 15-17's own
  proven non-look-ahead-by-construction property).

**No-look-ahead is proven, not just asserted**, by
`tests/unit/research/test_backtesting_engine.py`: truncating the bar
series at any point never changes an earlier decision
(`test_future_bars_do_not_affect_earlier_signals`), entries never fill
at the signal bar's own price, and warm-up is respected.

## Cost model assumptions (Part 3, explicitly labeled MODEL ASSUMPTIONS)

- **Brokerage**: a flat percentage of notional value on both entry and
  exit. Not a verified Indian brokerage/STT/GST formula - no
  authoritative source was available to verify against this checkpoint,
  so the simpler, honestly-labeled model was chosen over fabricating
  precision that cannot be justified.
- **Slippage**: a flat percentage price adjustment against the trader on
  every fill.
- **Position sizing**: `FIXED_QUANTITY` (an integer share count) or
  `PERCENT_OF_EQUITY` (a fraction of current running equity, whole-share
  rounding down, no margin/leverage modeled).
- **Max concurrent positions**: only `1` is supported by this POC
  engine - the field exists for forward compatibility and is validated
  against (rejecting any other value), never silently ignored.

Every `BacktestResult` carries these assumptions verbatim in its
`data_quality` disclosure - never left implicit (Part 24).

## Trade ledger, equity curve, metrics

`SimulatedTrade` is immutable, carries full strategy attribution
(`strategy_id`/`specification_version`/`code_version`/
`configuration_version`), and includes `mfe`/`mae` computed from the
trade's own entry-to-exit holding-period bars (Part 9).

`EquityPoint`s are derived from the trade ledger only - sampled at each
trade-close event plus a starting point. **Known POC limitation**: the
engine does not mark open positions to market between bars; the equity
curve reflects realized P&L at trade-close events only.

`BacktestMetrics` covers Total/Winning/Losing Trades, Win Rate, Gross
Profit/Loss, Net P&L, Profit Factor (`None` when gross loss is zero -
never fabricated as infinity), Max Drawdown, Average Trade/Winner/Loser,
and Sharpe/Sortino. **Sharpe/Sortino are computed on a PER-TRADE return
series (net_pnl / capital-at-entry), never an annualized daily-return
figure** - trade timestamps are irregular and no daily-return series
exists; labeled "trade-level, non-annualized" everywhere they are
surfaced (API, UI, this doc) to avoid a misleading number, and reported
as `None` when fewer than 2 trades exist.

## Reproducibility (Part 10/11)

`BacktestResult.backtest_id` is a deterministic SHA-256 hash of the
configuration identity + data identity (instrument/timeframe/date-range/
bar count/first-last timestamp) - never a random UUID. Two identical
runs produce byte-identical trades, equity curve, and metrics (proven by
`test_two_identical_runs_produce_identical_results`); re-running an
identical configuration through the API upserts the same persisted row
rather than creating a duplicate (proven by
`test_rerunning_identical_configuration_upserts_same_backtest_id`).

## Bias controls (Part 25/26)

- No-look-ahead: proven above.
- Survivorship bias: the historical/fixture data this platform uses does
  not track delisted/inactive securities - every `BacktestResult`
  discloses this explicitly (`survivorship_bias_note`). Not
  institutional-grade backtesting.
- SAMPLE_BAR: `DataQualityLabel.SAMPLE_BAR` exists in the contract for
  forward-compatibility, but is never actually reachable today - the
  only wired data source is `HistoricalMarketDataRepository` via
  `FixtureHistoricalMarketDataRepository`/future historical adapters,
  never live SAMPLE_BAR. If it ever were used, the UI renders "NOT
  SUITABLE FOR TRADING-GRADE PERFORMANCE CLAIMS" prominently.

## Persistence

`BacktestResultRecord` (Django, JSONField `result_payload` - mirrors the
`StrategyConfigurationRecord`/`UniverseVersion` JSONField precedent
rather than a relational trade/equity-point schema, which this POC's
scope does not require). Upserts by `backtest_id`. `WatchlistRecord` and
`StrategyResearchStatusRecord` are similarly small, purpose-built
tables - see their own model docstrings for why each is separate from
existing Checkpoint 5-26 concepts rather than overloading them.

## UI architecture

`BacktestingWorkbenchPage.tsx` implements Discover -> Configure ->
Backtest -> Review in one page (Parts 12-16), reusing the exact same
`ParameterSchemaFields` component Checkpoint 26's Strategy Configuration
screen uses (extracted into `common/components/ParameterSchemaFields.tsx`
specifically so the Backtest Workbench never duplicates strategy fields
- Part 14's own explicit instruction). Charts (`EquityChart.tsx`) are
plain inline SVG - no charting framework was introduced (Part 17: "do
not introduce a huge charting framework without justification"; two
simple line charts do not justify one). `ComparisonPage.tsx`,
`WatchlistPage.tsx`, and `StrategyMonitorPage.tsx` are separate, small
pages for Parts 19-21 - never merged into a live-trading-flavored UI (no
"Buy"/"Sell"/"Deploy Live" control exists anywhere in this codebase).

## Files

- `research/backtesting/{contracts,engine,errors,serialization}.py`
- `application/services/{backtesting,watchlist,strategy_research_status}.py`
- `infrastructure/api/{backtesting_views,watchlist_views,strategy_research_status_views}.py`
- `frontend/src/features/backtesting/{BacktestingWorkbenchPage,ComparisonPage,WatchlistPage,StrategyMonitorPage}.tsx`
- `frontend/src/common/components/{ParameterSchemaFields,EquityChart}.tsx`
- `tests/unit/research/test_backtesting_engine.py`
- `tests/unit/architecture/test_backtesting_sample_bar_boundary.py`
