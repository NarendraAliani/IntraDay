# File: src/intraday/trading_engine/risk_engine/evaluator.py
#
# Checkpoint 34 Part 10: the minimal, genuine risk-gating engine. A
# pure function (mirrors `domain/market_data/aggregation.py` and
# `research/backtesting/engine.py`'s own "pure function over an
# explicit context" discipline) - no I/O, no persistence, no broker
# knowledge. Every input the evaluation needs is passed in explicitly
# via `RiskEvaluationContext` - nothing is fetched, guessed, or
# defaulted from global state inside this module.
#
# Checks run in a fixed, documented order (Part 10) - the FIRST failing
# check's reason is returned; later checks are not evaluated once one
# has failed (an order is REJECTED for exactly one primary reason, not
# a list - keeps every rejection unambiguous and auditable).
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from intraday.domain.order.contracts import OrderIntent
from intraday.domain.risk.contracts import RiskDecisionOutcome, RiskLimits, TradingHaltStatus
from intraday.domain.shared_kernel.contracts import InstrumentId
from intraday.trading_engine.risk_engine.contracts import OrderRiskDecision, RiskRejectionReason


@dataclass(frozen=True, slots=True)
class RiskEvaluationContext:
    """Every fact the risk engine needs to evaluate one `OrderIntent` -
    all supplied explicitly by the caller (the paper-trading
    orchestration service, Checkpoint 34 Part 8), never looked up by
    this module itself."""

    risk_limits: RiskLimits
    risk_configuration_version: str
    now: datetime

    # Capital / exposure state
    current_daily_realized_pnl: Decimal
    current_total_exposure: Decimal
    current_open_positions_count: int
    current_position_size_for_instrument: Decimal
    estimated_order_notional: Decimal
    max_concurrent_positions: int
    max_total_exposure: Decimal

    # Safety gates
    kill_switch_status: TradingHaltStatus
    market_session_is_open: bool
    strategy_is_active: bool
    data_quality_is_stale: bool
    already_submitted_idempotency_keys: frozenset[str]

    # Position-tracking (for duplicate-order detection independent of
    # idempotency_key collisions - e.g. two DIFFERENT idempotency keys
    # both trying to open a second position in an instrument that
    # already has one open, within the same evaluation window)
    instruments_with_pending_or_open_orders: frozenset[InstrumentId]


def evaluate_order_risk(order: OrderIntent, context: RiskEvaluationContext) -> OrderRiskDecision:
    """The one, non-bypassable risk chokepoint (Rule 5.2, unchanged
    since Checkpoint 1). Returns an explicit APPROVED/REJECTED decision
    - callers (Checkpoint 34's paper-trading service) must never submit
    an order to any `BrokerGateway` without first calling this and
    checking `.outcome`."""

    def _reject(reason: RiskRejectionReason, explanation: str) -> OrderRiskDecision:
        return OrderRiskDecision(
            order_id=order.order_id,
            outcome=RiskDecisionOutcome.REJECTED,
            reason_code=reason,
            explanation=explanation,
            evaluated_at=context.now,
            risk_configuration_version=context.risk_configuration_version,
        )

    # 1. Kill switch - checked first, unconditionally overrides everything else.
    if context.kill_switch_status is TradingHaltStatus.HALTED:
        return _reject(
            RiskRejectionReason.KILL_SWITCH_ENGAGED,
            "The kill switch is engaged - no new order may be submitted while halted.",
        )

    # 2. Market session requirement.
    if not context.market_session_is_open:
        return _reject(
            RiskRejectionReason.MARKET_SESSION_CLOSED,
            "The market session is not currently open.",
        )

    # 3. Strategy activation requirement.
    if not context.strategy_is_active:
        return _reject(
            RiskRejectionReason.STRATEGY_NOT_ACTIVE,
            f"Strategy {order.strategy_id!r} is not active.",
        )

    # 4. Stale-data rejection.
    if context.data_quality_is_stale:
        return _reject(
            RiskRejectionReason.STALE_DATA,
            "The market data driving this order is stale - refusing to trade on it.",
        )

    # 5. Duplicate-order protection (idempotency key already submitted).
    if order.idempotency_key in context.already_submitted_idempotency_keys:
        return _reject(
            RiskRejectionReason.DUPLICATE_ORDER,
            f"idempotency_key {order.idempotency_key!r} has already been submitted.",
        )

    # 6. Duplicate-order protection (instrument already has a
    #    pending/open order - distinct from the idempotency-key case
    #    above; catches a second, differently-keyed order for the same
    #    instrument arriving before the first has settled).
    if order.instrument_id in context.instruments_with_pending_or_open_orders:
        return _reject(
            RiskRejectionReason.DUPLICATE_ORDER,
            f"{order.instrument_id} already has a pending or open order.",
        )

    # 7. Maximum daily loss.
    if context.current_daily_realized_pnl <= -context.risk_limits.max_intraday_loss:
        return _reject(
            RiskRejectionReason.MAX_DAILY_LOSS_EXCEEDED,
            f"Daily realized P&L ({context.current_daily_realized_pnl}) has reached "
            f"the configured maximum daily loss ({context.risk_limits.max_intraday_loss}).",
        )

    # 8. Maximum position size (this order, on top of any existing
    #    position in the same instrument).
    prospective_position_size = context.current_position_size_for_instrument + order.quantity
    if prospective_position_size > context.risk_limits.max_position_size:
        return _reject(
            RiskRejectionReason.MAX_POSITION_SIZE_EXCEEDED,
            f"Prospective position size ({prospective_position_size}) would exceed "
            f"the configured maximum ({context.risk_limits.max_position_size}).",
        )

    # 9. Maximum total exposure.
    prospective_exposure = context.current_total_exposure + context.estimated_order_notional
    if prospective_exposure > context.max_total_exposure:
        return _reject(
            RiskRejectionReason.MAX_TOTAL_EXPOSURE_EXCEEDED,
            f"Prospective total exposure ({prospective_exposure}) would exceed "
            f"the configured maximum ({context.max_total_exposure}).",
        )

    # 10. Maximum concurrent positions.
    if context.current_open_positions_count >= context.max_concurrent_positions:
        return _reject(
            RiskRejectionReason.MAX_CONCURRENT_POSITIONS_EXCEEDED,
            f"Already at the configured maximum concurrent positions "
            f"({context.max_concurrent_positions}).",
        )

    return OrderRiskDecision(
        order_id=order.order_id,
        outcome=RiskDecisionOutcome.APPROVED,
        reason_code=None,
        explanation="All risk checks passed.",
        evaluated_at=context.now,
        risk_configuration_version=context.risk_configuration_version,
    )
