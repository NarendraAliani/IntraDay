# File: src/intraday/research/backtesting/tradeplan_execution.py
#
# Checkpoint 64.21: closes the gap Checkpoint 64.20's own audit
# disclosed - the backtest engine's SIGNAL generation already reuses
# the exact strategy layer the live PAPER path uses (`execution.py`'s
# `compute_signals()`, unmodified, still calls `strategy.evaluate()`
# directly), but TradePlan/exit simulation did not exist in
# backtesting at all. This module adds it WITHOUT touching
# `compute_signals()`, `engine.py`, or `portfolio.py`'s existing,
# heavily-tested direction-flip simulation - it is new, additive,
# opt-in infrastructure a caller can use alongside the existing engine,
# not a replacement of it (see `taskReport.md`'s own honest disclosure
# of what remains unwired).
#
# TradePlan construction reuses the SAME optional `build_trade_plan()`
# hook the live coordinator calls (`trading_engine.strategy_execution.
# coordinator.py`'s own `getattr(strategy, "build_trade_plan", None)`
# pattern, copied verbatim here - never a second TradePlan
# CONSTRUCTION implementation, only a second, necessary CALL SITE for
# the same strategy method, exactly as `execution.py`'s own
# `compute_signals()` already re-calls `strategy.evaluate()` from a
# second call site rather than reusing the live coordinator object
# directly).
from __future__ import annotations

import enum
from dataclasses import dataclass
from decimal import Decimal

from intraday.domain.feature.contracts import FeatureValue
from intraday.domain.market_data.contracts import Bar
from intraday.research.backtesting import (
    Strategy,
    StrategyConfigurationValues,
    StrategyDirection,
    StrategySignal,
    TradePlan,
)
from intraday.research.backtesting.execution import FeatureSeriesComputer


def compute_trade_plans(
    bars: tuple[Bar, ...],
    strategy: Strategy,
    strategy_config: StrategyConfigurationValues,
    compute_feature_series: FeatureSeriesComputer,
    signals: list[StrategySignal | None],
) -> list[TradePlan | None]:
    """Parallel to `signals` (same index = same bar) - `None` for every
    bar with no signal, a directional-only strategy's signal (e.g.
    `ema_crossover`, which has no `build_trade_plan` method at all), or
    a strategy that itself returns `None` for this bar. Never fabricates
    a plan the strategy did not produce."""
    build_trade_plan = getattr(strategy, "build_trade_plan", None)
    if build_trade_plan is None:
        return [None] * len(signals)

    required_features = strategy.required_features(strategy_config)
    feature_lookup: dict[str, dict[object, FeatureValue]] = {
        field_id: {fv.timestamp: fv for fv in compute_feature_series(field_id, bars)}
        for field_id in required_features
    }

    plans: list[TradePlan | None] = []
    for bar, signal in zip(bars, signals, strict=True):
        if signal is None:
            plans.append(None)
            continue
        feature_values = {
            fid: feature_lookup[fid][bar.timestamp]
            for fid in required_features
            if bar.timestamp in feature_lookup[fid]
        }
        plans.append(build_trade_plan(bar, feature_values, strategy_config, signal))
    return plans


class ExitReason(enum.Enum):
    """Checkpoint 64.21 §16: the exact vocabulary the directive names -
    never a fabricated/ambiguous reason."""

    STOP_LOSS = "STOP_LOSS"
    TARGET_1 = "TARGET_1"
    TARGET_2 = "TARGET_2"
    TARGET_3 = "TARGET_3"
    TRAILING_STOP = "TRAILING_STOP"
    EOD = "EOD"


@dataclass(frozen=True, slots=True)
class TradePlanExitResult:
    exit_index: int
    """Index into the `bars` tuple `simulate_tradeplan_exit` was given -
    the FIRST bar (strictly after entry) whose OHLC range satisfies the
    exit condition."""
    exit_price: Decimal
    exit_reason: ExitReason


_INTRABAR_POLICY_VERSION = "v1"
"""Checkpoint 64.21 §6: versioned - a future policy change must bump
this, never silently change historical result semantics."""


def simulate_tradeplan_exit(
    *,
    trade_plan: TradePlan,
    direction: StrategyDirection,
    entry_index: int,
    bars: tuple[Bar, ...],
) -> TradePlanExitResult | None:
    """Checkpoint 64.21 §5/§6/§7/§14: simulates SL/T1/T2/T3 against each
    bar STRICTLY AFTER `entry_index` (never the entry bar itself - the
    entry decision and its own bar's range must never determine the
    exit, matching the existing `test_entry_never_fills_at_the_signal_
    bars_own_price` no-look-ahead discipline) until the FIRST bar whose
    OHLC range touches a real, non-`None` level from `trade_plan`.
    Returns `None` if no bar in `bars` ever touches a level (the
    position would still be open at the end of the supplied series -
    the caller force-closes at EOD, see `_INTRABAR_POLICY_VERSION`'s
    own EOD note below).

    INTRABAR AMBIGUITY POLICY (`_INTRABAR_POLICY_VERSION = "v1"`,
    conservative, per §6's explicit "prefer conservative when the exact
    intrabar sequence is unobservable"): when a single bar's OHLC range
    touches BOTH the stop-loss AND a target, STOP LOSS IS ASSUMED FIRST
    - the worse outcome for the position, never the favorable sequence.
    When a single bar touches multiple targets (e.g. T1 and T2 in one
    wide-range bar), the LOWEST-NUMBERED target reached is used
    (T1 before T2 before T3) - the conservative assumption that price
    only reached the nearer target within that bar, not that it
    travelled all the way to the further one and the intermediate fill
    is skipped. Trailing stop is evaluated using ONLY the trade's own
    entry-to-target-1 distance as its offset (the SAME value
    `TradePlan.trailing_stop_loss` already stores - a fixed level, not
    a bar-by-bar ratcheting simulation, since `TradePlan` stores one
    static trailing value, never a per-bar recomputed one)."""
    is_long = direction is StrategyDirection.BULLISH
    targets_in_order = [
        (ExitReason.TARGET_1, trade_plan.target_1),
        (ExitReason.TARGET_2, trade_plan.target_2),
        (ExitReason.TARGET_3, trade_plan.target_3),
    ]

    for index in range(entry_index + 1, len(bars)):
        bar = bars[index]

        stop_touched = trade_plan.stop_loss is not None and (
            bar.low <= trade_plan.stop_loss if is_long else bar.high >= trade_plan.stop_loss
        )
        if stop_touched:
            assert trade_plan.stop_loss is not None
            return TradePlanExitResult(
                exit_index=index,
                exit_price=trade_plan.stop_loss,
                exit_reason=ExitReason.STOP_LOSS,
            )

        trailing_touched = trade_plan.trailing_stop_loss is not None and (
            bar.low <= trade_plan.trailing_stop_loss
            if is_long
            else bar.high >= trade_plan.trailing_stop_loss
        )
        if trailing_touched:
            assert trade_plan.trailing_stop_loss is not None
            return TradePlanExitResult(
                exit_index=index,
                exit_price=trade_plan.trailing_stop_loss,
                exit_reason=ExitReason.TRAILING_STOP,
            )

        for reason, level in targets_in_order:
            if level is None:
                continue
            touched = bar.high >= level if is_long else bar.low <= level
            if touched:
                return TradePlanExitResult(exit_index=index, exit_price=level, exit_reason=reason)

    return None


__all__ = [
    "ExitReason",
    "TradePlanExitResult",
    "compute_trade_plans",
    "simulate_tradeplan_exit",
]
