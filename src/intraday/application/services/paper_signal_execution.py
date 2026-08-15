# File: src/intraday/application/services/paper_signal_execution.py
#
# Checkpoint 36 Part 4-6: the Strategy -> Signal -> Risk -> Paper Order
# bridge. Reuses the EXISTING strategy execution machinery verbatim -
# `trading_engine.strategy_execution.registry.build_default_registry()`,
# `StrategyExecutionCoordinator` (Checkpoint 26), and
# `application.services.strategy_execution.compute_feature_series`
# (the same SMA/EMA/ATR dispatcher backtesting/diagnostics already use)
# - never a second, parallel strategy-evaluation path. This module's
# only new responsibility is the LAST mile: turning one
# `StrategySignal` into a risk-gated `OrderIntent` submitted to
# `PaperTradingService`, with full lineage.
#
# Signal identity: `StrategySignal` (trading_engine.strategy_execution,
# Checkpoint 26) has no `signal_id` field - it is shared, unmodified,
# with `research.backtesting`'s own narrow `.importlinter` exception,
# and adding an ID there would touch a contract dozens of backtest
# tests depend on. Instead, this module derives a DETERMINISTIC
# `signal_id` from (strategy_id, configuration_version, instrument_id,
# timestamp) - the same "same inputs -> same ID, never random" discipline
# `research.backtesting`'s own `_deterministic_backtest_id()` already
# established (Checkpoint 27). This signal_id becomes the paper order's
# `idempotency_key` AND `OrderIntent.signal_id` - full lineage:
# strategy version -> signal_id -> order_id (ledger) -> trade_id/
# position_id (paper broker).
from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from intraday.application.services.paper_trading import (
    PaperOrderSubmissionResult,
    PaperTradingService,
)
from intraday.domain.market_data.contracts import Bar
from intraday.domain.order.contracts import OrderIntent, OrderType, TimeInForce
from intraday.domain.shared_kernel.contracts import InstrumentId, Side, SignalId
from intraday.trading_engine.strategy_execution.contracts import (
    StrategyConfigurationValues,
    StrategyDirection,
)
from intraday.trading_engine.strategy_execution.coordinator import StrategyExecutionCoordinator


def derive_signal_id(
    *,
    strategy_id: str,
    configuration_version: str,
    instrument_id: InstrumentId,
    timestamp: datetime,
) -> SignalId:
    """Deterministic - the SAME strategy evaluated against the SAME bar
    always derives the SAME signal_id, which is exactly what makes
    duplicate-evaluation protection possible (re-running the coordinator
    against a bar it already saw must never produce a second order)."""
    payload = f"{strategy_id}:{configuration_version}:{instrument_id}:{timestamp.isoformat()}"
    return SignalId(hashlib.sha256(payload.encode("utf-8")).hexdigest()[:32])


@dataclass(frozen=True, slots=True)
class PaperSignalExecutionResult:
    """What the caller gets back for ONE strategy's evaluation against
    ONE bar series - always reports what happened, even when nothing
    was submitted, so a caller (a future scheduler, a manual "evaluate
    now" API action) never has to guess why."""

    strategy_id: str
    signal_id: SignalId | None
    direction: StrategyDirection | None
    skipped_reason: str | None
    order_result: PaperOrderSubmissionResult | None


class PaperSignalExecutionService:
    """The ONE place a strategy's evaluated direction becomes a paper
    order. Bars are supplied by the CALLER (dependency injection,
    mirroring every other pure-orchestration service in this project) -
    this module makes no decision about where bars come from or
    whether they are trading-grade; see Part 8's own market-data
    decision (`docs/architecture/PAPER_TRADING_ARCHITECTURE.md`) for
    why an automatic feed was deliberately NOT wired here."""

    def __init__(
        self,
        *,
        coordinator: StrategyExecutionCoordinator,
        paper_trading_service: PaperTradingService,
        quantity: Decimal,
    ) -> None:
        self._coordinator = coordinator
        self._paper_trading_service = paper_trading_service
        self._quantity = quantity

    def evaluate_and_submit(
        self,
        *,
        bars: tuple[Bar, ...],
        instrument_id: InstrumentId,
        strategy_id: str,
        configuration: StrategyConfigurationValues,
        strategy_is_active: bool,
        market_session_is_open: bool,
        data_quality_is_stale: bool,
        already_processed_signal_ids: frozenset[str],
        already_submitted_idempotency_keys: frozenset[str],
    ) -> PaperSignalExecutionResult:
        if not bars:
            return PaperSignalExecutionResult(
                strategy_id=strategy_id,
                signal_id=None,
                direction=None,
                skipped_reason="no_bars_supplied",
                order_result=None,
            )

        result = self._coordinator.run(bars, {strategy_id: configuration})
        matching = [s for s in result.signals if s.strategy_id == strategy_id]
        if not matching:
            failure_reasons = [f.message for f in result.failures if f.strategy_id == strategy_id]
            return PaperSignalExecutionResult(
                strategy_id=strategy_id,
                signal_id=None,
                direction=None,
                skipped_reason=(
                    f"strategy_evaluation_failed: {failure_reasons[0]}"
                    if failure_reasons
                    else "no_signal_produced"
                ),
                order_result=None,
            )

        signal = matching[0]
        if signal.direction is StrategyDirection.NEUTRAL:
            return PaperSignalExecutionResult(
                strategy_id=strategy_id,
                signal_id=None,
                direction=signal.direction,
                skipped_reason="neutral_direction",
                order_result=None,
            )

        signal_id = derive_signal_id(
            strategy_id=strategy_id,
            configuration_version=configuration.configuration_version,
            instrument_id=instrument_id,
            timestamp=signal.timestamp,
        )

        if str(signal_id) in already_processed_signal_ids:
            return PaperSignalExecutionResult(
                strategy_id=strategy_id,
                signal_id=signal_id,
                direction=signal.direction,
                skipped_reason="signal_already_processed",
                order_result=None,
            )

        side = _side_for_direction(signal.direction)
        order = OrderIntent(
            order_id=str(uuid.uuid4()),  # type: ignore[arg-type]
            instrument_id=instrument_id,
            side=side,
            quantity=self._quantity,
            order_type=OrderType.MARKET,
            time_in_force=TimeInForce.DAY,
            strategy_id=strategy_id,  # type: ignore[arg-type]
            created_at=signal.timestamp,
            idempotency_key=str(signal_id),
            signal_id=signal_id,
        )

        order_result = self._paper_trading_service.submit_order(
            order,
            strategy_is_active=strategy_is_active,
            market_session_is_open=market_session_is_open,
            data_quality_is_stale=data_quality_is_stale,
            estimated_order_notional=self._quantity * signal.price,
            already_submitted_idempotency_keys=already_submitted_idempotency_keys,
        )

        return PaperSignalExecutionResult(
            strategy_id=strategy_id,
            signal_id=signal_id,
            direction=signal.direction,
            skipped_reason=None,
            order_result=order_result,
        )


def _side_for_direction(direction: StrategyDirection) -> Side:
    if direction is StrategyDirection.BULLISH:
        return Side.BUY
    return Side.SELL
