# GainzAlpha — Phased Roadmap (Recon)

Status: read-only investigation output. No code changed. Not committed
(per this checkpoint's own rule — leave uncommitted for operator review).

## 0. Headline finding: a Gainz adapter ALREADY EXISTS

`src/intraday/trading_engine/strategy_execution/strategies/gainz_compatible_research.py`
(Checkpoint 64.99) is a working `GainzCompatibleResearchStrategy`,
`strategy_id="gainz_compatible_research"`, profile `alpha` only. It:

- Implements the real `Strategy` protocol (`parameter_schema`,
  `required_features`, `evaluate`) plus `build_trade_plan` (not part of
  the frozen Protocol, but the same optional method
  `atr_volatility_breakout.py` also carries).
- Implements 8 of the reference engine's shared-base "alpha" conditions
  using ONLY canonical, already-tested features (EMA/RSI/ADX/±DI/MACD
  hist/relative volume/candle body ratio/bullish+bearish engulfing/
  price_delta).
- Documents 3 deliberately OMITTED conditions as blockers: (A) 20-bar
  breakout/breakdown — no canonical rolling-high/low feature existed at
  64.99; (B) RSI momentum ("rising vs previous bar") — the `Strategy`
  interface hands only the CURRENT bar's feature values, no 1-bar lag
  channel; (C) `regime` labeling — classified not-yet-available at 64.99.
- Uses an equal-weight (1/8 each) scoring scheme, explicitly NOT the
  reference's 25/15/12/10/8/7 weights and NOT the 0.72/0.28
  dominant-score/separation formula this task's prompt describes.
- Is deliberately **not registered** in `build_default_registry()`
  (`registry.py:88-90` registers only `EmaCrossoverStrategy`,
  `SmaTrendFilterStrategy`, `AtrVolatilityBreakoutStrategy`) — so it is
  unreachable from both the live scanner and the backtest API today.

**This changes the roadmap's shape.** The near-term plan below is not
"build Gainz from scratch" — it is "close 64.99's documented gaps,
adopt the prompt's scoring formula as a deliberate, separately-approved
change, add config presets, register it, and walk-forward it," each as
its own small checkpoint. Section 2 lays this out as Phases A–D,
re-mapped onto the actual starting point.

One correction to 64.99's own record: BLOCKER C (regime) is **no
longer accurate** — `market_regime` (`signal_intelligence/feature_engine/
market_regime.py`, Checkpoint 65.08, four states BULL/BEAR/SIDEWAYS/
TRANSITION, ADX+DI/EMA-based) was built one checkpoint after 64.99, via
`compute_feature_series`'s `market_regime` branch
(`application/services/strategy_execution.py:183-184`). A future Gainz
phase can now use it — but see honest complication #3 below on how it
scores (it's a separate, non-strategy Market Context feature).

## 1. Repository inspection findings (Part 1)

### 1.1 The `Strategy` interface

`src/intraday/trading_engine/strategy_execution/strategy.py:22-46` —
`Strategy(Protocol)`:

```
strategy_id: str
display_name: str
specification_version: str
code_version: str

def parameter_schema(self) -> StrategyParameterSchema: ...
def required_features(self, config: StrategyConfigurationValues) -> tuple[str, ...]: ...
def evaluate(self, bar: Bar, feature_values: dict[str, FeatureValue], config: StrategyConfigurationValues) -> StrategySignal | None: ...
```

- `parameter_schema()` returns a `StrategyParameterSchema` (`contracts.py:107-118`),
  an ordered tuple of `ParameterDefinition` (`contracts.py` ~line 60-103:
  `parameter_id`, `label`, `parameter_type` [INTEGER/DECIMAL/ENUM per
  `ParameterType`], `required`, `default`, `minimum`, `maximum`,
  `allowed_values`, `help_text`). `default` is the single canonical
  source of truth for a new configuration's starting values
  (`ema_crossover.py:40-52` comment).
- `required_features(config)` returns the `field_id`s (canonical feature
  registry names, e.g. `"ema_12"`, `"rsi_14"`) the strategy needs
  computed — lets the coordinator compute shared features once, not
  per-strategy (`strategy.py:30-34`). `EmaCrossoverStrategy.required_features`
  (`ema_crossover.py:79-82`) is the minimal reference example.
- `evaluate(bar, feature_values, config)` returns a `StrategySignal | None`
  — `None` means "no opinion" (insufficient warm-up etc.), mirrored by
  every strategy including the Gainz adapter (`gainz_compatible_research.py:557-562`).
  `feature_values` is `dict[str, FeatureValue]` — **one value per
  field_id, at the CURRENT bar only** — this is the exact mechanism
  behind BLOCKER B above (no previous-bar channel exists).
- `StrategySignal` (`contracts.py` ~line 309+): `strategy_id`,
  `specification_version`, `code_version`, `configuration_version`,
  `instrument_id`, `timeframe`, `timestamp`, `direction`
  (`StrategyDirection` BULLISH/BEARISH/NEUTRAL), `price` (`Decimal`),
  `evidence: tuple[FeatureValue, ...]`.
- Optional, not part of the frozen Protocol but used by 2 of 4 concrete
  strategies (`atr_volatility_breakout.py`, `gainz_compatible_research.py:659-724`):
  `build_trade_plan(bar, feature_values, config, signal) -> TradePlan | None`,
  returning `TradePlan` (`entry_price`, `stop_loss`, `target_1..3`,
  `calculation_method`).

`compute_feature_series(field_id, bars) -> tuple[AnyFeatureValue, ...]`
(`application/services/strategy_execution.py:109-185`) is the ONE
dispatcher from a `field_id` string to a real indicator function —
parses `"ema_12"`/`"macd_hist_12_26_9"`/etc. via
`feature_engine.field_registry.parse_feature_name`, then calls the
matching `compute_*` function over the full `bars` tuple for that
instrument+timeframe. It is injected into `StrategyExecutionCoordinator`
(constructor param, `build_coordinator()` at line 188-191) rather than
imported directly by `trading_engine`, per `.importlinter` contract 4
(module header, lines 31-38). `DiagnosticStrategyExecutionService.run()`
(lines 194-215) is the only orchestration entry point: it pulls bars for
ONE `instrument_id`/`timeframe`/date range from `HistoricalMarketDataService`
and hands them to the coordinator.

### 1.2 Scanner concept

A "scanner" concept exists but is **symbol-selection/lifecycle
simulation only — no signal scoring or ranking**:

- `ScannerConfiguration` (Django model, via
  `infrastructure/persistence/migrations/0021_scannerconfiguration_and_more.py`
  and later migrations 0023/0024/0035) + `application/contracts/scanner_configuration.py`
  + `application/repositories/scanner_configuration.py` — persists scan
  parameters (universe, session window, notification channels).
- `application/services/scanner_lifecycle_simulation.py` — simulates
  scan session lifecycle (start/stop/progress), not signal generation.
- `infrastructure/market_data_providers/dhan/scanner_universe.py` —
  builds the symbol universe to scan (watchlist), a Dhan-adjacent data
  concern.
- `infrastructure/api/scanner_configuration_views.py` constructs
  `_registry = build_default_registry()` (same registry as backtesting)
  but I found **no scoring/ranking logic** in the scanner files
  themselves — direct grep for "ranking"/"score" inside
  `scanner_lifecycle_simulation.py` returned zero matches. Conclusion:
  today's "scanner" is a watchlist/session-lifecycle mechanism that
  presumably runs the SAME registered strategies against a universe of
  symbols, not a distinct Gainz-style multi-factor scoring/ranking
  engine. (I did not exhaustively trace every scanner API view's runtime
  behavior — this is Part-1-inspection-level confidence, not a full
  behavioral audit; flagged as such rather than overstated.)

### 1.3 Multi-timeframe access — NOT available (make-or-break, confirmed)

Single-timeframe only, at every layer checked:

- `DiagnosticStrategyExecutionService.run(instrument_id, timeframe, start, end, configurations)`
  (`strategy_execution.py:205-214`) takes exactly ONE `timeframe: Timeframe`.
- `compute_feature_series(field_id, bars: tuple[Bar, ...])` operates
  over a single flat bar series — no per-timeframe partitioning
  concept.
- `run_backtest(bars, strategy, strategy_config, backtest_config, compute_feature_series, ...)`
  (`research/backtesting/engine.py:149-159`) also takes one flat `bars`
  tuple; `BacktestConfiguration` (`research/backtesting/contracts.py`
  line ~60) carries a single `instrument_id` and single `timeframe`
  field (grepped, one occurrence each in that dataclass region plus one
  in a second dataclass at line ~132 — no `timeframes: tuple[...]` or
  equivalent plural field anywhere in that file).
- `Strategy.evaluate(bar: Bar, feature_values: dict[str, FeatureValue], ...)`
  — `bar` is a single `Bar` (one instrument, one timeframe, one instant
  — `domain/market_data/contracts.py:51-71` docstring), and
  `feature_values` keys are plain feature names (`"ema_12"`), not
  `(timeframe, feature_name)` pairs — there is no namespacing that would
  let two timeframes' `ema_12` coexist in the same dict.

**Conclusion: this is confirmed, not inferred — a strategy today cannot
see more than one timeframe in the same `evaluate()` call.** Any
Gainz phase claiming multi-timeframe confirmation must either (a) be
scoped to single-timeframe only, or (b) treat multi-timeframe support
as its own prerequisite architecture checkpoint, never assumed away.

### 1.4 Indicator/feature inventory

`src/intraday/signal_intelligence/feature_engine/` contains, as
existing, reusable, presumably-tested `compute_*` functions (18 files):
`atr.py`, `bearish_engulfing.py`, `bullish_engulfing.py`,
`candle_body_ratio.py`, `directional_movement.py` (ADX/+DI/-DI),
`ema.py`, `macd_histogram.py`, `ma_divergence.py`, `market_regime.py`
(BULL/BEAR/SIDEWAYS/TRANSITION, Checkpoint 65.08), `price_delta.py`,
`price_vs_ma_pct.py`, `rebound_candidate.py`, `relative_volume.py`,
`rsi.py`, `sma.py`, plus `definitions.py` (parameter dataclasses) and
`field_registry.py` (name parsing). `compute_feature_series` dispatches
all of these (`strategy_execution.py:151-184`).

**Already reusable for a Gainz-style scorer:** trend (EMA/SMA,
ma_divergence, price_vs_ma_pct), momentum (RSI, MACD histogram),
volatility (ATR), volume (relative_volume), structure/candle
(bullish/bearish engulfing, candle_body_ratio, rebound_candidate),
direction/trend-strength (ADX/+DI/-DI), and now regime classification
(market_regime).

**Genuinely missing (would need new work), confirmed by the
`gainz_compatible_research.py` module header's own blocker list plus
this recon's own check of `field_registry`/`definitions.py`:**
- 20-bar breakout/breakdown (rolling N-bar high/low crossing) — BLOCKER A,
  still not present as of this recon (no `breakout`/rolling-high-low
  compute function found in the 18-file inventory above).
- A previous-bar (1-bar-lag) feature-value channel at the `Strategy.evaluate()`
  boundary — BLOCKER B, an architecture gap in `strategy.py`/`coordinator.py`,
  not a missing indicator per se.
- The prompt's specific "0.72×dominant_score + 0.28×separation" scoring
  formula and its rejection-reason-code taxonomy — neither exists
  anywhere in this codebase today (searched; only 64.99's own
  independent equal-weight scheme exists, explicitly NOT that formula).

### 1.5 `StrategyConfigurationRecord` / `StrategyResearchStatusRecord` / preset pattern

- `StrategyConfigurationRecord` (`infrastructure/persistence/models.py:182-225`):
  one immutable row per `(strategy_id, specification_version,
  code_version, configuration_version)`, `parameter_values` as one
  JSONField (mirrors `UniverseVersion.members`'s precedent), `created_at`,
  `created_by`. `StrategyConfigurationService.save_configuration(...)`
  (`application/services/strategy_configuration.py`, ~line 39) is the
  write path — it takes an explicit `configuration_version` string
  label and a values dict; there is no enum/fixed-set of preset names
  anywhere in code.
- **Correction to this task's own framing:** grepping the whole repo
  for "conservative"/"balanced"/"aggressive"/`_PRESET` found **no
  literal `ema_conservative`-style preset records or preset name
  constants**. What actually exists is a SINGLE canonical default
  parameter set per strategy, expressed as `ParameterDefinition.default`
  in `parameter_schema()` (documented as the "CONSERVATIVE BASELINE
  research starting point" in `ema_crossover.py:40-52`, and reconfirmed
  in `docs/architecture/STRATEGY_EXTENSIBILITY_AND_RESEARCH_ARCHITECTURE.md`
  §3's table: EMA 12/26, SMA 30/0.75, ATR 14/2.0/1.0/1.5/2.5/3.5/1.0).
  Multiple "presets" (conservative/balanced/aggressive) are a pattern
  this project's tooling *supports* (any number of
  `StrategyConfigurationRecord` rows can share a `strategy_id` with
  different `configuration_version` labels and different
  `parameter_values`) but has **never actually been exercised** for any
  of the 3 registered strategies — there is exactly one baseline default
  each, not three. Phase C below should say this precisely rather than
  imply an existing 3-preset pattern is being "reused."
- `StrategyResearchStatusRecord` (`models.py:859-883`): a small,
  separate `(RESEARCH_ACTIVE|RESEARCH_PAUSED|DISABLED)` state per
  `strategy_id`, explicitly NOT a live-trading control
  (`StrategyResearchStatusService`, `application/services/
  strategy_research_status.py:16-41`). `get_status()` defaults to
  `RESEARCH_ACTIVE` for ANY strategy known to the registry that has no
  explicit row (`DEFAULT_STATUS`, line 17, used at line 27). **Nothing
  currently gates this on walk-forward proof** — `set_status()` (line
  29-34) is a plain, unconditional setter callable by any actor
  (`updated_by` is just a string, no walk-forward-passed check anywhere
  in this file or its repository Protocol). In other words: today,
  "RESEARCH_ACTIVE" is a manual/default administrative flag, not an
  automatically-earned status — Phase D's walk-forward gate is a
  **project-discipline convention this checkpoint would have to
  introduce and enforce procedurally**, not something the code itself
  currently enforces.

### 1.6 Decimal / IST enforcement boundary

Enforced at the `Strategy` interface boundary itself, not only deeper
in execution:

- `StrategyConfigurationValues.values: dict[str, object]` — raw, but
  `coerce_configuration_values(schema, values)` (`contracts.py:148-`)
  MUST run before `validate_configuration()`/before a strategy ever
  sees the dict, converting any DECIMAL-typed parameter's JSON-native
  value (`"0.02"` string or a float) to a real `Decimal` via
  `Decimal(str(value))` — explicitly to dodge `Decimal(float)`
  binary-precision bugs. `require_decimal`/`require_int`
  (`contracts.py:274-293`) then do a hard `isinstance` check when a
  strategy reads a value — `gainz_compatible_research.py` uses exactly
  these (`require_decimal(config.values, "rsi_alpha_threshold")` etc.,
  lines 577-580).
- `StrategySignal.price`, `Bar` OHLCV fields, `FeatureValue.value` are
  all `Decimal` (confirmed by `gainz_compatible_research.py`'s own
  arithmetic, e.g. `entry - sign * stop_multiplier * atr_value` all
  operating on `Decimal`s, lines 703-723).
- Timestamps: `Bar.timestamp` is **UTC, bar CLOSE time** — NOT IST —
  by explicit, re-confirmed design (`domain/market_data/contracts.py:59-67`
  docstring: "IST wall-clock conversion happens only at the presentation
  boundary, never here"). So there is no IST convention to adapt to at
  the `Strategy` interface at all — IST is deliberately kept OUT of this
  layer.

**Conclusion for Part 1.6:** a float-based Gainz port would need
float→Decimal conversion at every indicator/config boundary (matching
what 64.99 already did), but would need ZERO IST handling inside
`evaluate()`/`required_features()` — the interface is UTC-only by
design, and any IST display logic belongs strictly downstream.

## 2. Phased roadmap (MVP)

### Deferred, explicitly, pending Gainz (and this project's other 3
strategies) actually proving out on walk-forward first:

- F&O scanner (options-specific instrument selection/scoring).
- Consensus / multi-strategy voting (already frozen-DEFER once, at
  64.98, per `gainz_compatible_research.py`'s own header).
- A signal-lifecycle state machine (issued → confirmed → invalidated
  etc.) — does not exist for ANY strategy today; not Gainz-specific
  scope.
- Multi-timeframe scanning/scoring — confirmed NOT POSSIBLE today
  (§1.3) without new cross-cutting architecture; explicitly out of
  scope for the MVP, not quietly assumed.
- All 6 Gainz profiles (Trend/Breakout/Mean Reversion/Hybrid/Scalp/
  Consensus) — only ONE profile (hybrid/balanced, replacing the
  existing `alpha`-only scope) is in scope for the MVP.
- BLOCKER A (20-bar breakout feature) and BLOCKER B (previous-bar
  feature-value channel) remain deferred unless a future phase
  explicitly authorizes building them — the MVP does not silently
  route around them.

### Phase A — Feature/indicator layer (new, minimal)

Build ONLY what §1.4 found missing and the chosen profile actually
needs:
- A rolling N-bar high/low "breakout" feature (closes BLOCKER A) —
  smallest, most clearly-scoped addition; follows the existing
  `compute_*`/`*Definition`/field-registry pattern exactly (no new
  dispatch mechanism, per `strategy_execution.py`'s own precedent).
- Skip BLOCKER B (previous-bar RSI momentum) for the MVP — it requires
  an architecture change to `Strategy.evaluate()`'s and
  `StrategyExecutionCoordinator.run()`'s signatures (a 1-bar-lag
  feature-value channel), which is cross-cutting and affects every
  existing strategy's contract, not scoped to a single-strategy
  checkpoint. Document as still-deferred, not solved by omission.
- Anti-overfitting checklist concept (from the reference documents):
  applies here as "do not add a feature/threshold that exists only to
  make one backtest window look good" — each new feature gets its own
  unit tests against known-shape synthetic fixtures, same as the
  existing 18 feature-engine modules, before any strategy uses it.

### Phase B — `GainzAlphaStrategy` (rename/supersede the existing
`gainz_compatible_research` identity, or add alongside it — operator
decision), single profile only

- Recommend **hybrid/balanced** per the task prompt, not `alpha` —
  meaning this is a NEW strategy_id/condition set, not simply "finish
  alpha." Decide explicitly (in the checkpoint that does this work)
  whether to extend `GainzCompatibleResearchStrategy` in place or add a
  new class — both are structurally identical to `EmaCrossoverStrategy`
  per §1.1.
- Scoring: adopt the prompt's `0.72×dominant_score + 0.28×separation`
  formula as a **deliberate, documented replacement** of 64.99's
  equal-weight scheme — this is a real behavior change from existing
  code and must be flagged as such in the checkpoint's own summary, not
  silently reframed as "the same feature, better weighted."
  `dominant_score`/`separation` need their own precise definitions
  written into that checkpoint's spec before implementation (this
  roadmap does not invent them, matching the instruction not to invent
  reference-document detail beyond what was given).
- Rejection-reason-code taxonomy: attach as `evidence` entries or a new
  `FeatureValue`-shaped field, exactly how 64.99 attached
  `setup_quality_score` (§1.1, `evidence` tuple extension point,
  `contracts.py`'s `StrategySignal.evidence`) — never modifying the
  frozen `StrategySignal` schema itself.
- Regime classification: the now-available `market_regime` feature
  (§1.4) can be READ as an input condition/gate, same as any other
  canonical feature — but see honest complication #3 below on why this
  is not a drop-in fix for BLOCKER C's original framing.
- Decimal/UTC conventions: reuse `require_decimal`/`require_int`/
  `coerce_configuration_values` exactly as 64.99 already does (§1.6) —
  no new coercion pattern needed.
- Single-timeframe only (§1.3's confirmed finding) — the hybrid/balanced
  profile's logic must be expressible from ONE timeframe's feature
  values; any reference-document condition that inherently needs a
  second timeframe is OUT OF SCOPE for this phase, not approximated.

### Phase C — Three config presets (conservative/balanced/aggressive)

- Reuses the EXISTING, unmodified pattern: N `StrategyConfigurationRecord`
  rows sharing `strategy_id`/`specification_version`/`code_version` with
  three different `configuration_version` labels and three different
  `parameter_values` JSON blobs, written via
  `StrategyConfigurationService.save_configuration()` (§1.5).
- Per §1.5's correction: this would be the **first time** this project
  actually exercises more than one preset per strategy — say this
  plainly in the checkpoint, don't claim it as "the same pattern EMA
  Crossover already uses" (EMA Crossover has exactly one baseline
  default, not three presets).
- No new architecture: `ParameterDefinition.default` stays the single
  "new configuration" baseline (conservative, per this project's
  existing convention); "balanced"/"aggressive" are simply additional
  saved `StrategyConfigurationRecord` rows with wider/looser thresholds,
  never a code branch inside the strategy class itself.

### Phase D — Walk-forward validation (mandatory gate)

- Reference: `src/intraday/research/backtesting/walk_forward.py`
  (Checkpoint 68.2). It is a pure orchestration layer around the
  EXISTING, unmodified `engine.run_backtest()` (module header,
  lines 1-18) — computes fold boundaries from real bar timestamps
  (`_distinct_calendar_dates`, lines 75-79, using `bar.timestamp.date()`
  UTC) and calls `run_backtest()` once per (in-sample, out-of-sample)
  slice per fold (`WalkForwardFold`, lines 61-72), then aggregates
  `BacktestResult`s (`run_walk_forward_backtest`, line 185, returns
  `WalkForwardResult`, line 157). No API endpoint, no Django model, no
  persistence in that module (lines 13-18) — callers supply `bars`
  directly.
- A future Gainz walk-forward run would: register (or locally construct,
  mirroring 64.99's own `test_checkpoint_64_99_gainz_research_adapter.py`
  precedent of a LOCAL `StrategyRegistry()`) the new strategy, build a
  `StrategyConfigurationValues` for one preset at a time, pull real
  historical bars for one instrument/timeframe (§1.3 constraint — one
  timeframe per run), and call `run_walk_forward_backtest(...)` per
  Phase C preset — same discipline already used for the other 3
  strategies per Checkpoint 68.3/68.4/LIVE-2 (per this repo's own recent
  commit history — `git log` shows 68.2/68.3/68.4/LIVE-2 as the walk-
  forward build-out and smoke-test sequence for the existing strategies,
  none yet marked genuinely trustworthy per the latest commit's own
  message "gate rejected, new coverage-gap finding").
- This is the mandatory gate before any `RESEARCH_ACTIVE`-with-actual-
  confidence status or registry registration is treated as meaningful —
  per §1.5's finding, the code itself does not enforce this, so it must
  be enforced as checkpoint discipline (a human/process gate), stated
  explicitly rather than assumed automatic.
- Anti-overfitting checklist concept applies most heavily here: report
  in-sample vs out-of-sample degradation honestly per fold, do not
  cherry-pick a favorable fold, and follow this project's own recent
  precedent (68.4/LIVE-2 commits) of reporting negative/inconclusive
  walk-forward results as such rather than as passes.

## 3. Most important honest complications (Part 1 findings that
constrain the plan, stated plainly)

1. **Multi-timeframe genuinely does not exist** (§1.3, confirmed at 4
   separate layers: service, feature dispatcher, backtest engine,
   `Strategy.evaluate()` itself). Phase B is single-timeframe-only as a
   direct consequence — this is not a simplification choice, it is the
   only thing currently buildable.
2. **A Gainz strategy already exists and is intentionally unregistered**
   (§0). The roadmap is therefore "extend/supersede/register," not
   "build from zero" — a future checkpoint prompt must decide explicitly
   whether Phase B supersedes `gainz_compatible_research` (profile
   `alpha`) or adds a second, separate strategy_id, since both the
   `alpha`-equal-weight scheme and the prompt's 0.72/0.28 formula cannot
   both be "the" Gainz scoring inside one strategy_id without a version
   bump.
3. **`market_regime` exists now but is not a drop-in fix for BLOCKER C.**
   64.99 correctly noted that in the reference engine, `regime` was
   informational only (never a scoring input to bull/bear totals). The
   new canonical `market_regime` feature (BULL/BEAR/SIDEWAYS/TRANSITION)
   COULD be wired in as a real scoring/gating input for the hybrid/
   balanced profile, but doing so would be a genuinely NEW behavior
   choice (this project's `market_regime`, not the reference engine's
   regime, and not previously used by any strategy) — must be justified
   on its own, not assumed as "restoring" the reference's regime concept.
4. **The "3 presets reuse an existing pattern" framing in the task
   prompt is only partially accurate** (§1.5) — the MECHANISM exists
   (`StrategyConfigurationRecord` supports arbitrary
   `configuration_version` labels) but no strategy in this codebase
   has ever actually had more than one preset. Phase C is the first
   real exercise of that capability, and should be described as such.
5. **`StrategyResearchStatusRecord` does not currently enforce a
   walk-forward gate in code** (§1.5) — `RESEARCH_ACTIVE` is a default/
   manual flag. Phase D's "mandatory gate before active status" is a
   project-discipline commitment this checkpoint sequence must uphold
   procedurally; it is not something `strategy_research_status.py`
   itself will block if skipped.
6. **BLOCKER A and BLOCKER B are still open** (§1.4) — Phase A closes
   BLOCKER A only (new breakout feature); BLOCKER B (previous-bar
   feature-value lag) requires a cross-cutting `Strategy`/coordinator
   interface change affecting all 4 existing strategies, correctly kept
   out of this MVP's scope.
7. **Decimal handling is a solved, reusable pattern; IST handling is a
   non-issue at this boundary** (§1.6) — `Bar.timestamp` is UTC-only by
   explicit design, so no IST adaptation work is needed inside
   `evaluate()`/`required_features()` at all, contrary to what an
   IST-heavy reference engine might imply is necessary.
