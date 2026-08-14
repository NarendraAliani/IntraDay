# tests/unit/trading_engine/test_risk_engine_evaluator.py
#
# Checkpoint 34 Part 10/18: exhaustive coverage of every risk rule, in
# isolation, plus the fixed evaluation order (kill switch first).
from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from intraday.domain.instrument.contracts import make_instrument_id
from intraday.domain.order.contracts import OrderIntent, OrderType, TimeInForce
from intraday.domain.risk.contracts import RiskDecisionOutcome, RiskLimits, TradingHaltStatus
from intraday.domain.shared_kernel.contracts import Exchange, Side
from intraday.trading_engine.risk_engine.contracts import RiskRejectionReason
from intraday.trading_engine.risk_engine.evaluator import (
    RiskEvaluationContext,
    evaluate_order_risk,
)

RELIANCE = make_instrument_id(Exchange.NSE, "RELIANCE")
TCS = make_instrument_id(Exchange.NSE, "TCS")
NOW = datetime(2026, 1, 5, 4, 0, tzinfo=UTC)

DEFAULT_LIMITS = RiskLimits(
    max_intraday_loss=Decimal("5000"),
    max_position_size=Decimal("100"),
    max_per_trade_risk=Decimal("1000"),
)


def _order(**overrides: object) -> OrderIntent:
    fields: dict[str, object] = {
        "order_id": "ord-1",
        "instrument_id": RELIANCE,
        "side": Side.BUY,
        "quantity": Decimal("10"),
        "order_type": OrderType.MARKET,
        "time_in_force": TimeInForce.DAY,
        "strategy_id": "orb-v1",
        "created_at": NOW,
        "idempotency_key": "idem-1",
    }
    fields.update(overrides)
    return OrderIntent(**fields)  # type: ignore[arg-type]


def _context(**overrides: object) -> RiskEvaluationContext:
    fields: dict[str, object] = {
        "risk_limits": DEFAULT_LIMITS,
        "risk_configuration_version": "v1",
        "now": NOW,
        "current_daily_realized_pnl": Decimal("0"),
        "current_total_exposure": Decimal("0"),
        "current_open_positions_count": 0,
        "current_position_size_for_instrument": Decimal("0"),
        "estimated_order_notional": Decimal("1000"),
        "max_concurrent_positions": 5,
        "max_total_exposure": Decimal("50000"),
        "kill_switch_status": TradingHaltStatus.ACTIVE,
        "market_session_is_open": True,
        "strategy_is_active": True,
        "data_quality_is_stale": False,
        "already_submitted_idempotency_keys": frozenset(),
        "instruments_with_pending_or_open_orders": frozenset(),
    }
    fields.update(overrides)
    return RiskEvaluationContext(**fields)  # type: ignore[arg-type]


def test_all_checks_pass_yields_approval() -> None:
    decision = evaluate_order_risk(_order(), _context())
    assert decision.outcome is RiskDecisionOutcome.APPROVED
    assert decision.reason_code is None


def test_kill_switch_engaged_rejects_before_anything_else() -> None:
    """Even with every other check violated, kill switch is checked
    first and its reason is the one reported."""
    context = _context(
        kill_switch_status=TradingHaltStatus.HALTED,
        market_session_is_open=False,
        strategy_is_active=False,
    )
    decision = evaluate_order_risk(_order(), context)
    assert decision.outcome is RiskDecisionOutcome.REJECTED
    assert decision.reason_code is RiskRejectionReason.KILL_SWITCH_ENGAGED


def test_market_session_closed_rejects() -> None:
    decision = evaluate_order_risk(_order(), _context(market_session_is_open=False))
    assert decision.reason_code is RiskRejectionReason.MARKET_SESSION_CLOSED


def test_strategy_not_active_rejects() -> None:
    decision = evaluate_order_risk(_order(), _context(strategy_is_active=False))
    assert decision.reason_code is RiskRejectionReason.STRATEGY_NOT_ACTIVE


def test_stale_data_rejects() -> None:
    decision = evaluate_order_risk(_order(), _context(data_quality_is_stale=True))
    assert decision.reason_code is RiskRejectionReason.STALE_DATA


def test_duplicate_idempotency_key_rejects() -> None:
    context = _context(already_submitted_idempotency_keys=frozenset({"idem-1"}))
    decision = evaluate_order_risk(_order(idempotency_key="idem-1"), context)
    assert decision.reason_code is RiskRejectionReason.DUPLICATE_ORDER


def test_duplicate_instrument_pending_order_rejects() -> None:
    context = _context(instruments_with_pending_or_open_orders=frozenset({RELIANCE}))
    decision = evaluate_order_risk(_order(instrument_id=RELIANCE), context)
    assert decision.reason_code is RiskRejectionReason.DUPLICATE_ORDER


def test_duplicate_instrument_check_does_not_affect_other_instruments() -> None:
    context = _context(instruments_with_pending_or_open_orders=frozenset({RELIANCE}))
    decision = evaluate_order_risk(_order(instrument_id=TCS), context)
    assert decision.outcome is RiskDecisionOutcome.APPROVED


def test_max_daily_loss_exceeded_rejects() -> None:
    context = _context(current_daily_realized_pnl=Decimal("-5000"))
    decision = evaluate_order_risk(_order(), context)
    assert decision.reason_code is RiskRejectionReason.MAX_DAILY_LOSS_EXCEEDED


def test_max_daily_loss_not_yet_reached_approves() -> None:
    context = _context(current_daily_realized_pnl=Decimal("-4999"))
    decision = evaluate_order_risk(_order(), context)
    assert decision.outcome is RiskDecisionOutcome.APPROVED


def test_max_position_size_exceeded_rejects() -> None:
    context = _context(current_position_size_for_instrument=Decimal("95"))
    decision = evaluate_order_risk(_order(quantity=Decimal("10")), context)
    assert decision.reason_code is RiskRejectionReason.MAX_POSITION_SIZE_EXCEEDED


def test_max_position_size_exactly_at_limit_approves() -> None:
    context = _context(current_position_size_for_instrument=Decimal("90"))
    decision = evaluate_order_risk(_order(quantity=Decimal("10")), context)
    assert decision.outcome is RiskDecisionOutcome.APPROVED


def test_max_total_exposure_exceeded_rejects() -> None:
    context = _context(
        current_total_exposure=Decimal("49500"), estimated_order_notional=Decimal("1000")
    )
    decision = evaluate_order_risk(_order(), context)
    assert decision.reason_code is RiskRejectionReason.MAX_TOTAL_EXPOSURE_EXCEEDED


def test_max_concurrent_positions_exceeded_rejects() -> None:
    context = _context(current_open_positions_count=5, max_concurrent_positions=5)
    decision = evaluate_order_risk(_order(), context)
    assert decision.reason_code is RiskRejectionReason.MAX_CONCURRENT_POSITIONS_EXCEEDED


def test_max_concurrent_positions_below_limit_approves() -> None:
    context = _context(current_open_positions_count=4, max_concurrent_positions=5)
    decision = evaluate_order_risk(_order(), context)
    assert decision.outcome is RiskDecisionOutcome.APPROVED


def test_rejection_decision_always_has_explanation() -> None:
    decision = evaluate_order_risk(_order(), _context(market_session_is_open=False))
    assert decision.explanation.strip() != ""


def test_approval_decision_has_no_reason_code() -> None:
    decision = evaluate_order_risk(_order(), _context())
    assert decision.reason_code is None
