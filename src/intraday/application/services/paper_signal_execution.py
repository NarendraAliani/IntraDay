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
from dataclasses import dataclass, replace
from datetime import datetime
from decimal import Decimal

from intraday.application.services.paper_trading import (
    PaperOrderSubmissionResult,
    PaperTradingService,
)
from intraday.application.services.signal_communication import SignalCommunicationService
from intraday.communication.contracts.signal_communication import (
    ExecutionStatus,
    MessageTemplateId,
    SignalCommunicationContext,
    derive_execution_status,
)
from intraday.domain.market_data.contracts import Bar
from intraday.domain.order.contracts import OrderIntent, OrderStatus, OrderType, TimeInForce
from intraday.domain.risk.contracts import RiskDecisionOutcome
from intraday.domain.shared_kernel.contracts import InstrumentId, Side, SignalId
from intraday.domain.signal.contracts import SignalStatus
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
        communication: SignalCommunicationService | None = None,
    ) -> None:
        self._coordinator = coordinator
        self._paper_trading_service = paper_trading_service
        self._quantity = quantity
        self._communication = communication

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
        context = _build_context(
            instrument_id=instrument_id,
            strategy_id=strategy_id,
            configuration=configuration,
            signal_id=signal_id,
            side=side,
            signal_price=signal.price,
            signal_timestamp=signal.timestamp,
            timeframe=str(signal.timeframe),
        )
        # SIGNAL TRUTH != EXECUTION TRUTH: this fires unconditionally,
        # before risk/broker involvement - a strategically audited
        # signal is a valid product event regardless of what happens
        # next (Checkpoint 37 Part 3/6).
        self._communicate(
            signal_id=signal_id,
            template_id=MessageTemplateId.VALIDATED_SIGNAL,
            context=context,
        )

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
        self._communicate_outcome(signal_id=signal_id, context=context, order_result=order_result)

        return PaperSignalExecutionResult(
            strategy_id=strategy_id,
            signal_id=signal_id,
            direction=signal.direction,
            skipped_reason=None,
            order_result=order_result,
        )

    def _communicate(
        self,
        *,
        signal_id: SignalId,
        template_id: MessageTemplateId,
        context: SignalCommunicationContext,
    ) -> None:
        if self._communication is None:
            return
        self._communication.communicate(
            signal_id=signal_id,
            template_id=template_id,
            context=context,
            correlation_id=str(signal_id),
        )

    def _communicate_outcome(
        self,
        *,
        signal_id: SignalId,
        context: SignalCommunicationContext,
        order_result: PaperOrderSubmissionResult,
    ) -> None:
        risk_decision = order_result.risk_decision
        broker_report = order_result.broker_report
        order_status = broker_report.status if broker_report is not None else None
        execution_status = derive_execution_status(
            risk_outcome=risk_decision.outcome, order_status=order_status
        )
        outcome_context = _with_execution_status(context, execution_status)

        if risk_decision.outcome is RiskDecisionOutcome.REJECTED:
            blocked_context = _replace_block_reason(
                outcome_context, risk_decision.explanation or "Risk engine rejected order"
            )
            self._communicate(
                signal_id=signal_id,
                template_id=MessageTemplateId.VALIDATED_SIGNAL_EXECUTION_BLOCKED,
                context=blocked_context,
            )
            return

        if broker_report is None:
            self._communicate(
                signal_id=signal_id,
                template_id=MessageTemplateId.ORDER_SUBMITTED,
                context=outcome_context,
            )
            return

        if order_status is OrderStatus.REJECTED:
            template = MessageTemplateId.ORDER_REJECTED
        elif order_status is OrderStatus.PARTIALLY_FILLED:
            template = MessageTemplateId.PARTIAL_FILL
        elif order_status is OrderStatus.FILLED:
            template = MessageTemplateId.ORDER_FILLED
        else:
            template = MessageTemplateId.ORDER_SUBMITTED

        self._communicate(signal_id=signal_id, template_id=template, context=outcome_context)


def _build_context(
    *,
    instrument_id: InstrumentId,
    strategy_id: str,
    configuration: StrategyConfigurationValues,
    signal_id: SignalId,
    side: Side,
    signal_price: Decimal,
    signal_timestamp: datetime,
    timeframe: str,
) -> SignalCommunicationContext:
    exchange, _, symbol = str(instrument_id).partition(":")
    return SignalCommunicationContext(
        strategy_id=strategy_id,  # type: ignore[arg-type]
        strategy_version=configuration.configuration_version,
        signal_id=signal_id,
        symbol=symbol or str(instrument_id),
        exchange=exchange,
        signal_time=signal_timestamp,
        timeframe=timeframe,
        spot_price=signal_price,
        direction=side,
        entry_price=signal_price,
        stop_loss=None,  # ema_crossover does not compute a stop loss - never fabricated
        targets=(),  # ema_crossover does not compute targets - never fabricated
        trailing_stop_enabled=False,
        confidence=None,
        signal_status=SignalStatus.VALIDATED,
        execution_status=ExecutionStatus.NOT_EVALUATED,
    )


def _with_execution_status(
    context: SignalCommunicationContext, execution_status: ExecutionStatus
) -> SignalCommunicationContext:
    return replace(context, execution_status=execution_status)


def _replace_block_reason(
    context: SignalCommunicationContext, reason: str
) -> SignalCommunicationContext:
    return replace(context, block_reason=reason)


def _side_for_direction(direction: StrategyDirection) -> Side:
    if direction is StrategyDirection.BULLISH:
        return Side.BUY
    return Side.SELL
