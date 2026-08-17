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
from typing import Protocol

from intraday.application.services.exit_plan_policy import derive_default_exit_plan
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
from intraday.domain.position.contracts import PositionStatus
from intraday.domain.risk.contracts import RiskDecisionOutcome
from intraday.domain.shared_kernel.contracts import InstrumentId, Side, SignalId
from intraday.domain.signal.contracts import SignalStatus
from intraday.trading_engine.position_management.contracts import ExitPlan
from intraday.trading_engine.strategy_execution.contracts import (
    StrategyConfigurationValues,
    StrategyDirection,
)
from intraday.trading_engine.strategy_execution.coordinator import StrategyExecutionCoordinator


class SignalRecorder(Protocol):
    """Checkpoint 62.x - `application.repositories`-style Protocol
    (Contract 6: this module must never import `infrastructure.*`
    directly), mirroring `ExitPlanAttacher`'s own established pattern.
    `DjangoSignalRepository.record_signal()` satisfies this
    structurally. Optional, defaults to `None` (no persistence) -
    mirrors `apply_default_exit_plan`'s own opt-in discipline, so
    every pre-existing caller/test of this service is unaffected."""

    def record_signal(
        self,
        *,
        signal_id: SignalId,
        strategy_id: str,
        instrument_id: InstrumentId,
        direction: str,
        price: Decimal,
        timeframe: str,
        signal_timestamp: datetime,
        risk_status: str,
        risk_reason: str,
        order_status: str,
    ) -> None: ...


class ExitPlanAttacher(Protocol):
    """Checkpoint 43 Part 4 - `application.repositories`-style Protocol
    (Contract 6: this module must never import `infrastructure.*`
    directly). `DjangoPaperLedgerRepository.attach_exit_plan()`
    satisfies this structurally."""

    def attach_exit_plan(
        self,
        *,
        position_id: str,
        strategy_id: str,
        strategy_version: str,
        entry_order_id: str,
        exit_plan: ExitPlan,
        quantity: object,
        entry_price: object,
    ) -> None: ...


def derive_signal_id(
    *,
    strategy_id: str,
    configuration_version: str,
    instrument_id: InstrumentId,
    timestamp: datetime,
    timeframe: str = "",
    specification_version: str = "",
    code_version: str = "",
) -> SignalId:
    """Deterministic - the SAME strategy evaluated against the SAME bar
    always derives the SAME signal_id, which is exactly what makes
    duplicate-evaluation protection possible (re-running the coordinator
    against a bar it already saw must never produce a second order).

    Checkpoint 38 Part 6 identity model - the full component list a
    signal's identity is justified against, and why each is/isn't in
    the hash:

    - `strategy_id`, `specification_version`, `code_version`,
      `configuration_version`: identifies WHICH decision logic
      produced this signal - two different strategy versions
      evaluating the identical bar are, by definition, different
      signals (a strategy upgrade must not be silently deduplicated
      against its predecessor's signal).
    - `instrument_id`: which instrument.
    - `timeframe`: which bar granularity - without this, a
      (hypothetical, not yet built) multi-timeframe strategy
      evaluating the SAME instrument at the SAME wall-clock timestamp
      on two different timeframes would collide.
    - `timestamp`: the BAR/EVENT identity proxy - `StrategySignal.
      timestamp` is the bar's own timestamp (Checkpoint 26), which is
      already a genuine per-instrument-per-timeframe unique key by
      construction (`domain.market_data.contracts.Bar`'s own
      timestamp-uniqueness discipline) - a second, separate "bar ID"
      field is not needed since the bar's timestamp already serves
      that role.
    - `direction` is DELIBERATELY EXCLUDED: it is an OUTPUT of
      evaluating (strategy, config, instrument, timeframe, bar), not
      an independent input - two evaluations of the identical inputs
      are REQUIRED to always produce the identical direction (strategy
      evaluation is a pure function over the bar series), so including
      it in the hash would be redundant, never additionally
      discriminating. Including a NON-deterministic input (direction,
      if evaluation were ever non-deterministic) would be a signal
      that determinism itself is broken - the correct fix is
      restoring determinism, not hashing around it.
    """
    payload = (
        f"{strategy_id}:{specification_version}:{code_version}:{configuration_version}:"
        f"{instrument_id}:{timeframe}:{timestamp.isoformat()}"
    )
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
        exit_plan_attacher: ExitPlanAttacher | None = None,
        apply_default_exit_plan: bool = False,
        signal_recorder: SignalRecorder | None = None,
    ) -> None:
        self._coordinator = coordinator
        self._paper_trading_service = paper_trading_service
        self._quantity = quantity
        self._communication = communication
        self._signal_recorder = signal_recorder
        """Checkpoint 62.x: optional, off by default - when supplied,
        every REAL signal this service produces (never a skipped/
        neutral/already-processed evaluation) is persisted through it,
        the one thing an "active signal monitor" UI needs to query
        instead of fabricating rows."""
        self._exit_plan_attacher = exit_plan_attacher
        self._apply_default_exit_plan = apply_default_exit_plan
        """Checkpoint 43 Part 4: OFF by default - see
        `exit_plan_policy.py`'s own module docstring for why the
        PROJECT_POLICY default exit plan is opt-in, not automatic for
        every strategy. When `True` AND `exit_plan_attacher` is
        supplied, a FILLED entry order's resulting position is given a
        real, monitorable `ExitPlan` via `derive_default_exit_plan()`."""

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
            timeframe=str(signal.timeframe),
            specification_version=configuration.specification_version,
            code_version=configuration.code_version,
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
        self._maybe_record_signal(
            signal_id=signal_id,
            strategy_id=strategy_id,
            instrument_id=instrument_id,
            direction=signal.direction,
            price=signal.price,
            # `.value` ("5m"), not `str(signal.timeframe)` ("Timeframe.
            # ONE_MINUTE") - `derive_signal_id()`'s own identity hash
            # (lines above, unchanged) still uses `str()`; this is a
            # SEPARATE, purely display/filter-facing field for the
            # persisted `SignalRecord`, found necessary while wiring
            # the Active Signal Monitor UI's timeframe filter.
            timeframe=signal.timeframe.value,
            signal_timestamp=signal.timestamp,
            order_result=order_result,
        )
        self._maybe_attach_exit_plan(
            order_result=order_result,
            instrument_id=instrument_id,
            side=side,
            strategy_id=strategy_id,
            configuration=configuration,
            entry_order_id=order.order_id,
        )

        return PaperSignalExecutionResult(
            strategy_id=strategy_id,
            signal_id=signal_id,
            direction=signal.direction,
            skipped_reason=None,
            order_result=order_result,
        )

    def _maybe_record_signal(
        self,
        *,
        signal_id: SignalId,
        strategy_id: str,
        instrument_id: InstrumentId,
        direction: StrategyDirection,
        price: Decimal,
        timeframe: str,
        signal_timestamp: datetime,
        order_result: PaperOrderSubmissionResult,
    ) -> None:
        """Only reached for a REAL, non-skipped, non-neutral,
        not-already-processed signal (see `evaluate_and_submit()`'s
        own early-return guards above) - never called for a skipped
        evaluation, so a signal-monitor UI querying this data can
        never show a fabricated "signal" for a bar where the strategy
        produced nothing actionable."""
        if self._signal_recorder is None:
            return
        risk_decision = order_result.risk_decision
        order_status = (
            order_result.broker_report.status.value
            if order_result.broker_report is not None
            else ""
        )
        self._signal_recorder.record_signal(
            signal_id=signal_id,
            strategy_id=strategy_id,
            instrument_id=instrument_id,
            direction=direction.value,
            price=price,
            timeframe=timeframe,
            signal_timestamp=signal_timestamp,
            risk_status=risk_decision.outcome.value,
            risk_reason=risk_decision.explanation,
            order_status=order_status,
        )

    def _maybe_attach_exit_plan(
        self,
        *,
        order_result: PaperOrderSubmissionResult,
        instrument_id: InstrumentId,
        side: Side,
        strategy_id: str,
        configuration: StrategyConfigurationValues,
        entry_order_id: object,
    ) -> None:
        """Checkpoint 43 Part 4: only when BOTH `apply_default_exit_plan`
        is on and the order genuinely FILLED - a rejected/unfilled
        order has no position to attach a plan to, and this method
        never invents one."""
        if not self._apply_default_exit_plan or self._exit_plan_attacher is None:
            return
        broker_report = order_result.broker_report
        if broker_report is None or broker_report.status is not OrderStatus.FILLED:
            return

        matching_positions = [
            p
            for p in self._paper_trading_service.broker.get_positions()
            if p.instrument_id == instrument_id and p.status is PositionStatus.OPEN
        ]
        if not matching_positions:
            return
        position = matching_positions[0]

        exit_plan = derive_default_exit_plan(
            entry_price=position.average_entry_price, direction=side
        )
        self._exit_plan_attacher.attach_exit_plan(
            position_id=str(position.position_id),
            strategy_id=strategy_id,
            strategy_version=configuration.configuration_version,
            entry_order_id=str(entry_order_id),
            exit_plan=exit_plan,
            quantity=position.quantity,
            entry_price=position.average_entry_price,
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
