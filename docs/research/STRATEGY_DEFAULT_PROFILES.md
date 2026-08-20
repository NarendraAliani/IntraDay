# Strategy Default Profiles

Checkpoint 64.17. Documents the conservative baseline defaults applied
to `ParameterDefinition.default` for each of the three executable
strategies, and the future backtesting research matrix that should
challenge them. **Nothing in this document is a claim of optimal
profitability.** Every value here is a research starting point only —
actual performance can only be established by running the existing
backtesting engine (Checkpoint 27/63.x) against real historical data.

## Canonical source of truth

The ONLY place a default value is defined is `ParameterDefinition.
default` inside each strategy's own `parameter_schema()` method:

```
Strategy.parameter_schema()
    -> ParameterDefinition.default
    -> strategy_configuration_views.py (API, serialized verbatim)
    -> generated TypeScript contract (api-types.ts)
    -> ParameterSchemaFields.tsx (generic frontend form, pre-fills from `default`)
```

No duplicate default dictionary exists anywhere else in this codebase
(audited this checkpoint — the only other place `.default` is read is
`strategy_configuration_views.py`, which serializes the schema
verbatim). This document is descriptive of that single source, not a
second one.

A default is consulted ONLY when an operator opens a blank NEW
configuration form. Once a `StrategyConfigurationRecord` is saved with
its own explicit values, that record is permanently independent of
whatever the schema's `default` is later changed to — proven by
`test_changing_a_strategys_default_does_not_mutate_an_existing_
configuration_record` (`tests/unit/infrastructure/persistence/
test_strategy_configuration_repository.py`).

## Conservative baseline defaults (Checkpoint 64.17)

### EMA Crossover (`ema_crossover`)

| Parameter ID | Value | Was |
|---|---|---|
| `fast_lookback` | 12 | 9 |
| `slow_lookback` | 26 | 21 |

### SMA Trend Filter (`sma_trend_filter`)

| Parameter ID | Value | Was |
|---|---|---|
| `lookback` | 30 | 20 |
| `band_percent` | 0.75 | 0.2 |

### ATR Volatility Breakout (`atr_volatility_breakout`)

| Parameter ID | Value | Was |
|---|---|---|
| `lookback` | 14 | 14 (unchanged) |
| `atr_multiplier` | 2.0 | `None` (no default at all) |
| `stop_loss_atr_multiplier` | 1.0 | 1.0 (unchanged) |
| `target_1_atr_multiplier` | 1.5 | 1.5 (unchanged) |
| `target_2_atr_multiplier` | 2.5 | 2.5 (unchanged) |
| `target_3_atr_multiplier` | 3.5 | 4.0 |
| `trailing_stop_atr_multiplier` | 1.0 | 1.0 (unchanged) |

## Research profiles (naming convention for future backtesting)

These are documented profile *names* for organizing future backtest
runs — no automatic optimizer or profile-selection UI was built this
checkpoint (explicitly out of scope, §16). "Conservative" here means
"the current schema default," never "empirically best."

- **Conservative** — the current schema defaults above. The starting
  assumption every new configuration begins from.
- **Balanced** — a shorter-lookback variant intended to react faster,
  still using the same risk:reward multiplier ladder for ATR.
- **Aggressive** — the shortest-lookback variant, tightest neutral band,
  intended to generate more signals per session at the cost of more
  noise. Empirical performance for ANY of these three labels is
  determined only by running the existing backtesting engine against
  real historical data — this document makes no performance claim for
  any of them.

## Experiment matrix (§17 — future backtesting inputs, not yet run)

Documented so a future checkpoint's backtest sweep has a concrete,
reproducible starting matrix, using the real parameter IDs above — not
run this checkpoint (no automatic optimizer was built, per §16's
explicit instruction).

### EMA Crossover (`fast_lookback` / `slow_lookback`)

| Profile | fast_lookback | slow_lookback |
|---|---|---|
| Aggressive | 5 | 13 |
| Balanced | 9 | 21 |
| Conservative (current default) | 12 | 26 |

### SMA Trend Filter (`lookback` / `band_percent`)

| Profile | lookback | band_percent |
|---|---|---|
| Aggressive | 10 | 0.25 |
| Balanced | 20 | 0.50 |
| Conservative (current default) | 30 | 0.75 |

### ATR Volatility Breakout (`lookback` / `atr_multiplier` /
`stop_loss_atr_multiplier` / `target_1_atr_multiplier` /
`target_2_atr_multiplier` / `target_3_atr_multiplier` /
`trailing_stop_atr_multiplier`)

| Profile | lookback | atr_multiplier | stop_loss | target_1 | target_2 | target_3 | trailing |
|---|---|---|---|---|---|---|---|
| Balanced | 14 | 1.5 | 1.0 | 1.5 | 2.5 | 4.0 | 1.0 |
| Conservative (current default) | 14 | 2.0 | 1.0 | 1.5 | 2.5 | 3.5 | 1.0 |

These profiles are research inputs for a future backtesting sweep, never
a trading recommendation. Running them requires nothing new — the
existing `HistoricalBacktestRunOrchestrator` (Checkpoint 63.x) already
accepts arbitrary `strategy_values` per run.
