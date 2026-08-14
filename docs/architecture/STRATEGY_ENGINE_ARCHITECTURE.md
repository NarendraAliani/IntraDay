# Strategy Engine Architecture (Checkpoint 26)

## Objective

Register, configure, and run multiple executable strategies against
fixture/historical bars, with a single canonical parameter schema the
frontend renders generically - without connecting any of it to live
trading. This document covers the domain/execution design; see
[STRATEGY_CONFIGURATION.md](STRATEGY_CONFIGURATION.md) for the
persistence/API/frontend layers.

## Identity chain

```
StrategyIdentity (Checkpoint 5, domain.strategy)
      |
StrategySpecification  -- not a separate type: "specification_version"
      |                    is a version-label string on StrategyVersion
StrategyParameterSchema (NEW, trading_engine.strategy_execution.contracts)
      |
StrategyConfigurationValues (NEW) -- validated parameter VALUES
      |
StrategyVersion (Checkpoint 5) -- version-IDENTITY record, unchanged
      |
ExecutableStrategy (NEW, implements the `Strategy` Protocol)
      |
StrategySignal (NEW) -- strategy-attributed directional signal
```

`domain.strategy.contracts.StrategyVersion` (Checkpoint 5) was, before
this checkpoint, the only strategy-related contract in the codebase and
deliberately carried no parameter VALUES - its own prior comment in
`application/config_schema/strategy.py` explicitly deferred that design
to "whichever future checkpoint first defines a concrete strategy
specification shape." This checkpoint is that checkpoint. `StrategyVersion`
itself is **unchanged** - it remains the version-identity/activation
record; `StrategyConfigurationValues`/`StrategyConfigurationRecord` are
layered alongside it, never replacing it.

## Why strategies never read Django/env/ORM/broker directly

Every strategy implements `trading_engine.strategy_execution.strategy.Strategy`
(a `Protocol`): `parameter_schema()`, `required_features(config)`,
`evaluate(bar, feature_values, config)`. All inputs are plain Python
values (`Bar`, `dict[str, FeatureValue]`, `StrategyConfigurationValues`)
- no strategy imports Django, an environment variable, an HTTP client,
or the ORM. This is proven by `.importlinter` contract 2 ("bounded
contexts must not depend on infrastructure") and re-verified live during
this checkpoint's own audit.

## The bounded-context-independence finding

`.importlinter` contract 4 ("Bounded-context independence") forbids
`intraday.trading_engine` from importing `intraday.signal_intelligence`
at all. An early draft of this checkpoint's coordinator/strategies
imported `signal_intelligence.feature_engine.sma/.ema/.atr` and
`signal_intelligence.signal_generation.contracts.SignalDirection`
directly, breaking that contract. Caught by re-running `lint-imports`
(Part 2's own "verify against the existing rules" instruction), and
fixed two ways:

1. **`StrategyDirection`** - a small enum, structurally identical to
   `SignalDirection` (BULLISH/BEARISH/NEUTRAL), defined locally in
   `trading_engine.strategy_execution.contracts`. Not imported from
   `signal_generation` (forbidden) and not promoted into
   `domain.shared_kernel` (locked to its originally-approved 14
   contracts since Checkpoint 3). A deliberate, small duplication of
   *vocabulary* forced by two independent architecture rules, not a
   second signal *model*.
2. **Feature computation dispatch** - moved out of
   `trading_engine.strategy_execution.coordinator` (which now takes a
   `compute_feature_series` callable, injected) into
   `application.services.strategy_execution.compute_feature_series`,
   where cross-bounded-context composition is architecturally
   permitted (`.importlinter` contract 3's layering: application ->
   bounded contexts -> domain).

## Canonical signal integration (Part 16)

`signal_intelligence.signal_generation.contracts.DirectionalIndication`
(Checkpoint 18) is untouched. It is the fixed-shape output of exactly
one rule (`generate_directional_indication` - hard-coded
`sma`/`ema`/`atr` fields, fixed `definition_name`/`definition_version`
constants) and cannot represent an arbitrary strategy's evidence.
`StrategySignal` (new, `trading_engine.strategy_execution.contracts`)
generalizes what `DirectionalIndication` fixes in place - a three-state
direction plus `FeatureValue` evidence tuple - and adds exactly what no
existing type carries: `strategy_id`/`specification_version`/
`code_version`/`configuration_version` attribution. This is the
evolution `DirectionalIndication`'s own Checkpoint 18 docstring
predicted ("future strategy layer will consume DirectionalIndications...
to eventually produce a real domain.signal.Signal"), not a second
competing pipeline. `StrategySignal` still does not become
`domain.signal.Signal` - no stop-loss/target/position-size authority is
claimed.

## Canonical field/feature registry

`signal_intelligence.feature_engine.field_registry.list_fields()` is the
single source of truth for every selectable field: raw OHLCV (from
`domain.market_data.contracts.Bar`) plus SMA/EMA/ATR (the only three
features `signal_intelligence.feature_engine` actually implements).
No RSI/VWAP/MACD/Bollinger/Supertrend entry exists - Part 4/10
explicitly forbids listing unimplemented indicators. The registry does
not duplicate `feature_engine/definitions.py`'s own
`SimpleMovingAverageDefinition`/etc. identities; it only *describes*
what those already-computed values mean, for selection/validation.

## Multi-strategy execution: shared features, failure isolation

`StrategyExecutionCoordinator.run(bars, configurations)`:

1. Computes the union of every active strategy's `required_features()`
   field_ids, calling the injected feature dispatcher **exactly once**
   per distinct field_id (proven by
   `test_coordinator_scenario_c_shared_feature_computed_once`, which
   counts real dispatcher calls - not inferred).
2. Evaluates each active strategy inside its own `try/except`. One
   strategy raising never prevents another from producing a signal
   (`test_coordinator_scenario_b_one_strategy_failure_is_isolated`).
   No strategy calls another strategy or the coordinator itself.

## The three strategies (Part 3: genuinely different, not cosmetic)

| Strategy | Shape | Required features | Parameters |
|---|---|---|---|
| EMA Crossover | two-EMA crossover vs. price | `ema_<fast>`, `ema_<slow>` | `fast_lookback`, `slow_lookback` |
| SMA Trend Filter | single-feature-vs-price with a neutral band | `sma_<lookback>` | `lookback`, `band_percent` |
| ATR Volatility Breakout | volatility-threshold on bar range | `atr_<lookback>` | `lookback`, `atr_multiplier` |

All three use only existing, tested SMA/EMA/ATR - no new indicator was
implemented to hit a strategy count.

## Activation is not trading authorization (Part 14)

`StrategyRegistry.activate()`/`get_active()` governs which strategies the
`StrategyExecutionCoordinator` runs for research/diagnostics/backtesting.
It has no connection whatsoever to `trading_engine.risk_engine`,
`order_management`, `broker_abstraction`, or the kill switch - none of
which this checkpoint touches. A strategy being "active" in the registry
means "eligible to produce a diagnostic `StrategySignal`", nothing more.

## SAMPLE_BAR safety gate (Part 15)

`application.services.strategy_execution.DiagnosticStrategyExecutionService`
is the **only** orchestration point that feeds bars into the
coordinator. It depends solely on `HistoricalMarketDataService`
(fixture/historical-only, the exact Checkpoint 18 `SignalGenerationService`
pattern) and imports nothing from `infrastructure.persistence.
live_market_data_repositories`, `application.services.bar_aggregation`,
or any Dhan module. Proven mechanically by
`tests/unit/architecture/test_strategy_execution_sample_bar_boundary.py`
(ast-based import scan), not merely documented. `SAMPLE_BAR` (Checkpoint
24A/25.1's own classification) remains blocked from live/actionable
signal execution; that boundary is unchanged and unrelated to this
checkpoint's registry-activation concept above.

## Files

- `signal_intelligence/feature_engine/field_registry.py`
- `trading_engine/strategy_execution/{contracts,errors,strategy,registry,coordinator}.py`
- `trading_engine/strategy_execution/strategies/{ema_crossover,sma_trend_filter,atr_volatility_breakout}.py`
- `application/services/{strategy_configuration,strategy_execution}.py`
- `tests/unit/trading_engine/test_strategy_execution.py`
- `tests/unit/architecture/test_strategy_execution_sample_bar_boundary.py`
