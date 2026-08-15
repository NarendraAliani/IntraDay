# tests/unit/infrastructure/api/test_emergency_square_off_crash_recovery.py
#
# Checkpoint 48 Part 3: proves the concern Checkpoint 47 explicitly
# left unresolved is actually closed - "if the process crashed
# mid-square-off, a cache-only claim could permanently mark the halt
# 'handled' with positions still open." These tests simulate exactly
# that crash by calling the repository directly (bypassing
# `check_and_trigger_automatic_square_off()`'s own claim/complete
# pairing) to leave a row stuck IN_PROGRESS, then prove the NEXT real
# call reclaims and finishes it - never accepting a claim alone as
# proof of completion.
from __future__ import annotations

import datetime as dt
from datetime import UTC, datetime
from decimal import Decimal

import pytest

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
from intraday.infrastructure.persistence.emergency_square_off_event_repository import (
    IN_PROGRESS_STALENESS_SECONDS,
    DjangoEmergencySquareOffEventRepository,
    SquareOffEventStatus,
)
from intraday.infrastructure.persistence.kill_switch_repository import DjangoKillSwitchRepository
from intraday.infrastructure.persistence.models import EmergencySquareOffEvent, PaperOrderRecord

pytestmark = pytest.mark.django_db

RELIANCE = make_instrument_id(Exchange.NSE, "RELIANCE")
NOW = datetime(2026, 1, 5, 6, 0, tzinfo=UTC)


@pytest.fixture(autouse=True)
def _reset():  # type: ignore[no-untyped-def]
    reset_paper_broker_for_testing()
    yield
    reset_paper_broker_for_testing()


def _open_a_position(order_id: str = "entry-1", idem: str = "idem-entry-1") -> None:
    trading_service = get_paper_trading_service()
    trading_service.broker.record_price(RELIANCE, Decimal("100"), NOW)
    order = OrderIntent(
        order_id=order_id,  # type: ignore[arg-type]
        instrument_id=RELIANCE,
        side=Side.BUY,
        quantity=Decimal("10"),
        order_type=OrderType.MARKET,
        time_in_force=TimeInForce.DAY,
        strategy_id="ema_crossover",  # type: ignore[arg-type]
        created_at=NOW,
        idempotency_key=idem,
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


def _engage_kill_switch(reason: str = "test halt") -> str:
    kill_switch = KillSwitchService(DjangoKillSwitchRepository())
    state = kill_switch.engage(reason=reason, actor="test", actor_user_id=1, request_id="r1")
    assert state.changed_at is not None
    return state.changed_at.isoformat()


def test_1_crash_before_square_off_starts_leaves_not_started_reclaimable() -> None:
    """A row that was created (get_or_create inside claim()) but the
    process died before even calling run_emergency_square_off() is
    indistinguishable from a fresh NOT_STARTED row - trivially
    reclaimable, no special handling needed. Proven by simply never
    having called claim() at all yet - the real first call must still
    succeed."""
    _open_a_position()
    _engage_kill_switch()
    outcome = check_and_trigger_automatic_square_off(
        current_prices={str(RELIANCE): Decimal("101")}, now=NOW
    )
    assert outcome.already_handled is False
    assert outcome.zero_exposure_confirmed is True


def test_2_crash_mid_square_off_leaves_row_stuck_in_progress_and_is_reclaimed() -> None:
    """THE central proof: simulate a crash by claiming the row directly
    (as the trigger's first line does) and then NEVER calling
    complete()/fail() - exactly what a process death mid-run would
    leave behind. The row must still be IN_PROGRESS (not silently
    'handled') and, once the staleness window has passed, the NEXT
    real trigger call must reclaim and actually finish it - proving a
    crash can never permanently strand a halt event as falsely
    handled."""
    _open_a_position()
    halt_identity = _engage_kill_switch()

    repository = DjangoEmergencySquareOffEventRepository()
    crash_time = NOW
    claim = repository.claim(halt_identity=halt_identity, now=crash_time)
    assert claim.claimed is True
    # ...and then nothing else happens - the "process" dies here.

    row = EmergencySquareOffEvent.objects.get(halt_identity=halt_identity)
    assert row.status == SquareOffEventStatus.IN_PROGRESS.value

    # Immediately retrying (before the staleness window) must NOT
    # reclaim - a genuinely concurrent/still-running attempt must not
    # be double-run.
    immediate_retry = check_and_trigger_automatic_square_off(
        current_prices={str(RELIANCE): Decimal("101")}, now=crash_time
    )
    assert immediate_retry.already_handled is False
    assert immediate_retry.square_off is None  # refused, not run
    trading_service = get_paper_trading_service()
    assert trading_service.broker.get_positions()[0].status.value == "OPEN"

    # Once the staleness window has elapsed, the SAME halt event must
    # be reclaimed and genuinely finished.
    after_staleness = crash_time + dt.timedelta(seconds=IN_PROGRESS_STALENESS_SECONDS + 1)
    recovered = check_and_trigger_automatic_square_off(
        current_prices={str(RELIANCE): Decimal("101")}, now=after_staleness
    )
    assert recovered.square_off is not None
    assert recovered.square_off.positions_closed == 1
    assert recovered.zero_exposure_confirmed is True

    row.refresh_from_db()
    assert row.status == SquareOffEventStatus.COMPLETED.value
    assert row.attempt_count == 2  # the crashed attempt + the recovered one


def test_3_retry_after_failed_retryable_actually_closes_the_position() -> None:
    """A position that could not be priced this attempt (no
    current_prices AND no broker-recorded price) leaves the event
    FAILED_RETRYABLE, not COMPLETED and not silently dropped - the
    next attempt, once a price becomes available, must succeed."""
    trading_service = get_paper_trading_service()
    # Deliberately do NOT record a price - the position enters OPEN
    # with no price the fallback can find either.
    order = OrderIntent(
        order_id="entry-unpriced",  # type: ignore[arg-type]
        instrument_id=RELIANCE,
        side=Side.BUY,
        quantity=Decimal("10"),
        order_type=OrderType.MARKET,
        time_in_force=TimeInForce.DAY,
        strategy_id="ema_crossover",  # type: ignore[arg-type]
        created_at=NOW,
        idempotency_key="idem-unpriced",
    )
    # A MARKET order needs SOME price to fill at all - record one just
    # to open the position, matching this project's existing test
    # precedent - then remove the broker's memory of it to force the
    # "genuinely cannot price it this attempt" branch via monkeypatch
    # instead, exactly as test_emergency_square_off.py does.
    trading_service.broker.record_price(RELIANCE, Decimal("100"), NOW)
    result = trading_service.submit_order(
        order,
        strategy_is_active=True,
        market_session_is_open=True,
        data_quality_is_stale=False,
        estimated_order_notional=Decimal("1000"),
        already_submitted_idempotency_keys=frozenset(),
    )
    assert result.broker_report is not None

    halt_identity = _engage_kill_switch()

    original_get_latest_price = trading_service.broker.get_latest_price
    trading_service.broker.get_latest_price = lambda instrument_id: None  # type: ignore[method-assign]
    try:
        first = check_and_trigger_automatic_square_off(current_prices={}, now=NOW)
    finally:
        trading_service.broker.get_latest_price = original_get_latest_price  # type: ignore[method-assign]

    assert first.square_off is not None
    assert first.square_off.positions_closed == 0
    assert first.zero_exposure_confirmed is False

    row = EmergencySquareOffEvent.objects.get(halt_identity=halt_identity)
    assert row.status == SquareOffEventStatus.FAILED_RETRYABLE.value
    assert row.attempt_count == 1

    # Now a price IS available (the broker's own last recorded price,
    # restored above) - the retry must succeed.
    second = check_and_trigger_automatic_square_off(
        current_prices={str(RELIANCE): Decimal("102")}, now=NOW
    )
    assert second.square_off is not None
    assert second.square_off.positions_closed == 1
    assert second.zero_exposure_confirmed is True

    row.refresh_from_db()
    assert row.status == SquareOffEventStatus.COMPLETED.value
    assert row.attempt_count == 2


def test_4_completed_event_is_never_reclaimed_or_rerun() -> None:
    _open_a_position()
    _engage_kill_switch()
    first = check_and_trigger_automatic_square_off(
        current_prices={str(RELIANCE): Decimal("101")}, now=NOW
    )
    assert first.zero_exposure_confirmed is True

    much_later = NOW + dt.timedelta(hours=5)
    second = check_and_trigger_automatic_square_off(
        current_prices={str(RELIANCE): Decimal("101")}, now=much_later
    )
    assert second.already_handled is True
    assert second.square_off is None
    assert PaperOrderRecord.objects.count() == 2  # entry + exactly one exit, never duplicated


def test_5_two_concurrent_claims_for_the_same_halt_event_only_one_wins() -> None:
    """Simulates the exact scenario Checkpoint 47 Part 4 introduced:
    the ingestion tick AND the independent 15s task could both call
    this function for the same halt event at nearly the same moment.
    The SECOND claim() call (same halt_identity, same instant) must be
    refused, not double-claimed."""
    _open_a_position()
    halt_identity = _engage_kill_switch()

    repository = DjangoEmergencySquareOffEventRepository()
    first_claim = repository.claim(halt_identity=halt_identity, now=NOW)
    second_claim = repository.claim(halt_identity=halt_identity, now=NOW)

    assert first_claim.claimed is True
    assert second_claim.claimed is False
    assert second_claim.already_terminal is False  # refused, not "done"
