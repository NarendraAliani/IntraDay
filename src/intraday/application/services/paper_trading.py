# File: src/intraday/application/services/paper_trading.py
#
# Checkpoint 34 Part 8: the paper-trading orchestration service - the
# ONE place that wires together, in the correct, non-bypassable order:
#
#     kill switch check
#           -> risk engine evaluation
#                 -> PaperBroker.submit_order()
#
# No order ever reaches `PaperBroker.submit_order()` without first
# passing both the kill-switch check and `evaluate_order_risk()` -
# mechanically proven by `test_paper_trading_architecture_fitness.py`
# (Part 19), not merely documented here.
#
# This module is application-layer (composes `trading_engine.risk_engine`,
# `domain.risk`, `domain.order`, and an injected `BrokerGateway` -
# exactly the "Application -> bounded contexts -> domain" layering
# `.importlinter` contract 3 already permits). It never imports
# `infrastructure.brokers.paper` directly - the broker is injected as a
# `BrokerGateway`-shaped object, so this service would work unchanged
# against a future real Dhan adapter (Part 7's own architecture goal).
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from intraday.application.repositories.paper_ledger import PaperLedgerRepository
from intraday.domain.broker.contracts import BrokerGateway, BrokerOrderStatusReport
from intraday.domain.order.contracts import OrderIntent
from intraday.domain.order.idempotency import derive_correlation_id
from intraday.domain.order.state_machine import is_terminal
from intraday.domain.position.contracts import PositionStatus
from intraday.domain.risk.contracts import RiskDecisionOutcome, RiskLimits, TradingHaltStatus
from intraday.trading_engine.risk_engine.contracts import OrderRiskDecision
from intraday.trading_engine.risk_engine.evaluator import (
    RiskEvaluationContext,
    evaluate_order_risk,
)

KillSwitchStatusProvider = Callable[[], TradingHaltStatus]
Clock = Callable[[], datetime]


@dataclass(frozen=True, slots=True)
class PaperOrderSubmissionResult:
    """What the caller (an API view, a future strategy-execution
    hook) gets back - always includes the risk decision, even when
    REJECTED, so the caller never has to guess whether the broker was
    ever actually reached."""

    risk_decision: OrderRiskDecision
    broker_report: BrokerOrderStatusReport | None
    """`None` when the risk engine rejected the order before it ever
    reached the broker - this field's own presence/absence is the
    proof of whether `BrokerGateway.submit_order()` was called at all."""


class PaperTradingService:
    def __init__(
        self,
        *,
        broker: BrokerGateway,
        risk_limits: RiskLimits,
        risk_configuration_version: str,
        max_concurrent_positions: int,
        max_total_exposure: Decimal,
        kill_switch_status_provider: KillSwitchStatusProvider,
        clock: Clock,
        ledger: PaperLedgerRepository | None = None,
    ) -> None:
        self.broker = broker
        self._risk_limits = risk_limits
        self._risk_configuration_version = risk_configuration_version
        self._max_concurrent_positions = max_concurrent_positions
        self._max_total_exposure = max_total_exposure
        self._kill_switch_status_provider = kill_switch_status_provider
        self._clock = clock
        self._ledger = ledger

    def submit_order(
        self,
        order: OrderIntent,
        *,
        strategy_is_active: bool,
        market_session_is_open: bool,
        data_quality_is_stale: bool,
        estimated_order_notional: Decimal,
        already_submitted_idempotency_keys: frozenset[str],
    ) -> PaperOrderSubmissionResult:
        """The one, non-bypassable entry point for a paper order -
        NEVER calls `self.broker.submit_order()` without first
        checking the kill switch and calling `evaluate_order_risk()`
        (Part 19's architecture-fitness requirement, proven by a
        dedicated test, not only by this docstring)."""
        now = self._clock()
        kill_switch_status = self._kill_switch_status_provider()

        positions = self.broker.get_positions()
        open_positions = [p for p in positions if p.status is PositionStatus.OPEN]
        position_for_instrument = next(
            (p for p in open_positions if p.instrument_id == order.instrument_id), None
        )
        current_exposure = sum(
            (p.quantity * p.average_entry_price for p in open_positions), Decimal("0")
        )
        daily_realized_pnl = sum((p.realized_pnl for p in positions), Decimal("0"))

        context = RiskEvaluationContext(
            risk_limits=self._risk_limits,
            risk_configuration_version=self._risk_configuration_version,
            now=now,
            current_daily_realized_pnl=daily_realized_pnl,
            current_total_exposure=current_exposure,
            current_open_positions_count=len(open_positions),
            current_position_size_for_instrument=(
                position_for_instrument.quantity if position_for_instrument else Decimal("0")
            ),
            estimated_order_notional=estimated_order_notional,
            max_concurrent_positions=self._max_concurrent_positions,
            max_total_exposure=self._max_total_exposure,
            kill_switch_status=kill_switch_status,
            market_session_is_open=market_session_is_open,
            strategy_is_active=strategy_is_active,
            data_quality_is_stale=data_quality_is_stale,
            already_submitted_idempotency_keys=already_submitted_idempotency_keys,
            # Checkpoint 35 Part 9: `BrokerOrderStatusReport` now carries
            # `instrument_id` (Checkpoint 34's own acknowledged gap,
            # closed this checkpoint) - every order in a non-terminal
            # state (CREATED/SUBMITTED/TRANSIT/ACKNOWLEDGED/PENDING/
            # PARTIALLY_FILLED/CANCEL_REQUESTED) blocks new orders on
            # the same instrument; a terminal order (FILLED/CANCELLED/
            # REJECTED/EXPIRED/ERROR) never does, reusing
            # `domain.order.state_machine.is_terminal` as the single
            # source of truth for "is this order still open," never a
            # second, hand-maintained status list.
            instruments_with_pending_or_open_orders=frozenset(
                report.instrument_id
                for report in self.broker.get_orders()
                if not is_terminal(report.status)
            ),
        )

        decision = evaluate_order_risk(order, context)
        if decision.outcome is RiskDecisionOutcome.REJECTED:
            return PaperOrderSubmissionResult(risk_decision=decision, broker_report=None)

        report = self.broker.submit_order(order)
        self._persist(order, report)
        return PaperOrderSubmissionResult(risk_decision=decision, broker_report=report)

    def _persist(self, order: OrderIntent, report: BrokerOrderStatusReport) -> None:
        """Checkpoint 35 Part 3: after every broker mutation, resync the
        FULL current broker-reported state into the durable ledger -
        never a partial/best-effort write. A no-op (never raises,
        never silently swallows a real persistence error - only skips
        entirely) when no `ledger` was injected, so this service
        remains usable in tests/contexts that don't need durability."""
        if self._ledger is None:
            return
        get_events = getattr(self.broker, "get_order_events", None)
        events = get_events(order.order_id) if get_events is not None else ()
        self._ledger.sync_snapshot(
            order=order,
            report=report,
            correlation_id=derive_correlation_id(order.idempotency_key),
            events=events,
            trades=self.broker.get_trades(),
            positions=self.broker.get_positions(),
            funds=self.broker.get_funds(),
        )
