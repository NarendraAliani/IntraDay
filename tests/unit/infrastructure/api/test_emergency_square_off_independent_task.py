# tests/unit/infrastructure/api/test_emergency_square_off_independent_task.py
#
# Checkpoint 47 Part 4: proves the emergency square-off check is now
# genuinely INDEPENDENT of market-data ingestion - the Celery task
# succeeds using ONLY the broker's own last recorded price, with zero
# dependency on a fresh Dhan quote fetch having just happened. This is
# the direct fix to the circular-dependency weakness named this
# checkpoint: "kill switch -> waiting for ingestion tick -> square-off."
from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from intraday.application.services.kill_switch import KillSwitchService
from intraday.domain.instrument.contracts import make_instrument_id
from intraday.domain.order.contracts import OrderIntent, OrderType, TimeInForce
from intraday.domain.shared_kernel.contracts import Exchange, Side
from intraday.infrastructure.api.paper_trading_runtime import (
    get_paper_trading_service,
    reset_paper_broker_for_testing,
)
from intraday.infrastructure.api.tasks import emergency_square_off_check_tick
from intraday.infrastructure.persistence.kill_switch_repository import DjangoKillSwitchRepository
from intraday.infrastructure.persistence.models import PaperOrderRecord

pytestmark = pytest.mark.django_db

RELIANCE = make_instrument_id(Exchange.NSE, "RELIANCE")
NOW = datetime(2026, 1, 5, 6, 0, tzinfo=UTC)


@pytest.fixture(autouse=True)
def _reset():  # type: ignore[no-untyped-def]
    from django.core.cache import cache

    cache.clear()
    reset_paper_broker_for_testing()
    yield
    cache.clear()
    reset_paper_broker_for_testing()


def test_task_reports_not_engaged_when_kill_switch_is_off() -> None:
    result = emergency_square_off_check_tick.run(now_override=NOW.isoformat())
    assert result == "not_engaged"


def test_task_closes_a_position_using_only_the_brokers_own_recorded_price() -> None:
    """THE proof: no current_prices are supplied to this task at all -
    it must still find and use the broker's own last recorded price
    (set once, at entry time, via record_price() - never re-supplied
    by a fresh quote fetch) to actually close the position. This
    proves emergency square-off no longer implicitly depends on
    market-data ingestion having just succeeded."""
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

    kill_switch = KillSwitchService(DjangoKillSwitchRepository())
    kill_switch.engage(reason="ingestion is down", actor="test", actor_user_id=1, request_id="r1")

    # No current_prices argument exists on this task at all - it is
    # architecturally impossible for a caller to supply fresh quotes
    # to it, proving the independence directly.
    task_result = emergency_square_off_check_tick.run(now_override=NOW.isoformat())

    assert task_result.startswith("handled:positions_closed=1")
    assert "zero_exposure_confirmed=True" in task_result
    assert PaperOrderRecord.objects.count() == 2  # entry + automatic exit
    assert trading_service.broker.get_positions()[0].status.value == "CLOSED"


def test_task_is_idempotent_across_repeated_independent_invocations() -> None:
    trading_service = get_paper_trading_service()
    trading_service.broker.record_price(RELIANCE, Decimal("100"), NOW)
    order = OrderIntent(
        order_id="entry-2",  # type: ignore[arg-type]
        instrument_id=RELIANCE,
        side=Side.BUY,
        quantity=Decimal("10"),
        order_type=OrderType.MARKET,
        time_in_force=TimeInForce.DAY,
        strategy_id="ema_crossover",  # type: ignore[arg-type]
        created_at=NOW,
        idempotency_key="idem-entry-2",
    )
    trading_service.submit_order(
        order,
        strategy_is_active=True,
        market_session_is_open=True,
        data_quality_is_stale=False,
        estimated_order_notional=Decimal("1000"),
        already_submitted_idempotency_keys=frozenset(),
    )
    kill_switch = KillSwitchService(DjangoKillSwitchRepository())
    kill_switch.engage(reason="halt", actor="test", actor_user_id=1, request_id="r1")

    first = emergency_square_off_check_tick.run(now_override=NOW.isoformat())
    second = emergency_square_off_check_tick.run(now_override=NOW.isoformat())

    assert first.startswith("handled:")
    assert second == "already_handled"
    assert PaperOrderRecord.objects.count() == 2  # never a duplicate exit
