# tests/unit/infrastructure/api/test_eod_sequence_task.py
#
# Checkpoint 65.34 Part 5: proves `eod_sequence_tick` - the FIRST
# scheduled Celery trigger for `run_eod_sequence()` - actually closes
# open positions using only the broker's own last recorded price
# (matching `emergency_square_off_check_tick`'s established
# independence precedent, Checkpoint 47 Part 4), and that repeated
# invocations for the same trading date remain idempotent (never a
# duplicate exit order), mirroring
# `test_emergency_square_off_independent_task.py`'s own proof shape.
from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from intraday.domain.instrument.contracts import make_instrument_id
from intraday.domain.order.contracts import OrderIntent, OrderType, TimeInForce
from intraday.domain.shared_kernel.contracts import Exchange, Side
from intraday.infrastructure.api.paper_trading_runtime import (
    get_paper_trading_service,
    reset_paper_broker_for_testing,
)
from intraday.infrastructure.api.tasks import eod_sequence_tick
from intraday.infrastructure.persistence.models import PaperOrderRecord

pytestmark = pytest.mark.django_db

RELIANCE = make_instrument_id(Exchange.NSE, "RELIANCE")
NOW = datetime(2026, 1, 5, 10, 15, tzinfo=UTC)


@pytest.fixture(autouse=True)
def _reset():  # type: ignore[no-untyped-def]
    from django.core.cache import cache

    cache.clear()
    reset_paper_broker_for_testing()
    yield
    cache.clear()
    reset_paper_broker_for_testing()


def _open_a_position() -> None:
    trading_service = get_paper_trading_service()
    trading_service.broker.record_price(RELIANCE, Decimal("100"), NOW)
    order = OrderIntent(
        order_id="entry-eod-1",  # type: ignore[arg-type]
        instrument_id=RELIANCE,
        side=Side.BUY,
        quantity=Decimal("10"),
        order_type=OrderType.MARKET,
        time_in_force=TimeInForce.DAY,
        strategy_id="ema_crossover",  # type: ignore[arg-type]
        created_at=NOW,
        idempotency_key="idem-entry-eod-1",
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


def test_task_with_no_open_positions_completes_without_error() -> None:
    result = eod_sequence_tick.run(now_override=NOW.isoformat())
    assert result.startswith("ran:positions_closed=0")
    assert "zero_exposure_confirmed=True" in result


def test_task_closes_an_open_position_using_only_the_brokers_own_recorded_price() -> None:
    """No current_prices argument exists on this task at all - it is
    architecturally impossible for a caller to supply fresh quotes -
    proving the scheduled EOD trigger works independently of a fresh
    market-data tick having just run, same as the emergency
    square-off task already proves."""
    trading_service = get_paper_trading_service()
    _open_a_position()

    result = eod_sequence_tick.run(now_override=NOW.isoformat())

    assert result.startswith("ran:positions_closed=1")
    assert "zero_exposure_confirmed=True" in result
    assert PaperOrderRecord.objects.count() == 2  # entry + EOD exit
    assert trading_service.broker.get_positions()[0].status.value == "CLOSED"


def test_task_is_idempotent_across_repeated_invocations_for_the_same_trading_date() -> None:
    _open_a_position()

    first = eod_sequence_tick.run(now_override=NOW.isoformat())
    second = eod_sequence_tick.run(now_override=NOW.isoformat())

    assert first.startswith("ran:positions_closed=1")
    assert second == "already_handled"
    assert PaperOrderRecord.objects.count() == 2  # never a duplicate exit
