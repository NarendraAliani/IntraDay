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

---

# Checkpoint 28 additions: trust level, mark-to-market, portfolio, cost model

## Backtest Trust Level (Part 3)

`BacktestTrustLevel`: `POC` / `RESEARCH_READY` / `VALIDATION_READY` /
`PRODUCTION_RESEARCH_READY`. Every result this engine produces today is
`POC` - promotion is never automatic. Measurable criteria for the next
level, `RESEARCH_READY`:

1. Mark-to-market equity/drawdown implemented and tested (done, this
   checkpoint).
2. Multi-instrument portfolio capital accounting invariants proven
   (done, this checkpoint).
3. A verified (not assumed) Indian brokerage/STT/GST cost model,
   checked against an authoritative published fee schedule.
4. At least one backtest validated against an independent, trusted
   reference (e.g. a well-known charting platform's own reported
   trade-level outcome for the same instrument/period) to catch
   systematic engine bugs no unit test would reveal.
5. `TRADING_GRADE_BAR` data (Checkpoint 25.1's own six-condition
   checklist) available as an alternative data source, so a result can
   state it did NOT run on sampling-limited data.

None of these five are satisfied yet. `VALIDATION_READY` and
`PRODUCTION_RESEARCH_READY` are not yet defined in detail - defining
them precisely before condition 1-5 above are met would be premature
specification of an unreached milestone.

## Mark-to-market equity (Part 4/5/6)

`MarkToMarketPoint` - one per bar, separating `realized_pnl` (cumulative,
from closed trades) from `unrealized_pnl` (0 unless a position is open
at that bar). **Mark-price convention**: unrealized P&L is valued at
that bar's own CLOSE (never intrabar high/low, which would silently
pick a favorable/adverse price). The equity identity
`initial_capital + realized_pnl + unrealized_pnl == total_equity` holds
at every bar - proven by `test_equity_identity_holds_at_every_bar`.

`max_drawdown`/`max_drawdown_percent` are now derived from this
mark-to-market curve, not the realized-only trade-close `EquityPoint`
curve (which is KEPT, unchanged, per Part 4's explicit instruction -
still the authoritative realized-only view). `max_drawdown_duration_bars`
is the longest streak of consecutive bars spent below the running peak.

Proven adversarially: `test_intrabar_adverse_move_is_captured_even_if_
trade_recovers_before_exit` injects a severe adverse bar into an
otherwise-profitable trade and confirms `max_drawdown > 0` even though
the trade itself never closes at a loss - the realized-only curve alone
could never show this.

## Portfolio / multi-instrument backtesting (Part 7/8/9)

`research/backtesting/portfolio.py` - built entirely on the
single-instrument primitives factored into `execution.py`/
`cost_model.py`/`metrics.py` (Part 27 non-redundancy carried forward).
`engine.run_backtest()` is completely unchanged and remains correct for
`max_concurrent_positions == 1`.

**Scope, explicit**: every instrument in one portfolio run must share
identical bar timestamps (same timeframe, same aligned session) - the
engine validates this and raises `InvalidBacktestConfigurationError`
rather than guessing an alignment. Not a general multi-timeframe engine.

**Capital accounting invariants** (Part 8, enforced, tested):
- `available_cash` decreases by an entry's own notional at entry,
  increases by `entry_notional + net_pnl` at exit (equivalent to the
  single-instrument engine's realized net P&L).
- An entry whose notional exceeds `available_cash` is REJECTED, never
  partially filled, never allowed to drive cash negative - proven by
  `test_capital_never_goes_negative_and_no_money_is_created`.
- An entry is REJECTED once `max_concurrent_positions` positions are
  already open, regardless of cash - proven by
  `test_max_concurrent_positions_1_matches_single_instrument_style_behavior`
  (no overlapping intervals) and
  `test_max_concurrent_positions_5_allows_up_to_5_open_positions`.
- Duplicate instrument assignments are rejected at configuration time -
  one open position per instrument, never two simultaneous strategies on
  the same instrument.

**Attribution** (Part 9): `PortfolioBacktestResult.trades` reuses
`SimulatedTrade` unchanged - no second trade type. Strategy A ->
instrument X, Strategy B -> instrument Y, and "same strategy, multiple
instruments" are all proven in
`test_attribution_preserved_across_multi_strategy_multi_instrument`.

## Cost model abstraction (Part 10/11)

`cost_model.CostModel` (Protocol) + `FlatPercentageCostModel` (the only
implementation, carried over unchanged from Checkpoint 27's inline
calculation, now isolated behind the Protocol). Both `engine.py` and
`portfolio.py` call `CostModel.brokerage()`/`.slippage_adjusted_price()`
- neither inlines a formula. Explicitly labeled MODEL ASSUMPTION - not a
verified Indian brokerage/STT/GST/exchange-charge schedule (no
authoritative source was available to verify against in this
checkpoint). Extension points identified but NOT implemented (Part 11's
own scope limit): fixed-points slippage, spread-based, volatility-based,
liquidity-aware models, and a verified Indian cost schedule - each would
be a second `CostModel` implementation, requiring no engine change.

## Bar semantics / quantitative bias audit (Part 12/13)

Backtesting consumes bars exclusively through
`HistoricalMarketDataService.get_bars()` (Checkpoint 14/18/27), which
already calls `domain.market_data.quality.ensure_chronological()` -
duplicate timestamps raise `DuplicateBarTimestampError`, out-of-order
bars raise `OutOfOrderBarError`, BEFORE any bar reaches the engine.
Proven (not merely asserted) by
`tests/unit/research/test_bar_semantics_and_bias_audit.py`. No gap-
filling or synthetic bar is ever fabricated (`ResultValidationSummary.
data_gaps_note` honestly states gap detection is not performed, rather
than reporting a false "0 gaps").

Look-ahead audit, reconfirmed this checkpoint:
- Signal computed from bar `i`'s close never fills before bar `i+1`'s
  open (`test_entry_never_fills_at_the_signal_bars_own_price`).
- Truncating the bar series never changes an earlier decision
  (`test_future_bars_do_not_affect_earlier_signals`).
- Indicator warm-up bars produce no signal at all
  (`test_indicator_warmup_is_respected_no_trade_before_warmup`).
- Portfolio decisions never see another instrument's future bars or
  results - each instrument's signal series is precomputed independently
  from its own bars only (`execution.compute_signals`), before any
  cross-instrument capital-allocation decision is made.
- Comparison (`ComparisonPage.tsx`) only ever reads already-persisted
  `BacktestResult` rows - it cannot influence or re-trigger the original
  simulation.

## MFE/MAE semantic distinction (Part 25)

Reconfirmed and now mechanically guarded:
`tests/unit/research/test_mfe_mae_semantics.py` proves
`research.backtesting.execution.mfe_mae` never imports
`signal_intelligence.theoretical_outcome`, is a distinct function object,
and has a structurally different signature (`holding_bars`, a variable-
length trade-defined window, vs. `theoretical_outcome`'s own fixed
`horizon_bars` integer) - the two computations can never be accidentally
conflated.

## Result validation summary (Part 15)

`ResultValidationSummary` - `bar_count`, `signal_count`, `trade_count`,
`warmup_bars`, `skipped_signals` (same-direction signal while a position
was already open), `rejected_trades` (entry computed a zero quantity),
and an honest `data_gaps_note`. Every field is COUNTED from the actual
simulated path, never estimated.

## Reproducibility across the full stack (Part 17)

Proven not just at the engine level (Checkpoint 27) but through
persistence + API serialization + API retrieval:
`test_displayed_result_matches_stored_result_exactly_after_roundtrip`
asserts the immediately-returned run response and the subsequently
GET-fetched, persisted response are byte-for-byte dict-equal.
`test_rerunning_same_configuration_produces_identical_persisted_payload`
confirms re-running an identical configuration through the real API
produces an identical `backtest_id`, trades, mark-to-market curve, and
metrics.

## Data quality gate levels (Part 14)

Frontend (`BacktestingWorkbenchPage.tsx`): `FIXTURE_OR_HISTORICAL` is
rendered as an informational badge; `SAMPLE_BAR` (unreachable today,
since no live-data path is wired - see the safety-gate section above)
would render as a warning badge plus the explicit "NOT SUITABLE FOR
TRADING-GRADE PERFORMANCE CLAIMS" text. No BLOCKING level exists in the
UI because corrupted/rejected data never reaches a result at all - the
API rejects it (via `ensure_chronological`) before a `BacktestResult`
is ever constructed, which is a stronger guarantee than a UI-level block.

## Browser UX validation (Part 2/27)

**Not available in this environment** - no Playwright/Selenium/browser-
automation tooling is installed (`import playwright` fails; no
`node_modules/.bin/playwright`). Not claimed as performed. Frontend
correctness for this checkpoint's changes was validated via
`vitest`/Testing Library against the real components (network mocked at
the `fetch` boundary only) plus `tsc --noEmit`/`vite build`, matching
Checkpoint 27's own documented limitation.
