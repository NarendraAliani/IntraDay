# File: src/intraday/infrastructure/api/signal_pipeline_runtime.py
#
# Checkpoint 64.2: the ONE shared "closed bars -> promotion gate ->
# strategy/signal/risk/paper trigger" function - extracted verbatim
# from `market_data_ingestion_runtime.py::_run_locked()` (the REST-
# ingestion path, Checkpoint 41/46), which already implemented this
# exact sequence for its own tick. That inline block is now a call to
# this function instead - never a second, duplicated implementation -
# so the live WebSocket worker (`run_market_data_worker.py --provider
# dhan`, Checkpoint 64.1's own named "single largest remaining gap")
# can drive the SAME strategy -> signal -> risk -> PaperBroker ->
# position-management -> signal-communication pipeline the REST path
# already exercises, from its own newly-aggregated bars.
#
# Reuses, unmodified: `evaluate_bar_promotion()` (the TRADING_GRADE_BAR
# gate - a bar is NEVER promoted just because a WebSocket connects, it
# is promoted only when its own six real-world conditions are met) and
# `run_active_loop_tick()` (which itself composes the EXISTING, real,
# tested strategy engine, `PaperSignalExecutionService`, risk
# evaluation, `PaperBroker`, and `SignalCommunicationService` -
# Telegram/Discord publication - nothing here reimplements any of
# that).
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from decimal import Decimal

from intraday.domain.market_data.aggregation import (
    AggregatedBar,
    BarAggregationResult,
    BarQualityGrade,
    BarStatus,
)
from intraday.domain.market_data.promotion import evaluate_bar_promotion
from intraday.domain.session.contracts import TradingSession
from intraday.infrastructure.api.active_loop_runtime import run_active_loop_tick
from intraday.trading_engine.strategy_execution.contracts import StrategyConfigurationValues

DEFAULT_STRATEGY_ID = "ema_crossover"
DEFAULT_QUANTITY = Decimal("1")


@dataclass(frozen=True, slots=True)
class SignalPipelineOutcome:
    promoted_count: int
    active_loop_invocations: int


def promote_bars_and_trigger_signals(
    aggregation_result: BarAggregationResult,
    *,
    session: TradingSession,
    clock: dt.datetime,
    connection_is_healthy: bool,
    strategy_id: str = DEFAULT_STRATEGY_ID,
    quantity: Decimal = DEFAULT_QUANTITY,
) -> SignalPipelineOutcome:
    """For every newly-CLOSED bar, per instrument, in chronological
    order: run the REAL `evaluate_bar_promotion()` gate (never skipped,
    never bypassed by "the connection is currently up" alone), and for
    every genuinely `TRADING_GRADE_BAR` result, call the EXISTING
    `run_active_loop_tick()` with the full closed-bar history up to and
    including that bar (strategy warm-up, e.g. EMA lookback, needs a
    series - never a single bar, matching every other caller of
    `evaluate_and_submit()` in this codebase).

    `connection_is_healthy` is supplied by the caller, not assumed here
    - the REST ingestion tick passes `True` unconditionally (a
    completed HTTP round trip proves it), while the live WebSocket
    worker should pass its own actual current connection state, not a
    blind constant (see `run_market_data_worker.py`'s own caller for
    how it derives this)."""
    closed_bars = [b for b in aggregation_result.bars if b.status is BarStatus.CLOSED]

    promoted_count = 0
    active_loop_invocations = 0

    by_instrument: dict[str, list[AggregatedBar]] = {}
    for bar in sorted(closed_bars, key=lambda b: b.interval_end):
        by_instrument.setdefault(str(bar.instrument_id), []).append(bar)

    for bars_for_instrument in by_instrument.values():
        preceding: list[AggregatedBar] = []
        for bar in bars_for_instrument:
            promotion = evaluate_bar_promotion(
                bar=bar,
                session=session,
                preceding_bars=tuple(preceding),
                connection_is_healthy=connection_is_healthy,
                now=clock,
            )
            preceding.append(bar)
            if promotion.grade is not BarQualityGrade.TRADING_GRADE_BAR:
                continue
            promoted_count += 1

            configuration = StrategyConfigurationValues(strategy_id, "v1", "v1", "v1", {})
            run_active_loop_tick(
                instrument_id=bar.instrument_id,
                strategy_id=strategy_id,
                configuration=configuration,
                bars=tuple(b.to_bar() for b in preceding),
                quantity=quantity,
                now=clock,
            )
            active_loop_invocations += 1

    return SignalPipelineOutcome(
        promoted_count=promoted_count, active_loop_invocations=active_loop_invocations
    )


__all__ = [
    "SignalPipelineOutcome",
    "promote_bars_and_trigger_signals",
    "DEFAULT_STRATEGY_ID",
    "DEFAULT_QUANTITY",
]
