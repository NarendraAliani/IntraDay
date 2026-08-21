# tests/unit/domain/test_risk_policy.py
#
# Checkpoint 64.24: regression-safety net for the relocation of
# `evaluate_order_risk()`/`RiskEvaluationContext` from
# `trading_engine.risk_engine.evaluator` into `intraday.domain.risk.
# policy` (the one layer every part of this codebase - trading_engine,
# application, AND research - is permitted to import). Proves all 13
# risk checks documented in the source function still fire correctly
# post-move, imported directly from their new canonical location, and
# that the fixed first-failing-check-wins evaluation order survives the
# move (a scenario where two checks would both fail asserts only the
# earlier one's reason is returned). This is NOT a test that two
# separate implementations agree - there is only one implementation
# now; it is a proof the relocation changed nothing observable.
from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from intraday.domain.instrument.contracts import make_instrument_id
from intraday.domain.order.contracts import OrderIntent, OrderType, TimeInForce
from intraday.domain.risk.contracts import (
    RiskDecisionOutcome,
    RiskLimits,
    RiskRejectionReason,
    TradingHaltStatus,
)
from intraday.domain.risk.policy import RiskEvaluationContext, evaluate_order_risk
from intraday.domain.shared_kernel.contracts import Exchange, Side

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


# --- All 13 checks, each proven to fire post-relocation ---------------------


def test_check_01_kill_switch_engaged() -> None:
    decision = evaluate_order_risk(_order(), _context(kill_switch_status=TradingHaltStatus.HALTED))
    assert decision.outcome is RiskDecisionOutcome.REJECTED
    assert decision.reason_code is RiskRejectionReason.KILL_SWITCH_ENGAGED


def test_check_02_market_session_closed() -> None:
    decision = evaluate_order_risk(_order(), _context(market_session_is_open=False))
    assert decision.reason_code is RiskRejectionReason.MARKET_SESSION_CLOSED


def test_check_03_strategy_not_active() -> None:
    decision = evaluate_order_risk(_order(), _context(strategy_is_active=False))
    assert decision.reason_code is RiskRejectionReason.STRATEGY_NOT_ACTIVE


def test_check_04_stale_data() -> None:
    decision = evaluate_order_risk(_order(), _context(data_quality_is_stale=True))
    assert decision.reason_code is RiskRejectionReason.STALE_DATA


def test_check_05_duplicate_order_idempotency_key() -> None:
    context = _context(already_submitted_idempotency_keys=frozenset({"idem-1"}))
    decision = evaluate_order_risk(_order(idempotency_key="idem-1"), context)
    assert decision.reason_code is RiskRejectionReason.DUPLICATE_ORDER


def test_check_06_duplicate_order_instrument_pending() -> None:
    context = _context(instruments_with_pending_or_open_orders=frozenset({RELIANCE}))
    decision = evaluate_order_risk(_order(instrument_id=RELIANCE), context)
    assert decision.reason_code is RiskRejectionReason.DUPLICATE_ORDER


def test_check_07_max_daily_loss_exceeded() -> None:
    context = _context(current_daily_realized_pnl=Decimal("-5000"))
    decision = evaluate_order_risk(_order(), context)
    assert decision.reason_code is RiskRejectionReason.MAX_DAILY_LOSS_EXCEEDED


def test_check_08_max_position_size_exceeded() -> None:
    context = _context(current_position_size_for_instrument=Decimal("95"))
    decision = evaluate_order_risk(_order(quantity=Decimal("10")), context)
    assert decision.reason_code is RiskRejectionReason.MAX_POSITION_SIZE_EXCEEDED


def test_check_09_max_total_exposure_exceeded() -> None:
    context = _context(
        current_total_exposure=Decimal("49500"), estimated_order_notional=Decimal("1000")
    )
    decision = evaluate_order_risk(_order(), context)
    assert decision.reason_code is RiskRejectionReason.MAX_TOTAL_EXPOSURE_EXCEEDED


def test_check_10_max_concurrent_positions_exceeded() -> None:
    context = _context(current_open_positions_count=5, max_concurrent_positions=5)
    decision = evaluate_order_risk(_order(), context)
    assert decision.reason_code is RiskRejectionReason.MAX_CONCURRENT_POSITIONS_EXCEEDED


def test_check_11_instrument_not_allowed_allowlist() -> None:
    decision = evaluate_order_risk(_order(), _context(allowed_instruments=frozenset({TCS})))
    assert decision.reason_code is RiskRejectionReason.INSTRUMENT_NOT_ALLOWED


def test_check_11_instrument_not_allowed_denylist() -> None:
    decision = evaluate_order_risk(_order(), _context(denied_instruments=frozenset({RELIANCE})))
    assert decision.reason_code is RiskRejectionReason.INSTRUMENT_NOT_ALLOWED


def test_check_12_daily_trade_limit_exceeded() -> None:
    decision = evaluate_order_risk(
        _order(), _context(current_daily_trade_count=5, max_daily_trades=5)
    )
    assert decision.reason_code is RiskRejectionReason.DAILY_TRADE_LIMIT_EXCEEDED


def test_check_13_per_trade_risk_unknown() -> None:
    decision = evaluate_order_risk(
        _order(),
        _context(estimated_per_trade_risk=None, enforce_per_trade_risk_limit=True),
    )
    assert decision.reason_code is RiskRejectionReason.PER_TRADE_RISK_UNKNOWN


def test_check_13_max_per_trade_risk_exceeded() -> None:
    decision = evaluate_order_risk(
        _order(),
        _context(estimated_per_trade_risk=Decimal("1500"), enforce_per_trade_risk_limit=True),
    )
    assert decision.reason_code is RiskRejectionReason.MAX_PER_TRADE_RISK_EXCEEDED


def test_all_checks_pass_yields_approval() -> None:
    decision = evaluate_order_risk(_order(), _context())
    assert decision.outcome is RiskDecisionOutcome.APPROVED
    assert decision.reason_code is None


# --- Fixed check order preserved post-relocation -----------------------------


def test_first_failing_check_wins_kill_switch_over_market_session() -> None:
    """Kill switch (check 1) and market session closed (check 2) would
    BOTH fail here - only the earlier check's reason must be reported."""
    context = _context(
        kill_switch_status=TradingHaltStatus.HALTED,
        market_session_is_open=False,
        strategy_is_active=False,
    )
    decision = evaluate_order_risk(_order(), context)
    assert decision.outcome is RiskDecisionOutcome.REJECTED
    assert decision.reason_code is RiskRejectionReason.KILL_SWITCH_ENGAGED


def test_first_failing_check_wins_market_session_over_max_daily_loss() -> None:
    """Market session closed (check 2) and max daily loss exceeded
    (check 7) would BOTH fail - the earlier one wins."""
    context = _context(
        market_session_is_open=False,
        current_daily_realized_pnl=Decimal("-5000"),
    )
    decision = evaluate_order_risk(_order(), context)
    assert decision.reason_code is RiskRejectionReason.MARKET_SESSION_CLOSED


def test_first_failing_check_wins_max_position_size_over_instrument_denylist() -> None:
    """Max position size (check 8) and instrument denylist (check 11)
    would BOTH fail - the earlier, lower-numbered check wins."""
    context = _context(
        current_position_size_for_instrument=Decimal("95"),
        denied_instruments=frozenset({RELIANCE}),
    )
    decision = evaluate_order_risk(_order(quantity=Decimal("10")), context)
    assert decision.reason_code is RiskRejectionReason.MAX_POSITION_SIZE_EXCEEDED
