# tests/unit/infrastructure/api/test_emergency_square_off_trigger.py
#
# Checkpoint 46 Part 2: THE closing proof for Checkpoint 45's own
# named gap - "run_emergency_square_off() exists but nothing
# automatically invokes it when the kill switch engages." Proves the
# full chain: KILL SWITCH ENGAGED -> DETECT -> AUTOMATIC SQUARE-OFF ->
# RECONCILIATION -> ZERO OPEN EXPOSURE CONFIRMED, and that it runs
# EXACTLY ONCE per halt event (idempotent across repeated ticks).
from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest
from django.core.cache import cache

from intraday.application.services.kill_switch import KillSwitchService
from intraday.domain.instrument.contracts import make_instrument_id
from intraday.domain.order.contracts import OrderIntent, OrderType, TimeInForce
from intraday.domain.shared_kernel.contracts import Exchange, Side
from intraday.infrastructure.api.emergency_square_off_trigger import (
    check_and_trigger_automatic_square_off,
)
from intraday.infrastructure.api.paper_trading_runtime import (
    get_paper_trading_service,
    reset_paper_broker_for_testing,
)
from intraday.infrastructure.persistence.kill_switch_repository import DjangoKillSwitchRepository
from intraday.infrastructure.persistence.models import PaperOrderRecord

pytestmark = pytest.mark.django_db

RELIANCE = make_instrument_id(Exchange.NSE, "RELIANCE")
NOW = datetime(2026, 1, 5, 6, 0, tzinfo=UTC)


@pytest.fixture(autouse=True)
def _reset():  # type: ignore[no-untyped-def]
    cache.clear()
    reset_paper_broker_for_testing()
    yield
    cache.clear()
    reset_paper_broker_for_testing()


def _open_a_position() -> None:
    trading_service = get_paper_trading_service()
    trading_service.broker.record_price(RELIANCE, Decimal("100"), NOW)
    order = OrderIntent(
        order_id="entry-1",  # type: ignore[arg-type]
        instrument_id=RELIANCE,
        side=Side.BUY,
        quantity=Decimal("10"),
        order_type=OrderType.MARKET,
        time_in_force=TimeInForce.DAY,
        strategy_id="ema_crossover",  # type: ignore[arg-type]
        created_at=NOW,
        idempotency_key="idem-entry-1",
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


def test_no_action_when_kill_switch_is_not_engaged() -> None:
    _open_a_position()
    outcome = check_and_trigger_automatic_square_off(
        current_prices={str(RELIANCE): Decimal("101")}, now=NOW
    )
    assert outcome.kill_switch_engaged is False
    assert outcome.square_off is None

    trading_service = get_paper_trading_service()
    assert trading_service.broker.get_positions()[0].status.value == "OPEN"


def test_full_chain_kill_switch_to_zero_exposure() -> None:
    """THE acceptance proof: KILL SWITCH -> AUTOMATIC SQUARE-OFF ->
    EXIT -> RECONCILIATION -> ZERO OPEN EXPOSURE, entirely automatic."""
    _open_a_position()

    kill_switch = KillSwitchService(DjangoKillSwitchRepository())
    kill_switch.engage(reason="test halt", actor="test", actor_user_id=1, request_id="req-1")

    outcome = check_and_trigger_automatic_square_off(
        current_prices={str(RELIANCE): Decimal("101")}, now=NOW
    )

    assert outcome.kill_switch_engaged is True
    assert outcome.already_handled is False
    assert outcome.square_off is not None
    assert outcome.square_off.positions_closed == 1
    # Checkpoint 47 Part 2: MUST be exactly zero - Checkpoint 46 left a
    # real MISSING_LOCALLY divergence unresolved here (a genuine bug
    # in load_positions_for_reconciliation(), root-caused and fixed
    # this checkpoint - see Decision 199). Both "zero exposure" AND
    # "zero reconciliation divergence" are required for this checkpoint
    # to consider emergency square-off genuinely proven, not merely
    # "closed but murky."
    assert outcome.reconciliation_divergence_count == 0
    assert outcome.zero_exposure_confirmed is True

    trading_service = get_paper_trading_service()
    assert trading_service.broker.get_positions()[0].status.value == "CLOSED"
    assert PaperOrderRecord.objects.count() == 2  # entry + automatic exit


def test_repeated_ticks_do_not_double_square_off() -> None:
    """Idempotency: the SAME halt event must only be handled once,
    even if the scheduled tick calls this function repeatedly."""
    _open_a_position()
    kill_switch = KillSwitchService(DjangoKillSwitchRepository())
    kill_switch.engage(reason="test halt", actor="test", actor_user_id=1, request_id="req-1")

    first = check_and_trigger_automatic_square_off(
        current_prices={str(RELIANCE): Decimal("101")}, now=NOW
    )
    assert first.already_handled is False
    assert first.square_off is not None
    assert first.square_off.positions_closed == 1

    second = check_and_trigger_automatic_square_off(
        current_prices={str(RELIANCE): Decimal("101")}, now=NOW
    )
    assert second.already_handled is True
    assert second.square_off is None

    # Still exactly 2 orders (entry + one exit) - no duplicate exit.
    assert PaperOrderRecord.objects.count() == 2


def test_a_new_halt_event_after_reset_is_handled_as_a_fresh_event() -> None:
    """Resetting and re-engaging the kill switch produces a NEW
    `changed_at` identity - the new halt event must still be handled
    (this is a DIFFERENT event, not a repeat of the first)."""
    _open_a_position()
    kill_switch = KillSwitchService(DjangoKillSwitchRepository())
    kill_switch.engage(reason="first halt", actor="test", actor_user_id=1, request_id="req-1")
    check_and_trigger_automatic_square_off(current_prices={str(RELIANCE): Decimal("101")}, now=NOW)
    kill_switch.reset(actor="test", actor_user_id=1, request_id="req-2")

    _open_a_position_second_time()
    kill_switch.engage(reason="second halt", actor="test", actor_user_id=1, request_id="req-3")

    second_outcome = check_and_trigger_automatic_square_off(
        current_prices={str(RELIANCE): Decimal("101")}, now=NOW
    )
    assert second_outcome.already_handled is False
    assert second_outcome.square_off is not None
    assert second_outcome.square_off.positions_closed == 1


def _open_a_position_second_time() -> None:
    trading_service = get_paper_trading_service()
    order = OrderIntent(
        order_id="entry-2",  # type: ignore[arg-type]
        instrument_id=RELIANCE,
        side=Side.BUY,
        quantity=Decimal("5"),
        order_type=OrderType.MARKET,
        time_in_force=TimeInForce.DAY,
        strategy_id="ema_crossover",  # type: ignore[arg-type]
        created_at=NOW,
        idempotency_key="idem-entry-2",
    )
    result = trading_service.submit_order(
        order,
        strategy_is_active=True,
        market_session_is_open=True,
        data_quality_is_stale=False,
        estimated_order_notional=Decimal("500"),
        already_submitted_idempotency_keys=frozenset(),
    )
    assert result.broker_report is not None
