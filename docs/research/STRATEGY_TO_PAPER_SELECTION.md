# Strategy-to-Paper Selection (Checkpoint 36 Part 6)

## Decision

**Exactly one strategy is wired into the Strategy -> Signal -> Risk -> Paper
Order bridge: `ema_crossover` (EMA Crossover), via
`src/intraday/application/services/paper_signal_execution.py`.**

No other registered strategy is wired this checkpoint. This is a deliberate
narrowing, not an oversight — the checkpoint asks for "exactly ONE existing
strategy with evidence," not the broadest set that compiles.

## Why `ema_crossover` and not another registered strategy

| Criterion | EMA Crossover | Other registered strategies |
|---|---|---|
| Independently reference-validated | Yes — Checkpoint 30 built an external, hand-computed reference implementation and diffed it bar-by-bar against the engine's own EMA Crossover output; zero `UNEXPLAINED_MISMATCH`. | No equivalent independent reference validation exists for any other strategy in this repository as of Checkpoint 36. |
| Used as the running example across checkpoints | Yes — the primary illustrative strategy in Checkpoints 27, 28, 29, 30 (backtest engine construction, differential testing, reference validation). | Other strategies exist in the registry but have not been the subject of repeated, deep verification. |
| Fixture behavior already proven | Yes — the exact "flat warm-up bars, then a clean directional run" fixture shape that reliably forces a real BULLISH crossover was proven correct in Checkpoint 30 and is reused verbatim in this checkpoint's tests (`tests/unit/application/services/test_paper_signal_execution.py::_uptrend_bars`). | Not proven for this checkpoint's purposes. |
| Computation is simple enough to reason about at the paper-order boundary | Yes — two EMAs and a crossover comparison; no state carried across bars beyond the EMA accumulators the engine already manages. | Strategies with position-aware or multi-bar-memory logic would need separate, undone verification that their state resets correctly between paper-trading evaluation calls. |

## What "wired" means precisely

`PaperSignalExecutionService` is constructed with a
`StrategyExecutionCoordinator` built the standard way
(`build_default_registry()` -> `registry.activate("ema_crossover")` ->
`build_coordinator(registry)` — the exact same composition backtesting and
diagnostics use, per the checkpoint's "do not create a parallel strategy
execution framework" instruction). No strategy-specific branching exists
inside `paper_signal_execution.py` itself — the module is strategy-agnostic
by construction (it filters `CoordinatorResult.signals` by whatever
`strategy_id` the caller passes in). Activating a second strategy in the
registry and passing its `strategy_id` would work mechanically today; it is
withheld because no second strategy has the evidence trail above yet, and
adding one without that evidence would be exactly the kind of
evidence-free feature growth this checkpoint explicitly forbids.

## Lineage, end to end

```
strategy_id + configuration_version   (ema_crossover, v1)
        |
        v
StrategyExecutionCoordinator.run(bars, {...})   -> StrategySignal (direction, price, timestamp)
        |
        v
derive_signal_id(strategy_id, configuration_version, instrument_id, timestamp)
        |  deterministic sha256 - same inputs always produce the same ID,
        |  never random (mirrors research.backtesting's own
        |  _deterministic_backtest_id() precedent, Checkpoint 27)
        v
OrderIntent(signal_id=..., idempotency_key=str(signal_id), strategy_id=...)
        |
        v
PaperTradingService.submit_order(...)   -> risk-gated, then PaperBroker
        |
        v
PaperOrderRecord.signal_id (durable ledger, migration 0011)
        |
        v
PaperTradeRecord / PaperPositionRecord   (existing FK-free but order_id-linked lineage, Checkpoint 35)
```

Every step above is proven by a passing test in
`tests/unit/application/services/test_paper_signal_execution.py` (8/8
passing): a real BULLISH signal produces a real filled paper order; a flat
series produces no order; the same signal evaluated twice is not
double-submitted; the kill switch blocks strategy-generated orders exactly
as it blocks manual ones; `derive_signal_id` is deterministic and
timestamp-sensitive; an empty bar series is skipped cleanly; the order that
reaches the broker carries the same `signal_id` the result object reports.

## What is explicitly NOT done this checkpoint

- **No automatic trigger.** Nothing calls `evaluate_and_submit()` against
  live or `SAMPLE_BAR` market data automatically. Bars are supplied by the
  caller in every current call site (tests only). See
  `PAPER_TRADING_ARCHITECTURE.md` for the reasoning — wiring this against
  live data without a dedicated design review would itself be a premature
  feature per this checkpoint's own governing principle.
- **No API endpoint** exposes `PaperSignalExecutionService` yet. The
  service is a real, tested backend capability, not a reachable operator
  action, until that data-source decision is made deliberately.
- **No second strategy** is activated for paper trading.
