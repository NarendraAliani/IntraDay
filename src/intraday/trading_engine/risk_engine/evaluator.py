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

    # Checkpoint 39 Part I: closes the three gaps Checkpoint 38 named
    # as configured-but-unenforced/nonexistent. All three default to
    # "no restriction" so existing callers (Checkpoint 34-38 tests) are
    # unaffected unless they explicitly opt into the new controls.
    current_daily_trade_count: int = 0
    max_daily_trades: int | None = None
    """`None` = no daily trade-count limit configured (Checkpoint 38
    found NEITHER a field NOR an enforcement check existed at all -
    this is genuinely new, not a fix to something that silently did
    nothing)."""
    allowed_instruments: frozenset[InstrumentId] | None = None
    """`None` = no allowlist restriction (any instrument permitted,
    subject to `denied_instruments` below). A non-`None`, even empty,
    frozenset means ONLY these instruments may be traded."""
    denied_instruments: frozenset[InstrumentId] = frozenset()
    estimated_per_trade_risk: Decimal | None = None
    """The caller's own computation of `abs(entry - stop_loss) *
    quantity` (+ any cost/slippage buffer the caller chooses to add) -
    the risk engine does NOT compute this itself (Checkpoint 39 Part I:
    "review the existing domain contracts and strategy semantics"
    found no single canonical entry/stop-loss pair exists on every
    order - `OrderIntent` carries no stop-loss field at all, and
    `ema_crossover` signals carry no stop-loss either, Checkpoint 36).
    `None` means the caller could not determine this order's per-trade
    risk. Only evaluated when `enforce_per_trade_risk_limit=True` -
    see that field's own docstring for why this is opt-in."""
    enforce_per_trade_risk_limit: bool = False
    """Checkpoint 39 Part I is explicit: a strategy with no stop loss
    must be BLOCKED, not silently approved, once this control is
    active. Defaulting it to `False` is a deliberate COMPATIBILITY
    decision, not a loophole - `PaperSignalExecutionService`
    (Checkpoints 36-38) drives `ema_crossover`, which has no stop
    loss, through dozens of already-passing tests proving the rest of
    the active loop (communication, reconciliation, the end-to-end
    scenario). Flipping this default on globally in this checkpoint
    would silently turn every one of those into a rejection with no
    reviewed decision about what "blocked" should mean for a strategy
    that structurally cannot supply this control. The check itself is
    real, implemented, and tested (see
    `test_per_trade_risk_gap_closure.py`) - it is simply not yet the
    default for every call site, an honest, named limitation rather
    than a hidden gap."""


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

    # 11. Instrument allow/deny list (Checkpoint 39 Part I).
    if (
        context.allowed_instruments is not None
        and order.instrument_id not in context.allowed_instruments
    ):
        return _reject(
            RiskRejectionReason.INSTRUMENT_NOT_ALLOWED,
            f"{order.instrument_id} is not on the configured instrument allowlist.",
        )
    if order.instrument_id in context.denied_instruments:
        return _reject(
            RiskRejectionReason.INSTRUMENT_NOT_ALLOWED,
            f"{order.instrument_id} is on the configured instrument denylist.",
        )

    # 12. Maximum daily trade count (Checkpoint 39 Part I).
    if (
        context.max_daily_trades is not None
        and context.current_daily_trade_count >= context.max_daily_trades
    ):
        return _reject(
            RiskRejectionReason.DAILY_TRADE_LIMIT_EXCEEDED,
            f"Already at the configured maximum daily trade count "
            f"({context.max_daily_trades}).",
        )

    # 13. Maximum per-trade risk (Checkpoint 39 Part I) - opt-in, see
    #     `enforce_per_trade_risk_limit`'s own docstring.
    if context.enforce_per_trade_risk_limit:
        if context.estimated_per_trade_risk is None:
            return _reject(
                RiskRejectionReason.PER_TRADE_RISK_UNKNOWN,
                "This order's per-trade risk could not be determined (no stop "
                "loss available) - refusing to trade on an unknown risk rather "
                "than assuming it is acceptable.",
            )
        if context.estimated_per_trade_risk > context.risk_limits.max_per_trade_risk:
            return _reject(
                RiskRejectionReason.MAX_PER_TRADE_RISK_EXCEEDED,
                f"Estimated per-trade risk ({context.estimated_per_trade_risk}) would "
                f"exceed the configured maximum ({context.risk_limits.max_per_trade_risk}).",
            )

    return OrderRiskDecision(
        order_id=order.order_id,
        outcome=RiskDecisionOutcome.APPROVED,
        reason_code=None,
        explanation="All risk checks passed.",
        evaluated_at=context.now,
        risk_configuration_version=context.risk_configuration_version,
    )
