# tests/unit/trading_engine/test_risk_engine_gap_closure.py
#
# Checkpoint 39 Part I: proves the three gaps Checkpoint 38 found
# (max_per_trade_risk configured-but-unenforced; no daily trade-count
# limit; no instrument allow/deny list) are now REAL, enforced checks -
# not merely documented as gaps a second time.
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


# --- Instrument allow/deny list --------------------------------------------


def test_instrument_not_on_allowlist_is_rejected() -> None:
    decision = evaluate_order_risk(_order(), _context(allowed_instruments=frozenset({TCS})))
    assert decision.outcome is RiskDecisionOutcome.REJECTED
    assert decision.reason_code is RiskRejectionReason.INSTRUMENT_NOT_ALLOWED


def test_instrument_on_allowlist_is_not_rejected_for_this_reason() -> None:
    decision = evaluate_order_risk(_order(), _context(allowed_instruments=frozenset({RELIANCE})))
    assert decision.outcome is RiskDecisionOutcome.APPROVED


def test_no_allowlist_configured_means_any_instrument_permitted() -> None:
    decision = evaluate_order_risk(_order(), _context(allowed_instruments=None))
    assert decision.outcome is RiskDecisionOutcome.APPROVED


def test_instrument_on_denylist_is_rejected_even_without_an_allowlist() -> None:
    decision = evaluate_order_risk(_order(), _context(denied_instruments=frozenset({RELIANCE})))
    assert decision.outcome is RiskDecisionOutcome.REJECTED
    assert decision.reason_code is RiskRejectionReason.INSTRUMENT_NOT_ALLOWED


def test_denylist_does_not_affect_other_instruments() -> None:
    decision = evaluate_order_risk(_order(), _context(denied_instruments=frozenset({TCS})))
    assert decision.outcome is RiskDecisionOutcome.APPROVED


# --- Daily trade-count limit -------------------------------------------------


def test_daily_trade_limit_reached_is_rejected() -> None:
    decision = evaluate_order_risk(
        _order(),
        _context(current_daily_trade_count=5, max_daily_trades=5),
    )
    assert decision.outcome is RiskDecisionOutcome.REJECTED
    assert decision.reason_code is RiskRejectionReason.DAILY_TRADE_LIMIT_EXCEEDED


def test_daily_trade_count_below_limit_is_approved() -> None:
    decision = evaluate_order_risk(
        _order(),
        _context(current_daily_trade_count=4, max_daily_trades=5),
    )
    assert decision.outcome is RiskDecisionOutcome.APPROVED


def test_no_daily_trade_limit_configured_means_unlimited() -> None:
    decision = evaluate_order_risk(
        _order(),
        _context(current_daily_trade_count=10_000, max_daily_trades=None),
    )
    assert decision.outcome is RiskDecisionOutcome.APPROVED


# --- Max per-trade risk (opt-in) --------------------------------------------


def test_per_trade_risk_check_is_off_by_default_even_with_no_stop_loss() -> None:
    """Backward compatibility: existing callers (PaperSignalExecutionService
    driving ema_crossover, which has no stop loss) must be unaffected
    unless they explicitly opt in."""
    decision = evaluate_order_risk(
        _order(), _context(estimated_per_trade_risk=None, enforce_per_trade_risk_limit=False)
    )
    assert decision.outcome is RiskDecisionOutcome.APPROVED


def test_unknown_per_trade_risk_is_blocked_when_enforcement_is_enabled() -> None:
    """Part I's explicit instruction: a strategy that cannot supply a
    stop loss must be BLOCKED, never assumed safe, once enforcement is
    active."""
    decision = evaluate_order_risk(
        _order(), _context(estimated_per_trade_risk=None, enforce_per_trade_risk_limit=True)
    )
    assert decision.outcome is RiskDecisionOutcome.REJECTED
    assert decision.reason_code is RiskRejectionReason.PER_TRADE_RISK_UNKNOWN


def test_known_per_trade_risk_within_limit_is_approved() -> None:
    decision = evaluate_order_risk(
        _order(),
        _context(estimated_per_trade_risk=Decimal("500"), enforce_per_trade_risk_limit=True),
    )
    assert decision.outcome is RiskDecisionOutcome.APPROVED


def test_known_per_trade_risk_exceeding_limit_is_rejected() -> None:
    decision = evaluate_order_risk(
        _order(),
        _context(estimated_per_trade_risk=Decimal("1500"), enforce_per_trade_risk_limit=True),
    )
    assert decision.outcome is RiskDecisionOutcome.REJECTED
    assert decision.reason_code is RiskRejectionReason.MAX_PER_TRADE_RISK_EXCEEDED


def test_per_trade_risk_exactly_at_limit_is_approved() -> None:
    """Boundary: AT the limit is not OVER the limit - mirrors this
    project's own established '>' not '>=' convention for exceedance
    checks (see max_position_size/max_total_exposure)."""
    decision = evaluate_order_risk(
        _order(),
        _context(estimated_per_trade_risk=Decimal("1000"), enforce_per_trade_risk_limit=True),
    )
    assert decision.outcome is RiskDecisionOutcome.APPROVED


# --- Fixed evaluation order still holds -------------------------------------


def test_kill_switch_still_overrides_every_new_check() -> None:
    decision = evaluate_order_risk(
        _order(),
        _context(
            kill_switch_status=TradingHaltStatus.HALTED,
            allowed_instruments=frozenset({TCS}),  # would also fail, but kill switch wins
        ),
    )
    assert decision.reason_code is RiskRejectionReason.KILL_SWITCH_ENGAGED
