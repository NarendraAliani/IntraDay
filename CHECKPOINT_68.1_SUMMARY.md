# CHECKPOINT 68.1 — Walk-Forward / Out-of-Sample Testing (DESIGN ONLY)

```
checkpoint: 68.1
verdict: DESIGN_PROPOSED
splitting_strategy_recommended: rolling window (anchored, expanding in-sample; short fixed OOS window), with a fixed single split as the honest fallback while real data is scarce
depends_on_64_25_resolution: NO for a single-fill / direction-flip strategy (ema_crossover, sma_trend_filter) — these run through run_backtest() today unmodified. YES for atr_volatility_breakout once/if a genuinely partial-exit TradePlan is exercised on real data — that strategy's equity curve is currently produced by run_backtest()'s single-fill model too, so it is NOT blocked today, but any future move to fill-granular partial-exit accounting for reporting purposes would need 64.25 resolved first. See §B4.
minimal_viable_scope: A single new orchestration function, run_walk_forward_backtest(), that calls the existing, completely unmodified run_backtest() N times over N pre-computed (in-sample, out-of-sample) date-range pairs, and returns a new WalkForwardResult dataclass bundling the N individual BacktestResult objects plus a small aggregate summary (mean/median OOS return, OOS win rate, in-sample-vs-out-of-sample degradation ratio). No change to engine.py, no new persistence model, no new API endpoint in v1 — a script/notebook-callable function and a printed report table, because real research-eligible data (0 rows today per RECON-BACKTEST §3) cannot yet support more than 2-3 narrow windows.
commit: <filled in after commit>
blockers: []
```

---

## A. How the engine currently works [F]

### A1. `engine.py::run_backtest()` (the live, single-fill engine)

- **Inputs**: `bars: tuple[Bar, ...]` (already loaded, already date-range-filtered by the
  caller — the engine itself does no date filtering), a `Strategy` + its
  `StrategyConfigurationValues` (both loaded by strategy_id/config_version, no
  in-engine tuning), a `BacktestConfiguration` (instrument, timeframe, start/end,
  position sizing, brokerage/slippage percentages, optional risk limits), a
  `compute_feature_series` callback, a `DataQualityDisclosure`, `generated_at`, and
  an optional `CostModel` override.
- **What it does**: computes strategy signals once over the full bar history
  (`compute_signals`), computes `TradePlan`s where the strategy produces one
  (`compute_trade_plans`), then walks bars once in a single forward pass. Entries
  always fill at the next bar's open; exits are either a signal-reversal flip (for
  `ema_crossover`/`sma_trend_filter`) or a precomputed, no-look-ahead SL/T1/T2/T3/
  trailing-stop simulation (`tradeplan_execution.simulate_tradeplan_exit()`, for
  `atr_volatility_breakout`); the final bar force-closes any still-open position.
  Costs are applied via an injected `CostModel` (production default:
  `IndianCashEquityIntradayCostModel`, NSE cash-equity intraday only).
- **What it outputs**: a `BacktestResult` — `trades` (one `SimulatedTrade` per
  round-trip position, single-fill-per-position: a TradePlan position is one trade
  even if it would have partially exited at T1/T2 in reality), a realized-only
  `EquityPoint` curve, a per-bar `MarkToMarketPoint` curve, `compute_metrics()`
  output (returns/drawdown/etc.), a `ResultValidationSummary` (signal/trade/
  rejection counts), cost-model identity, and `trust_level=BacktestTrustLevel.POC`
  (every result produced by this engine today is stamped POC, never a higher trust
  level — confirmed by RECON-BACKTEST §4's query of all 208 `BacktestResultRecord`
  rows).
- **One backtest run = one fixed date range, one strategy config, one pass.** There
  is no date-range subdivision, no repeated re-run, no held-out period anywhere in
  this function or its callers.

### A2. `historical_execution.py::run_stateful_backtest()` / `HistoricalExecutionSimulator`

- Fill-granular: drives the **real** domain risk/exit policy
  (`evaluate_order_risk()`, `evaluate_position_exit()`) through a per-bar loop via
  an in-memory `BrokerGateway`-shaped simulator, correctly handling partial exits
  (T1/T2 reduce a position's `remaining_quantity` without closing it).
- Produces `StatefulBacktestResult` — signal/risk-decision outcomes, per-position
  `StatefulPositionOutcome` records, final balance. **No `EquityPoint` curve, no
  `MarkToMarketPoint` curve at all.** This is checkpoint 64.25's exact,
  never-resolved finding.
- Explicitly documented in its own module header as "ADDITIVE, NOT A REPLACEMENT"
  of `run_backtest()`.

### A3. Which engine is actually live [F]

Traced both real API paths end to end:

1. **`POST /backtesting/run/`** → `backtesting_views.run_backtest_view()` →
   imports `run_backtest` directly from `intraday.research.backtesting.engine`
   (`backtesting_views.py:44`, called at `:225`). Synchronous.
2. **DB-first path** (`POST /historical-backtest-runs/...` and its Celery-dispatched
   task) → `historical_backtesting_views.py` → `dispatch_historical_backtest_run`
   → the orchestrator in `application/services/historical_backtest_run.py`, whose
   own header comment states plainly: *"Strategy lookup, feature computation, and
   `run_backtest()` [happen] elsewhere"* → routes through
   `application/services/backtesting.py::BacktestingService`, which imports and
   calls `run_backtest` from `engine.py` (confirmed by direct grep: `from
   intraday.research.backtesting.engine import run_backtest`, called at line 225).

**Both real, reachable API entry points call `engine.py::run_backtest()`.**
`run_stateful_backtest()`/`HistoricalExecutionSimulator` are imported and exercised
only from `src/intraday/research/backtesting/tests` (its own test suite) — grep for
`run_stateful_backtest|HistoricalExecutionSimulator` across `src/` finds matches
only inside `historical_execution.py` and `mark_to_market.py` (a module that itself
documents the same equity-curve gap), never from any `application/` or
`infrastructure/api/` caller. **This confirms RECON-BACKTEST §5 directly: the
stateful/fill-granular engine is real, tested, and completely unreachable from any
live request path today.**

### A4. Confirms no auto-tuning/optimizer exists [F]

Grepped `src/` for `optim|auto.tun|grid.search|hyperparam` (case-insensitive): 13
files matched, all unrelated hits (feature names like `directional_movement`,
`market_regime`, docstring mentions of "optimal" as English prose, a broker
`idempotency` module) — **no optimizer, tuner, or grid-search module of any kind**.
Parameters are manually chosen and saved as `StrategyConfigurationRecord` rows (12
total across 3 strategies, per RECON-BACKTEST §1). This matches RECON-BACKTEST's
claim; independently re-confirmed this run.

---

## B. Walk-forward design

### B1. Splitting strategy — recommend **rolling window, anchored/expanding
in-sample**, with an explicit fixed-split fallback

Given the actual available data volume (RECON-BACKTEST §3: **zero**
`REAL_DHAN`/`CANONICALIZED` rows today; the best-populated real scope is 10,562
`5m` `UNCANONICALIZED` bars for one `(NSE_EQ, FIVE_MINUTE, CAS_ERA)` scope — roughly
36-37 trading days of 5-minute bars for one instrument, and even that is not yet
research-eligible), a classic multi-fold rolling walk-forward (5-10 folds, each with
its own independent in-sample fit window) is **not realistic yet** — it would
require months of clean data per instrument to produce even 3-4 non-overlapping
windows with enough bars each to be statistically meaningful.

Recommended design, in priority order:

1. **Primary: rolling window, anchored (expanding) in-sample / fixed-size
   out-of-sample.** Split the available range into an initial in-sample window of
   `N` days, evaluate an out-of-sample window of the next `M` days immediately
   following it, then slide forward by `M` days and repeat, each time **including**
   all prior data in the (expanding) in-sample window rather than a fixed-width
   sliding window. Anchored/expanding is recommended over a fixed-width sliding
   window specifically *because* data is scarce — a fixed-width window would throw
   away already-scarce history on every slide; expanding uses everything available
   up to that point. `M` (the OOS window) should be small — days, not weeks — so
   that even a ~35-40 day dataset can produce 2-3 folds.
2. **Fallback: a single fixed split** (e.g. 70/30 or 80/20 by date, first N days
   in-sample, remaining days out-of-sample) when the available range is too short
   for even 2 rolling folds with a statistically meaningful bar count each. The
   design should **not force multi-fold rolling on a dataset where it would produce
   a 3-day OOS window from 10 bars** — that would manufacture a misleadingly
   precise-looking report from noise. The orchestration function should
   compute the fold plan from the actual bar count and degrade to a single split
   automatically (see §B5) rather than requiring a caller to know in advance.

### B2. What "in-sample" means for parameter fitting — honest statement

**No optimizer exists in this codebase (confirmed §A4).** All strategy parameters
are manually chosen and stored as `StrategyConfigurationRecord` rows. This means
"in-sample" in this design does **not** mean "fit an optimizer inside the in-sample
window" — there is nothing to fit automatically. It means: **evaluate a fixed,
already-manually-chosen configuration against the in-sample window, then evaluate
the SAME unmodified configuration against the immediately-following out-of-sample
window, and compare.**

This still has real, non-trivial value, stated plainly rather than oversold: it
answers "does this manually-chosen parameter set's performance generalize to data
the person choosing it did not look at while choosing it," which is a distinct and
weaker (but genuine) question from "did this optimizer overfit its search." Walk-
forward here is a **generalization check on a human's manual choice**, not a
guard against optimizer curve-fitting — because there is no optimizer to guard
against. If an optimizer is added later, this same splitting machinery becomes the
natural place to also re-fit parameters inside each in-sample window before
testing OOS — but that is out of scope for this checkpoint and not assumed here.

### B3. Reporting — concrete, not abstract

A walk-forward result should show, per fold and in aggregate:

- **Per-window table**: for each fold, in-sample window dates, OOS window dates,
  bar counts on each side, and each side's own `compute_metrics()` output (total
  return, win rate, max drawdown, trade count, Sharpe-like ratio if already computed
  by `compute_metrics()` — reuse whatever that function already reports, do not
  invent a new metric set).
- **Aggregate OOS metric**: mean and median OOS return/win-rate across folds (not
  in-sample — the in-sample number is never the headline result of a walk-forward
  report, it exists only for comparison).
- **In-sample vs out-of-sample degradation**: a simple ratio or difference
  (OOS return − in-sample return, or OOS/in-sample ratio) per fold and averaged —
  this is the single number that most directly answers "does performance survive
  contact with unseen data."
- **Explicit fold count and data-sufficiency disclosure**: the report must say
  plainly how many folds were produced and how many bars/days were in each window
  — given how little data exists today, a 1-fold or 2-fold result must be labeled
  as such, never presented with the same visual confidence as a hypothetical
  10-fold result. This mirrors the existing `trust_level=POC` /
  `DataQualityDisclosure` discipline `run_backtest()` already applies — the
  walk-forward report should carry an analogous disclosure field, not silently
  omit it.
- A per-bar or per-fold equity-curve comparison chart (in-sample curve vs OOS
  curve, or a bar chart of per-fold OOS return) is a reasonable v2 addition but is
  explicitly **not** part of the minimal viable version (§B5) — a table is
  sufficient to prove the concept and is far cheaper to build and to trust.

### B4. Which existing engine this attaches to — explicit dependency statement

**This design attaches to `engine.py::run_backtest()`, unmodified, called once per
fold.** Rationale:

- It is the only engine actually reachable from a live request path (§A3).
- All three registered strategies (`ema_crossover`, `sma_trend_filter`,
  `atr_volatility_breakout`) already run through it today, including the
  TradePlan/partial-exit-capable `atr_volatility_breakout` — `run_backtest()`
  represents a `TradePlan` position as a **single simulated trade** (single-fill
  model), which is a known simplification (64.25's finding) but is not a blocker
  for walk-forward validation itself: walk-forward only needs *some* consistent,
  already-trusted-enough-to-report P&L number per window, and `run_backtest()`'s
  number is exactly the number already being reported today for every one of the
  208 existing `BacktestResultRecord` rows.
- **This design does NOT depend on 64.25's resolution to be built and be useful.**
  It would produce results with the same fidelity/limitations `run_backtest()`
  already has today (single-fill P&L representation for partial-exit strategies).
  That limitation is inherited, not introduced, by this design.
- **It WOULD depend on 64.25's resolution** only if a future goal is to report
  walk-forward results using the fill-granular, partial-exit-correct accounting
  that `HistoricalExecutionSimulator` provides — that engine has no equity curve at
  all today (§A2), so no metrics comparable to `compute_metrics()`'s output exist
  for it yet. That is out of scope here and should be a separate, explicitly-named
  future checkpoint if ever pursued.

### B5. Minimal viable version — concrete and scoped to actual data volume

Given zero research-eligible rows today and ~36-37 days of real (not-yet-
canonicalized) 5-minute data as the best case once the migration eventually runs,
the smallest genuinely useful version is:

- A single new orchestration function that takes the **same inputs** `run_backtest`
  already takes (bars, strategy, config, backtest_config template) plus two new
  parameters: `min_oos_days` and `min_folds` (both with small conservative
  defaults, e.g. 5 and 1). It computes fold boundaries from the actual bar
  timestamps (not a hardcoded calendar assumption), calls `run_backtest()` once per
  fold — **no modification to `run_backtest()` itself, ever** — and if the data is
  too short to produce `min_folds` folds of `min_oos_days` each, it degrades to a
  single fixed split (or refuses with a clear "insufficient data for walk-forward"
  error rather than silently producing a misleading 1-bar OOS window).
- Output is a plain Python dataclass + a simple printed/logged table — **no new
  Django model, no new API endpoint, no new persistence** in v1. This keeps the
  blast radius at zero for P3 (no DB writes) and P6 (no network calls) and lets the
  operator validate the concept on whatever small real dataset becomes available
  once the canonicalization migration is eventually re-attempted, before investing
  in a persisted `WalkForwardRunRecord`/API surface that would be premature given
  current data volume.

---

## C. What would need to be built (plan only — not built this checkpoint)

1. **`src/intraday/research/backtesting/walk_forward.py`** (new file):
   - `@dataclass WalkForwardFold` — `in_sample_start`, `in_sample_end`,
     `out_of_sample_start`, `out_of_sample_end`, `in_sample_bar_count`,
     `out_of_sample_bar_count`.
   - `def compute_walk_forward_folds(bars: tuple[Bar, ...], *, min_oos_days: int, min_folds: int) -> tuple[WalkForwardFold, ...]`
     — pure function, no I/O, derives fold boundaries from bar timestamps only.
     Raises a dedicated `InsufficientDataForWalkForwardError` (mirrors the existing
     `InsufficientHistoricalDataError` naming convention already in
     `engine.errors`) when the data cannot support even one fold of the requested
     size.
   - `@dataclass WalkForwardResult` — `folds: tuple[WalkForwardFold, ...]`,
     `in_sample_results: tuple[BacktestResult, ...]`,
     `out_of_sample_results: tuple[BacktestResult, ...]`,
     `aggregate_oos_return`, `aggregate_oos_win_rate`,
     `mean_degradation_ratio`, `data_sufficiency_note: str` (the disclosure from
     §B3).
   - `def run_walk_forward_backtest(bars, strategy, strategy_config, backtest_config_template, compute_feature_series, *, data_quality, generated_at, cost_model=None, min_oos_days=5, min_folds=1) -> WalkForwardResult`
     — calls `compute_walk_forward_folds()`, then calls the **existing, unmodified**
     `engine.run_backtest()` twice per fold (once with `bars` sliced to the
     in-sample window, once to the OOS window), assembles the aggregate metrics.
     Zero changes to `engine.py`.
2. **Tests**: a new `tests/unit/research/test_walk_forward.py` — fold-boundary
   correctness (no overlap, no look-ahead across the IS/OOS boundary), the
   insufficient-data refusal path, and an end-to-end run against a small synthetic
   fixture proving the aggregate numbers are computed correctly from known
   per-fold `BacktestResult` inputs.
3. **No new API endpoint, no new Django model, no new report format beyond a
   printed/returned dataclass** in this minimal version — deferred to a later
   checkpoint once the concept is validated against real (even if small) data.

## D. Recommendation for the next checkpoint

Build **only** `compute_walk_forward_folds()` and `run_walk_forward_backtest()` as
scoped in §C, tested against synthetic fixture bars (not real data, since zero rows
are research-eligible today) — proving the splitting/aggregation logic is correct
in isolation from the data-availability problem. Do **not** attempt to wire it to a
new API endpoint or persistence model in the same checkpoint; that should wait
until the checkpoint 67.x canonicalization migration is actually re-attempted and
produces a non-zero research-eligible row count, so the next real usage of this
tool is against genuine data rather than another fixture-only exercise.
