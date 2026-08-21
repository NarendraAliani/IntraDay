# File: src/intraday/research/backtesting/execution.py
#
# Checkpoint 28: pricing/sizing/excursion primitives shared by both the
# single-instrument engine (`engine.py`) and the multi-instrument
# portfolio engine (`portfolio.py`) - factored out so Checkpoint 27's
# single-instrument logic is never re-implemented for the portfolio case
# (Part 27's own non-redundancy requirement, carried forward).
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from intraday.domain.feature.contracts import FeatureValue
from intraday.domain.market_data.contracts import Bar
from intraday.domain.order.contracts import OrderIntent
from intraday.research.backtesting import (
    Strategy,
    StrategyConfigurationValues,
    StrategyDirection,
    StrategySignal,
)
from intraday.research.backtesting.contracts import BacktestConfiguration, PositionSizingMode
from intraday.research.backtesting.position_lifecycle import BacktestPosition

FeatureSeriesComputer = Callable[[str, "tuple[Bar, ...]"], "tuple[FeatureValue, ...]"]


@dataclass
class OpenPosition:
    instrument_id: str
    direction: StrategyDirection
    entry_index: int
    entry_timestamp: datetime
    entry_price: Decimal
    quantity: Decimal
    order_intent: OrderIntent | None = None
    """Checkpoint 64.31: the REAL canonical `domain.order.contracts.
    OrderIntent` that represents this accepted entry - the SAME object
    `engine.py` builds via `order_intent_adapter.
    build_backtest_entry_order_intent()` for every accepted entry
    (constructed once, at entry time, never rebuilt per bar), and the
    SAME object fed to the risk gate when `BacktestConfiguration.
    risk_limits` is configured (never a second, separately-constructed
    OrderIntent). `None` only in the theoretical case a caller
    constructs `OpenPosition` directly without going through
    `run_backtest()`'s own entry branch (e.g. a future/alternate
    engine) - `run_backtest()` itself always supplies a real value."""
    position_lifecycle: BacktestPosition | None = None
    """Checkpoint 64.32: the REAL canonical `position_lifecycle.
    BacktestPosition` (Checkpoint 64.29's previously-unwired adapter,
    consumed here without modification) representing this accepted
    entry's OPEN/HELD/CLOSED lifecycle state. Constructed via
    `position_lifecycle.open_backtest_position()` at the moment this
    `OpenPosition` is created (always starts `OPEN`), then advanced to
    `HELD` in place (reassigned, since `BacktestPosition` is frozen -
    see that module's docstring) by `position_lifecycle.
    hold_backtest_position()` once the engine's own bar loop has let it
    survive past its entry bar with no exit - purely a REFLECTION of
    the engine's own existing state, never an independent decision
    about whether to hold or close. `None` only in the same theoretical
    direct-construction case as `order_intent` above; `run_backtest()`
    itself always supplies a real value."""


def signed_gross_pnl(
    direction: StrategyDirection, entry_price: Decimal, exit_price: Decimal, quantity: Decimal
) -> Decimal:
    if direction == StrategyDirection.BULLISH:
        return (exit_price - entry_price) * quantity
    return (entry_price - exit_price) * quantity


def quantity_for(
    sizing_mode: PositionSizingMode,
    sizing_value: Decimal,
    available_capital: Decimal,
    entry_price: Decimal,
) -> Decimal:
    """`available_capital` is the pool the sizing decision may draw
    from - the full running equity for the single-instrument engine, or
    the portfolio's own available cash for the multi-instrument engine
    (Part 8: sizing must never let the backtester "create money")."""
    if sizing_mode == PositionSizingMode.FIXED_QUANTITY:
        return sizing_value.to_integral_value(rounding="ROUND_DOWN")
    if entry_price <= 0:
        return Decimal("0")
    notional = available_capital * sizing_value
    return (notional / entry_price).to_integral_value(rounding="ROUND_DOWN")


def quantity_for_config(
    config: BacktestConfiguration, available_capital: Decimal, entry_price: Decimal
) -> Decimal:
    return quantity_for(
        config.position_sizing_mode, config.position_size_value, available_capital, entry_price
    )


def compute_signals(
    bars: tuple[Bar, ...],
    strategy: Strategy,
    strategy_config: StrategyConfigurationValues,
    compute_feature_series: FeatureSeriesComputer,
) -> tuple[list[StrategySignal | None], int, int]:
    """Computes one signal per bar (or `None` during indicator warm-up),
    shared by both `engine.py` (single-instrument) and `portfolio.py`
    (multi-instrument) so this logic is never duplicated per engine.
    Returns `(signals, warmup_bars, signal_count)` - `signal_count`
    counts non-NEUTRAL signals (Part 15's `ResultValidationSummary`)."""
    required_features = strategy.required_features(strategy_config)
    feature_lookup: dict[str, dict[object, FeatureValue]] = {}
    for field_id in required_features:
        series = compute_feature_series(field_id, bars)
        feature_lookup[field_id] = {fv.timestamp: fv for fv in series}

    warmup_bars = 0
    signal_count = 0
    signals: list[StrategySignal | None] = []
    for bar in bars:
        feature_values = {
            fid: feature_lookup[fid][bar.timestamp]
            for fid in required_features
            if bar.timestamp in feature_lookup[fid]
        }
        if required_features and len(feature_values) < len(required_features):
            warmup_bars += 1
            signals.append(None)
            continue
        signal = strategy.evaluate(bar, feature_values, strategy_config)
        signals.append(signal)
        if signal is not None and signal.direction != StrategyDirection.NEUTRAL:
            signal_count += 1
    return signals, warmup_bars, signal_count


def mfe_mae(
    direction: StrategyDirection, entry_price: Decimal, holding_bars: tuple[Bar, ...]
) -> tuple[Decimal, Decimal]:
    """MFE/MAE computed directly from the trade's own holding-period
    bars (entry bar through exit bar, inclusive) - a DIFFERENT
    computation basis than `signal_intelligence.theoretical_outcome`
    (which measures a fixed future horizon from a `DirectionalIndication`,
    not a trade's actual holding period). See
    `docs/architecture/BACKTESTING_ARCHITECTURE.md`'s "MFE/MAE semantic
    distinction" section - the two are deliberately never interchanged,
    and `tests/unit/research/test_mfe_mae_semantics.py` proves the
    engine's own basis mechanically."""
    if direction == StrategyDirection.BULLISH:
        favorable = max(bar.high - entry_price for bar in holding_bars)
        adverse = max(entry_price - bar.low for bar in holding_bars)
    else:
        favorable = max(entry_price - bar.low for bar in holding_bars)
        adverse = max(bar.high - entry_price for bar in holding_bars)
    return max(favorable, Decimal("0")), max(adverse, Decimal("0"))
