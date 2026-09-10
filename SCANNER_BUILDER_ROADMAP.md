# Discretionary Screening Feature ("Scanner Builder") — Recon + Roadmap

Status: **read-only investigation, deliberately uncommitted** (same
convention as `GAINZ_ROADMAP.md`/`VWAP_STRATEGY_ROADMAP.md`/
`ORB_STRATEGY_ROADMAP.md`/`SINGLE_ENV_AUTHORIZATION_PROPOSAL.md`). No
code was written or modified to produce this document.

## Part 1 — Inspection findings

### 1. What `ScannerConfiguration` actually does today

`[F]` Re-confirmed directly against the current code (not trusted from
`RECON-GAINZ-ARCHITECTURE`'s own citation alone) — **still accurate**.
`ScannerConfiguration` (`persistence/models.py`,
`application/contracts/scanner_configuration.py`) is a single
singleton row per provider holding: `enabled`, `timeframe`,
`universe_mode` (`ALL_CONFIGURED`/`SELECTED`/`WATCHLIST`),
`selected_instrument_ids`, `selected_watchlist_name`,
`selected_strategy_ids`, `selected_notification_channels`. **It has no
concept of a condition, a field, an operator, or a threshold anywhere
in its schema.** It is purely: which instruments, which timeframe,
which registered `Strategy` ids, which notification channels, on/off.
The live worker reconciles against it once per aggregation cycle and
feeds `selected_strategy_ids` straight into
`run_active_loop_tick()`/`StrategyExecutionCoordinator`.

### 2. Reusable indicators in `signal_intelligence/feature_engine/`

`[F]` The real, active location is
`src/intraday/signal_intelligence/feature_engine/` (a `signal_intelligence/`
directory also exists at repo root but only holds a `README.md` — not
where the actual implementation lives; sourced from the correct path
directly, not assumed). The canonical registry
(`feature_engine/field_registry.py`, `list_fields()`) is **already a
mature, 27-field catalog** — far more than the reference site's own
example list already exists here:

| field_id | What it is |
|---|---|
| `open`/`high`/`low`/`close`/`volume` | raw OHLCV |
| `sma`, `ema` | Simple / Exponential Moving Average (parameterized lookback) |
| `atr` | Wilder Average True Range |
| `rsi` | Wilder RSI |
| `adx`, `plus_di`, `minus_di` | Wilder ADX / +DI / -DI |
| `relative_volume` | current vol / trailing mean vol (RVOL) |
| `macd_hist` | standard 12/26/9 MACD histogram |
| `candle_body_ratio` | \|close-open\| / (high-low) |
| `bullish_engulfing`, `bearish_engulfing` | 2-candle patterns (0/1) |
| `price_delta` | signed N-bar close-to-close delta |
| `price_vs_ma_pct_sma`, `price_vs_ma_pct_ema` | signed % distance from MA |
| `ma_divergence_sma`, `ma_divergence_ema` | fast-vs-slow MA divergence % |
| `rebound_candidate` | composite context flag (0/1) |
| `rolling_breakout` | N-bar Donchian-style breakout/breakdown (-1/0/1) |
| `vwap` | session-anchored VWAP |
| `opening_range_high`, `opening_range_low` | fixed opening-window high/low |
| `market_regime` | categorical BULL/BEAR/SIDEWAYS/TRANSITION |

Every one of these is a real, tested, standard-TA-convention
implementation — **exactly the raw material "pick a field, operator,
value" needs**, already parameterizable (`ema_20`, `rsi_14`,
`macd_hist_12_26_9`, etc. via `field_registry.parse_feature_name()`/
`resolve_feature_name()`) and already dispatched through ONE existing
pure function: `application/services/strategy_execution.py`'s
`compute_feature_series(field_id, bars) -> tuple[FeatureValue, ...]`.
This dispatcher takes a resolved field_id and a `Bar` sequence and
returns computed values — **it has no dependency on `Strategy`, the
registry, or the execution coordinator; it is a pure
field-name-to-values function** that any new caller could import and
call directly. (Note: it currently lives inside
`strategy_execution.py` — a naming/location detail worth resolving in
Phase A, see Architecture Boundary below, not a functional coupling.)

### 3. Existing ad-hoc, whole-universe query mechanism

`[F]` **None exists.** Checked directly:
- `BacktestingService.run()` operates on exactly ONE
  `config.instrument_id` per call — no multi-instrument loop anywhere
  in that service.
- The live scanner's own per-sweep loop
  (`signal_pipeline_runtime.promote_bars_and_trigger_signals()`) DOES
  iterate a whole universe, but it is tightly wired to
  `run_active_loop_tick()` (strategy execution) for every instrument —
  not reusable as a generic "evaluate a condition" loop without
  dragging the strategy pipeline along with it.
- No `screener`/`rule_builder`/`condition_builder`/`adhoc` concept
  exists anywhere in the codebase (grepped `src/` and `frontend/src/`
  directly — zero real matches).

**A universe-wide ad-hoc evaluator would need new (but thin)
orchestration**: loop over the operator's selected instruments,
fetch each one's recent bars via the EXISTING read-only
`DjangoHistoricalBarRepository.get_bars()` (or, for real-time
freshness, `DjangoAggregatedBarRepository.get_recent()` — see below),
call the EXISTING `compute_feature_series()` per field the condition
references, evaluate the comparison, combine via AND/OR. No new
compute logic, no new data-access primitive — genuinely new only at
the orchestration layer.

### 4. What data a condition would actually evaluate against

`[F]` This is the single most important, most honestly-complicating
finding. **Two genuinely different data sources exist, and they answer
"Close > EMA(20)" very differently**:

- **`HistoricalBar`** (the canonicalized/migration-backed table this
  entire session's `CHECKPOINT_83`–`89` work has been about) — this is
  END-OF-DAY / backfilled data, **not live**. Evaluating a condition
  against it answers "was this true on some past closed trading day,"
  never "is this true right now." It also inherits every one of this
  project's own current, real data-completeness gaps (only 18-27
  gate-verified days per symbol as of `CHECKPOINT_89`, an active,
  unresolved constraint — see `PROJECT_STRATEGY_STATUS.md`).
- **`AggregatedBarObservation`** (`DjangoAggregatedBarRepository`,
  `infrastructure/persistence/live_market_data_repositories.py`) —
  this IS the real-time, session-scoped bar table
  `run_market_data_worker.py` writes to (`aggregate_and_persist()`),
  separate from `HistoricalBar` entirely. `get_recent()` already
  exists as a read-only accessor. **This is what "Close > EMA(20),
  right now" would actually need to query.**

**The honest constraint**: `AggregatedBarObservation` is only ever
populated while a live worker process is genuinely running — this
project has no standing, always-on market-data service (confirmed
repeatedly across every `LIVE-*`/`CHECKPOINT_8x` checkpoint this
session: the worker is an operator-launched process, not a daemon).
**A "live" screener therefore only works during market hours, only
while an operator has already launched the worker for some other
reason (a live paper session) — it cannot be a standalone "check
anytime" tool** without either (a) launching a worker just for
screening (a new, separately-justified operational action, not free),
or (b) accepting it only ever shows end-of-day data outside an active
session, with this project's own current, real data-completeness
gaps attached.

### 5. Existing frontend condition-builder-style UI

`[F]` **No existing condition-builder UI anywhere** — checked directly
(`frontend/src`, no `filter`/`condition`/`rule` component exists).
**But one genuinely reusable primitive already exists**:
`ParameterSchemaFields.tsx`'s own `FIELD_REFERENCE` case already
renders a `<select>` populated from `FieldDefinition[]` (the exact
same registry `field_registry.py` exposes) — this is literally the
"pick a field" half of "pick a field, operator, indicator" already
built and already wired to the live field registry via the API. The
"pick an operator" (`>`, `<`, `>=`, `<=`, `==`) and "combine with
AND/OR" pieces have no existing analogue anywhere and would be
genuinely new UI.

## Part 2 — Roadmap

### 1. Scope recommendation — honestly small, not the reference site's scale

The reference site screens thousands of stocks end-of-day. This
project's own reality: a **4-6 symbol universe** (the same
`RELIANCE`/`TCS`/`HDFCBANK`/`INFY`/`ICICIBANK`-class set every
`LIVE-PAPER`/backtest checkpoint has used), intraday timeframes, and —
per finding 4 above — real-time data available only during an active
session. A realistically-scoped version:

- **Universe**: the operator's own existing configured universe
  (reuse `InstrumentPicker.tsx`, already built) — not "all NSE
  stocks." At this scale, a full-table scan is instant; there is no
  performance problem to design around, unlike the reference site's
  own thousands-of-rows case.
- **Conditions**: single field vs. constant (`RSI(14) < 30`) or field
  vs. field (`Close > EMA(20)`), combined with AND/OR, no nested
  groups initially — the reference site's own advanced nested-group
  UI is not needed at this scale and would be pure UI complexity for
  no real benefit yet.
- **Data mode, explicit and visible to the operator**: two clearly
  labeled modes, never silently blended —
  **"Live" (requires an active worker session, evaluates
  `AggregatedBarObservation`)** and **"Historical" (evaluates
  `HistoricalBar`, explicitly dated, subject to this project's own
  known coverage gaps, shown honestly if a symbol/day isn't
  gate-verified)**. Never presenting historical results as if they were
  live, or vice versa.
- **Output**: a simple table (matched instrument, the field values that
  made it match, timestamp) — not a saved/scheduled/alerted screener
  in the first version. Re-run is a manual button click.

### 2. Architecture boundary — how this never touches `Strategy`/paper-trading

- **A new, separately-named service**, e.g.
  `application/services/adhoc_screening.py` (`AdhocScreeningService`
  or similar) — imports `compute_feature_series` (relocate it out of
  `strategy_execution.py` into a neutral module, e.g.
  `feature_engine`'s own dispatch, or a small new
  `application/services/feature_computation.py` shared by both callers
  — a one-time, mechanical extraction, not a behavior change) and
  `field_registry.py` directly. **It never imports `Strategy`,
  `StrategyRegistry`, `StrategyExecutionCoordinator`,
  `run_active_loop_tick`, `PaperBroker`, or `ScannerConfiguration`.**
- **A new condition-evaluation domain type** (e.g.
  `domain/screening/contracts.py`: `ScreeningCondition(field_id,
  operator, comparison_value_or_field)`, `ScreeningRule(conditions,
  combinator)`) — deliberately NOT reusing `Strategy`'s own
  `ParameterDefinition`/signal-decision types, even though both
  reference the same field registry. A condition is not a strategy
  parameter and should not be forced to look like one.
  `docs/architecture/CANONICAL_TRADE_LIFECYCLE_AND_PNL_ARCHITECTURE.md`-
  style separation: this produces a MATCH/NO-MATCH table, never a
  `SignalRecord`, never a `BUY`/`SELL`/`HOLD` decision.
  `test_api_boundaries.py`'s own architecture-fitness-function
  discipline (already enforced in this codebase) would be the natural
  place to add "screening never imports strategy_execution/paper
  broker" as an explicit, tested boundary.
- **Its own API endpoints and its own frontend page** — a new
  `ScreenerPage.tsx` under a new `frontend/src/features/screening/`
  directory, its own route, never embedded inside
  `StrategyConfigurationPage`/`BacktestingWorkbenchPage`/the Live Paper
  Operations Console. Shares only genuinely generic UI primitives
  (`InstrumentPicker`, the `FIELD_REFERENCE` dropdown pattern from
  `ParameterSchemaFields.tsx`, `Pagination`).
- **No new write path to anything strategy/paper-trading-related.**
  The only new persistence (if any is added at all — see Phase A/B
  below) would be the screener's own rule definitions, in a new table,
  never touching `ScannerConfiguration`, `SignalRecord`,
  `PaperOrderRecord`, or `MigrationRun`/`HistoricalBar`.

### 3. Phased build sequence

- **Phase A — pure evaluation, no persistence, no UI.** A single
  `evaluate_condition(field_id, operator, value, bars) -> bool` pure
  function plus a thin `AdhocScreeningService.screen(rule, instrument_ids,
  timeframe, mode) -> tuple[ScreeningMatch, ...]` orchestrator, reusing
  `compute_feature_series` and `get_bars()`/`get_recent()` exactly as
  they exist today. Fully unit-tested against fixture bars, zero DB
  writes, zero API surface. Proves the core mechanism cheaply before
  any UI investment.
- **Phase B — read-only API + minimal UI, Historical mode only.** One
  `POST /api/screening/evaluate` endpoint (rule + universe + date range
  in, matches out — no persistence of the rule itself yet), and a
  single-page UI: field/operator/value picker (reusing the existing
  `FIELD_REFERENCE` dropdown component), a "Run" button, a results
  table. Historical mode only, since it needs no live worker
  dependency and is safe to build/demo any time. Honestly labeled with
  this project's own current data-coverage caveat where a selected
  day/symbol isn't gate-verified.
- **Phase C — Live mode.** Add the `AggregatedBarObservation`-backed
  path, gated behind "requires an active worker session" (checked via
  the same `WorkerRuntimeStatus` read every other live-facing screen
  already uses) — explicit, visible, never silently falling back to
  stale historical data if live isn't available.
- **Phase D (optional, only if Phase B/C prove genuinely useful in
  practice) — saved rules.** A `ScreeningRule` table so a rule can be
  named/reused across sessions, still never wired to
  `ScannerConfiguration` or any automated trigger — running a saved
  rule remains an explicit, manual, operator-initiated action every
  time, exactly like today's manual backtest runs.
- **Explicitly out of scope, indefinitely, not just "not yet"**:
  scheduled/automated screening, alerting on a match, any path from a
  screening match to an order or a `SignalRecord` — any of those would
  turn this into an undeclared second strategy-signal pathway, exactly
  what this checkpoint's own framing warns against.

### 4. Honest complications — including whether this is worth doing now

- **Real-time data availability is the single biggest constraint**,
  not a minor detail: "Live" mode only works while a worker is
  already running for some other reason. This isn't a "screen the
  market whenever curious" tool as initially envisioned by the
  reference-site comparison — it's closer to "see which of my current
  live-session symbols match this condition, right now, while I
  happen to be running one."
- **Historical mode inherits this project's own current, real,
  actively-being-worked-on data gap**: as of `CHECKPOINT_89`, only
  18-27 gate-verified days exist per symbol (of a 47-day target this
  session's own recent checkpoints have been grinding toward). A
  screener built on `HistoricalBar` today would frequently report "no
  data" or incomplete results for many requested date ranges — not a
  screener bug, but a direct, honest consequence of where the
  project's data actually stands right now.
- **Said plainly, per this checkpoint's own explicit instruction**:
  **this reads as a lower-priority, genuinely-nice-to-have feature
  relative to what is actually occupying and blocking this project
  right now.** The last ~10 checkpoints of this session (`CHECKPOINT_83`
  through `CHECKPOINT_90`, plus both `LIVE-PAPER` sessions) have been
  entirely about (a) closing the migration/canonicalization gap toward
  the 47-day strategy-tuning threshold and (b) hardening the live
  worker/supervisor infrastructure that same live data depends on. A
  discretionary screening UI does not move either of those forward —
  it's a genuinely separate, operator-facing convenience feature, not
  something the strategy-validation pipeline needs to function. It is
  also NOT free: even Phase A/B, done properly with this project's own
  established rigor (tests, architecture-boundary enforcement, an
  honest data-mode split), is real implementation effort competing
  with that same higher-priority work.
- **This is not a reason to refuse the feature** — it's a legitimate,
  reasonably-scoped idea with real reusable building blocks already in
  place (the field registry, the compute dispatcher, the
  `FIELD_REFERENCE` UI pattern) — but it should be explicitly
  operator-prioritized against the data-completeness/tuning-threshold
  work, not started on the strength of a competitor screenshot alone.
  If the operator's own priority is "I want to explore stocks myself
  while I wait for the data gap to close," Phase A/B (no live-data
  dependency, cheap, fully decoupled) is a genuinely reasonable
  parallel-track use of time; Phase C (Live mode) should wait until
  it's clear the live-worker infrastructure itself has stabilized
  further, given `CHECKPOINT_90`'s own recent orphaned-process finding
  in that exact subsystem.
